import csv
import json
import sys
import time
from pathlib import Path

import ijson


INPUT_FILE = Path("input.json")
OUTPUT_DIR = Path("csv_output")

PROGRESS_INTERVAL = 100_000
READ_BUFFER_SIZE = 1024 * 1024

PROFILES_FILE = OUTPUT_DIR / "profiles.csv"
LOYALTY_FILE = OUTPUT_DIR / "loyalty.csv"
FLIGHTS_FILE = OUTPUT_DIR / "flights.csv"


class ProgressReader:
    def __init__(self, file_obj, total_size):
        self.file = file_obj
        self.total_size = total_size
        self.bytes_read = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = READ_BUFFER_SIZE

        data = self.file.read(size)
        self.bytes_read += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self.file, name)


def get_value(obj, key, default=""):
    if not isinstance(obj, dict):
        return default

    value = obj.get(key, default)

    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    return value


def validate_array(value, field_name):
    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(
            f"Поле {field_name!r} должно быть массивом или null, "
            f"получен тип {type(value).__name__}"
        )

    return value


def format_duration(seconds):
    if seconds is None or seconds < 0:
        return "расчёт..."

    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {seconds} сек"

    return f"{seconds} сек"


def show_progress(reader, total_profiles, loyalty_count, flights_count,
                  started_at, last_profiles):
    elapsed = time.monotonic() - started_at

    if elapsed > 0 and reader.bytes_read > 0:
        speed = reader.bytes_read / elapsed
        remaining_bytes = max(0, reader.total_size - reader.bytes_read)
        eta = remaining_bytes / speed if speed > 0 else None
    else:
        eta = None

    if reader.total_size:
        percent = min(100, reader.bytes_read * 100 / reader.total_size)
    else:
        percent = 0

    size_mb = reader.bytes_read / (1024 * 1024)
    total_mb = reader.total_size / (1024 * 1024)

    profiles_per_second = (
        total_profiles / elapsed if elapsed > 0 else 0
    )

    print(
        f"\r"
        f"Прочитано: {percent:6.2f}% | "
        f"{size_mb:,.0f}/{total_mb:,.0f} МБ | "
        f"Профилей: {total_profiles:,} | "
        f"Программ: {loyalty_count:,} | "
        f"Рейсов: {flights_count:,} | "
        f"Скорость: {profiles_per_second:,.0f} проф./сек | "
        f"Осталось: {format_duration(eta)}",
        end="",
        flush=True,
    )


def main():
    if not INPUT_FILE.is_file():
        print(f"ОШИБКА: входной файл не найден: {INPUT_FILE.resolve()}")
        print("Положи JSON-файл рядом со скриптом и назови его input.json.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_files = [PROFILES_FILE, LOYALTY_FILE, FLIGHTS_FILE]
    existing_files = [path for path in output_files if path.exists()]

    if existing_files:
        print("ОШИБКА: следующие выходные файлы уже существуют:")
        for path in existing_files:
            print(f"  {path.resolve()}")
        sys.exit(1)

    total_size = INPUT_FILE.stat().st_size

    print(f"Входной файл: {INPUT_FILE.resolve()}")
    print(f"Размер: {total_size / (1024 ** 3):.2f} ГБ")
    print(f"Папка результатов: {OUTPUT_DIR.resolve()}")
    print("Начинаю обработку...\n")

    started_at = time.monotonic()
    profile_count = 0
    loyalty_count = 0
    flights_count = 0

    try:
        with (
            INPUT_FILE.open("rb") as raw_input,
            PROFILES_FILE.open("w", newline="", encoding="utf-8-sig") as profiles_out,
            LOYALTY_FILE.open("w", newline="", encoding="utf-8-sig") as loyalty_out,
            FLIGHTS_FILE.open("w", newline="", encoding="utf-8-sig") as flights_out,
        ):
            reader = ProgressReader(raw_input, total_size)

            profiles_writer = csv.DictWriter(
                profiles_out,
                fieldnames=[
                    "ProfileID",
                    "NickName",
                    "Sex",
                    "First Name",
                    "Last Name",
                ],
                extrasaction="ignore",
            )

            loyalty_writer = csv.DictWriter(
                loyalty_out,
                fieldnames=[
                    "ProfileID",
                    "Status",
                    "programm",
                    "Number",
                ],
                extrasaction="ignore",
            )

            flights_writer = csv.DictWriter(
                flights_out,
                fieldnames=[
                    "ProfileID",
                    "Date",
                    "Codeshare",
                    "Flight",
                    "Departure.City",
                    "Departure.Airport",
                    "Departure.Country",
                    "Arrival.City",
                    "Arrival.Airport",
                    "Arrival.Country",
                ],
                extrasaction="ignore",
            )

            profiles_writer.writeheader()
            loyalty_writer.writeheader()
            flights_writer.writeheader()

            last_progress_at = 0

            profiles = ijson.items(
                reader,
                "Forum Profiles.item",
                buf_size=READ_BUFFER_SIZE,
            )

            for profile in profiles:
                profile_count += 1

                if not isinstance(profile, dict):
                    raise ValueError(
                        f"Профиль №{profile_count} не является JSON-объектом."
                    )

                real_name = profile.get("Real Name") or {}

                if not isinstance(real_name, dict):
                    raise ValueError(
                        f"Поле 'Real Name' в профиле №{profile_count} "
                        "должно быть объектом или null."
                    )

                profiles_writer.writerow({
                    "ProfileID": profile_count,
                    "NickName": get_value(profile, "NickName"),
                    "Sex": get_value(profile, "Sex"),
                    "First Name": get_value(real_name, "First Name"),
                    "Last Name": get_value(real_name, "Last Name"),
                })

                loyalty_programs = validate_array(
                    profile.get("Loyality Programm"),
                    "Loyality Programm",
                )

                for program in loyalty_programs:
                    if not isinstance(program, dict):
                        continue

                    loyalty_writer.writerow({
                        "ProfileID": profile_count,
                        "Status": get_value(program, "Status"),
                        "programm": get_value(program, "programm"),
                        "Number": get_value(program, "Number"),
                    })

                    loyalty_count += 1

                registered_flights = validate_array(
                    profile.get("Registered Flights"),
                    "Registered Flights",
                )

                for flight in registered_flights:
                    if not isinstance(flight, dict):
                        continue

                    departure = flight.get("Departure") or {}
                    arrival = flight.get("Arrival") or {}

                    if not isinstance(departure, dict):
                        departure = {}

                    if not isinstance(arrival, dict):
                        arrival = {}

                    codeshare = flight.get("Codeshare", "")

                    if codeshare is None:
                        codeshare = ""

                    flights_writer.writerow({
                        "ProfileID": profile_count,
                        "Date": get_value(flight, "Date"),
                        "Codeshare": codeshare,
                        "Flight": get_value(flight, "Flight"),
                        "Departure.City": get_value(departure, "City"),
                        "Departure.Airport": get_value(departure, "Airport"),
                        "Departure.Country": get_value(departure, "Country"),
                        "Arrival.City": get_value(arrival, "City"),
                        "Arrival.Airport": get_value(arrival, "Airport"),
                        "Arrival.Country": get_value(arrival, "Country"),
                    })

                    flights_count += 1

                if profile_count % PROGRESS_INTERVAL == 0:
                    profiles_out.flush()
                    loyalty_out.flush()
                    flights_out.flush()

                    show_progress(
                        reader,
                        profile_count,
                        loyalty_count,
                        flights_count,
                        started_at,
                        last_progress_at,
                    )

                    last_progress_at = profile_count

            profiles_out.flush()
            loyalty_out.flush()
            flights_out.flush()

            show_progress(
                reader,
                profile_count,
                loyalty_count,
                flights_count,
                started_at,
                last_progress_at,
            )

        elapsed = time.monotonic() - started_at

        print("\n\nГОТОВО!")
        print(f"Обработано профилей: {profile_count:,}")
        print(f"Экспортировано программ лояльности: {loyalty_count:,}")
        print(f"Экспортировано рейсов: {flights_count:,}")
        print(f"Время обработки: {format_duration(elapsed)}")
        print("\nСозданы файлы:")

        for path in output_files:
            print(f"  {path.resolve()} ({path.stat().st_size / (1024 ** 2):,.1f} МБ)")

    except KeyboardInterrupt:
        print("\n\nОбработка прервана пользователем.")
        sys.exit(130)

    except Exception as error:
        print(f"\n\nОШИБКА: {error}")
        print(
            "Конвертация не завершена. CSV-файлы могут содержать частичные данные."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
