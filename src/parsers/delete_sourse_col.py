import pandas as pd

df = pd.read_csv("YourBoardingPassDotAero/all_boarding_passes_no_constants.csv", dtype=str)

# Убираем технические столбцы из набора признаков
df_ml = df.drop(
    columns=["source_file", "source_sheet"],
    errors="ignore"
)

df_ml.to_csv("all_boarding_no_source.csv", index=False)