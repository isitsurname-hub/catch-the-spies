#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize the agreed travel CSV exports. Python standard library only."""
import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

NA = "NA"
ISSUES = []
COUNTRIES = {}
CYR = dict(zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
               ["A", "B", "V", "G", "D", "E", "E", "ZH", "Z", "I", "I", "K", "L", "M", "N", "O", "P", "R", "S", "T",
                "U", "F", "KH", "TS", "CH", "SH", "SHCH", "", "Y", "", "E", "YU", "YA"]))


def clean(v): return re.sub(r"\s+", " ", (v or "").strip())


def missing(v): return clean(v).casefold() in {"", "n/a", "na", "not presented", "none", "null"}


def na(v): return NA if missing(v) else clean(v)


def log(file, row, field, value, reason): ISSUES.append(
    {"file": file, "row": str(row), "field": field, "original_value": str(value or ""), "reason": reason})


def latin(v):
    v = clean(v)
    out = "".join(CYR.get(c.upper(), c) for c in v).upper()
    return "".join(c for c in unicodedata.normalize("NFKD", out) if not unicodedata.combining(c))


def sex(v):
    v = clean(v).casefold()
    if v in {"m", "male", "м", "мужской", "муж"}:
        return "MALE"
    if v in {"f", "female", "ж", "женский", "жен"}:
        return "FEMALE"
    return NA


def date(v, file, row, field, formats=None):
    v = clean(v)
    if missing(v):
        return NA
    for fmt in formats or ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y"]:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    log(file, row, field, v, "Unrecognized date format")
    return NA


def time(v, file, row, field):
    v = clean(v)
    if missing(v):
        return NA
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return datetime.strptime(v, fmt).strftime("%H:%M")
        except ValueError:
            pass
    log(file, row, field, v, "Unrecognized time; expected HH:MM")
    return NA


def country(v, file, row, field):
    v = clean(v)
    if missing(v):
        if v.casefold() == "united":
            log(file, row, field, v, "Ambiguous country value mapped to NA")
        return NA
    if v.casefold() in COUNTRIES:
        result = COUNTRIES[v.casefold()]
        if result == NA:
            log(file, row, field, v, "Country mapping explicitly marks value as NA")
        return result
    log(file, row, field, v, "Country not found in country_mapping.json; preserved original value")
    return v


def airport(v, file, row, field):
    raw = clean(v)
    v = raw.upper()
    if missing(v):
        return NA
    if not re.fullmatch(r"[A-Z0-9]{3,4}", v):
        log(file, row, field, raw, "Unexpected airport-code shape; mapped to NA")
        return NA
    return v


def flight(v): return NA if missing(v) else clean(v).upper()


def name_parts(v, file, row, field, order="first_last"):
    p = clean(v).split()
    if not p or missing(v):
        return NA, NA, NA
    if order == "surname_first":
        if len(p) == 2:
            return latin(p[1]), NA, latin(p[0])
        if len(p) >= 3:
            return latin(p[1]), latin(" ".join(p[2:])), latin(p[0])
    else:
        initials = [i for i, token in enumerate(p) if len(token.rstrip(".")) == 1 and token.rstrip(".").isalpha()]
        if initials and len(p) >= 3:
            idx = initials[0]
            remaining = [token for j, token in enumerate(p) if j != idx]
            if len(initials) > 1:
                log(file, row, field, v, "Multiple one-letter tokens; first treated as middle initial")
            if len(remaining) > 2:
                log(file, row, field, v, "Extra name tokens; only first and last retained")
            return latin(remaining[0]), latin(p[idx]), latin(remaining[-1])
        if len(p) == 2:
            return latin(p[0]), NA, latin(p[1])
        if len(p) == 3:
            log(file, row, field, v, "Middle token has more than one character; retained")
            return latin(p[0]), latin(p[1]), latin(p[2])
        if len(p) > 3:
            log(file, row, field, v, "Unexpected number of name parts; no one-letter initial detected")
            return latin(p[0]), latin(" ".join(p[1:-1])), latin(p[-1])
    log(file, row, field, v, "Could not split name reliably")
    return NA, NA, NA


def read_csv(path):
    delim = ";" if path.name.casefold() in {"skyteam_timetable.csv", "boardingdata.csv"} else ","
    with path.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        if path.name.casefold() not in {"skyteam_timetable.csv", "boardingdata.csv"}:
            try:
                delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
            except csv.Error:
                pass
        reader = csv.DictReader(f, delimiter=delim)
        return list(reader.fieldnames or []), [{(k or "").strip(): (v or "") for k, v in row.items()} for row in
                                               reader], delim


def write_csv(path, headers, rows, delim):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=delim, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def process(path, headers, rows):
    fn = path.name
    low = fn.casefold()
    for i, r in enumerate(rows, 2):
        if low == "profiles.csv":
            if "ProfileID" in r:
                r["ProfileID"] = clean(r["ProfileID"]) or NA
            if "NickName" in r:
                r["NickName"] = na(r["NickName"])
            if "Sex" in r:
                r["Sex"] = sex(r["Sex"])
            for f in ("First Name", "Last Name"):
                if f in r:
                    r[f] = latin(r[f]) if not missing(r[f]) else NA
        elif low == "loyality.csv":
            for f in ("ProfileID", "Status", "Number"):
                if f in r:
                    r[f] = na(r[f])
            if "programm" in r:
                r["programm"] = latin(r["programm"])
        elif low == "flights.csv":
            if "ProfileID" in r:
                r["ProfileID"] = clean(r["ProfileID"]) or NA
            if "Date" in r:
                r["Date"] = date(r["Date"], fn, i, "Date")
            if "Codeshare" in r:
                v = clean(r["Codeshare"]).casefold()
                r["Codeshare"] = {"true": "Other", "false": "Own", "yes": "Other", "no": "Own", "own": "Own",
                                  "operated": "Other", "other": "Other"}.get(v, NA)
                if r["Codeshare"] == NA:
                    log(fn, i, "Codeshare", v, "Unknown codeshare value")
            if "Flight" in r:
                r["Flight"] = flight(r["Flight"])
            for f in ("Departure.City", "Arrival.City"):
                if f in r:
                    r[f] = NA if missing(r[f]) else clean(r[f]).title()
            for f in ("Departure.Airport", "Arrival.Airport"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
            for f in ("Departure.Country", "Arrival.Country"):
                if f in r:
                    r[f] = country(r[f], fn, i, f)
        elif low == "skyteam_timetable.csv":
            for old, city, countrycol in (
                    ("From_City", "From_City", "From_Country"), ("To_City", "To_City", "To_Country")):
                if old in r:
                    v = clean(r.pop(old))
                    if "," not in v:
                        r[city] = v.title() if v else NA
                        r[countrycol] = NA
                        log(fn, i, old, v, "Missing city-country comma")
                    else:
                        c, n = v.split(",", 1)
                        r[city] = clean(c).title() if clean(c) else NA
                        r[countrycol] = country(n, fn, i, countrycol)
                        if missing(n):
                            log(fn, i, countrycol, n, "Country missing after comma")
            if "Validity" in r:
                v = clean(r.pop("Validity"))
                m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})\s*-\s*(\d{1,2})\s+([A-Za-z]{3})", v)

                def make_day(d, mon):
                    try:
                        return "YYYY-%02d-%02d" % (datetime.strptime(mon.title(), "%b").month, int(d))
                    except ValueError:
                        return NA

                if m:
                    r["Validity_Start"] = make_day(m.group(1), m.group(2))
                    r["Validity_End"] = make_day(m.group(3), m.group(4))
                    if NA in (r["Validity_Start"], r["Validity_End"]):
                        log(fn, i, "Validity", v, "Invalid date component")
                else:
                    r["Validity_Start"] = r["Validity_End"] = NA
                    log(fn, i, "Validity", v, "Expected DD Mon - DD Mon")
            for f in ("From_Code", "To_Code"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
            if "Days" in r:
                r["Days"] = re.sub(r"\s+", "", clean(r["Days"])) or NA
            for f in ("Dep_Time", "Arr_Time"):
                if f in r:
                    r[f] = time(r[f], fn, i, f)
            if "Flight" in r:
                r["Flight"] = flight(r["Flight"])
            if "Aircraft" in r:
                r["Aircraft"] = latin(r["Aircraft"])
            if "Travel_Time" in r:
                v = clean(r["Travel_Time"]).upper()
                m = re.fullmatch(r"(?:(\d+)\s*H)?\s*(?:(\d+)\s*M)?", v)
                if missing(v):
                    r["Travel_Time"] = NA
                elif m and (m.group(1) or m.group(2)):
                    r["Travel_Time"] = str(int(m.group(1) or 0) * 60 + int(m.group(2) or 0))
                else:
                    r["Travel_Time"] = NA
                    log(fn, i, "Travel_Time", v, "Expected e.g. 1H25M")
            if "Operated_By" in r:
                r["Operated_By"] = na(r["Operated_By"])
        elif low in {"all_boarding_passes.csv", "all_boarding_no_sourse.csv", "all_boarding_passes_no_constants.csv"}:
            if "passenger_name" in r:
                a, b, c = name_parts(r["passenger_name"], fn, i, "passenger_name")
                r["passenger_first_name"], r["passenger_middle_initial"], r["passenger_last_name"] = a, b, c
                r.pop("passenger_name", None)
            if "title" in r:
                v = clean(r.pop("title")).upper()
                r["passenger_sex"] = {"MR": "MALE", "MRS": "FEMALE", "MS": "FEMALE", "MISS": "FEMALE"}.get(v, NA)
                if v and r["passenger_sex"] == NA:
                    log(fn, i, "title", v, "Unknown title")
            for f in (
                    "source_file", "source_sheet", "extra_code_F3", "gate", "seat", "operator_note", "boarding_notice",
                    "e_ticket", "pnr", "document_type", "booking_class", "flight_number"):
                if f in r:
                    v = clean(r[f])
                    r[f] = v.upper() if f in {"document_type", "booking_class", "flight_number", "pnr"} and not missing(
                        v) else na(v)
            if "sequence" in r:
                v = clean(r["sequence"])
                r["sequence"] = str(int(v)) if v.isdigit() else NA
                if not v.isdigit():
                    log(fn, i, "sequence", v, "Sequence is not an integer")
            for f in ("departure_airport", "arrival_airport"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
            if "departure_date" in r:
                r["departure_date"] = date(r["departure_date"], fn, i, "departure_date")
            if "departure_time" in r:
                r["departure_time"] = time(r["departure_time"], fn, i, "departure_time")
            for f in ("departure_city", "arrival_city"):
                if f in r:
                    r[f] = NA if missing(r[f]) else clean(r[f]).title()
        elif low == "pointz_airlines_data.csv":
            for f in ("uid", "card_number"):
                if f in r:
                    r[f] = na(r[f])
            for f in ("first_name", "last_name", "bonus_programm", "activity_type", "code", "fare"):
                if f in r:
                    r[f] = latin(r[f])
            if "card_number" in r and r["card_number"] != NA:
                r["card_number"] = re.sub(r"\s+", " ", r["card_number"])
            if "date" in r:
                r["date"] = date(r["date"], fn, i, "date")
            for f in ("departure", "arrival"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
        elif low == "skyteam-exchange.csv":
            if "DATE" in r:
                r["DATE"] = date(r["DATE"], fn, i, "DATE")
            for f in ("FLIGHT", "CLASS", "FARE", "STATUS"):
                if f in r:
                    r[f] = latin(r[f])
            if "FF_PROGRAM" in r:
                r["FF_PROGRAM"] = na(r["FF_PROGRAM"])
                r["FF_PROGRAM"] = r["FF_PROGRAM"].upper() if r[
                                                                 "FF_PROGRAM"] != NA else NA
            for f in ("FROM", "TO"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
        elif low == "boardingdata.csv":
            for f in ("PassengerFirstName", "PassengerSecondName", "PassengerLastName"):
                if f in r:
                    r[f] = latin(r[f])
            if "PassengerSex" in r:
                r["PassengerSex"] = sex(r["PassengerSex"])
            if "PassengerBirthDate" in r:
                r["PassengerBirthDate"] = date(r["PassengerBirthDate"], fn, i,
                                               "PassengerBirthDate", ["%m/%d/%Y", "%Y-%m-%d"])
            for f in ("PassengerDocument", "TicketNumber"):
                if f in r:
                    r[f] = na(r[f])
            if "BookingCode" in r:
                r["BookingCode"] = latin(r["BookingCode"])
            if "Baggage" in r:
                r["Baggage"] = latin(r["Baggage"])
            if "FlightDate" in r:
                r["FlightDate"] = date(r["FlightDate"], fn, i, "FlightDate")
            if "FlightTime" in r:
                r["FlightTime"] = time(r["FlightTime"], fn, i, "FlightTime")
            if "FlightNumber" in r:
                r["FlightNumber"] = flight(r["FlightNumber"])
            if "CodeShare" in r:
                v = clean(r["CodeShare"]).upper()
                mapping = {"NO": "Own", "OWN": "Own", "YES": "Other", "OPERATED": "Other", "OTHER": "Other"}
                if v in mapping:
                    r["CodeShare"] = mapping[v]
                else:
                    r["CodeShare"] = NA
                    log(fn, i, "CodeShare", v, "Unknown codeshare value")
            if "Destination" in r:
                r["Destination"] = NA if missing(r["Destination"]) else clean(r["Destination"]).title()
        elif low == "sirena-export-fixed.csv":
            if "PaxName" in r:
                a, b, c = name_parts(r["PaxName"], fn, i, "PaxName", "surname_first")
                r["PaxFirstName"], r["PaxMiddleName"], r["PaxLastName"] = a, b, c
                r.pop("PaxName", None)
            for f in ("PaxBirthDate", "DepartDate", "ArrivalDate"):
                if f in r:
                    r[f] = date(r[f], fn, i, f)
            for f in ("DepartTime", "ArrivalTime"):
                if f in r:
                    r[f] = time(r[f], fn, i, f)
            if "Flight" in r:
                r["Flight"] = flight(r["Flight"])
            if "CodeSh" in r:
                v = clean(r["CodeSh"]).upper()
                if missing(v):
                    r["CodeSh"] = NA
                elif v in {"NO", "YES", "OWN", "OPERATED", "OTHER"}:
                    r["CodeSh"] = {"NO": "Own", "OWN": "Own", "YES": "Other", "OPERATED": "Other", "OTHER": "Other"}[v]
                else:
                    r["CodeSh"] = NA
                    log(fn, i, "CodeSh", v, "Unknown codeshare value; mapped to NA")
            for f in ("From", "Dest"):
                if f in r:
                    r[f] = airport(r[f], fn, i, f)
            for f in ("Code", "Meal", "TrvCls", "Fare", "Baggage"):
                if f in r:
                    r[f] = latin(r[f])
            for f in ("e-Ticket", "TravelDoc", "Seat", "PaxAdditionalInfo", "UnnamedColumn", "AgentInfo"):
                if f in r:
                    r[f] = na(r[f])
        else:
            if i == 2:
                log(fn, 0, "*", "", "No file-specific rules; copied without field normalization")
    if low == "loyality.csv":
        seen = {}
        for rownum, r in enumerate(rows, 2):
            key = (r.get("ProfileID", NA), r.get("programm", NA))
            current = (r.get("Status", NA), r.get("Number", NA))
            if key in seen and seen[key] != current:
                log(fn, rownum, "ProfileID+programm", "|".join(key),
                    "Repeated profile/program with conflicting status or number")
            else:
                seen[key] = current
    if low == "skyteam_timetable.csv":
        out = []
        for h in headers:
            if h == "From_City":
                out += ["From_City", "From_Country"]
            elif h == "To_City":
                out += ["To_City", "To_Country"]
            elif h == "Validity":
                out += ["Validity_Start", "Validity_End"]
            else:
                out.append(h)
        for h in ("From_Country", "To_Country", "Validity_Start", "Validity_End"):
            if rows and h in rows[0] and h not in out:
                out.append(h)
        headers = out
    if low in {"all_boarding_passes.csv", "all_boarding_no_sourse.csv", "all_boarding_passes_no_constants.csv"}:
        if "passenger_name" in headers:
            idx = headers.index("passenger_name")
            headers[idx:idx + 1] = ["passenger_first_name", "passenger_middle_initial", "passenger_last_name"]
        if "title" in headers:
            idx = headers.index("title")
            headers[idx:idx + 1] = ["passenger_sex"]
    if low == "sirena-export-fixed.csv" and "PaxName" in headers:
        idx = headers.index("PaxName")
        headers[idx:idx + 1] = ["PaxFirstName", "PaxMiddleName", "PaxLastName"]
    return headers, rows


def main():
    ap = argparse.ArgumentParser(description="Normalize the agreed CSV files")
    ap.add_argument("--input", required=True, help="Folder with source CSV files")
    ap.add_argument("--output", required=True, help="Folder for normalized CSVs and report")
    ap.add_argument("--config", default="country_mapping.json", help="Editable country mapping JSON")
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    global COUNTRIES
    COUNTRIES = {clean(k).casefold(): clean(v) for k, v in config.get("country_mapping", {}).items()}
    src, dst = Path(args.input), Path(args.output)
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*.csv")):
        headers, rows, delimiter = read_csv(path)
        headers, rows = process(path, headers, rows)
        write_csv(dst / path.name, headers, rows, delimiter)
        print("Normalized:", path.name)
    with (dst / "normalization_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "row", "field", "original_value", "reason"])
        w.writeheader()
        w.writerows(ISSUES)
    print("Report:", dst / "normalization_report.csv", "issues:", len(ISSUES))


if __name__ == "__main__":
    main()
