#!/usr/bin/env python3
"""Удаляет из CSV столбцы, значения которых одинаковы во всех строках.

Работает в два прохода, не загружая весь файл в память.
Исходный CSV не изменяется.
"""

import argparse
import csv
from pathlib import Path

# ---------------- НАСТРОЙКИ ----------------
# Файл CSV, который был получен после объединения посадочных талонов.
# Путь задаётся относительно папки со скриптом (проекта PyCharm).
INPUT_CSV = (
    Path(__file__).resolve().parent
    / "YourBoardingPassDotAero"
    / "all_boarding_passes.csv"
)

# None = автоматически добавить _no_constants к имени исходного файла.
OUTPUT_CSV = None
# -------------------------------------------


def read_and_check_rows(reader, column_count):
    """Возвращает очередные строки, проверяя правильность количества полей."""
    for row in reader:
        if len(row) != column_count:
            raise ValueError(
                f"Строка CSV {reader.line_num}: ожидалось {column_count} полей, "
                f"получено {len(row)}. Обработка остановлена."
            )
        yield row


def remove_constant_columns(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"CSV-файл не найден: {source}")
    if source.resolve() == target.resolve():
        raise ValueError("Исходный и выходной файлы не должны совпадать!")

    # Проход 1: выяснить, какие столбцы меняются от строки к строке.
    with source.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        if not headers:
            raise ValueError("CSV пустой или не содержит заголовков.")

        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("В CSV нет строк с данными.")
        if len(first_row) != len(headers):
            raise ValueError("Количество полей первой строки не совпадает с заголовком.")

        is_variable = [False] * len(headers)
        count = 1
        for row in read_and_check_rows(reader, len(headers)):
            count += 1
            for i, value in enumerate(row):
                if value != first_row[i]:
                    is_variable[i] = True

    if count == 1:
        raise ValueError(
            "В CSV только одна строка с данными. "
            "Удаление константных столбцов неинформативно."
        )

    kept_indices = [i for i, varies in enumerate(is_variable) if varies]
    removed = [(headers[i], first_row[i]) for i, varies in enumerate(is_variable) if not varies]
    if not kept_indices:
        raise ValueError("Во всех столбцах постоянные значения: сохранять CSV без столбцов бессмысленно.")

    # Проход 2: записать только переменные столбцы.
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("r", encoding="utf-8-sig", newline="") as src,
        target.open("w", encoding="utf-8-sig", newline="") as dst,
    ):
        reader = csv.reader(src)
        writer = csv.writer(dst)
        original_headers = next(reader)
        writer.writerow([original_headers[i] for i in kept_indices])
        for row in read_and_check_rows(reader, len(headers)):
            writer.writerow([row[i] for i in kept_indices])

    print(f"Обработано строк: {count}")
    print(f"Всего столбцов: {len(headers)}")
    print(f"Удалено постоянных: {len(removed)}")
    print(f"Осталось: {len(kept_indices)}")
    if removed:
        print("\nУдалённые столбцы (название = общее значение):")
        for name, value in removed:
            print(f"  {name} = {value!r}")
    else:
        print("\nПостоянных столбцов нет, сохранены все столбцы.")
    print(f"\nНовый CSV сохранён: {target}")


def main():
    parser = argparse.ArgumentParser(description="Удаление постоянных столбцов CSV")
    parser.add_argument(
        "input_csv", nargs="?", type=Path, default=INPUT_CSV,
        help="Путь к исходному CSV (необязателен, можно задать в настройках)"
    )
    parser.add_argument("-o", "--output", type=Path, help="Путь к итоговому CSV")
    args = parser.parse_args()

    source = args.input_csv.expanduser().resolve()
    target = (
        args.output.expanduser().resolve()
        if args.output is not None
        else Path(OUTPUT_CSV).expanduser().resolve()
        if OUTPUT_CSV is not None
        else source.with_name(f"{source.stem}_no_constants.csv")
    )
    try:
        remove_constant_columns(source, target)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"ОШИБКА: {exc}\n")


if __name__ == "__main__":
    main()
