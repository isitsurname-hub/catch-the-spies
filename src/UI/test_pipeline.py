import csv
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import (PRIMARY_GENERATORS, SECONDARY_GENERATORS, expand_secondary,
                      name_equivalent, prepare, read_csv, run_secondary_signal,
                      run_signal, score_primary)


def table(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class PipelineTest(unittest.TestCase):
    def test_name_variants_are_not_identity_conflicts(self):
        self.assertTrue(name_equivalent("MAIIA LYKOVA", "MAIYA LYKOVA"))
        self.assertTrue(name_equivalent("GORIUNOVA TAMARA", "TAMARA GORYUNOVA"))
        self.assertFalse(name_equivalent("GORDEI GLEBOV", "RAMIL BUROV"))

    def test_conflict_and_two_round_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, outputs = root / "inputs", root / "outputs"
            inputs.mkdir()
            table(inputs / "dim_person.csv",
                  ["ProfileID", "First_Name", "Last_Name", "Sex"],
                  [{"ProfileID": str(i), "First_Name": name, "Last_Name": "TEST", "Sex": "MALE"}
                   for i, name in enumerate(["ALICE", "BOB", "CAROL", "DAVE"], 1)])
            ticket_headers = ["ticket_key", "pnr", "flight_key", "ProfileID", "passenger_first_name",
                              "passenger_last_name", "sex", "birth_date", "document",
                              "departure_date", "departure_time", "departure_airport", "arrival_airport"]
            docs = {1: "1234 000001", 2: "1234 000001", 3: "1234 000002", 4: "1234 000003"}
            names = {1: "ALICE", 2: "BOB", 3: "CAROL", 4: "DAVE"}
            births = {1: "1980-01-01", 2: "1990-01-01", 3: "1985-01-01", 4: "1986-01-01"}
            rows = []
            # Two PNRs for 1–3 and two for 3–4, each on different routes.
            for key, pnr, pids in [(1, "ABCD01", [1, 3]), (2, "ABCD02", [1, 3]),
                                   (3, "CDEF01", [3, 4]), (4, "CDEF02", [3, 4])]:
                for pid in pids:
                    rows.append({"ticket_key": f"T{key}-{pid}", "pnr": pnr,
                                 "flight_key": f"F{key}{pid}_2017-01-{key:02d}",
                                 "ProfileID": str(pid), "passenger_first_name": names[pid],
                                 "passenger_last_name": "TEST", "sex": "MALE",
                                 "birth_date": births[pid], "document": docs[pid],
                                 "departure_date": f"2017-01-{key:02d}", "departure_time": "10:00",
                                 "departure_airport": "AAA", "arrival_airport": f"X{pid}X"})
            rows.append({"ticket_key": "T2", "pnr": "BBBB02",
                         "flight_key": "B2_2017-02-01", "ProfileID": "2",
                         "passenger_first_name": "BOB", "passenger_last_name": "TEST",
                         "sex": "MALE", "birth_date": births[2], "document": docs[2],
                         "departure_date": "2017-02-01", "departure_time": "12:00",
                         "departure_airport": "AAA", "arrival_airport": "BBB"})
            # Missing ProfileID attaches only when doc+DOB+full name agree.
            rows.append({"ticket_key": "T1-extra", "pnr": "EXTRA1",
                         "flight_key": "A1_2017-02-01", "ProfileID": "",
                         "passenger_first_name": "ALICE", "passenger_last_name": "TEST",
                         "sex": "MALE", "birth_date": births[1], "document": docs[1],
                         "departure_date": "2017-02-01", "departure_time": "15:00",
                         "departure_airport": "AAA", "arrival_airport": "CCC"})
            table(inputs / "fact_tickets.csv", ticket_headers, rows)
            table(inputs / "fact_flights.csv",
                  ["ProfileID", "flight_key", "Date", "Departure.Airport", "Arrival.Airport"], [])
            prepare(inputs, outputs)
            for kind in PRIMARY_GENERATORS:
                run_signal(kind, outputs)
            score_primary(outputs)
            for kind in SECONDARY_GENERATORS:
                run_secondary_signal(kind, outputs)
            expand_secondary(outputs)

            links = list(read_csv(outputs / "identity_links.csv"))
            self.assertEqual(links[0]["ticket_key"], "T1-extra")
            self.assertEqual(links[0]["entity_id"], "P:1")
            seeds = {r["candidate_id"] for r in read_csv(outputs / "primary_candidates.csv")}
            self.assertIn("P:1", seeds)
            self.assertIn("P:2", seeds)
            final = {r["candidate_id"]: r for r in read_csv(outputs / "primary_candidates_final.csv")}
            self.assertEqual(final["P:3"]["promotion_round"], "1")
            self.assertEqual(final["P:4"]["promotion_round"], "2")
            self.assertIn("P:3", json.loads(final["P:4"]["parent_ids"]))
            self.assertTrue(json.loads(final["P:4"]["reasons_json"]))
            graph = list(read_csv(outputs / "chain_edges.csv"))
            self.assertTrue(any(r["link_stage"] == "primary" and
                                {r["candidate_id"], r["anchor_id"]} == {"P:1", "P:2"}
                                for r in graph))
            self.assertTrue(any(r["link_stage"] == "secondary" and
                                r["candidate_id"] == "P:4" and r["anchor_id"] == "P:3"
                                for r in graph))


if __name__ == "__main__":
    unittest.main()
