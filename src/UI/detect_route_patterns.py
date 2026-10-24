"""Detect advanced route and itinerary behavioral anomalies:
1. IN_FLIGHT_OVERLAP: flight departure while passenger is already in the air on another flight.
2. SHORT_STAY_LONG_HAUL: short stay (<36h) after long-haul flight (>=4h travel time).
3. BROKEN_CONTINENT_ROUTE: changing continents without an intervening flight in the database.
4. CONSECUTIVE_SPRINT: flying 3 or more consecutive days without breaks.
5. NOMADIC_HUBLESS: frequent flyer (>=15 flights) without a dominant home base airport (<22% share).
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

EURASIA = {
    "Russian Federation", "Armenia", "Azerbaijan", "Belarus", "Georgia", "Kazakhstan", "Kyrgyzstan",
    "Moldova", "Tajikistan", "Turkmenistan", "Uzbekistan", "Ukraine",
    "Albania", "Austria", "Belgium", "Bosnia and Herzegovina", "Bulgaria", "Croatia", "Cyprus",
    "Czech Republic", "Denmark", "Estonia", "Finland", "France", "Germany", "Greece", "Hungary",
    "Iceland", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Montenegro",
    "Netherlands", "Norway", "Poland", "Portugal", "Romania", "Serbia", "Slovakia", "Slovenia",
    "Spain", "Sweden", "Switzerland", "Turkey", "United Kingdom",
    "China", "India", "Japan", "South Korea", "Thailand", "Vietnam", "Singapore", "Malaysia",
    "Indonesia", "United Arab Emirates", "Saudi Arabia", "Qatar", "Israel", "Jordan", "Lebanon",
    "Iran", "Iraq", "Kuwait", "Oman", "Pakistan", "Mongolia", "Philippines", "Sri Lanka", "Maldives"
}
NORTH_AMERICA = {
    "United States of America", "United States", "Canada", "Mexico", "Cuba",
    "Dominican Republic", "Jamaica", "Bahamas", "Panama", "Costa Rica", "Guatemala", "Honduras"
}
SOUTH_AMERICA = {
    "Argentina", "Brazil", "Chile", "Colombia", "Peru", "Ecuador", "Bolivia",
    "Uruguay", "Paraguay", "Venezuela"
}
AFRICA = {
    "Kenya", "Algeria", "Egypt", "South Africa", "Morocco", "Tunisia", "Nigeria",
    "Ghana", "Ethiopia", "Tanzania", "Seychelles", "Mauritius"
}
OCEANIA = {
    "Australia", "New Zealand", "Fiji", "Papua New Guinea"
}

def get_continent(country: str) -> str:
    if not country or country == "UNKNOWN":
        return "UNKNOWN"
    if country in NORTH_AMERICA: return "North America"
    if country in SOUTH_AMERICA: return "South America"
    if country in AFRICA: return "Africa"
    if country in OCEANIA: return "Oceania"
    return "Eurasia"


def build_lookups(timetable_path: Path):
    airport_continent = {}
    airport_country = {}
    airport_city = {}
    flight_durations = {}

    if timetable_path.exists():
        with timetable_path.open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                fc = (r.get("from_code") or "").strip().upper()
                tc = (r.get("to_code") or "").strip().upper()
                f_c = (r.get("from_country") or "").strip()
                t_c = (r.get("to_country") or "").strip()
                if fc and fc not in airport_continent:
                    airport_continent[fc] = get_continent(f_c)
                    airport_country[fc] = f_c
                    airport_city[fc] = (r.get("from_city") or "").strip()
                if tc and tc not in airport_continent:
                    airport_continent[tc] = get_continent(t_c)
                    airport_country[tc] = t_c
                    airport_city[tc] = (r.get("to_city") or "").strip()
                fn = (r.get("flight_number") or "").strip().upper()
                tt = r.get("travel_time")
                if fn and tt:
                    try:
                        flight_durations[fn] = float(tt)
                    except ValueError:
                        pass
    return airport_continent, airport_country, airport_city, flight_durations


def generate_route_anomalies(data_dir: Path, results_dir: Path):
    timetable_path = data_dir / "dim_timetable.csv"
    airport_continent, airport_country, airport_city, flight_durations = build_lookups(timetable_path)
    db_path = results_dir / "index.sqlite"

    if not db_path.exists():
        print("index.sqlite не найден. Сначала выполните подготовку индекса.")
        return

    conn = sqlite3.connect(db_path)
    itineraries = defaultdict(list)

    print("Загрузка маршрутов пассажиров из tickets...")
    for r in conn.execute("""
        SELECT entity_id, ticket_key, flight_key, departure_date, departure_time, departure_airport, arrival_airport
        FROM tickets
        WHERE entity_id NOT LIKE 'T:%' AND departure_date!=''
        ORDER BY entity_id, departure_date, departure_time
    """):
        itineraries[r[0]].append({
            "ticket_key": r[1], "flight_key": r[2], "date": r[3], "time": r[4], "dep": r[5], "arr": r[6]
        })

    entity_events = defaultdict(list)
    print("Загрузка полной истории рейсов из events...")
    for r in conn.execute("""
        SELECT entity_id, flight_key, departure_date, departure_airport, arrival_airport
        FROM events
        WHERE entity_id NOT LIKE 'T:%' AND departure_date!=''
        ORDER BY entity_id, departure_date
    """):
        entity_events[r[0]].append({
            "flight_key": r[1], "date": r[2], "dep": r[3], "arr": r[4]
        })

    anomalies = []

    # 1 & 2: Time overlaps and short stays after long haul
    print("Анализ временных наложений и коротких пребываний...")
    for ent, flights in itineraries.items():
        for i in range(len(flights) - 1):
            f1, f2 = flights[i], flights[i+1]
            fn1 = f1["flight_key"].split("_")[0]
            dur1 = flight_durations.get(fn1, 120.0) # default 2 hours

            if f1["time"] and f2["time"]:
                try:
                    dt1 = datetime.strptime(f"{f1['date']} {f1['time'][:5]}", "%Y-%m-%d %H:%M")
                    dt2 = datetime.strptime(f"{f2['date']} {f2['time'][:5]}", "%Y-%m-%d %H:%M")
                    arr1 = dt1 + timedelta(minutes=dur1)

                    # In-flight departure: flight 2 departs while flight 1 is still in the air!
                    if dt1 < dt2 < arr1:
                        overlap_mins = int((arr1 - dt2).total_seconds() / 60)
                        anomalies.append({
                            "entity_id": ent,
                            "anomaly_type": "IN_FLIGHT_OVERLAP",
                            "severity": "CRITICAL",
                            "weight": 10,
                            "reason": f"Вылет рейса {f2['flight_key']} ({f2['dep']}→{f2['arr']}) в {dt2.strftime('%H:%M')} оформлен до прилёта рейса {f1['flight_key']} ({f1['dep']}→{f1['arr']}) в {arr1.strftime('%H:%M')} (наложение {overlap_mins} мин)",
                            "flight_1": f1["flight_key"],
                            "flight_2": f2["flight_key"],
                            "date": f1["date"],
                            "details_json": json.dumps({
                                "flight_1": f1["flight_key"], "dep_1": f1["dep"], "arr_1": f1["arr"], "dep_time_1": str(dt1), "arr_time_1": str(arr1), "duration_min": dur1,
                                "flight_2": f2["flight_key"], "dep_2": f2["dep"], "arr_2": f2["arr"], "dep_time_2": str(dt2), "overlap_minutes": overlap_mins
                            }, ensure_ascii=False)
                        })

                    # Short stay (<12h) after long flight (>=12h):
                    if dur1 >= 720.0:
                        stay_hours = (dt2 - arr1).total_seconds() / 3600.0
                        if 0 <= stay_hours < 12.0 and f2["dep"] == f1["arr"]:
                            anomalies.append({
                                "entity_id": ent,
                                "anomaly_type": "SHORT_STAY_LONG_HAUL",
                                "severity": "HIGH",
                                "weight": 5,
                                "reason": f"Быстрый визит ({stay_hours:.1f} ч < 12ч) в пункте {f1['arr']} ({airport_city.get(f1['arr'], f1['arr'])}) после дальнего перелёта {dur1/60:.1f} ч (≥12 ч) на рейсе {f1['flight_key']}",
                                "flight_1": f1["flight_key"],
                                "flight_2": f2["flight_key"],
                                "date": f1["date"],
                                "details_json": json.dumps({
                                    "destination": f1["arr"], "destination_city": airport_city.get(f1["arr"], ""), "destination_country": airport_country.get(f1["arr"], ""),
                                    "inbound_flight": f1["flight_key"], "outbound_flight": f2["flight_key"], "flight_duration_min": dur1, "flight_duration_hours": round(dur1/60, 1), "stay_duration_hours": round(stay_hours, 1)
                                }, ensure_ascii=False)
                            })
                except Exception:
                    pass

    # 3, 4, 5: Broken continent routes, consecutive flight streaks, hubless nomadic travelers
    print("Анализ смены континентов, серий полётов и кочевого профиля...")
    for ent, trips in entity_events.items():
        # 4. Consecutive days flying streak (>= 3 days in a row)
        unique_dates = sorted(set(t["date"] for t in trips))
        if len(unique_dates) >= 3:
            streak = 1
            max_streak = 1
            streak_start = unique_dates[0]
            best_streak_start = streak_start
            for i in range(len(unique_dates)-1):
                try:
                    d1 = datetime.strptime(unique_dates[i], "%Y-%m-%d")
                    d2 = datetime.strptime(unique_dates[i+1], "%Y-%m-%d")
                    if (d2 - d1).days == 1:
                        streak += 1
                        if streak > max_streak:
                            max_streak = streak
                            best_streak_start = streak_start
                    else:
                        streak = 1
                        streak_start = unique_dates[i+1]
                except Exception:
                    pass
            if max_streak >= 3:
                anomalies.append({
                    "entity_id": ent,
                    "anomaly_type": "CONSECUTIVE_SPRINT",
                    "severity": "LOW",
                    "weight": 2,
                    "reason": f"Интенсивная серия перелётов: {max_streak} дня подряд без пауз (с {best_streak_start})",
                    "flight_1": "",
                    "flight_2": "",
                    "date": best_streak_start,
                    "details_json": json.dumps({"consecutive_days": max_streak, "start_date": best_streak_start}, ensure_ascii=False)
                })

        # 5. Hubless nomadic traveler: high volume (>=15 flights), no home base (<22% share)
        if len(trips) >= 15:
            aps = Counter()
            for t in trips:
                if t["dep"]: aps[t["dep"]] += 1
                if t["arr"]: aps[t["arr"]] += 1
            total_visits = sum(aps.values())
            top_ap, top_cnt = aps.most_common(1)[0]
            share = top_cnt / total_visits
            countries = {airport_country.get(ap) for ap in aps if airport_country.get(ap)}
            if share <= 0.22 and len(countries) >= 4:
                anomalies.append({
                    "entity_id": ent,
                    "anomaly_type": "NOMADIC_HUBLESS",
                    "severity": "LOW",
                    "weight": 2,
                    "reason": f"Кочевой профиль: {len(trips)} перелётов по {len(aps)} аэропортам ({len(countries)} стран) без постоянного базового хаба (макс. {top_ap}: {share*100:.1f}%)",
                    "flight_1": "",
                    "flight_2": "",
                    "date": trips[0]["date"],
                    "details_json": json.dumps({
                        "total_flights": len(trips), "unique_airports": len(aps), "unique_countries": len(countries),
                        "top_airport": top_ap, "top_airport_share": round(share, 3), "countries": sorted(list(countries))[:8]
                    }, ensure_ascii=False)
                })

        # 3. Broken continent transitions: arrived in continent A, next departure from continent B without connecting flight
        for i in range(len(trips) - 1):
            t1, t2 = trips[i], trips[i+1]
            c1 = airport_continent.get(t1["arr"], "UNKNOWN")
            c2 = airport_continent.get(t2["dep"], "UNKNOWN")
            if c1 not in ("UNKNOWN", "") and c2 not in ("UNKNOWN", "") and c1 != c2:
                try:
                    d1 = datetime.strptime(t1["date"], "%Y-%m-%d")
                    d2 = datetime.strptime(t2["date"], "%Y-%m-%d")
                    days = (d2 - d1).days
                    if days <= 14: # rapid continent change without flight
                        anomalies.append({
                            "entity_id": ent,
                            "anomaly_type": "BROKEN_CONTINENT_ROUTE",
                            "severity": "HIGH",
                            "weight": 4,
                            "reason": f"Разрыв маршрута между континентами: прибыл в {t1['arr']} ({c1}, {t1['date']}), а следующий вылет через {days} дн. из {t2['dep']} ({c2}, {t2['date']}) без связующего авиарейса",
                            "flight_1": t1["flight_key"],
                            "flight_2": t2["flight_key"],
                            "date": t1["date"],
                            "details_json": json.dumps({
                                "arrived_airport": t1["arr"], "arrived_continent": c1, "arrived_country": airport_country.get(t1["arr"], ""),
                                "next_departure_airport": t2["dep"], "next_continent": c2, "next_country": airport_country.get(t2["dep"], ""),
                                "days_gap": days, "flight_1": t1["flight_key"], "flight_2": t2["flight_key"]
                            }, ensure_ascii=False)
                        })
                except Exception:
                    pass

    # Save to CSV
    out_file = results_dir / "route_anomalies.csv"
    fieldnames = ["entity_id", "anomaly_type", "severity", "weight", "reason", "flight_1", "flight_2", "date", "details_json"]
    with out_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(anomalies)

    # Save individual signal CSVs for web interface
    sig_map = {
        "IN_FLIGHT_OVERLAP": ("11_in_flight_overlap.csv", "in_flight_overlap"),
        "SHORT_STAY_LONG_HAUL": ("12_short_stay_long_haul.csv", "short_stay_long_haul"),
        "BROKEN_CONTINENT_ROUTE": ("13_broken_continent.csv", "broken_continent"),
        "CONSECUTIVE_SPRINT": ("14_consecutive_sprint.csv", "consecutive_sprint"),
        "NOMADIC_HUBLESS": ("15_nomadic_hubless.csv", "nomadic_hubless"),
    }
    sig_fieldnames = ["subject_id", "related_ids", "signal", "weight", "reason", "evidence_json"]
    for anom_type, (fname, sig_key) in sig_map.items():
        sub_rows = [
            {
                "subject_id": a["entity_id"],
                "related_ids": "[]",
                "signal": sig_key,
                "weight": a["weight"],
                "reason": a["reason"],
                "evidence_json": a["details_json"]
            }
            for a in anomalies if a["anomaly_type"] == anom_type
        ]
        with (results_dir / fname).open("w", newline="", encoding="utf-8-sig") as sf:
            swriter = csv.DictWriter(sf, fieldnames=sig_fieldnames)
            swriter.writeheader()
            swriter.writerows(sub_rows)

    # Summary
    type_counts = Counter(a["anomaly_type"] for a in anomalies)
    summary_file = results_dir / "route_anomalies_summary.json"
    summary_data = {
        "total_anomalies": len(anomalies),
        "unique_entities": len(set(a["entity_id"] for a in anomalies)),
        "by_type": dict(type_counts),
        "in_flight_overlap_count": type_counts.get("IN_FLIGHT_OVERLAP", 0),
        "short_stay_count": type_counts.get("SHORT_STAY_LONG_HAUL", 0),
        "broken_continent_count": type_counts.get("BROKEN_CONTINENT_ROUTE", 0),
        "consecutive_sprint_count": type_counts.get("CONSECUTIVE_SPRINT", 0),
        "nomadic_hubless_count": type_counts.get("NOMADIC_HUBLESS", 0),
    }
    with summary_file.open("w", encoding="utf-8") as sf:
        json.dump(summary_data, sf, ensure_ascii=False, indent=2)

    print(f"\nАнализ маршрутных аномалий завершён. Найдено {len(anomalies):,} инцидентов по {summary_data['unique_entities']:,} личностям:")
    for t, cnt in type_counts.most_common():
        print(f"  • {t}: {cnt:,} записей")
    print(f"Сохранено в: {out_file}")
    print(f"Сводка в: {summary_file}")
    return out_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    generate_route_anomalies(args.data_dir, args.results_dir)
