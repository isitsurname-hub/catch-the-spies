#!/usr/bin/env python3
"""
Парсинг PDF-таблицы расписания SkyTeam в плоский CSV.

Страница режется пополам (двухколоночный журнал), из каждой половины
извлекаются слова через PyMuPDF, группируются в строки по координате Y,
затем регуляркой выдёргиваются поля рейса (Validity, дни, время вылета/
прилёта, номер, борт, время в пути). Заголовки FROM/TO запоминаются
в состоянии и применяются ко всем рейсам до следующей шапки.

Строка "Operated by ..." идёт после рейса, поэтому рейс держится
в pending_row и дописывается только при следующем событии (новая строка,
"Consult your travel agent" или конец половины страницы).

Попутно собирается статистика (звёздочки, операторы, дефисы) — по ней
легко проверить, что парсер ничего не потерял.

Запуск без аргументов: читает Skyteam_Timetable.pdf из текущей папки,
пишет Skyteam_Parsed.csv рядом. Первые 4 страницы пропускаются (титул).
"""

import pymupdf as fitz
import csv
import re
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

PDF_FILE = "Skyteam_Timetable.pdf"
CSV_FILE = "Skyteam_Parsed.csv"

#   Период действия	1 Jan - 2 Feb
#	Дни недели	1234567
#	Время вылета	09:30
#	Время прилёта	12:45
#	Номер рейса (* опционально)	SU123*
#	Код самолёта	320
#	Время в пути	3H15M

RE_FLIGHT_ROW = re.compile(
    r'^(\d{1,2}\s+[A-Za-z]{3}\s*-\s*\d{1,2}\s+[A-Za-z]{3})\s+'
    r'([1-7\s]*?)\s*'
    r'(\d{2}:\d{2}[^\s]*)\s+'
    r'(\d{2}:\d{2}[^\s]*)\s+'
    r'([A-Z0-9]{2}\s*\d{1,4}\s*\*?)\s+'
    r'([A-Z0-9]{3})\s+'
    r'(\d{1,2}H\d{1,2}M)'
)

# Строка
def extract_lines_from_clip(page, clip_rect):
    # set(), чтобы убрать слои дублирования невидимого текста
    words = list(set(page.get_text("words", clip=clip_rect)))
    if not words: return []

    words.sort(key=lambda w: (w[1], w[0]))
    lines = []
    current_line = []
    current_y = words[0][1]

    for w in words:
        if abs(w[1] - current_y) <= 2.0:
            current_line.append(w)
        else:
            current_line.sort(key=lambda x: x[0])
            lines.append(" ".join([word[4] for word in current_line]))
            current_line = [w]
            current_y = w[1]
    if current_line:
        current_line.sort(key=lambda x: x[0])
        lines.append(" ".join([word[4] for word in current_line]))

    return lines

# Страны
def extract_headers(text):
    f_city, f_code, t_city, t_code = "", "", "", ""
    if "Validity" in text:
        header_text = text.split("Validity")[0]
    else:
        header_text = text
    lines = [l.strip() for l in header_text.split('\n') if l.strip()]
    for i, line in enumerate(lines):
        if "FROM:" in line:
            if line != "FROM:":
                match = re.search(r'FROM:\s*(.*?)\s+([A-Z]{3})', line)
                if match: f_city, f_code = match.group(1), match.group(2)
            elif i > 0:
                match = re.search(r'(.*?)\s+([A-Z]{3})$', lines[i - 1])
                if match: f_city, f_code = match.group(1), match.group(2)
        if "TO:" in line:
            if line != "TO:":
                match = re.search(r'TO:\s*(.*?)\s+([A-Z]{3})', line)
                if match: t_city, t_code = match.group(1), match.group(2)
            elif i > 0:
                match = re.search(r'(.*?)\s+([A-Z]{3})$', lines[i - 1])
                if match: t_city, t_code = match.group(1), match.group(2)
    return f_city, f_code, t_city, t_code


def process_page_half(page, clip_rect, writer, state, stats):
    lines = extract_lines_from_clip(page, clip_rect)
    if not lines: return state

    full_text = "\n".join(lines)
    new_f_city, new_f_code, new_t_city, new_t_code = extract_headers(full_text)
    if new_f_city: state['f_city'], state['f_code'] = new_f_city, new_f_code
    if new_t_city: state['t_city'], state['t_code'] = new_t_city, new_t_code

    pending_row = state.get('pending_row', None)
    pending_has_star = state.get('pending_has_star', False)

    def write_and_count(row):
        if not row: return
        # звездочки в номере рейса
        if '*' in row[8]:
            stats['stars'] += 1
        # операторы
        if row[11]:
            stats['operated'] += 1
        # дефисы во всех колонках
        row_str = " ".join([str(x) for x in row])
        stats['hyphens'] += row_str.count('-')
        stats['plus_minus'] += row_str.count('+-')

        writer.writerow(row)

    for line in lines:
        line = line.strip()
        if not line: continue

        if "Consult your travel agent" in line:
            write_and_count(pending_row)
            pending_row = None
            pending_has_star = False
            write_and_count(
                [state['f_city'], state['f_code'], state['t_city'], state['t_code'], "NO_DATA", line, "", "", "", "",
                 "", ""])
            continue

        if "Operated by" in line:
            if pending_row and pending_has_star:
                pending_row[11] = line
                pending_has_star = False
            continue

        match_flight = RE_FLIGHT_ROW.search(line)
        if match_flight:
            write_and_count(pending_row)

            flight_num = match_flight.group(5)
            pending_row = [
                state['f_city'], state['f_code'], state['t_city'], state['t_code'],
                match_flight.group(1), match_flight.group(2).strip(),
                match_flight.group(3), match_flight.group(4),
                flight_num, match_flight.group(6),
                match_flight.group(7), ""
            ]

            if '*' in flight_num:
                pending_has_star = True
            else:
                pending_has_star = False

    state['pending_row'] = pending_row
    state['pending_has_star'] = pending_has_star
    return state


def main():
    start_time = time.time()

    doc = fitz.open(PDF_FILE)
    total_pages = len(doc)

    # счетчики
    stats = {"stars": 0, "operated": 0, "hyphens": 0, "plus_minus": 0}

    with open(CSV_FILE, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(
            ["From_City", "From_Code", "To_City", "To_Code", "Validity", "Days", "Dep_Time", "Arr_Time", "Flight",
             "Aircraft", "Travel_Time", "Operated_By"])

        left_state = {"f_city": "", "f_code": "", "t_city": "", "t_code": "", "pending_row": None,
                      "pending_has_star": False}
        right_state = {"f_city": "", "f_code": "", "t_city": "", "t_code": "", "pending_row": None,
                       "pending_has_star": False}

        for page_num in range(4, total_pages):
            if page_num % 1000 == 0:
                elapsed = time.time() - start_time
                print(f"{page_num}/{total_pages} Прошло: {elapsed / 60:.1f} мин.")

            page = doc.load_page(page_num)
            width, height = page.rect.width, page.rect.height

            left_clip = fitz.Rect(0, 0, width / 2, height)
            right_clip = fitz.Rect(width / 2, 0, width, height)

            left_state = process_page_half(page, left_clip, writer, left_state, stats)
            right_state = process_page_half(page, right_clip, writer, right_state, stats)

        # Сохраняем остатки из памяти
        if left_state.get('pending_row'):
            # Копируем логику подсчета для последних строк
            row = left_state['pending_row']
            if '*' in row[8]: stats['stars'] += 1
            if row[11]: stats['operated'] += 1
            row_str = " ".join([str(x) for x in row])
            stats['hyphens'] += row_str.count('-')
            stats['plus_minus'] += row_str.count('+-')
            writer.writerow(row)

        if right_state.get('pending_row'):
            row = right_state['pending_row']
            if '*' in row[8]: stats['stars'] += 1
            if row[11]: stats['operated'] += 1
            row_str = " ".join([str(x) for x in row])
            stats['hyphens'] += row_str.count('-')
            stats['plus_minus'] += row_str.count('+-')
            writer.writerow(row)

    doc.close()

    print(f"*:  {stats['stars']}")
    print(f"Operated by:  {stats['operated']}")
    print(f"'-' {stats['hyphens'] - stats['plus_minus']}")


if __name__ == "__main__":
    main()
