"""Generate flight occupancy and anomaly detection table.

Matches registered bookings (fact_tickets) vs actual flyers (fact_flights)
and applies aircraft capacity limits from airplanes.csv.

Flags:
1. OVERCAPACITY_FLEW: actual passengers on board exceed aircraft maximum capacity.
2. OVERCAPACITY_BOOKED: tickets booked exceed aircraft maximum capacity.
3. NO_TICKETS_FLIGHT: flight completed, but 0 tickets found in booking database.
4. UNBOOKED_PASSENGERS: specific passengers flew on flight without a ticket.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, Counter
from pathlib import Path


DEFAULT_CAPACITY = 90


AIRLINE_NAMES = {
    "SU": "Аэрофлот (Aeroflot)",
    "DL": "Delta Air Lines",
    "AF": "Air France",
    "KL": "KLM Royal Dutch Airlines",
    "KQ": "Kenya Airways",
    "UX": "Air Europa",
    "CZ": "China Southern",
    "MU": "China Eastern",
    "AM": "Aeromexico",
    "AZ": "Alitalia",
    "OK": "Czech Airlines",
    "RO": "TAROM",
    "GA": "Garuda Indonesia",
    "ME": "Middle East Airlines",
    "SV": "Saudia",
    "VN": "Vietnam Airlines",
    "MF": "Xiamen Airlines",
    "AR": "Aerolineas Argentinas",
    "CI": "China Airlines",
    "S7": "Siberia Airlines (S7)",
}


def build_timetable_lookup(timetable_path: Path) -> dict[str, dict]:
    """Load flight_number -> {aircraft, operated_by} from dim_timetable.csv."""
    lookup = {}
    if not timetable_path.is_file():
        return lookup
    with timetable_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_fn = (row.get("flight_number") or "").strip().upper()
            fn = raw_fn.rstrip("*").strip()
            ac = (row.get("aircraft") or "").strip().upper()
            op = (row.get("operated_by") or "").strip()
            if op.startswith("Operated by:"):
                op = op[len("Operated by:"):].strip()
            entry = {"aircraft": ac, "operated_by": op}
            if fn and fn not in lookup:
                lookup[fn] = entry
            if raw_fn and raw_fn not in lookup:
                lookup[raw_fn] = entry
    return lookup


def get_airline_info(fn: str, timetable_lookup: dict[str, dict]) -> tuple[str, str, str]:
    prefix = fn[:2]
    mkt = AIRLINE_NAMES.get(prefix, f"Авиакомпания {prefix}")
    tt_entry = timetable_lookup.get(fn, {})
    op_raw = tt_entry.get("operated_by", "")
    op = op_raw if op_raw else mkt
    if op_raw and op_raw != mkt:
        display = f"{op_raw} (код {mkt})"
    else:
        display = op
    return op, mkt, display


def build_airplanes_lookup(airplanes_path: Path) -> dict[str, dict]:
    """Load Code -> {model, max_capacity} from airplanes.csv."""
    lookup = {}
    if not airplanes_path.is_file():
        return lookup
    with airplanes_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("Code") or "").strip().upper()
            model = (row.get("Model") or "").strip()
            try:
                cap = int(row.get("Max_Capacity") or 0)
            except ValueError:
                cap = 0
            if code:
                lookup[code] = {"model": model, "max_capacity": cap}

    # Standard variants & aliases mapping
    aliases = {
        "32A": "320",   # Airbus A320 with Sharklets (180 seats)
        "32B": "321",   # Airbus A321 with Sharklets (240 seats)
        "73M": "738",   # Boeing 737 MAX 8 (189 seats)
        "7M8": "738",   # Boeing 737 MAX 8 (189 seats)
        "789": "787",   # Boeing 787-9 (440 seats)
        "350": "333",   # Airbus A350-900 (440 seats)
        "359": "333",   # Airbus A350-900 (440 seats)
        "E7W": "E75",   # Embraer 175 with winglets (88 seats)
        "AT4": "AT5",   # ATR 42-500 (50 seats)
    }
    for alias, target in aliases.items():
        if alias not in lookup and target in lookup:
            lookup[alias] = {
                "model": f"{lookup[target]['model']} (variant {alias})",
                "max_capacity": lookup[target]["max_capacity"]
            }

    known_extras = {
        "DH3": {"model": "De Havilland DHC-8-300 Dash 8", "max_capacity": 50},
        "DH2": {"model": "De Havilland DHC-8-200 Dash 8", "max_capacity": 37},
        "DH1": {"model": "De Havilland DHC-8-100 Dash 8", "max_capacity": 37},
        "DHC": {"model": "De Havilland Dash 8 Series", "max_capacity": 50},
    }
    for code, info in known_extras.items():
        if code not in lookup:
            lookup[code] = info

    return lookup


def generate_flight_occupancy(
    input_dir: Path,
    output_dir: Path,
    default_capacity: int = DEFAULT_CAPACITY,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timetable_lookup = build_timetable_lookup(input_dir / "dim_timetable.csv")
    airplanes_lookup = build_airplanes_lookup(input_dir / "airplanes.csv")
    print(f"Загружено моделей самолётов из airplanes.csv: {len(airplanes_lookup)}")

    print("Шаг 1: Сканирование fact_flights (реальные перелёты)...")
    flight_data = {}
    with (input_dir / "fact_flights.csv").open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            fk = (row.get("flight_key") or "").strip().upper()
            if not fk:
                continue
            pid = (row.get("ProfileID") or "").strip()
            status = (row.get("STATUS") or "").strip().upper()

            if fk not in flight_data:
                fn = (row.get("Flight") or "").strip().upper() or fk.split("_")[0]
                tt_entry = timetable_lookup.get(fn, {})
                ac_code = tt_entry.get("aircraft", "")
                op_airline, mkt_airline, airline_disp = get_airline_info(fn, timetable_lookup)
                plane_info = airplanes_lookup.get(ac_code)
                flight_data[fk] = {
                    "flight_key": fk,
                    "flight_number": fn,
                    "flight_date": (row.get("Date") or "").strip(),
                    "departure_airport": (row.get("Departure.Airport") or "").strip().upper(),
                    "arrival_airport": (row.get("Arrival.Airport") or "").strip().upper(),
                    "operating_airline": op_airline,
                    "marketing_airline": mkt_airline,
                    "airline_display": airline_disp,
                    "aircraft_code": ac_code,
                    "aircraft_model": plane_info["model"] if plane_info else "",
                    "max_capacity": plane_info["max_capacity"] if (plane_info and plane_info["max_capacity"] > 0) else default_capacity,
                    "capacity_source": "airplanes.csv" if (plane_info and plane_info["max_capacity"] > 0) else f"default_{default_capacity}",
                    "flew_profiles": set(),
                    "flew_count": 0,
                    "landed_count": 0,
                    "booked_profiles": set(),
                    "booked_count": 0,
                }
            item = flight_data[fk]
            item["flew_count"] += 1
            if status == "LANDED":
                item["landed_count"] += 1
            if pid:
                item["flew_profiles"].add(pid)

            if i > 0 and i % 300000 == 0:
                print(f"  обработано {i:,} строк fact_flights...")

    print(f"  Всего уникальных совершенных рейсов: {len(flight_data):,}")

    print("Шаг 2: Сканирование fact_tickets (бронирования и билеты)...")
    with (input_dir / "fact_tickets.csv").open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            fk = (row.get("flight_key") or "").strip().upper()
            if not fk:
                continue
            pid = (row.get("ProfileID") or "").strip()

            if fk not in flight_data:
                # Билет был оформлен, но рейс отсутствует в fact_flights
                fn = fk.split("_")[0] if "_" in fk else ""
                tt_entry = timetable_lookup.get(fn, {})
                ac_code = tt_entry.get("aircraft", "")
                op_airline, mkt_airline, airline_disp = get_airline_info(fn, timetable_lookup)
                plane_info = airplanes_lookup.get(ac_code)
                flight_data[fk] = {
                    "flight_key": fk,
                    "flight_number": fn,
                    "flight_date": (row.get("departure_date") or "").strip(),
                    "departure_airport": (row.get("departure_airport") or "").strip().upper(),
                    "arrival_airport": (row.get("arrival_airport") or "").strip().upper(),
                    "operating_airline": op_airline,
                    "marketing_airline": mkt_airline,
                    "airline_display": airline_disp,
                    "aircraft_code": ac_code,
                    "aircraft_model": plane_info["model"] if plane_info else "",
                    "max_capacity": plane_info["max_capacity"] if (plane_info and plane_info["max_capacity"] > 0) else default_capacity,
                    "capacity_source": "airplanes.csv" if (plane_info and plane_info["max_capacity"] > 0) else f"default_{default_capacity}",
                    "flew_profiles": set(),
                    "flew_count": 0,
                    "landed_count": 0,
                    "booked_profiles": set(),
                    "booked_count": 0,
                }
            item = flight_data[fk]
            item["booked_count"] += 1
            if pid:
                item["booked_profiles"].add(pid)

            if i > 0 and i % 300000 == 0:
                print(f"  обработано {i:,} строк fact_tickets...")

    print("Шаг 3: Выявление аномалий и сохранение...")
    csv_file = output_dir / "flight_occupancy.csv"
    anomalies_file = output_dir / "flight_anomalies.csv"
    critical_file = output_dir / "flight_critical_anomalies.csv"
    summary_file = output_dir / "flight_occupancy_summary.json"

    fieldnames = [
        "flight_key", "flight_number", "flight_date",
        "departure_airport", "arrival_airport",
        "operating_airline", "marketing_airline", "airline_display",
        "aircraft_code", "aircraft_model", "capacity_limit", "capacity_source",
        "booked_count", "flew_count", "landed_count",
        "unbooked_flyers_count", "booked_no_show_count",
        "is_overcapacity_flew", "is_overcapacity_booked", "is_unbooked_flight",
        "anomaly_flags", "unbooked_sample_profiles"
    ]

    total_rows = 0
    anomaly_rows = 0
    over_flew_rows = 0
    over_booked_rows = 0
    no_tickets_rows = 0
    unbooked_flyers_total_rows = 0
    critical_rows = 0

    airport_cities = {}
    with (input_dir / "dim_timetable.csv").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fc = (row.get("from_code") or "").strip().upper()
            tc = (row.get("to_code") or "").strip().upper()
            if fc and fc not in airport_cities:
                airport_cities[fc] = (row.get("from_city") or "").strip()
            if tc and tc not in airport_cities:
                airport_cities[tc] = (row.get("to_city") or "").strip()

    company_agg = defaultdict(lambda: {
        "name": "", "marketing": "", "total_anom_flights": 0,
        "overcapacity_flew": 0, "overcapacity_booked": 0,
        "unbooked_passengers": 0, "extra_pax_flew": 0
    })
    dep_agg = Counter()
    arr_agg = Counter()
    dep_flights = Counter()
    arr_flights = Counter()
    route_agg = Counter()
    route_flights = Counter()
    route_airline = {}

    with csv_file.open("w", newline="", encoding="utf-8-sig") as out_all, \
         anomalies_file.open("w", newline="", encoding="utf-8-sig") as out_anom, \
         critical_file.open("w", newline="", encoding="utf-8-sig") as out_crit:

        writer_all = csv.DictWriter(out_all, fieldnames=fieldnames)
        writer_all.writeheader()
        writer_anom = csv.DictWriter(out_anom, fieldnames=fieldnames)
        writer_anom.writeheader()
        writer_crit = csv.DictWriter(out_crit, fieldnames=fieldnames)
        writer_crit.writeheader()

        for fk, d in flight_data.items():
            flew = d["flew_count"]
            booked = d["booked_count"]
            flew_profs = d["flew_profiles"]
            booked_profs = d["booked_profiles"]
            capacity = d["max_capacity"]

            # Пассажиры, которые полетели, но не имели билета на рейс с этим ProfileID
            unbooked_flyers = flew_profs - booked_profs
            # Пассажиры, купившие билет, но не зафиксированные в fact_flights
            no_show_profs = booked_profs - flew_profs

            flags = []
            is_over_flew = 1 if flew > capacity else 0
            if is_over_flew:
                flags.append("OVERCAPACITY_FLEW")
                over_flew_rows += 1

            is_over_booked = 1 if booked > capacity else 0
            if is_over_booked:
                flags.append("OVERCAPACITY_BOOKED")
                over_booked_rows += 1

            is_no_tix = 1 if (flew > 0 and booked == 0) else 0
            if is_no_tix:
                flags.append("NO_TICKETS_FLIGHT")
                no_tickets_rows += 1

            if len(unbooked_flyers) > 0:
                flags.append(f"UNBOOKED_PASSENGERS_{len(unbooked_flyers)}")
                unbooked_flyers_total_rows += 1

            row_out = {
                "flight_key": d["flight_key"],
                "flight_number": d["flight_number"],
                "flight_date": d["flight_date"],
                "departure_airport": d["departure_airport"],
                "arrival_airport": d["arrival_airport"],
                "operating_airline": d["operating_airline"],
                "marketing_airline": d["marketing_airline"],
                "airline_display": d["airline_display"],
                "aircraft_code": d["aircraft_code"],
                "aircraft_model": d["aircraft_model"],
                "capacity_limit": capacity,
                "capacity_source": d["capacity_source"],
                "booked_count": booked,
                "flew_count": flew,
                "landed_count": d["landed_count"],
                "unbooked_flyers_count": len(unbooked_flyers),
                "booked_no_show_count": len(no_show_profs),
                "is_overcapacity_flew": is_over_flew,
                "is_overcapacity_booked": is_over_booked,
                "is_unbooked_flight": is_no_tix,
                "anomaly_flags": ";".join(flags) if flags else "NORMAL",
                "unbooked_sample_profiles": json.dumps(sorted(list(unbooked_flyers))[:10])
            }

            writer_all.writerow(row_out)
            total_rows += 1

            if flags:
                writer_anom.writerow(row_out)
                anomaly_rows += 1

            # Критические аномалии (физический перегруз или овербукинг или массовые безбилетники)
            if is_over_flew or is_over_booked or len(unbooked_flyers) > 10:
                writer_crit.writerow(row_out)
                critical_rows += 1

                comp = d["operating_airline"]
                c = company_agg[comp]
                c["name"] = comp
                c["marketing"] = d["marketing_airline"]
                c["total_anom_flights"] += 1
                if is_over_flew:
                    c["overcapacity_flew"] += 1
                    c["extra_pax_flew"] += max(0, flew - capacity)
                if is_over_booked:
                    c["overcapacity_booked"] += 1
                c["unbooked_passengers"] += len(unbooked_flyers)

                dep = d["departure_airport"]
                arr = d["arrival_airport"]
                unb = len(unbooked_flyers)
                dep_agg[dep] += unb
                arr_agg[arr] += unb
                dep_flights[dep] += 1
                arr_flights[arr] += 1
                r = f"{dep} → {arr}"
                route_agg[r] += unb
                route_flights[r] += 1
                route_airline[r] = comp

    summary_stats = {
        "total_flights": total_rows,
        "anomaly_flights": anomaly_rows,
        "overcapacity_flew": over_flew_rows,
        "overcapacity_booked": over_booked_rows,
        "no_tickets_count": no_tickets_rows,
        "critical_flights": critical_rows,
        "companies": sorted(company_agg.values(), key=lambda x: (x["overcapacity_flew"], x["unbooked_passengers"]), reverse=True),
        "airports_departure": [
            {"code": ap, "city": airport_cities.get(ap, ap), "unbooked_passengers": dep_agg[ap], "anom_flights": dep_flights[ap]}
            for ap, _ in dep_agg.most_common(15)
        ],
        "airports_arrival": [
            {"code": ap, "city": airport_cities.get(ap, ap), "unbooked_passengers": arr_agg[ap], "anom_flights": arr_flights[ap]}
            for ap, _ in arr_agg.most_common(15)
        ],
        "top_routes": [
            {
                "route": r,
                "city_from": airport_cities.get(r.split(" → ")[0], ""),
                "city_to": airport_cities.get(r.split(" → ")[1], ""),
                "unbooked_passengers": route_agg[r],
                "anom_flights": route_flights[r],
                "airline": route_airline.get(r, "")
            }
            for r, _ in route_agg.most_common(12)
        ]
    }
    with summary_file.open("w", encoding="utf-8") as sf:
        json.dump(summary_stats, sf, ensure_ascii=False, indent=2)

    print("\n--- Результаты анализа с учетом airplanes.csv ---")
    print(f"Всего проанализировано рейсов: {total_rows:,}")
    print(f"Рейсов с аномалиями: {anomaly_rows:,}")
    print(f" • Физический перегруз борта (flew > вместимости): {over_flew_rows:,}")
    print(f" • Овербукинг (билетов продано > вместимости): {over_booked_rows:,}")
    print(f" • Рейс состоялся, но 0 билетов в базе: {no_tickets_rows:,}")
    print(f" • Рейсов с пассажирами без билета: {unbooked_flyers_total_rows:,}")
    print(f"Полная таблица сохранена в: {csv_file}")
    print(f"Таблица только аномальных рейсов сохранена в: {anomalies_file}")
    print(f"Таблица критических аномалий: {critical_file}")
    print(f"Сводная статистика JSON сохранена в: {summary_file}")

    return csv_file, anomalies_file


def generate_flight_anomaly_signal(data_dir: Path, results_dir: Path) -> Path:
    """Generate 10_flight_anomaly.csv signal from critical anomaly flights."""
    critical_path = results_dir / "flight_critical_anomalies.csv"
    anomalies_path = results_dir / "flight_anomalies.csv"
    source_path = critical_path if critical_path.exists() else anomalies_path
    if not source_path.exists():
        print("Файл аномалий не найден для генерации сигнала")
        return results_dir / "10_flight_anomaly.csv"

    anom_flights = {}
    with source_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fk = row["flight_key"]
            if row.get("is_overcapacity_flew") == "1" or row.get("is_overcapacity_booked") == "1":
                anom_flights[fk] = row

    print(f"Генерация сигнала по {len(anom_flights)} критическим рейсам...")
    flight_passengers = defaultdict(list)
    fact_flights_file = data_dir / "fact_flights.csv"
    profile_flight_counts = Counter()
    if fact_flights_file.exists():
        with fact_flights_file.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                fk = (row.get("flight_key") or "").strip().upper()
                pid = (row.get("ProfileID") or "").strip()
                if pid:
                    profile_flight_counts[pid] += 1
                if fk in anom_flights and pid:
                    flight_passengers[fk].append(pid)

    signal_rows = []
    seen = set()
    for fk, pids in flight_passengers.items():
        info = anom_flights[fk]
        flew = int(info["flew_count"])
        booked = int(info["booked_count"])
        cap = int(info["capacity_limit"])
        model = info["aircraft_model"] or info["aircraft_code"] or "борт"
        airline_str = info.get("airline_display") or info.get("operating_airline") or ""
        airline_desc = f"{airline_str}, {model}" if airline_str else model
        is_over_flew = info.get("is_overcapacity_flew") == "1"
        is_over_booked = info.get("is_overcapacity_booked") == "1"
        try:
            unbooked_pids = set(json.loads(info.get("unbooked_sample_profiles") or "[]"))
        except Exception:
            unbooked_pids = set()

        for pid in pids:
            subject = "P:" + pid
            marker = (subject, fk)
            if marker in seen:
                continue
            seen.add(marker)

            related = ["P:" + other for other in pids[:10] if other != pid]
            is_unbooked = pid in unbooked_pids
            user_flights = profile_flight_counts.get(pid, 0)
            is_rare = user_flights <= 8

            if is_over_flew and is_unbooked:
                weight = 3
                reason = f"Ручная посадка на рейс {fk} ({airline_desc}) с оверспейсом (людей {flew} при лимите {cap}) вне брони GDS. Требуется ручная проверка"
            elif is_over_flew:
                weight = 2
                reason = f"Пассажир находился на рейсе {fk} ({airline_desc}) с оверспейсом (людей {flew} при лимите {cap}). Вес снижен, требуется ручная проверка"
            elif is_unbooked and is_rare:
                weight = 2
                reason = f"Покупка билета на месте при редких перелётах ({user_flights} перелётов) на рейсе {fk} ({airline_desc}) вне брони GDS"
            elif is_unbooked:
                weight = 1
                reason = f"Покупка билета на месте на регулярном маршруте на рейсе {fk} ({airline_desc})"
            elif is_over_booked:
                weight = 1
                reason = f"Рейс {fk} ({airline_desc}) со сверхлимитным овербукингом авиакомпании (продано {booked} при лимите {cap})"
            else:
                weight = 1
                reason = f"Аномалия рейса {fk}: несоответствие бронирований и перелётов"

            evidence = {
                "flight_key": fk,
                "flight_number": info["flight_number"],
                "flight_date": info["flight_date"],
                "departure_airport": info["departure_airport"],
                "arrival_airport": info["arrival_airport"],
                "operating_airline": info.get("operating_airline", ""),
                "marketing_airline": info.get("marketing_airline", ""),
                "airline": info.get("airline_display", ""),
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
                "user_flight_count": user_flights,
                "manual_review": is_over_flew,
                "manual_review_reason": "Оверспейс борта (число пассажиров превысило вместимость судна)" if is_over_flew else ""
            }

            signal_rows.append({
                "subject_id": subject,
                "related_ids": json.dumps(sorted(set(related[:5])), ensure_ascii=False),
                "signal": "flight_anomaly",
                "weight": weight,
                "reason": reason,
                "evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            })

    out_signal = results_dir / "10_flight_anomaly.csv"
    with out_signal.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["subject_id", "related_ids", "signal", "weight", "reason", "evidence_json"])
        writer.writeheader()
        writer.writerows(signal_rows)

    print(f"Сигнал 10_flight_anomaly.csv успешно создан: {len(signal_rows)} записей")
    return out_signal


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--default-capacity", type=int, default=DEFAULT_CAPACITY)
    args = parser.parse_args()
    generate_flight_occupancy(args.input_dir, args.output_dir, args.default_capacity)
    generate_flight_anomaly_signal(args.input_dir, args.output_dir)
