"""Checks for the local CSV explorer without opening a network socket."""

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from web.server import Handler


class WebTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        inputs, results = root / "inputs", root / "results"
        inputs.mkdir()
        results.mkdir()
        with (inputs / "fact_tickets.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["ticket_key", "passenger_first_name", "reason"])
            writer.writeheader()
            writer.writerows([{"ticket_key": str(i), "passenger_first_name": name,
                               "reason": "Длинное объяснение " * 40 if i == 1 else ""}
                              for i, name in enumerate(["ALICE", "BOB", "ALICE", "CAROL"], 1)])
        conn = sqlite3.connect(results / "index.sqlite")
        try:
            conn.executescript("""
                CREATE TABLE events(entity_id TEXT,flight_key TEXT,departure_date TEXT,
                    departure_airport TEXT,arrival_airport TEXT);
                CREATE TABLE tickets(entity_id TEXT,pnr TEXT);
                INSERT INTO events VALUES
                    ('P:1','F1','2017-01-01','AAA','BBB'),
                    ('P:2','F1','2017-01-01','AAA','BBB'),
                    ('P:1','F2','2017-02-01','AAA','CCC'),
                    ('P:2','F3','2017-02-01','DDD','CCC');
                INSERT INTO tickets VALUES ('P:1','GOOD'),('P:2','GOOD');
            """)
            conn.executemany("INSERT INTO tickets VALUES (?, 'GENERIC')",
                             [(f"P:{i}",) for i in range(1, 15)])
            conn.commit()
        finally:
            conn.close()
        self.handler = object.__new__(Handler)
        self.handler.server = SimpleNamespace(input_dir=inputs, results_dir=results)

    def test_csv_search_and_pagination(self):
        first = self.handler.api_table({"name": "fact_tickets", "size": "2"})
        self.assertEqual([r["ticket_key"] for r in first["rows"]], ["1", "2"])
        self.assertEqual(first["rows"][0]["reason"], "Длинное объяснение " * 40)
        self.assertTrue(first["has_more"])
        second = self.handler.api_table({"name": "fact_tickets", "size": "2", "page": "2"})
        self.assertEqual([r["ticket_key"] for r in second["rows"]], ["3", "4"])
        self.assertFalse(second["has_more"])
        match = self.handler.api_table({"name": "fact_tickets", "q": "alice"})
        self.assertEqual([r["ticket_key"] for r in match["rows"]], ["1", "3"])
        with self.assertRaises(ValueError):
            self.handler.api_table({"name": "../../index.sqlite"})

    def test_compare_shows_real_intersections_and_skips_generic_pnr(self):
        result = self.handler.api_compare({"a": "P:1", "b": "P:2"})
        self.assertEqual([r["flight_key"] for r in result["shared_flights"]], ["F1"])
        self.assertEqual([(r["flight_a"], r["flight_b"]) for r in result["parallel_arrivals"]],
                         [("F2", "F3")])
        self.assertEqual(result["shared_pnrs"], ["GOOD"])
        with self.assertRaises(ValueError):
            self.handler.api_compare({"a": "P:1", "b": "P:1"})

    def test_api_occupancy(self):
        import json
        summary = {
            "total_flights": 100,
            "anomaly_flights": 10,
            "overcapacity_flew": 1,
            "overcapacity_booked": 2,
            "no_tickets_count": 7
        }
        with (self.handler.server.results_dir / "flight_occupancy_summary.json").open("w", encoding="utf-8") as sf:
            json.dump(summary, sf)
        with (self.handler.server.results_dir / "flight_critical_anomalies.csv").open("w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=["flight_key", "is_overcapacity_flew", "is_overcapacity_booked", "is_unbooked_flight"])
            writer.writeheader()
            writer.writerow({"flight_key": "SU100", "is_overcapacity_flew": "1", "is_overcapacity_booked": "1", "is_unbooked_flight": "0"})
        res = self.handler.api_occupancy({"kind": "over_flew"})
        self.assertEqual(res["stats"]["total_flights"], 100)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["flight_key"], "SU100")

    def test_api_candidates_manual_review(self):
        with (self.handler.server.results_dir / "manual_review_candidates.csv").open("w", newline="", encoding="utf-8") as rf:
            writer = csv.DictWriter(rf, fieldnames=["candidate_id", "stage", "score", "signal_types", "reasons_json", "related_ids"])
            writer.writeheader()
            writer.writerow({
                "candidate_id": "P:999",
                "stage": "manual_review",
                "score": "2",
                "signal_types": '["flight_anomaly"]',
                "reasons_json": '[]',
                "related_ids": '[]'
            })
        res = self.handler.api_candidates({"kind": "review"})
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["rows"][0]["id"], "P:999")
        self.assertEqual(res["rows"][0]["stage"], "manual_review")
        self.assertTrue(res["rows"][0]["is_manual_review"])


if __name__ == "__main__":
    unittest.main()
