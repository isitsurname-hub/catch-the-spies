"""Local, dependency-free explorer for the spy-detection CSVs and SQLite index."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import shutil
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
DEFAULT_INPUT = (ROOT / "data") if (ROOT / "data").is_dir() else Path("data")

SIGNALS = [
    {"key": "passport_collision", "file": "01_passport_collision.csv", "title": "Один документ — разные люди",
     "group": "primary", "weight": "8 / 6", "description": "Разные даты рождения или существенно разные имена при одном документе.",
     "case": "Поддельные паспорта в деле аль-Мабхуха; настоящие владельцы могли быть жертвами.",
     "source": "https://publications.parliament.uk/pa/cm200910/cmhansrd/chan62.pdf"},
    {"key": "profile_conflict", "file": "02_profile_conflict.csv", "title": "Противоречия в профиле",
     "group": "primary", "weight": "7 / 4", "description": "Несовместимые установочные данные внутри одного ProfileID.",
     "case": "Проверка противоречий личности — адаптация к качеству данных, сама по себе не доказывает шпионаж.",
     "source": "https://assets.publishing.service.gov.uk/media/6981f8438c1e89ed1e91bb7d/E03283426_Project_Orbit_Accessible_v2.pdf"},
    {"key": "joint_travel", "file": "03_joint_travel.csv", "title": "Повторные совместные рейсы",
     "group": "primary", "weight": "3", "description": "Пара людей встречается на трёх или более разных рейсах.",
     "case": "Повторяемость поездок изучалась в расследовании группы, следившей за Навальным.",
     "source": "https://www.bellingcat.com/news/2020/12/14/fsb-team-of-chemical-weapon-experts-implicated-in-alexey-navalny-novichok-poisoning/"},
    {"key": "near_passports_with_travel", "file": "04_near_passports_with_travel.csv", "title": "Близкие паспорта и маршрут",
     "group": "primary", "weight": "4", "description": "Номера рядом в серии и совпадает направление в один день.",
     "case": "Близкие номера фигурировали в деле Солсбери; официальный отчёт называет это неокончательным свидетельством.",
     "source": "https://assets.publishing.service.gov.uk/media/6981f8438c1e89ed1e91bb7d/E03283426_Project_Orbit_Accessible_v2.pdf"},
    {"key": "schedule_conflict", "file": "05_schedule_conflict.csv", "title": "Несовместимые вылеты",
     "group": "primary", "weight": "10 / 2", "description": "Вылет во время полёта (+10) или из одного аэропорта почти одновременно (+2).",
     "case": "Физическая невозможность быть на двух рейсах одновременно или конфликт бронирований.", "source": ""},
    {"key": "near_passport", "file": "06_near_passport.csv", "title": "Близкие номера документов",
     "group": "secondary", "weight": "2", "description": "Номера различаются не более чем на три в одной числовой серии.",
     "case": "Зацепка из дела Солсбери; без сведений о выдаче документов связь слабая.",
     "source": "https://assets.publishing.service.gov.uk/media/6981f8438c1e89ed1e91bb7d/E03283426_Project_Orbit_Accessible_v2.pdf"},
    {"key": "shared_pnr", "file": "07_shared_pnr.csv", "title": "Повторные общие брони",
     "group": "secondary", "weight": "3", "description": "У пары есть два и более общих PNR.",
     "case": "Совместно приобретённые билеты помогли расширить круг людей в расследовании Навального.",
     "source": "https://www.bellingcat.com/resources/2020/12/14/navalny-fsb-methodology/"},
    {"key": "parallel_arrivals", "file": "08_parallel_arrivals.csv", "title": "Параллельные прибытия",
     "group": "secondary", "weight": "3", "description": "Повторные прибытия в один аэропорт разными рейсами в один день.",
     "case": "Параллельные рейсы были отправной точкой расследования Навального.",
     "source": "https://www.bellingcat.com/resources/2020/12/14/navalny-fsb-methodology/"},
    {"key": "convergence", "file": "09_convergence.csv", "title": "Схождение маршрутов",
     "group": "secondary", "weight": "3", "description": "Повторные прибытия в один аэропорт из разных мест.",
     "case": "Полиция Дубая восстановила маршруты сходившихся и расходившихся групп подозреваемых.",
     "source": "https://www.wam.ae/en/article/hsyj2mra-dubai-police-names-suspects-al-mabhouh-murder"},
    {"key": "flight_anomaly", "file": "10_flight_anomaly.csv", "title": "Аномалии рейса и перегруз борта",
     "group": "primary", "weight": "1–3", "description": "Посадка на месте или перегруз борта. Веса снижены (1–3); пассажиры с оверспейсом направляются на ручную проверку.",
     "case": "Перемещение под прикрытием без официальной брони или ручная посадка в кассе. Рейтинг снижен, чтобы не завышать балл случайным попутчикам.",
     "source": ""},
    {"key": "in_flight_overlap", "file": "11_in_flight_overlap.csv", "title": "Вылет во время полёта",
     "group": "route", "weight": "10", "description": "Вылет следующего рейса оформлен до прилёта предыдущего (физический конфликт нахождения в воздухе).",
     "case": "Невозможно лететь на двух рейсах одновременно. Указывает на использование нескольких личностей или фиктивные перелёты.",
     "source": ""},
    {"key": "short_stay_long_haul", "file": "12_short_stay_long_haul.csv", "title": "Быстрый визит после дальнего рейса",
     "group": "route", "weight": "5", "description": "Пребывание в пункте назначения менее 12 часов после перелёта длительностью более 12 часов.",
     "case": "Характерно для курьерских миссий, оперативных контактов и передачи разведматериалов без отдыха и туризма.",
     "source": ""},
    {"key": "broken_continent", "file": "13_broken_continent.csv", "title": "Смена континентов без авиарейса",
     "group": "route", "weight": "4", "description": "Прибытие на один континент и вылет с другого без связующего авиаперелёта в базе данных.",
     "case": "Использование неавиационного транспорта (паромы, наземный транспорт) для обхода контроля в аэропортах.",
     "source": ""},
    {"key": "consecutive_sprint", "file": "14_consecutive_sprint.csv", "title": "Серии перелётов день в день",
     "group": "route", "weight": "2", "description": "Непрерывные перелёты 3 и более дней подряд без остановок (интенсивные цепочки перемещений).",
     "case": "Плотный график пересадок с частой сменой юрисдикций и запутыванием маршрута следования.",
     "source": ""},
    {"key": "nomadic_hubless", "file": "15_nomadic_hubless.csv", "title": "Кочевой профиль без базы",
     "group": "route", "weight": "2", "description": "Высокая частота перелётов (15+) при отсутствии выраженного базового хаба (<22% визитов в один порт).",
     "case": "Человек равномерно распределяет перелёты по десяткам городов и стран, не имея домашней базы.",
     "source": ""},
]

RAW_TABLES = [
    ("dim_person", "Люди", "dim_person.csv"),
    ("dim_timetable", "Расписание", "dim_timetable.csv"),
    ("fact_bonus_activity", "Бонусная активность", "fact_bonus_activity.csv"),
    ("fact_flights", "Перелёты", "fact_flights.csv"),
    ("fact_tickets", "Билеты", "fact_tickets.csv"),
]
RESULT_TABLES = [
    ("primary_candidates_final", "Итоговые кандидаты", "primary_candidates_final.csv"),
    ("primary_candidates", "Первичные кандидаты", "primary_candidates.csv"),
    ("manual_review_candidates", "Ручная проверка (оверспейс)", "manual_review_candidates.csv"),
    ("secondary_candidates", "Вторичные кандидаты", "secondary_candidates.csv"),
    ("flight_anomalies", "Аномалии загрузки рейсов", "flight_anomalies.csv"),
    ("flight_occupancy", "Все рейсы (билеты vs полёты)", "flight_occupancy.csv"),
    ("route_anomalies", "Маршрутные аномалии и паттерны (все)", "route_anomalies.csv"),
    ("11_in_flight_overlap", "11. Вылет во время полёта", "11_in_flight_overlap.csv"),
    ("12_short_stay_long_haul", "12. Быстрые визиты (<12ч после рейса ≥12ч)", "12_short_stay_long_haul.csv"),
    ("13_broken_continent", "13. Разрыв континентов", "13_broken_continent.csv"),
    ("14_consecutive_sprint", "14. Серии перелётов день в день", "14_consecutive_sprint.csv"),
    ("15_nomadic_hubless", "15. Кочевой профиль без базы", "15_nomadic_hubless.csv"),
    ("primary_scores_all", "Баллы всех людей", "primary_scores_all.csv"),
    ("chain_edges", "Цепочки связей", "chain_edges.csv"),
    ("secondary_links", "Вторичные связи", "secondary_links.csv"),
    ("identity_links", "Привязанные билеты", "identity_links.csv"),
] + [(item["key"], item["title"], item["file"]) for item in SIGNALS]


def csv_rows(path: Path):
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def count_csv(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for _ in csv_rows(path))


def db_connect(results: Path) -> sqlite3.Connection:
    path = (results / "index.sqlite").resolve()
    if not path.is_file():
        raise FileNotFoundError("Индекс ещё не создан. Сначала запустите первичный этап.")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def candidate_rows(results: Path, filename: str):
    return list(csv_rows(results / filename))


def candidate_label(row: dict) -> str:
    try:
        names = json.loads(row.get("names_json") or "[]")
        if names:
            return names[0]
    except (ValueError, KeyError):
        pass
    return row.get("candidate_id") or row.get("subject_id") or row.get("entity_id") or ""


class App(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, input_dir: Path, results_dir: Path):
        super().__init__(address, Handler)
        self.input_dir = input_dir
        self.results_dir = results_dir
        self.job_lock = threading.Lock()
        self.job = {"status": "idle", "stage": "", "lines": [], "started_at": "", "finished_at": ""}

    def start_job(self, stage: str) -> bool:
        with self.job_lock:
            if self.job["status"] == "running":
                return False
            self.job = {"status": "running", "stage": stage, "lines": [],
                        "started_at": datetime.now().isoformat(timespec="seconds"), "finished_at": ""}

        def worker():
            if shutil.which("make") and sys.platform != "win32":
                command = ["make", stage, f"INPUT_DIR={self.input_dir}", f"OUTPUT_DIR={self.results_dir}"]
            else:
                command = [sys.executable, "-u", str(ROOT / "pipeline.py"), stage,
                           "--input-dir", str(self.input_dir), "--output-dir", str(self.results_dir)]
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True,
                                           encoding="utf-8", errors="replace", bufsize=1)
                assert process.stdout is not None
                for line in process.stdout:
                    with self.job_lock:
                        self.job["lines"].append(line.rstrip())
                        self.job["lines"] = self.job["lines"][-150:]
                code = process.wait()
                with self.job_lock:
                    self.job["status"] = "success" if code == 0 else "error"
                    self.job["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    self.job["lines"].append(f"Код завершения: {code}")
            except Exception as exc:
                with self.job_lock:
                    self.job["status"] = "error"
                    self.job["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    self.job["lines"].append(str(exc))

        threading.Thread(target=worker, daemon=True).start()
        return True


class Handler(BaseHTTPRequestHandler):
    server: App

    def log_message(self, fmt, *args):
        # Keep terminal output focused on startup and pipeline runs.
        return

    def json_response(self, payload, code=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def static_response(self, filename: str):
        path = WEB / filename
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self.static_response("index.html")
        if parsed.path in ("/styles.css", "/app.js"):
            return self.static_response(parsed.path[1:])
        if not parsed.path.startswith("/api/"):
            return self.json_response({"error": "Не найдено"}, 404)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            method = getattr(self, "api_" + parsed.path[5:].replace("-", "_"), None)
            if not method:
                return self.json_response({"error": "Неизвестный запрос"}, 404)
            return self.json_response(method(params))
        except (ValueError, FileNotFoundError) as exc:
            return self.json_response({"error": str(exc)}, 400)
        except sqlite3.Error as exc:
            return self.json_response({"error": "База данных занята или недоступна: " + str(exc)}, 503)

    def do_POST(self):
        if self.path != "/api/run":
            return self.json_response({"error": "Не найдено"}, 404)
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if origin and origin not in ("http://" + host, "https://" + host):
            return self.json_response({"error": "Недопустимый источник запроса"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.json_response({"error": "Требуется JSON"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.json_response({"error": "Некорректная длина запроса"}, 400)
        if length < 0 or length > 1024:
            return self.json_response({"error": "Слишком большой запрос"}, 413)
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, TypeError):
            return self.json_response({"error": "Некорректный JSON"}, 400)
        stage = body.get("stage") if isinstance(body, dict) else None
        if stage not in {"primary", "expand", "all"}:
            return self.json_response({"error": "Неизвестный этап"}, 400)
        if not self.server.start_job(stage):
            return self.json_response({"error": "Другой расчёт ещё выполняется"}, 409)
        return self.json_response({"status": "running", "stage": stage}, 202)

    def api_overview(self, _):
        results = self.server.results_dir
        counts = {item["key"]: count_csv(results / item["file"]) for item in SIGNALS}
        final = candidate_rows(results, "primary_candidates_final.csv")
        primary = candidate_rows(results, "primary_candidates.csv")
        secondary = candidate_rows(results, "secondary_candidates.csv")
        review = candidate_rows(results, "manual_review_candidates.csv")
        db_counts = {"profiles": 0, "tickets": 0, "events": 0}
        if (results / "index.sqlite").exists():
            with closing(db_connect(results)) as conn:
                for table in db_counts:
                    db_counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        file = results / "primary_candidates_final.csv"
        updated = datetime.fromtimestamp(file.stat().st_mtime).isoformat(timespec="minutes") if file.exists() else ""
        top = sorted(final, key=lambda row: int(row.get("score") or 0), reverse=True)[:6]
        route_summary_file = results / "route_anomalies_summary.json"
        route_summary = {}
        if route_summary_file.is_file():
            try:
                with route_summary_file.open(encoding="utf-8") as rf:
                    route_summary = json.load(rf)
            except Exception:
                pass
        return {"counts": counts, "final_count": len(final), "primary_count": len(primary),
                "secondary_count": len([r for r in secondary if r.get("stage") == "promoted_secondary"]),
                "review_count": len(review),
                "route_summary": route_summary,
                "db_counts": db_counts, "updated_at": updated,
                "top_candidates": [{"id": r["candidate_id"], "label": candidate_label(r),
                                    "score": r.get("score", ""), "stage": r.get("stage", "")}
                                   for r in top]}

    def api_signals(self, _):
        return [{**item, "count": count_csv(self.server.results_dir / item["file"])} for item in SIGNALS]

    def api_occupancy(self, params):
        anomalies_file = self.server.results_dir / "flight_anomalies.csv"
        critical_file = self.server.results_dir / "flight_critical_anomalies.csv"
        occupancy_file = self.server.results_dir / "flight_occupancy.csv"
        summary_file = self.server.results_dir / "flight_occupancy_summary.json"

        kind = params.get("kind", "over_flew")
        query = params.get("q", "").strip().casefold()[:100]
        page = min(max(int(params.get("page", "1")), 1), 1000)
        size = min(max(int(params.get("size", "30")), 1), 100)

        # 1. Мгновенная загрузка счетчиков из JSON или кэша (0.1 мс вместо сканирования 2.1 млн строк)
        stats = getattr(self.server, "_occupancy_stats_cache", None)
        if stats is None:
            if summary_file.is_file():
                try:
                    with summary_file.open(encoding="utf-8") as sf:
                        stats = json.load(sf)
                except Exception:
                    stats = None
            if stats is None:
                stats = {
                    "total_flights": count_csv(occupancy_file),
                    "anomaly_flights": count_csv(anomalies_file),
                    "overcapacity_flew": 0,
                    "overcapacity_booked": 0,
                    "no_tickets_count": 0,
                }
            self.server._occupancy_stats_cache = stats

        # 2. Выбор оптимального файла:
        # Для over_flew и over_booked читаем компактный critical_file (~36 строк)
        target_file = anomalies_file
        if kind in ("over_flew", "over_booked") and critical_file.is_file():
            target_file = critical_file

        rows = []
        offset = (page - 1) * size
        limit_target = offset + size + 1
        total_matching = 0

        if target_file.is_file():
            with target_file.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    is_over_flew = row.get("is_overcapacity_flew") == "1"
                    is_over_booked = row.get("is_overcapacity_booked") == "1"
                    is_no_tix = row.get("is_unbooked_flight") == "1"

                    if kind == "over_flew" and not is_over_flew:
                        continue
                    if kind == "over_booked" and not is_over_booked:
                        continue
                    if kind == "no_tickets" and not is_no_tix:
                        continue

                    if query:
                        searchable = " ".join([
                            row.get("flight_key", ""),
                            row.get("flight_number", ""),
                            row.get("departure_airport", ""),
                            row.get("arrival_airport", ""),
                            row.get("operating_airline", ""),
                            row.get("marketing_airline", ""),
                            row.get("airline_display", ""),
                            row.get("aircraft_code", ""),
                            row.get("aircraft_model", ""),
                        ]).casefold()
                        if query not in searchable:
                            continue

                    total_matching += 1

                    # Для огромного no_tickets без текстового фильтра делаем early-exit (выборка нужной страницы)
                    if not query and kind == "no_tickets":
                        if total_matching > offset and len(rows) < size:
                            rows.append(row)
                        if total_matching >= limit_target:
                            break
                    else:
                        rows.append(row)

        if not query and kind == "no_tickets":
            total_count = stats.get("no_tickets_count", total_matching)
            page_rows = rows
            has_more = total_matching >= limit_target or (offset + size) < total_count
        else:
            total_count = len(rows)
            page_rows = rows[offset:offset + size]
            has_more = len(rows) > (offset + size)

        return {
            "stats": stats,
            "kind": kind,
            "total": total_count,
            "page": page,
            "size": size,
            "rows": page_rows,
            "has_more": has_more
        }

    def api_tables(self, _):
        def info(key, title, filename, base, group):
            path = base / filename
            return {"key": key, "title": title, "file": filename, "group": group,
                    "exists": path.is_file(), "size_bytes": path.stat().st_size if path.is_file() else 0}
        return ([info(*item, self.server.results_dir, "results") for item in RESULT_TABLES] +
                [info(*item, self.server.input_dir, "raw") for item in RAW_TABLES])

    def api_table(self, params):
        key = params.get("name", "")
        lookup = {item[0]: (self.server.results_dir / item[2]) for item in RESULT_TABLES}
        lookup.update({item[0]: (self.server.input_dir / item[2]) for item in RAW_TABLES})
        if key not in lookup:
            raise ValueError("Неизвестная таблица")
        path = lookup[key]
        if not path.is_file():
            raise FileNotFoundError("Таблица ещё не создана")
        page = min(max(int(params.get("page", "1")), 1), 10000)
        size = min(max(int(params.get("size", "25")), 1), 100)
        query = params.get("q", "").strip().casefold()[:100]
        offset = (page - 1) * size
        rows = []
        matched = 0
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames or []
            for row in reader:
                if query and not any(query in str(value or "").casefold() for value in row.values()):
                    continue
                if matched >= offset:
                    rows.append({col: row.get(col, "") for col in columns})
                    if len(rows) > size:
                        break
                matched += 1
        return {"name": key, "columns": columns, "rows": rows[:size],
                "page": page, "size": size, "has_more": len(rows) > size,
                "query": params.get("q", "")}

    def api_candidates(self, params):
        kind = params.get("kind", "final")
        files = {
            "final": "primary_candidates_final.csv",
            "primary": "primary_candidates.csv",
            "secondary": "secondary_candidates.csv",
            "review": "manual_review_candidates.csv",
            "route_overlap": "11_in_flight_overlap.csv",
            "route_short": "12_short_stay_long_haul.csv",
            "route_continent": "13_broken_continent.csv",
            "route_sprint": "14_consecutive_sprint.csv",
            "route_nomadic": "15_nomadic_hubless.csv",
            "all": "primary_scores_all.csv"
        }
        if kind not in files:
            raise ValueError("Неизвестный список")
        query = params.get("q", "").strip().casefold()[:100]
        rows = candidate_rows(self.server.results_dir, files[kind])
        if query:
            rows = [row for row in rows if query in (row.get("candidate_id") or row.get("subject_id") or row.get("entity_id") or "").casefold() or
                    query in row.get("names_json", "").casefold() or
                    query in row.get("reason", "").casefold()]
        rows.sort(key=lambda row: int(row.get("score") or row.get("weight") or 0), reverse=True)
        page = min(max(int(params.get("page", "1")), 1), 1000)
        size = min(max(int(params.get("size", "30")), 1), 100)
        subset = rows[(page - 1) * size:page * size]

        is_route = kind.startswith("route_")
        p_ids = []
        for r in subset:
            cid = r.get("candidate_id") or r.get("subject_id") or r.get("entity_id") or ""
            if cid.startswith("P:") and cid[2:].isdigit():
                p_ids.append(int(cid[2:]))
        profile_names = {}
        if p_ids:
            try:
                with closing(db_connect(self.server.results_dir)) as conn:
                    q_marks = ",".join("?" for _ in p_ids)
                    for prow in conn.execute(f"SELECT profile_id, full_name FROM profiles WHERE profile_id IN ({q_marks})", p_ids):
                        profile_names[f"P:{prow['profile_id']}"] = prow["full_name"]
            except Exception:
                pass

        result_rows = []
        for row in subset:
            cid = row.get("candidate_id") or row.get("subject_id") or row.get("entity_id") or ""
            lbl = candidate_label(row)
            if (not lbl or lbl == cid) and cid in profile_names and profile_names[cid]:
                lbl = profile_names[cid]
            result_rows.append({
                "id": cid,
                "label": lbl,
                "score": row.get("score") or row.get("weight") or "",
                "stage": row.get("stage") or (kind if is_route else ""),
                "is_manual_review": row.get("stage") == "manual_review" or "оверспейс" in row.get("reasons_json", "").casefold(),
                "route_kind": kind if is_route else "",
                "hint": row.get("reason", "")[:90] if is_route else "",
                "signals": json.loads(row.get("signal_types") or "[]") if row.get("signal_types") else [],
                "links": json.loads(row.get("related_ids") or "[]") if row.get("related_ids") else []
            })
        return {"rows": result_rows, "total": len(rows), "page": page, "size": size}

    def api_people(self, params):
        query = params.get("q", "").strip()[:100]
        if not query:
            rows = candidate_rows(self.server.results_dir, "primary_candidates_final.csv")
            return [{"id": row["candidate_id"], "label": candidate_label(row),
                     "hint": "Кандидат · балл " + str(row.get("score", ""))} for row in rows[:20]]
        match = "%" + query.upper() + "%"
        found = {}
        with closing(db_connect(self.server.results_dir)) as conn:
            for row in conn.execute("""
                SELECT 'P:' || profile_id id,full_name FROM profiles
                WHERE profile_id LIKE ? OR full_name LIKE ? LIMIT 20
            """, (match, match)):
                found[row["id"]] = {"id": row["id"], "label": row["full_name"] or row["id"],
                                    "hint": "ProfileID " + row["id"][2:]}
            for row in conn.execute("""
                SELECT entity_id id,MIN(full_name) name,COUNT(*) tickets FROM tickets
                WHERE entity_id LIKE ? OR full_name LIKE ?
                GROUP BY entity_id LIMIT 40
            """, (match, match)):
                if row["id"] not in found:
                    found[row["id"]] = {"id": row["id"], "label": row["name"] or row["id"],
                                        "hint": str(row["tickets"]) + " билетов"}
        return list(found.values())[:40]

    def api_person(self, params):
        entity = params.get("id", "")[:100]
        if not entity or not entity.startswith(("P:", "U:", "T:")):
            raise ValueError("Укажите ID человека")
        with closing(db_connect(self.server.results_dir)) as conn:
            tickets = [dict(row) for row in conn.execute("""
                SELECT ticket_key,pnr,flight_key,full_name,birth_date,document,
                       departure_date,departure_time,departure_airport,arrival_airport,source
                FROM tickets WHERE entity_id=? ORDER BY departure_date DESC LIMIT 50
            """, (entity,))]
            flights = [dict(row) for row in conn.execute("""
                SELECT flight_key,departure_date,departure_airport,arrival_airport,source_ref
                FROM events WHERE entity_id=? ORDER BY departure_date DESC LIMIT 70
            """, (entity,))]
            total_tickets = conn.execute("SELECT COUNT(*) FROM tickets WHERE entity_id=?", (entity,)).fetchone()[0]
            total_flights = conn.execute("SELECT COUNT(*) FROM events WHERE entity_id=?", (entity,)).fetchone()[0]
            profile = dict(conn.execute("SELECT * FROM profiles WHERE profile_id=?", (entity[2:],)).fetchone() or {}) if entity.startswith("P:") else None
        candidates = {}
        for filename in ("primary_candidates_final.csv", "primary_scores_all.csv", "secondary_candidates.csv"):
            for row in csv_rows(self.server.results_dir / filename):
                if row["candidate_id"] == entity and entity not in candidates:
                    candidates[entity] = row
        signals = []
        for item in SIGNALS:
            for row in csv_rows(self.server.results_dir / item["file"]):
                if row["subject_id"] == entity:
                    signals.append({"signal": item["key"], "title": item["title"],
                                    "weight": row["weight"], "reason": row["reason"],
                                    "related": json.loads(row["related_ids"]),
                                    "evidence": json.loads(row["evidence_json"])})
                    if len(signals) >= 60:
                        break
        links = []
        for row in csv_rows(self.server.results_dir / "chain_edges.csv"):
            if entity in (row["candidate_id"], row["anchor_id"]):
                links.append({"other": row["anchor_id"] if row["candidate_id"] == entity else row["candidate_id"],
                              "signal": row["signal"], "stage": row["link_stage"],
                              "reason": row["reason"]})
        route_anomalies = []
        route_file = self.server.results_dir / "route_anomalies.csv"
        if route_file.is_file():
            for row in csv_rows(route_file):
                if row["entity_id"] == entity:
                    route_anomalies.append({
                        "type": row["anomaly_type"],
                        "severity": row["severity"],
                        "weight": row["weight"],
                        "reason": row["reason"],
                        "date": row["date"],
                        "details": json.loads(row.get("details_json") or "{}")
                    })
                    if len(route_anomalies) >= 20:
                        break
        candidate = candidates.get(entity)
        return {"id": entity, "profile": profile, "candidate": candidate,
                "tickets": tickets, "flights": flights, "ticket_count": total_tickets,
                "flight_count": total_flights, "signals": signals, "links": links,
                "route_anomalies": route_anomalies}

    def api_compare(self, params):
        a, b = params.get("a", "")[:100], params.get("b", "")[:100]
        if not a or not b or a == b:
            raise ValueError("Выберите двух разных людей")
        with closing(db_connect(self.server.results_dir)) as conn:
            shared = [dict(row) for row in conn.execute("""
                SELECT a.flight_key,a.departure_date,a.departure_airport,a.arrival_airport
                FROM events a JOIN events b ON a.flight_key=b.flight_key
                WHERE a.entity_id=? AND b.entity_id=?
                ORDER BY a.departure_date DESC LIMIT 100
            """, (a, b))]
            parallel = [dict(row) for row in conn.execute("""
                SELECT DISTINCT a.departure_date,a.arrival_airport,
                       a.flight_key flight_a,b.flight_key flight_b,
                       a.departure_airport origin_a,b.departure_airport origin_b
                FROM events a JOIN events b
                  ON a.departure_date=b.departure_date AND a.arrival_airport=b.arrival_airport
                WHERE a.entity_id=? AND b.entity_id=? AND a.flight_key!=b.flight_key
                  AND a.departure_date!='' AND a.arrival_airport!=''
                ORDER BY a.departure_date DESC LIMIT 100
            """, (a, b))]
            bookings = [dict(row) for row in conn.execute("""
                SELECT DISTINCT a.pnr FROM tickets a JOIN tickets b ON a.pnr=b.pnr
                WHERE a.entity_id=? AND b.entity_id=? AND a.pnr!=''
                  AND (SELECT COUNT(DISTINCT entity_id) FROM tickets t WHERE t.pnr=a.pnr) <= 12
                LIMIT 100
            """, (a, b))]
        return {"a": a, "b": b, "shared_flights": shared, "parallel_arrivals": parallel,
                "shared_pnrs": [row["pnr"] for row in bookings],
                "note": "Совпадение билетов и маршрутов не подтверждает посадку на рейс или знакомство людей."}

    def api_network(self, _):
        rows = list(csv_rows(self.server.results_dir / "chain_edges.csv"))
        edges = [{"source": r["candidate_id"], "target": r["anchor_id"],
                  "signal": r["signal"], "stage": r.get("link_stage", ""), "reason": r["reason"]}
                 for r in rows]
        candidates = {r["candidate_id"]: r for r in csv_rows(self.server.results_dir / "primary_candidates_final.csv")}
        ids = {e["source"] for e in edges} | {e["target"] for e in edges} | set(candidates)
        nodes = [{"id": entity, "label": candidate_label(candidates[entity]) if entity in candidates else entity,
                  "score": candidates[entity]["score"] if entity in candidates else "",
                  "stage": candidates[entity]["stage"] if entity in candidates else "related"}
                 for entity in sorted(ids)]
        return {"nodes": nodes, "edges": edges}

    def api_job(self, _):
        with self.server.job_lock:
            return dict(self.server.job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = App((args.host, args.port), args.input_dir.resolve(), args.results_dir.resolve())
    print(f"Локальный сайт: http://{args.host}:{args.port}", flush=True)
    print(f"Результаты: {args.results_dir.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
