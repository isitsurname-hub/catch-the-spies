#!/usr/bin/env python3
"""Собрать посадочные талоны из всех листов Excel-файлов в один CSV.

Ожидаемый шаблон: YourBoardingPassDotAero-*.xlsx (каждый лист — один талон).
Используется только стандартная библиотека Python; установка пакетов не нужна.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import posixpath
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile


# ───────────── НАСТРОЙКИ: МЕНЯТЬ НУЖНО В ОСНОВНОМ ТОЛЬКО ЭТО ─────────────
# INPUT_FOLDER = Path.home() / "gotm/PycharmProjects/SpionProject/YourBoardingPassDotAero"  # Папка со всеми файлами .xlsx
INPUT_FOLDER = Path("/home/gotm/PycharmProjects/SpionProject/YourBoardingPassDotAero")  # Папка со всеми файлами .xlsx
OUTPUT_FILENAME = "all_boarding_passes.csv"     # Имя итогового CSV
SEARCH_SUBFOLDERS = False                       # True — искать и во вложенных папках
# ─────────────────────────────────────────────────────────────────────────

XML_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XML_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XML_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Названия столбцов CSV и координаты значений в каждом посадочном талоне.
# Код из F3 присутствует не у всех пассажиров, но мы обязательно его сохраняем.
FIELD_CELLS = {
    "document_type": "A1",             # BOARDING PASS
    "sequence": "H1",                  # Номер в последовательности регистрации
    "title": "A3",                    # MR / MRS
    "passenger_name": "B3",           # ФИО
    "extra_code_F3": "F3",            # Дополнительный код без подписи в исходном файле
    "booking_class": "H3",            # Y / A / J / P
    "flight_number": "A5",            # Номер рейса
    "departure_city": "D5",           # Город вылета
    "arrival_city": "H5",             # Город прибытия
    "gate": "B7",                     # Выход на посадку
    "departure_airport": "D7",       # Код аэропорта вылета
    "arrival_airport": "H7",         # Код аэропорта прибытия
    "departure_date": "A9",          # Дата вылета
    "departure_time": "C9",          # Время вылета
    "operator_note": "E9",            # Информация об обслуживающей авиакомпании
    "boarding_notice": "A11",        # Предупреждение о завершении посадки
    "seat": "H11",                   # Место
    "pnr": "B13",                    # Код бронирования
    "e_ticket": "E13",               # Номер электронного билета (строка!)
}

CSV_COLUMNS = ["source_file", "source_sheet", *FIELD_CELLS.keys()]
REQUIRED_CELLS = set(FIELD_CELLS.values())


def shared_strings_from_book(zf: ZipFile) -> list[str]:
    """Текстовые значения, используемые на листах .xlsx."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in item.iter(XML_MAIN + "t"))
        for item in root.findall(XML_MAIN + "si")
    ]


def worksheets_from_book(zf: ZipFile):
    """Выдать пары (отображаемое имя листа, путь XML-листа внутри .xlsx)."""
    book = ET.fromstring(zf.read("xl/workbook.xml"))
    relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.get("Id"): rel.get("Target", "")
        for rel in relationships.findall(XML_PKG_REL + "Relationship")
        if rel.get("Type", "").endswith("/worksheet")
    }
    sheets_tag = book.find(XML_MAIN + "sheets")
    if sheets_tag is None:
        return
    for sheet in sheets_tag.findall(XML_MAIN + "sheet"):
        rid = sheet.get(XML_DOC_REL + "id")
        target = targets.get(rid)
        if not target:
            continue
        # OOXML допускает как относительные, так и абсолютные пути.
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        elif target.startswith("xl/"):
            sheet_path = target
        else:
            sheet_path = posixpath.normpath(posixpath.join("xl", target))
        yield sheet.get("name", ""), sheet_path


def values_from_sheet(zf: ZipFile, sheet_path: str, shared: list[str]) -> dict[str, str]:
    """Прочитать только нужные ячейки, не загружая Excel через тяжёлые библиотеки."""
    root = ET.fromstring(zf.read(sheet_path))
    result: dict[str, str] = {}
    for cell in root.iter(XML_MAIN + "c"):
        address = cell.get("r")
        if address not in REQUIRED_CELLS:
            continue

        cell_type = cell.get("t", "")
        raw = cell.find(XML_MAIN + "v")
        if cell_type == "inlineStr":
            # Встроенные строки встречаются в некоторых вариантах Excel.
            inline = cell.find(XML_MAIN + "is")
            value = "".join(t.text or "" for t in inline.iter(XML_MAIN + "t")) if inline is not None else ""
        elif raw is None or raw.text is None:
            value = ""
        elif cell_type == "s":
            value = shared[int(raw.text)]
        elif cell_type == "b":
            value = "TRUE" if raw.text == "1" else "FALSE"
        else:
            value = raw.text
        result[address] = value.strip()
    return result


def excel_files(folder: Path, recursive: bool) -> list[Path]:
    source = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        (p for p in source if p.is_file() and p.suffix.lower() in {".xlsx", ".xlsm"}
         and not p.name.startswith("~$")),
        key=lambda p: str(p).lower(),
    )


def run(folder: Path, output: Path, recursive: bool) -> int:
    if not folder.is_dir():
        print(f"[ОШИБКА] Папка не существует: {folder}", file=sys.stderr)
        return 1

    files = excel_files(folder, recursive)
    if not files:
        print(f"[ОШИБКА] В папке нет .xlsx/.xlsm файлов: {folder}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    failures = 0
    print(f"Найдено Excel-файлов: {len(files)}")

    # utf-8-sig добавляет BOM: Excel корректно распознаёт русские буквы.
    with output.open("w", newline="", encoding="utf-8-sig") as result_file:
        writer = csv.DictWriter(result_file, fieldnames=CSV_COLUMNS, delimiter=",")
        writer.writeheader()
        for file in files:
            file_count = 0
            try:
                with ZipFile(file) as zf:
                    shared = shared_strings_from_book(zf)
                    for sheet_name, sheet_path in worksheets_from_book(zf):
                        try:
                            cells = values_from_sheet(zf, sheet_path, shared)
                        except (KeyError, ValueError, IndexError, ET.ParseError) as exc:
                            print(f"[ОШИБКА] {file.name}, лист {sheet_name}: {exc}", file=sys.stderr)
                            failures += 1
                            continue

                        # Листы другой структуры не считаем посадочными талонами.
                        if cells.get("A1", "").upper() != "BOARDING PASS":
                            print(f"[ПРОПУСК] {file.name}, лист {sheet_name}: нет 'BOARDING PASS' в A1")
                            continue

                        row = {"source_file": file.name, "source_sheet": sheet_name}
                        row.update({col: cells.get(address, "") for col, address in FIELD_CELLS.items()})
                        writer.writerow(row)
                        file_count += 1
                        total += 1
            except (BadZipFile, OSError, KeyError, ET.ParseError) as exc:
                print(f"[ОШИБКА] Не удалось обработать {file}: {exc}", file=sys.stderr)
                failures += 1
                continue
            print(f"[OK] {file.name}: {file_count} талонов")

    print(f"\nГотово. Строк с талонами: {total}")
    print(f"CSV: {output.resolve()}")
    if failures:
        print(f"Внимание: при чтении возникло ошибок: {failures}", file=sys.stderr)
    return 0 if total > 0 and failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Сбор посадочных талонов из множества .xlsx файлов в единый CSV")
    parser.add_argument("folder", nargs="?", type=Path, default=INPUT_FOLDER,
                        help="Папка с файлами .xlsx (можно также задать INPUT_FOLDER в скрипте)")
    parser.add_argument("-o", "--output", type=Path,
                        help=f"Куда сохранить CSV (по умолчанию: <папка>/{OUTPUT_FILENAME})")
    parser.add_argument("-r", "--recursive", action="store_true", default=SEARCH_SUBFOLDERS,
                        help="Искать также во вложенных папках")
    args = parser.parse_args()
    folder = args.folder.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else folder / OUTPUT_FILENAME
    return run(folder, output, args.recursive)


if __name__ == "__main__":
    raise SystemExit(main())
