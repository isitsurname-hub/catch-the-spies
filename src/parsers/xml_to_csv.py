#!/usr/bin/env python3
"""
Конвертация PointzAggregator-AirlinesData.xml в плоский CSV.

Использует потоковый парсер lxml.etree.iterparse для минимизации
потребления оперативной памяти. Иерархия XML сплющивается:
одна строка CSV соответствует одному событию (activity),
а данные пользователя и карты дублируются в каждой строке.

Запуск без аргументов использует пути по умолчанию от корня проекта.
"""
import argparse
import csv
import sys
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    sys.exit("Ошибка: библиотека 'lxml' не установлена. Выполните: pip install lxml")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable=None, **kwargs):
        return iterable

# Корень проекта: поднимаемся из src/parsers на 2 уровня вверх
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT = PROJECT_ROOT / "data" / "00_raw" / "PointzAggregator-AirlinesData.xml"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "01_interim" / "pointz_airlines_data.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Конвертация XML-полетов в CSV")
    parser.add_argument(
        'input_file',
        nargs='?',
        default=DEFAULT_INPUT,
        type=Path,
        help=f'Путь к исходному XML (по умолчанию: {DEFAULT_INPUT})'
    )
    parser.add_argument(
        'output_file',
        nargs='?',
        default=DEFAULT_OUTPUT,
        type=Path,
        help=f'Путь к выходному CSV (по умолчанию: {DEFAULT_OUTPUT})'
    )
    args = parser.parse_args()

    in_path: Path = args.input_file
    out_path: Path = args.output_file

    if not in_path.exists():
        sys.exit(f"Файл не найден: {in_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Обеспечение корректного вывода Unicode в консоли Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(f"Чтение: {in_path}")
    print(f"Запись: {out_path}")

    fields = [
        'uid', 'first_name', 'last_name',
        'card_number', 'bonus_programm',
        'activity_type', 'code', 'date', 'departure', 'arrival', 'fare'
    ]

    # Контекст текущих элементов при обходе дерева
    current_user = {}
    current_card = {}
    activity_data = {}

    context = etree.iterparse(
        str(in_path), events=('start', 'end'), recover=True, huge_tree=True
    )

    with open(out_path, 'w', encoding='utf-8', newline='') as fout:
        writer = csv.DictWriter(fout, fieldnames=fields)
        writer.writeheader()

        pbar = tqdm(desc="Конвертация", unit=" user")

        try:
            for event, elem in context:
                if event == 'start':
                    if elem.tag == 'user':
                        current_user = {'uid': elem.get('uid'), 'first_name': '', 'last_name': ''}
                    elif elem.tag == 'name':
                        current_user['first_name'] = elem.get('first', '')
                        current_user['last_name'] = elem.get('last', '')
                    elif elem.tag == 'card':
                        current_card = {'card_number': elem.get('number'), 'bonus_programm': ''}
                    elif elem.tag == 'activity':
                        activity_data = {
                            'activity_type': elem.get('type'),
                            'code': '', 'date': '', 'departure': '', 'arrival': '', 'fare': ''
                        }

                elif event == 'end':
                    if elem.tag == 'bonusprogramm':
                        current_card['bonus_programm'] = elem.text.strip() if elem.text else ''
                    elif elem.tag == 'Code':
                        activity_data['code'] = elem.text.strip() if elem.text else ''
                    elif elem.tag == 'Date':
                        activity_data['date'] = elem.text.strip() if elem.text else ''
                    elif elem.tag == 'Departure':
                        activity_data['departure'] = elem.text.strip() if elem.text else ''
                    elif elem.tag == 'Arrival':
                        activity_data['arrival'] = elem.text.strip() if elem.text else ''
                    elif elem.tag == 'Fare':
                        activity_data['fare'] = elem.text.strip() if elem.text else ''

                    elif elem.tag == 'activity':
                        row = {**current_user, **current_card, **activity_data}
                        writer.writerow(row)

                    elif elem.tag == 'user':
                        pbar.update(1)

                    # Освобождение памяти (критично при использовании iterparse)
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]

        except etree.XMLSyntaxError as e:
            print(f"\nПредупреждение: синтаксическая ошибка XML ({e}).")
            print("Обработка остановлена, но сохранено всё, что удалось прочитать.")
        finally:
            pbar.close()

    print(f"\nГотово. Данные выгружены в {out_path}")


if __name__ == '__main__':
    main()