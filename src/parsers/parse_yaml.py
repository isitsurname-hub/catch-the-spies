import argparse
import csv
import re
import sys
import time
from pathlib import Path

INPUT_YAML = "SkyTeam-Exchange.yaml"
PROGRESS_INTERVAL = 1.0

COLUMNS = [
    "DATE",
    "FLIGHT",
    "FF_PROGRAM",
    "CLASS",
    "FARE",
    "FROM",
    "TO",
    "STATUS",
]

DATE_RE = re.compile(r"""^['"]?([^:'"]+)['"]?:\s*(?:#.*)?$""")
FLIGHT_RE = re.compile(r"^  ([^ \t][^:]*):\s*(?:#.*)?$")
FIELD_RE = re.compile(r"^    (FROM|TO|STATUS):\s*(.*?)\s*$")
FF_RE = re.compile(r"^      (.+?):\s*\{(.*)\}\s*$")

CLASS_RE = re.compile(r"(?:^|,)\s*CLASS:\s*([^,}]+)")
FARE_RE = re.compile(r"(?:^|,)\s*FARE:\s*([^,}]+)")


def clean(value):
    value = value.strip()
    if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in "'\""
    ):
        value = value[1:-1]
    return value


def parse_ff(line):
    """Разобрать одну строку FF, например FB 520518073: {...}."""
    match = FF_RE.match(line)
    if not match:
        return None

    ff_program, details = match.groups()

    class_match = CLASS_RE.search(details)
    fare_match = FARE_RE.search(details)

    if not class_match or not fare_match:
        return None

    return {
        "FF_PROGRAM": clean(ff_program),
        "CLASS": clean(class_match.group(1)),
        "FARE": clean(fare_match.group(1)),
    }


def convert(source: Path, destination: Path):
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    if source.resolve() == destination.resolve():
        raise ValueError("Входной и выходной файлы должны различаться.")

    total_bytes = source.stat().st_size
    if total_bytes == 0:
        raise ValueError("Исходный файл пуст.")

    destination.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    last_report = started
    lines = 0
    flights = 0
    records = 0
    malformed = 0
    current_date = ""
    flight = None
    departure = ""
    arrival = ""
    status = ""
    ff_entries = []

    def write_flight(writer):
        """Записать FF-записи завершённого рейса."""
        nonlocal records, flights

        if flight is None:
            return

        flights += 1

        for ff in ff_entries:
            writer.writerow({
                "DATE": current_date,
                "FLIGHT": flight,
                "FF_PROGRAM": ff["FF_PROGRAM"],
                "CLASS": ff["CLASS"],
                "FARE": ff["FARE"],
                "FROM": departure,
                "TO": arrival,
                "STATUS": status,
            })
            records += 1

    with source.open("rb") as fin, destination.open(
            "w", encoding="utf-8-sig", newline=""
    ) as fout:
        writer = csv.DictWriter(fout, fieldnames=COLUMNS)
        writer.writeheader()

        while True:
            raw = fin.readline()
            if not raw:
                break

            lines += 1
            line = raw.decode("utf-8-sig" if lines == 1 else "utf-8").rstrip(
                "\r\n"
            )

            if line and not line[0].isspace():
                match = DATE_RE.match(line)
                if match:
                    write_flight(writer)
                    flight = None
                    current_date = clean(match.group(1))
                    continue

            match = FLIGHT_RE.match(line)
            if match:
                write_flight(writer)
                flight = clean(match.group(1))
                departure = ""
                arrival = ""
                status = ""
                ff_entries = []
                continue

            if flight is not None:
                match = FIELD_RE.match(line)
                if match:
                    key, value = match.groups()
                    value = clean(value)

                    if key == "FROM":
                        departure = value
                    elif key == "TO":
                        arrival = value
                    elif key == "STATUS":
                        status = value
                    continue

                if line.startswith("      "):
                    if FF_RE.match(line):
                        ff = parse_ff(line)
                        if ff is None:
                            malformed += 1
                        else:
                            ff_entries.append(ff)

            now = time.monotonic()
            if now - last_report >= PROGRESS_INTERVAL:
                percent = min(100.0, fin.tell() / total_bytes * 100)
                elapsed = now - started
                speed = lines / elapsed if elapsed else 0

                print(
                    f"\rПрогресс: {percent:6.2f}% | "
                    f"строк: {lines:,} | "
                    f"рейсов: {flights:,} | "
                    f"записей CSV: {records:,} | "
                    f"скорость: {speed:,.0f} строк/с",
                    end="",
                    flush=True,
                )
                last_report = now

        write_flight(writer)

    elapsed = time.monotonic() - started

    print("\n\nОбработка завершена.")
    print(f"Прочитано строк YAML: {lines:,}")
    print(f"Обработано рейсов: {flights:,}")
    print(f"Записано строк CSV: {records:,}")
    print(f"Некорректных записей FF: {malformed:,}")
    print(f"Время: {elapsed:.1f} сек.")
    print(f"Результат: {destination.resolve()}")

    if malformed:
        print(
            "ВНИМАНИЕ: некоторые строки FF не удалось разобрать.",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Потоковое преобразование YAML с рейсами в CSV"
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=INPUT_YAML,
        help="Путь к исходному YAML",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Путь к итоговому CSV",
    )

    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    destination = (
        args.output.expanduser().resolve()
        if args.output
        else source.with_suffix(".csv")
    )

    try:
        convert(source, destination)
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        sys.exit(f"\nОШИБКА: {exc}")


if __name__ == "__main__":
    main()
