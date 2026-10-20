#!/usr/bin/env python3
"""
Конвертация FrequentFlyerForum-Profiles.json в плоский CSV.

Потоковое чтение (ijson) — не загружает 500+ МБ в память.
Вложенные структуры (рейсы, программы лояльности) сохраняются как JSON-строки.

Запуск без аргументов: берет пути по умолчанию от корня проекта.
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import ijson
except ImportError:
    sys.exit("Ошибка: библиотека 'ijson' не установлена. Выполните: pip install ijson")

try:
    import orjson as fast_json

    def dumps(obj: Any) -> str:
        return fast_json.dumps(obj).decode('utf-8')
except ImportError:
    def dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable


# Корень проекта: поднимаемся из src/parsers на 2 уровня вверх
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT = PROJECT_ROOT / "data" / "00_raw" / "FrequentFlyerForum-Profiles.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "01_interim" / "frequent_flyer_profiles.csv"


def extract_profile(record: Dict[str, Any]) -> Dict[str, Any]:
    """Извлекает нужные поля из сырой записи."""
    real_name = record.get('Real Name') or {}
    first_name = real_name.get('First Name')
    last_name = real_name.get('Last Name')

    loyalty = record.get('Loyality Programm', [])
    # Убираем случайные пробелы в номерах карт
    for item in loyalty:
        if 'Number' in item and isinstance(item['Number'], str):
            item['Number'] = item['Number'].strip()

    flights = record.get('Registered Flights', [])

    return {
        'NickName': record.get('NickName'),
        'Sex': record.get('Sex'),
        'First Name': first_name,
        'Last Name': last_name,
        'Loyalty_JSON': dumps(loyalty) if loyalty else None,
        'Flights_JSON': dumps(flights) if flights else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Конвертация JSON-профилей в CSV")
    parser.add_argument(
        'input_file',
        nargs='?',
        default=DEFAULT_INPUT,
        type=Path,
        help=f'Путь к исходному JSON (по умолчанию: {DEFAULT_INPUT})',
    )
    parser.add_argument(
        'output_file',
        nargs='?',
        default=DEFAULT_OUTPUT,
        type=Path,
        help=f'Путь к выходному CSV (по умолчанию: {DEFAULT_OUTPUT})',
    )
    args = parser.parse_args()

    in_path: Path = args.input_file
    out_path: Path = args.output_file

    if not in_path.exists():
        sys.exit(f"Файл не найден: {in_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 в консоли Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(f"Чтение: {in_path}")
    print(f"Запись: {out_path}")

    fields = ['NickName', 'Sex', 'First Name', 'Last Name', 'Loyalty_JSON', 'Flights_JSON']

    # newline='' предотвращает пустые строки между записями в Windows
    with open(in_path, 'rb') as fin, open(out_path, 'w', encoding='utf-8', newline='') as fout:
        writer = csv.DictWriter(fout, fieldnames=fields)
        writer.writeheader()

        # Генератор: одна запись за раз, без загрузки массива целиком
        records = ijson.items(fin, 'Forum Profiles.item')

        count = 0
        for record in tqdm(records, desc="Конвертация", unit="профиль"):
            writer.writerow(extract_profile(record))
            count += 1

    print(f"Готово. Обработано записей: {count}")


if __name__ == '__main__':
    main()