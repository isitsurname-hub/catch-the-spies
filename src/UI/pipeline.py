"""Explainable, conservative heuristics for the airline investigation dataset.

Only the Python standard library is required.  A ticket/flight describes an
itinerary, not proof that a passenger boarded or committed an offence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path


INPUTS = {
    "dim_person": "dim_person.csv",
    "fact_tickets": "fact_tickets.csv",
    "fact_flights": "fact_flights.csv",
}
SIGNAL_FILES = {
    "passport_collision": "01_passport_collision.csv",
    "profile_conflict": "02_profile_conflict.csv",
    "joint_travel": "03_joint_travel.csv",
    "near_passports_with_travel": "04_near_passports_with_travel.csv",
    "schedule_conflict": "05_schedule_conflict.csv",
    "flight_anomaly": "10_flight_anomaly.csv",
}
SECONDARY_FILES = {
    "near_passport": "06_near_passport.csv",
    "shared_pnr": "07_shared_pnr.csv",
    "parallel_arrivals": "08_parallel_arrivals.csv",
    "convergence": "09_convergence.csv",
}
WEIGHTS = {
    "passport_collision": 8,
    "profile_conflict": 7,
    "joint_travel": 3,
    "near_passports_with_travel": 4,
    "schedule_conflict": 2,
    "near_passport": 2,
    "shared_pnr": 3,
    "parallel_arrivals": 3,
    "convergence": 3,
    "flight_anomaly": 2,
}
SIGNAL_COLUMNS = ["subject_id", "related_ids", "signal", "weight", "reason", "evidence_json"]
PRIMARY_COLUMNS = ["candidate_id", "stage", "score", "signal_types", "reasons_json",
                   "related_ids", "promotion_round", "parent_ids", "profile_id",
                   "names_json", "birth_dates_json", "documents_json", "ticket_keys_json",
                   "ticket_count"]
EDGE_COLUMNS = ["candidate_id", "anchor_id", "signal", "weight", "reason",
                "evidence_json", "round", "link_stage"]


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def person_name(first: str | None, last: str | None) -> str:
    return f"{norm(first)} {norm(last)}".strip()


def canonical_token(value: str) -> str:
    token = re.sub(r"[^A-Z]", "", norm(value))
    for old, new in [("SHCH", "SCH"), ("YA", "IA"), ("YU", "IU"),
                     ("YE", "E"), ("YO", "E"), ("X", "KS"),
                     ("TC", "TS"), ("Y", "I"), ("J", "I")]:
        token = token.replace(old, new)
    return token


def canonical_name(value: str) -> str:
    return " ".join(sorted(canonical_token(piece) for piece in norm(value).split()))


def name_equivalent(a: str, b: str) -> bool:
    left, right = canonical_name(a).split(), canonical_name(b).split()
    if not left or not right or len(left) != len(right):
        return False
    # Two-token names can have first/last reversed in the source. Sort above;
    # compare both matchings to allow small transliteration differences.
    options = [right]
    if len(right) == 2:
        options.append(right[::-1])
    return any(all(SequenceMatcher(None, x, y).ratio() >= 0.78
                   for x, y in zip(left, option)) for option in options)


def document(value: str | None) -> str:
    result = re.sub(r"[^A-Z0-9]", "", norm(value))
    return result if len(result) >= 7 and len(set(result)) > 1 else ""


def entity_for_ticket(row: dict) -> str:
    if row["raw_profile_id"]:
        return "P:" + row["raw_profile_id"]
    if row["document"] and row["full_name"]:
        key = "|".join([row["document"], row["birth_date"], canonical_name(row["full_name"])])
        return "U:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return "T:" + row["ticket_key"]


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def checked_reader(path: Path, required: set[str]):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        yield from reader


def prepare(input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in INPUTS.values():
        if not (input_dir / name).is_file():
            raise FileNotFoundError(input_dir / name)
    db = output_dir / "index.sqlite"
    if db.exists():
        db.unlink()
    conn = connect(db)
    conn.executescript("""
        CREATE TABLE profiles(profile_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT,
                              full_name TEXT, sex TEXT);
        CREATE TABLE tickets(ticket_key TEXT PRIMARY KEY, pnr TEXT, flight_key TEXT,
            raw_profile_id TEXT, entity_id TEXT, first_name TEXT, last_name TEXT,
            full_name TEXT, sex TEXT, birth_date TEXT, document TEXT,
            departure_date TEXT, departure_time TEXT, departure_airport TEXT,
            arrival_date TEXT, arrival_time TEXT, arrival_airport TEXT, source TEXT);
        CREATE TABLE events(entity_id TEXT, flight_key TEXT, departure_date TEXT,
            departure_airport TEXT, arrival_airport TEXT, source_ref TEXT,
            PRIMARY KEY(entity_id, flight_key));
        CREATE TABLE identity_links(ticket_key TEXT PRIMARY KEY, entity_id TEXT,
            method TEXT, evidence TEXT);
    """)
    profiles = []
    for row in checked_reader(input_dir / INPUTS["dim_person"], {"ProfileID", "First_Name", "Last_Name", "Sex"}):
        pid = row["ProfileID"].strip()
        if pid:
            profiles.append((pid, norm(row["First_Name"]), norm(row["Last_Name"]),
                             person_name(row["First_Name"], row["Last_Name"]), norm(row["Sex"])))
        if len(profiles) >= 10000:
            conn.executemany("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?)", profiles)
            profiles.clear()
    conn.executemany("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?)", profiles)
    conn.commit()

    tickets = []
    for row in checked_reader(input_dir / INPUTS["fact_tickets"],
                              {"ticket_key", "pnr", "flight_key", "ProfileID", "passenger_first_name",
                               "passenger_last_name", "birth_date", "document", "departure_date",
                               "departure_airport", "arrival_airport"}):
        key = row["ticket_key"].strip()
        if not key:
            continue
        first, last = norm(row["passenger_first_name"]), norm(row["passenger_last_name"])
        clean = {
            "ticket_key": key, "pnr": norm(row["pnr"]), "flight_key": norm(row["flight_key"]),
            "raw_profile_id": row["ProfileID"].strip(), "first_name": first, "last_name": last,
            "full_name": person_name(first, last), "sex": norm(row.get("sex")),
            "birth_date": (row.get("birth_date") or "").strip(), "document": document(row["document"]),
            "departure_date": (row["departure_date"] or "").strip(),
            "departure_time": (row.get("departure_time") or "").strip(),
            "departure_airport": norm(row["departure_airport"]),
            "arrival_date": (row.get("arrival_date") or "").strip(),
            "arrival_time": (row.get("arrival_time") or "").strip(),
            "arrival_airport": norm(row["arrival_airport"]), "source": norm(row.get("source")),
        }
        clean["entity_id"] = entity_for_ticket(clean)
        tickets.append(tuple(clean[k] for k in ["ticket_key", "pnr", "flight_key", "raw_profile_id",
            "entity_id", "first_name", "last_name", "full_name", "sex", "birth_date", "document",
            "departure_date", "departure_time", "departure_airport", "arrival_date", "arrival_time",
            "arrival_airport", "source"]))
        if len(tickets) >= 10000:
            conn.executemany("INSERT OR IGNORE INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tickets)
            tickets.clear()
    conn.executemany("INSERT OR IGNORE INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tickets)
    conn.commit()
    conn.executescript("""
        CREATE INDEX ix_ticket_doc ON tickets(document);
        CREATE INDEX ix_ticket_anchor ON tickets(document,birth_date,full_name);
        CREATE INDEX ix_ticket_entity ON tickets(entity_id);
        CREATE INDEX ix_ticket_raw_profile ON tickets(raw_profile_id);
        CREATE INDEX ix_ticket_pnr ON tickets(pnr);
    """)
    # Only an exact document + DOB + full-name match to one explicit profile is
    # attached. Conflicting identities retain separate IDs for collision checks.
    conn.executescript("""
        CREATE TEMP TABLE unique_doc_birth AS
        SELECT document,birth_date,MIN(raw_profile_id) pid
        FROM tickets WHERE document!='' AND birth_date!='' AND raw_profile_id!=''
        GROUP BY document,birth_date HAVING COUNT(DISTINCT raw_profile_id)=1;
    """)
    anchors = conn.execute("""
        SELECT DISTINCT t.document,t.birth_date,t.full_name,u.pid
        FROM tickets t JOIN unique_doc_birth u
          ON t.document=u.document AND t.birth_date=u.birth_date
        WHERE t.raw_profile_id=u.pid AND t.full_name!=''
    """).fetchall()
    anchor_map = defaultdict(list)
    for anchor in anchors:
        anchor_map[anchor["document"], anchor["birth_date"]].append(
            (anchor["pid"], anchor["full_name"]))
    updates, identity_links = [], []
    for ticket in conn.execute("""
        SELECT ticket_key,document,birth_date,full_name FROM tickets
        WHERE raw_profile_id='' AND document!='' AND birth_date!='' AND full_name!=''
    """):
        options = anchor_map.get((ticket["document"], ticket["birth_date"]), [])
        matches = {pid for pid, name in options if name_equivalent(name, ticket["full_name"])}
        if len(matches) == 1:
            entity = "P:" + next(iter(matches))
            updates.append((entity, ticket["ticket_key"]))
            identity_links.append((ticket["ticket_key"], entity,
                                   "document_birth_equivalent_name",
                                   ticket["document"] + " / " + ticket["birth_date"] +
                                   " / " + ticket["full_name"]))
    conn.executemany("UPDATE tickets SET entity_id=? WHERE ticket_key=?", updates)
    conn.executemany("INSERT OR IGNORE INTO identity_links VALUES(?,?,?,?)", identity_links)
    conn.commit()

    events = []
    for row in checked_reader(input_dir / INPUTS["fact_flights"],
                              {"ProfileID", "flight_key", "Date", "Departure.Airport", "Arrival.Airport"}):
        pid, key = row["ProfileID"].strip(), norm(row["flight_key"])
        if pid and key:
            events.append(("P:" + pid, key, (row["Date"] or "").strip(),
                           norm(row["Departure.Airport"]), norm(row["Arrival.Airport"]),
                           "fact_flights:" + pid + ":" + key))
        if len(events) >= 10000:
            conn.executemany("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)", events)
            events.clear()
    conn.executemany("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)", events)
    conn.execute("""
        INSERT OR IGNORE INTO events
        SELECT entity_id,flight_key,departure_date,departure_airport,arrival_airport,
               'ticket:' || ticket_key FROM tickets
        WHERE flight_key!='' AND departure_date!='' AND arrival_airport!=''
    """)
    conn.executescript("""
        CREATE INDEX ix_events_flight ON events(flight_key);
        CREATE INDEX ix_events_destination ON events(departure_date,arrival_airport);
        CREATE INDEX ix_events_entity ON events(entity_id);
    """)
    conn.commit()
    links_path = output_dir / "identity_links.csv"
    write_rows(links_path, ["ticket_key", "entity_id", "method", "evidence"],
               (dict(row) for row in conn.execute("SELECT * FROM identity_links ORDER BY ticket_key")))
    conn.close()


def write_rows(path: Path, columns: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def signal(subject: str, related: list[str], kind: str, reason: str, evidence: dict,
           weight: int | None = None) -> dict:
    return {"subject_id": subject, "related_ids": json.dumps(sorted(set(related)), ensure_ascii=False),
            "signal": kind, "weight": weight if weight is not None else WEIGHTS[kind],
            "reason": reason, "evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True)}


def passport_collision(conn: sqlite3.Connection):
    for group in conn.execute("""
        SELECT document,COUNT(DISTINCT entity_id) n FROM tickets
        WHERE document!='' GROUP BY document HAVING n>1 ORDER BY document
    """):
        rows = conn.execute("""
            SELECT entity_id,full_name,birth_date,ticket_key FROM tickets
            WHERE document=? ORDER BY entity_id,ticket_key
        """, (group["document"],)).fetchall()
        births = {r["birth_date"] for r in rows if r["birth_date"]}
        names = {r["full_name"] for r in rows if r["full_name"]}
        birth_conflict = len(births) > 1
        name_conflict = any(not name_equivalent(a, b)
                            for a, b in itertools.combinations(sorted(names), 2))
        if not (birth_conflict or name_conflict):
            continue
        entities = sorted({r["entity_id"] for r in rows})
        evidence = {"document": group["document"], "birth_dates": sorted(births),
                    "names": sorted(names), "ticket_keys": [r["ticket_key"] for r in rows[:30]],
                    "total_ticket_records": len(rows)}
        reason = ("Один документ указан с разными датами рождения" if birth_conflict else
                  "Один документ указан с разными именами; возможны опечатка или транслитерация")
        for entity in entities:
            yield signal(entity, [x for x in entities if x != entity], "passport_collision",
                         reason, evidence, 8 if birth_conflict else 6)


def profile_conflict(conn: sqlite3.Connection):
    for row in conn.execute("SELECT * FROM profiles ORDER BY profile_id"):
        pid = row["profile_id"]
        tickets = conn.execute("""
            SELECT full_name,sex,birth_date,ticket_key FROM tickets
            WHERE raw_profile_id=? ORDER BY ticket_key
        """, (pid,)).fetchall()
        if not tickets:
            continue
        names = {r["full_name"] for r in tickets if r["full_name"]}
        if row["full_name"]:
            names.add(row["full_name"])
        sexes = {r["sex"] for r in tickets if r["sex"]}
        if row["sex"]:
            sexes.add(row["sex"])
        births = {r["birth_date"] for r in tickets if r["birth_date"]}
        conflicts = []
        if len(births) > 1:
            conflicts.append("разные даты рождения")
        if len(sexes) > 1:
            conflicts.append("разный пол")
        if any(not name_equivalent(a, b)
               for a, b in itertools.combinations(sorted(names), 2)):
            conflicts.append("разные имена")
        if conflicts:
            hard = len(births) > 1 or len(sexes) > 1
            yield signal("P:" + pid, [], "profile_conflict",
                         "В одном ProfileID: " + ", ".join(conflicts),
                         {"names": sorted(names), "birth_dates": sorted(births),
                          "sex_values": sorted(sexes),
                          "ticket_keys": [r["ticket_key"] for r in tickets[:30]],
                          "total_ticket_records": len(tickets)}, 7 if hard else 4)


def event_pairs(conn: sqlite3.Connection, query: str, max_group: int = 20):
    """Yield pairs within one bounded event group; skip mass routes/flights."""
    previous_key = None
    group = []
    for row in conn.execute(query):
        key = row["group_key"]
        if key != previous_key and group:
            if len(group) <= max_group:
                yield previous_key, group
            group = []
        group.append(row)
        previous_key = key
    if group and len(group) <= max_group:
        yield previous_key, group


def joint_travel(conn: sqlite3.Connection):
    pairs = defaultdict(set)
    refs = defaultdict(list)
    query = """
        SELECT flight_key group_key,entity_id,departure_date,source_ref FROM events
        WHERE flight_key!='' AND entity_id NOT LIKE 'T:%'
        ORDER BY flight_key,entity_id
    """
    for key, group in event_pairs(conn, query):
        for a, b in itertools.combinations(group, 2):
            pair = tuple(sorted((a["entity_id"], b["entity_id"])))
            if pair[0] == pair[1]:
                continue
            pairs[pair].add(key)
            if len(refs[pair]) < 10:
                refs[pair].append({"flight_key": key, "date": a["departure_date"]})
    for (a, b), flights in sorted(pairs.items()):
        if len(flights) >= 3:
            evidence = {"shared_flights": len(flights), "examples": refs[a, b]}
            reason = f"Совместные записи на {len(flights)} разных рейсах"
            yield signal(a, [b], "joint_travel", reason, evidence)
            yield signal(b, [a], "joint_travel", reason, evidence)


def document_entities(conn: sqlite3.Connection):
    """One document can have multiple entities; keep those separate."""
    for row in conn.execute("""
        SELECT DISTINCT document,entity_id FROM tickets WHERE document!=''
        ORDER BY document,entity_id
    """):
        yield row["document"], row["entity_id"]


def near_documents(conn: sqlite3.Connection, distance: int = 3):
    buckets = defaultdict(list)
    for doc, entity in document_entities(conn):
        if doc.isdigit() and len(doc) >= 8:
            prefix, suffix = doc[:-4], int(doc[-4:])
            buckets[(len(doc), prefix)].append((suffix, doc, entity))
    seen = set()
    for group in buckets.values():
        group.sort()
        for i, (number, doc, entity) in enumerate(group):
            for other_number, other_doc, other_entity in group[i + 1:]:
                delta = other_number - number
                if delta > distance:
                    break
                if not delta or entity == other_entity:
                    continue
                pair = tuple(sorted((entity, other_entity)))
                marker = (pair, tuple(sorted((doc, other_doc))))
                if marker not in seen:
                    seen.add(marker)
                    yield pair[0], pair[1], doc, other_doc, delta


def common_destinations(conn: sqlite3.Connection, a: str, b: str, different_flights=False) -> list[dict]:
    clause = "AND x.flight_key!=y.flight_key" if different_flights else ""
    rows = conn.execute(f"""
        SELECT DISTINCT x.departure_date day,x.arrival_airport destination,
               x.flight_key flight_a,y.flight_key flight_b
        FROM events x JOIN events y ON x.departure_date=y.departure_date
          AND x.arrival_airport=y.arrival_airport
        WHERE x.entity_id=? AND y.entity_id=? AND x.departure_date!=''
          AND x.arrival_airport!='' {clause}
        LIMIT 20
    """, (a, b)).fetchall()
    return [dict(row) for row in rows]


def near_passports_with_travel(conn: sqlite3.Connection):
    yielded = set()
    for a, b, doc_a, doc_b, delta in near_documents(conn):
        if (a, b) in yielded:
            continue
        shared = common_destinations(conn, a, b)
        if shared:
            yielded.add((a, b))
            evidence = {"documents": [doc_a, doc_b], "number_distance": delta,
                        "same_day_destinations": shared}
            reason = "Близкие номера документов и совпадающее направление в один день; страна/дата выдачи неизвестны"
            yield signal(a, [b], "near_passports_with_travel", reason, evidence)
            yield signal(b, [a], "near_passports_with_travel", reason, evidence)


def schedule_conflict(conn: sqlite3.Connection):
    # Same *origin* means times use the same local clock; no cross-zone inference.
    for group in conn.execute("""
        SELECT entity_id,departure_date,departure_airport,COUNT(*) n FROM tickets
        WHERE departure_date!='' AND departure_time!='' AND departure_airport!=''
          AND flight_key!='' AND entity_id NOT LIKE 'T:%'
        GROUP BY entity_id,departure_date,departure_airport HAVING n>1
    """):
        rows = conn.execute("""
            SELECT departure_time,flight_key,arrival_airport,ticket_key FROM tickets
            WHERE entity_id=? AND departure_date=? AND departure_airport=?
              AND departure_time!='' ORDER BY departure_time
        """, (group["entity_id"], group["departure_date"], group["departure_airport"])).fetchall()
        conflicts = []
        for a, b in itertools.combinations(rows, 2):
            try:
                ma = int(a["departure_time"][:2]) * 60 + int(a["departure_time"][3:5])
                mb = int(b["departure_time"][:2]) * 60 + int(b["departure_time"][3:5])
            except (ValueError, IndexError):
                continue
            if a["flight_key"] != b["flight_key"] and a["arrival_airport"] != b["arrival_airport"] and abs(ma-mb) <= 30:
                conflicts.append({"ticket_keys": [a["ticket_key"], b["ticket_key"]],
                                  "flight_keys": [a["flight_key"], b["flight_key"]],
                                  "times": [a["departure_time"], b["departure_time"]]})
        if conflicts:
            yield signal(group["entity_id"], [], "schedule_conflict",
                         "На одну личность оформлены рейсы из одного аэропорта в разные пункты с вылетом в пределах 30 минут; возможны две брони",
                         {"date": group["departure_date"], "origin": group["departure_airport"],
                          "examples": conflicts[:10], "total_conflicts": len(conflicts)})

    # Also detect physical in-flight overlaps: departure while previous flight is still in the air
    timetable_path = Path("data") / "dim_timetable.csv"
    durations = {}
    if timetable_path.exists():
        with timetable_path.open(newline="", encoding="utf-8-sig") as tf:
            for r in csv.DictReader(tf):
                fn = (r.get("flight_number") or "").strip().upper()
                tt = r.get("travel_time")
                if fn and tt:
                    try:
                        durations[fn] = float(tt)
                    except ValueError:
                        pass

    for ent_row in conn.execute("SELECT DISTINCT entity_id FROM tickets WHERE entity_id NOT LIKE 'T:%' AND departure_date!='' AND departure_time!=''"):
        ent = ent_row[0]
        flights = conn.execute("""
            SELECT ticket_key, flight_key, departure_date, departure_time, departure_airport, arrival_airport
            FROM tickets
            WHERE entity_id=? AND departure_date!='' AND departure_time!=''
            ORDER BY departure_date, departure_time
        """, (ent,)).fetchall()
        in_flight_conflicts = []
        for i in range(len(flights) - 1):
            f1, f2 = flights[i], flights[i+1]
            fn1 = f1["flight_key"].split("_")[0]
            dur1 = durations.get(fn1, 120.0)
            try:
                dt1 = datetime.strptime(f"{f1['departure_date']} {f1['departure_time'][:5]}", "%Y-%m-%d %H:%M")
                dt2 = datetime.strptime(f"{f2['departure_date']} {f2['departure_time'][:5]}", "%Y-%m-%d %H:%M")
                arr1 = dt1 + timedelta(minutes=dur1)
                if dt1 < dt2 < arr1:
                    overlap_mins = int((arr1 - dt2).total_seconds() / 60)
                    in_flight_conflicts.append({
                        "flight_1": f1["flight_key"], "dep_1": f1["departure_airport"], "arr_1": f1["arrival_airport"],
                        "time_1": str(dt1), "expected_arrival_1": str(arr1), "duration_1": dur1,
                        "flight_2": f2["flight_key"], "dep_2": f2["departure_airport"], "arr_2": f2["arrival_airport"],
                        "time_2": str(dt2), "overlap_minutes": overlap_mins
                    })
            except Exception:
                pass
        if in_flight_conflicts:
            yield signal(ent, [], "schedule_conflict",
                         f"Физический конфликт расписания: вылет следующего рейса оформлен во время нахождения в воздухе на предыдущем рейсе ({len(in_flight_conflicts)} эп.)",
                         {"conflicts": in_flight_conflicts[:5], "total_conflicts": len(in_flight_conflicts)},
                         weight=10)


def flight_anomaly(conn: sqlite3.Connection):
    anomalies_file = Path("results") / "flight_anomalies.csv"
    if not anomalies_file.exists():
        return
    anom_flights = {}
    with anomalies_file.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("is_overcapacity_flew") == "1" or r.get("is_overcapacity_booked") == "1":
                anom_flights[r["flight_key"]] = r
    if not anom_flights:
        return
    user_counts = dict(conn.execute("SELECT entity_id, COUNT(*) FROM events GROUP BY entity_id").fetchall())
    for fk, info in sorted(anom_flights.items()):
        passengers = conn.execute("SELECT entity_id FROM events WHERE flight_key=? AND entity_id NOT LIKE 'T:%'", (fk,)).fetchall()
        pids = [p["entity_id"] for p in passengers]
        flew = int(info["flew_count"])
        booked = int(info["booked_count"])
        cap = int(info["capacity_limit"])
        model = info["aircraft_model"] or info["aircraft_code"] or "борт"
        is_over_flew = info.get("is_overcapacity_flew") == "1"
        is_over_booked = info.get("is_overcapacity_booked") == "1"
        unbooked_pids = {"P:" + x for x in json.loads(info.get("unbooked_sample_profiles") or "[]")}
        for entity in pids:
            is_unbooked = entity in unbooked_pids
            user_cnt = user_counts.get(entity, 0)
            is_rare = user_cnt <= 8

            if is_over_flew and is_unbooked:
                weight = 3
                reason = f"Ручная посадка на рейс {fk} ({model}) с оверспейсом (людей {flew} при лимите {cap}) вне брони GDS. Требуется ручная проверка"
            elif is_over_flew:
                weight = 2
                reason = f"Пассажир находился на рейсе {fk} ({model}) с оверспейсом (людей {flew} при лимите {cap}). Вес снижен, требуется ручная проверка"
            elif is_unbooked and is_rare:
                weight = 2
                reason = f"Покупка билета на месте при редких перелётах ({user_cnt} перелётов) на рейсе {fk} ({model}) вне брони GDS"
            elif is_unbooked:
                weight = 1
                reason = f"Покупка билета на месте на регулярном маршруте на рейсе {fk} ({model})"
            elif is_over_booked:
                weight = 1
                reason = f"Рейс {fk} ({model}) со сверхлимитным овербукингом авиакомпании (продано {booked} при лимите {cap})"
            else:
                weight = 1
                reason = f"Аномалия рейса {fk}: несоответствие бронирований и перелётов"

            evidence = {
                "flight_key": fk,
                "flight_number": info["flight_number"],
                "flight_date": info["flight_date"],
                "departure_airport": info["departure_airport"],
                "arrival_airport": info["arrival_airport"],
                "aircraft_model": model,
                "capacity_limit": cap,
                "passengers_on_board": flew,
                "tickets_booked": booked,
                "unbooked_flyers_count": int(info["unbooked_flyers_count"]),
                "passenger_has_ticket": not is_unbooked,
                "anomaly_flags": info["anomaly_flags"],
                "is_over_flew": is_over_flew,
                "is_unbooked": is_unbooked,
                "is_rare_traveler": is_rare,
                "user_flight_count": user_cnt,
                "manual_review": is_over_flew,
                "manual_review_reason": "Оверспейс борта (число пассажиров превысило вместимость судна)" if is_over_flew else ""
            }
            yield signal(entity, [x for x in pids[:10] if x != entity], "flight_anomaly", reason, evidence, weight)


PRIMARY_GENERATORS = {
    "passport_collision": passport_collision,
    "profile_conflict": profile_conflict,
    "joint_travel": joint_travel,
    "near_passports_with_travel": near_passports_with_travel,
    "schedule_conflict": schedule_conflict,
    "flight_anomaly": flight_anomaly,
}


def run_signal(name: str, output_dir: Path) -> int:
    conn = connect(output_dir / "index.sqlite")
    count = write_rows(output_dir / SIGNAL_FILES[name], SIGNAL_COLUMNS, PRIMARY_GENERATORS[name](conn))
    conn.close()
    return count


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def enrich_candidates(output_dir: Path, rows: list[dict]) -> None:
    conn = connect(output_dir / "index.sqlite")
    for row in rows:
        entity = row["candidate_id"]
        row["profile_id"] = entity[2:] if entity.startswith("P:") else ""
        records = conn.execute("""
            SELECT full_name,birth_date,document,ticket_key FROM tickets
            WHERE entity_id=? ORDER BY ticket_key LIMIT 200
        """, (entity,)).fetchall()
        profile = conn.execute("SELECT full_name FROM profiles WHERE profile_id=?",
                               (row["profile_id"],)).fetchone() if row["profile_id"] else None
        names = {r["full_name"] for r in records if r["full_name"]}
        if profile and profile["full_name"]:
            names.add(profile["full_name"])
        row["names_json"] = json.dumps(sorted(names), ensure_ascii=False)
        row["birth_dates_json"] = json.dumps(sorted({r["birth_date"] for r in records
                                                      if r["birth_date"]}), ensure_ascii=False)
        row["documents_json"] = json.dumps(sorted({r["document"] for r in records
                                                    if r["document"]}), ensure_ascii=False)
        row["ticket_keys_json"] = json.dumps([r["ticket_key"] for r in records[:30]], ensure_ascii=False)
        row["ticket_count"] = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE entity_id=?", (entity,)).fetchone()[0]
    conn.close()


def score_primary(output_dir: Path, threshold: int = 8) -> None:
    evidence = defaultdict(lambda: defaultdict(list))
    for name, filename in SIGNAL_FILES.items():
        path = output_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Run signal {name} first: {path}")
        for row in read_csv(path):
            evidence[row["subject_id"]][row["signal"]].append(row)
    all_rows, seeds, manual_review_rows = [], [], []
    for entity, types in sorted(evidence.items()):
        total = sum(max(int(r["weight"]) for r in records) for records in types.values())
        has_over_flew = False
        for records in types.get("flight_anomaly", []):
            try:
                ev = json.loads(records.get("evidence_json") or "{}")
                if ev.get("is_over_flew") or ev.get("manual_review"):
                    has_over_flew = True
                    break
            except Exception:
                pass

        reasons = [{"signal": kind, "max_weight": max(int(r["weight"]) for r in records),
                    "occurrences": len(records), "details": [
                        {"reason": r["reason"], "related_ids": json.loads(r["related_ids"]),
                         "evidence": json.loads(r["evidence_json"])} for r in records[:20]]}
                   for kind, records in sorted(types.items())]
        related = sorted({other for records in types.values() for r in records
                          for other in json.loads(r["related_ids"])})

        if total >= threshold:
            stage = "primary_signal"
        elif has_over_flew:
            stage = "manual_review"
        else:
            stage = "below_threshold"

        row = {"candidate_id": entity, "stage": stage,
               "score": total, "signal_types": json.dumps(sorted(types), ensure_ascii=False),
               "reasons_json": json.dumps(reasons, ensure_ascii=False),
               "related_ids": json.dumps(related, ensure_ascii=False),
               "promotion_round": 0, "parent_ids": "[]"}
        all_rows.append(row)
        if total >= threshold:
            seeds.append(row)
        if has_over_flew:
            manual_review_rows.append(row)

    enrich_candidates(output_dir, all_rows)
    enrich_candidates(output_dir, manual_review_rows)
    write_rows(output_dir / "primary_scores_all.csv", PRIMARY_COLUMNS, all_rows)
    write_rows(output_dir / "primary_candidates.csv", PRIMARY_COLUMNS, seeds)
    write_rows(output_dir / "manual_review_candidates.csv", PRIMARY_COLUMNS, manual_review_rows)


def secondary_near_passport(conn: sqlite3.Connection):
    for a, b, doc_a, doc_b, delta in near_documents(conn):
        yield (a, b, "near_passport", "Близкие номера документов; требуется независимое подтверждение",
               {"documents": [doc_a, doc_b], "number_distance": delta})


def pair_groups(conn: sqlite3.Connection, query: str, signal_name: str,
                min_groups: int, predicate=None):
    pairs = defaultdict(set)
    examples = defaultdict(list)
    for key, group in event_pairs(conn, query, max_group=12):
        for a, b in itertools.combinations(group, 2):
            left, right = a["entity_id"], b["entity_id"]
            if left == right or (predicate and not predicate(a, b)):
                continue
            pair = tuple(sorted((left, right)))
            pairs[pair].add(key)
            if len(examples[pair]) < 10:
                examples[pair].append(key)
    for (a, b), keys in sorted(pairs.items()):
        if len(keys) >= min_groups:
            yield (a, b, signal_name,
                   f"Совпадение по {len(keys)} разным эпизодам: {signal_name}",
                   {"count": len(keys), "examples": examples[a, b]})


def secondary_shared_pnr(conn: sqlite3.Connection):
    query = """
        SELECT pnr group_key,entity_id,flight_key FROM tickets
        WHERE pnr!='' AND entity_id NOT LIKE 'T:%'
        GROUP BY pnr,entity_id ORDER BY pnr,entity_id
    """
    yield from pair_groups(conn, query, "shared_pnr", 2)


def secondary_parallel_arrivals(conn: sqlite3.Connection):
    query = """
        SELECT departure_date || ':' || arrival_airport group_key,entity_id,flight_key
        FROM events WHERE departure_date!='' AND arrival_airport!=''
          AND entity_id NOT LIKE 'T:%'
        GROUP BY group_key,entity_id,flight_key ORDER BY group_key,entity_id
    """
    yield from pair_groups(conn, query, "parallel_arrivals", 2,
                           lambda a, b: a["flight_key"] != b["flight_key"])


def secondary_convergence(conn: sqlite3.Connection):
    query = """
        SELECT departure_date || ':' || arrival_airport group_key,entity_id,
               departure_airport,flight_key FROM events
        WHERE departure_date!='' AND arrival_airport!='' AND departure_airport!=''
          AND entity_id NOT LIKE 'T:%'
        GROUP BY group_key,entity_id,departure_airport,flight_key
        ORDER BY group_key,entity_id
    """
    yield from pair_groups(conn, query, "convergence", 2,
                           lambda a, b: a["departure_airport"] != b["departure_airport"])


SECONDARY_GENERATORS = {
    "near_passport": secondary_near_passport,
    "shared_pnr": secondary_shared_pnr,
    "parallel_arrivals": secondary_parallel_arrivals,
    "convergence": secondary_convergence,
}


def run_secondary_signal(name: str, output_dir: Path) -> int:
    conn = connect(output_dir / "index.sqlite")

    def rows():
        for a, b, kind, reason, evidence in SECONDARY_GENERATORS[name](conn):
            yield signal(a, [b], kind, reason, evidence)
            yield signal(b, [a], kind, reason, evidence)

    count = write_rows(output_dir / SECONDARY_FILES[name], SIGNAL_COLUMNS, rows())
    conn.close()
    return count


def expand_secondary(output_dir: Path, min_score: int = 5,
                     min_types: int = 2, max_rounds: int = 3) -> None:
    seed_rows = list(read_csv(output_dir / "primary_candidates.csv"))
    known = {row["candidate_id"]: row for row in seed_rows}
    original_seeds = set(known)
    # Build only direct entity-to-entity edges. They never merge identities.
    edges = defaultdict(list)
    dedupe = set()
    for name, filename in SECONDARY_FILES.items():
        path = output_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Run secondary signal {name} first: {path}")
        for row in read_csv(path):
            a = row["subject_id"]
            related = json.loads(row["related_ids"])
            if len(related) != 1:
                continue
            b = related[0]
            pair = tuple(sorted((a, b)))
            marker = (pair, row["signal"])
            if marker in dedupe:
                continue
            dedupe.add(marker)
            edge = {"a": a, "b": b, "signal": row["signal"], "weight": int(row["weight"]),
                    "reason": row["reason"], "evidence": json.loads(row["evidence_json"])}
            edges[a].append(edge)
            edges[b].append(edge)

    all_links = []
    recorded_links = set()
    candidates = {}
    for round_num in range(1, max_rounds + 1):
        promotions = []
        for entity in sorted(edges):
            if entity in known:
                continue
            relevant = [e for e in edges[entity]
                        if (e["b"] if e["a"] == entity else e["a"]) in known]
            if not relevant:
                continue
            # Cap each sign type, retaining the strongest evidence and links.
            kinds = sorted({e["signal"] for e in relevant})
            score = sum(WEIGHTS[kind] for kind in kinds)
            parents = sorted({e["b"] if e["a"] == entity else e["a"] for e in relevant})
            promoted = score >= min_score and len(kinds) >= min_types
            reasons = []
            for e in relevant:
                anchor = e["b"] if e["a"] == entity else e["a"]
                detail = {"anchor_id": anchor, "signal": e["signal"], "weight": e["weight"],
                          "reason": e["reason"], "evidence": e["evidence"]}
                reasons.append(detail)
                link_key = (entity, anchor, e["signal"])
                if link_key not in recorded_links:
                    recorded_links.add(link_key)
                    all_links.append({"candidate_id": entity, "anchor_id": anchor,
                                      "signal": e["signal"], "weight": e["weight"],
                                      "reason": e["reason"],
                                      "evidence_json": json.dumps(e["evidence"], ensure_ascii=False),
                                      "round": round_num, "link_stage": "secondary"})
            row = {"candidate_id": entity,
                   "stage": "promoted_secondary" if promoted else "secondary_review",
                   "score": score, "signal_types": json.dumps(kinds, ensure_ascii=False),
                   "reasons_json": json.dumps(reasons, ensure_ascii=False),
                   "related_ids": json.dumps(parents, ensure_ascii=False),
                   "promotion_round": round_num if promoted else "",
                   "parent_ids": json.dumps(parents, ensure_ascii=False)}
            candidates[entity] = row
            if promoted:
                promotions.append(row)
        if not promotions:
            break
        for row in promotions:
            known[row["candidate_id"]] = row
    final = list(seed_rows) + [row for key, row in sorted(known.items()) if key not in original_seeds]
    secondary_rows = [row for key, row in sorted(candidates.items())]
    enrich_candidates(output_dir, secondary_rows)
    write_rows(output_dir / "secondary_candidates.csv", PRIMARY_COLUMNS, secondary_rows)
    write_rows(output_dir / "secondary_links.csv", EDGE_COLUMNS, all_links)
    enrich_candidates(output_dir, final)
    write_rows(output_dir / "primary_candidates_final.csv", PRIMARY_COLUMNS, final)
    graph_edges = [row for row in all_links if row["candidate_id"] in known]
    primary_edges_seen = set()
    for filename in SIGNAL_FILES.values():
        for row in read_csv(output_dir / filename):
            a = row["subject_id"]
            if a not in known:
                continue
            for b in json.loads(row["related_ids"]):
                if b not in known or a == b:
                    continue
                marker = (tuple(sorted((a, b))), row["signal"])
                if marker in primary_edges_seen:
                    continue
                primary_edges_seen.add(marker)
                graph_edges.append({"candidate_id": a, "anchor_id": b,
                                    "signal": row["signal"], "weight": row["weight"],
                                    "reason": row["reason"], "evidence_json": row["evidence_json"],
                                    "round": 0, "link_stage": "primary"})
    # This includes initial pair links and later promotion links.
    write_rows(output_dir / "chain_edges.csv", EDGE_COLUMNS, graph_edges)


def run_primary_pipeline(input_dir: Path, output_dir: Path, threshold: int = 8) -> None:
    db = output_dir / "index.sqlite"
    if not db.exists():
        print("1/3 Подготовка индекса (prepare)...", flush=True)
        prepare(input_dir, output_dir)
    else:
        print("1/3 Индекс уже существует, пропускаем prepare", flush=True)
    print("2/3 Расчёт первичных признаков...", flush=True)
    for name in SIGNAL_FILES:
        count = run_signal(name, output_dir)
        print(f"  • {name}: {count} записей", flush=True)
    print(f"3/3 Подсчёт первичных баллов (порог: {threshold})...", flush=True)
    score_primary(output_dir, threshold)
    print("Первичный этап успешно завершён.", flush=True)


def run_expand_pipeline(input_dir: Path | None, output_dir: Path,
                        min_score: int = 5, min_types: int = 2,
                        max_rounds: int = 3, threshold: int = 8) -> None:
    if not (output_dir / "primary_candidates.csv").exists():
        if not input_dir:
            raise ValueError("Для первичного расчёта требуется указать --input-dir")
        print("Первичные кандидаты не найдены. Запуск первичного этапа...", flush=True)
        run_primary_pipeline(input_dir, output_dir, threshold)
    print("1/2 Расчёт вторичных признаков...", flush=True)
    for name in SECONDARY_FILES:
        count = run_secondary_signal(name, output_dir)
        print(f"  • {name}: {count} записей", flush=True)
    print(f"2/2 Расширение связей (мин. балл: {min_score}, типов: {min_types}, раундов: {max_rounds})...", flush=True)
    expand_secondary(output_dir, min_score, min_types, max_rounds)
    print("Вторичное расширение успешно завершено.", flush=True)


def run_all_pipeline(input_dir: Path, output_dir: Path,
                     threshold: int = 8, min_score: int = 5,
                     min_types: int = 2, max_rounds: int = 3) -> None:
    print("=== ЭТАП 1: Подготовка индекса ===", flush=True)
    prepare(input_dir, output_dir)
    print("=== ЭТАП 2: Первичные признаки ===", flush=True)
    for name in SIGNAL_FILES:
        count = run_signal(name, output_dir)
        print(f"  • {name}: {count} записей", flush=True)
    print(f"=== ЭТАП 3: Скоринг первичных кандидатов (порог: {threshold}) ===", flush=True)
    score_primary(output_dir, threshold)
    print("=== ЭТАП 4: Вторичные признаки ===", flush=True)
    for name in SECONDARY_FILES:
        count = run_secondary_signal(name, output_dir)
        print(f"  • {name}: {count} записей", flush=True)
    print(f"=== ЭТАП 5: Расширение связей (порог: {min_score}, типов: {min_types}, раундов: {max_rounds}) ===", flush=True)
    expand_secondary(output_dir, min_score, min_types, max_rounds)
    print("=== Полный расчёт успешно завершён! ===", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--input-dir", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    for name in SIGNAL_FILES:
        sub.add_parser(name).add_argument("--output-dir", type=Path, required=True)
    for name in SECONDARY_FILES:
        sub.add_parser(name).add_argument("--output-dir", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--output-dir", type=Path, required=True)
    score.add_argument("--threshold", type=int, default=8)

    prim = sub.add_parser("primary")
    prim.add_argument("--input-dir", type=Path, required=True)
    prim.add_argument("--output-dir", type=Path, required=True)
    prim.add_argument("--threshold", type=int, default=8)

    expand = sub.add_parser("expand")
    expand.add_argument("--output-dir", type=Path, required=True)
    expand.add_argument("--input-dir", type=Path, default=None)
    expand.add_argument("--min-score", type=int, default=5)
    expand.add_argument("--min-types", type=int, default=2)
    expand.add_argument("--max-rounds", type=int, default=3)
    expand.add_argument("--threshold", type=int, default=8)

    all_cmd = sub.add_parser("all")
    all_cmd.add_argument("--input-dir", type=Path, required=True)
    all_cmd.add_argument("--output-dir", type=Path, required=True)
    all_cmd.add_argument("--threshold", type=int, default=8)
    all_cmd.add_argument("--min-score", type=int, default=5)
    all_cmd.add_argument("--min-types", type=int, default=2)
    all_cmd.add_argument("--max-rounds", type=int, default=3)

    run = sub.add_parser("run")
    run.add_argument("--input-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--threshold", type=int, default=8)
    run.add_argument("--min-score", type=int, default=5)
    run.add_argument("--min-types", type=int, default=2)
    run.add_argument("--max-rounds", type=int, default=3)

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.input_dir, args.output_dir)
    elif args.command in SIGNAL_FILES:
        print(args.command, run_signal(args.command, args.output_dir))
    elif args.command in SECONDARY_FILES:
        print(args.command, run_secondary_signal(args.command, args.output_dir))
    elif args.command == "score":
        score_primary(args.output_dir, args.threshold)
    elif args.command == "primary":
        run_primary_pipeline(args.input_dir, args.output_dir, args.threshold)
    elif args.command == "expand":
        if args.input_dir or not (args.output_dir / "06_near_passport.csv").exists():
            run_expand_pipeline(args.input_dir, args.output_dir, args.min_score, args.min_types, args.max_rounds, args.threshold)
        else:
            expand_secondary(args.output_dir, args.min_score, args.min_types, args.max_rounds)
    elif args.command in ("run", "all"):
        run_all_pipeline(args.input_dir, args.output_dir, args.threshold,
                         getattr(args, "min_score", 5),
                         getattr(args, "min_types", 2),
                         getattr(args, "max_rounds", 3))


if __name__ == "__main__":
    main()
