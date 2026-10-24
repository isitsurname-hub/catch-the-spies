from pathlib import Path

import pandas as pd
from tqdm import tqdm


INPUT_FILE = Path(r"Sirena-export-fixed.tab")
OUTPUT_FILE = Path(r"input/Sirena-export-fixed.csv")

ENCODING = "utf-8"
CHUNK_SIZE = 50_000

COLUMNS = [
    "PaxName",
    "PaxBirthDate",
    "DepartDate",
    "DepartTime",
    "ArrivalDate",
    "ArrivalTime",
    "Flight",
    "CodeSh",
    "From",
    "Dest",
    "Code",
    "e-Ticket",
    "TravelDoc",
    "Seat",
    "Meal",
    "TrvCls",
    "Fare",
    "Baggage",
    "PaxAdditionalInfo",
    "UnnamedColumn",
    "AgentInfo",
]


COLSPECS = [
    (0, 60),  # PaxName
    (60, 72),  # PaxBirthDate
    (72, 84),  # DepartDate
    (84, 95),  # DepartTime
    (95, 107),  # ArrivalDate
    (107, 118),  # ArrivalTime
    (118, 126),  # Flight
    (126, 129),  # CodeSh
    (129, 138),  # From
    (138, 141),  # Dest
    (141, 150),  # Code
    (150, 168),  # e-Ticket
    (168, 179),  # TravelDoc
    (179, 186),  # Seat
    (186, 192),  # Meal
    (192, 198),  # TrvCls
    (198, 204),  # Fare
    (204, 216),  # Baggage
    (216, 240),  # PaxAdditionalInfo
    (240, 276),  # UnnamedColumn
    (276, None),  # AgentInfo
]


def main():
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(
            f"Исходный файл не найден: {INPUT_FILE}"
        )

    if len(COLSPECS) != len(COLUMNS):
        raise ValueError(
            f"Укажи диапазоны для всех столбцов: "
            f"нужно {len(COLUMNS)}, задано {len(COLSPECS)}."
        )
    print("Подсчитываю строки...")
    with INPUT_FILE.open(
        "r", encoding=ENCODING, errors="replace"
    ) as f:
        total_lines = sum(1 for _ in f)
    total_rows = max(0, total_lines - 1)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.unlink(missing_ok=True)

    first_chunk = True
    processed = 0

    with tqdm(
        total=total_rows,
        desc="Конвертация",
        unit="строк",
    ) as progress:

        for chunk in pd.read_fwf(
            INPUT_FILE,
            colspecs=COLSPECS,
            names=COLUMNS,
            header=None,
            skiprows=1,
            chunksize=CHUNK_SIZE,
            encoding=ENCODING,
            dtype=str,
            keep_default_na=False,
        ):
            chunk = chunk.fillna("")

            chunk.to_csv(
                OUTPUT_FILE,
                index=False,
                header=first_chunk,
                mode="w" if first_chunk else "a",
                encoding="utf-8-sig",
            )

            first_chunk = False
            processed += len(chunk)
            progress.update(len(chunk))

    print(f"\nГотово! Обработано строк: {processed:,}")
    print(f"Результат: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
