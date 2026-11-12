"""Build census_zip_codes.csv: residents, median household income and median rent for each NYC ZIP code.

The numbers come from the US Census Bureau's American Community Survey, 5-year estimates. They change once a
year, so the app reads this file instead of asking the Census Bureau each time, and the live site needs no key.

Run once from the repo folder, with a free Census key (https://api.census.gov/data/key_signup.html) either in
the CENSUS_API_KEY environment variable or in the file ~/.census_api_key:
    .venv/bin/python data/build_census_zip_codes.py
"""

import csv
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neighborhoods import area_table  # noqa: E402  (the ZIP codes the housing tools can count over)

# --- Setup ---

SURVEY_YEAR = 2024              # the 2020-2024 5-year estimates; the Census Bureau releases a new one each December
CENSUS_URL = f"https://api.census.gov/data/{SURVEY_YEAR}/acs/acs5"
KEY_FILE = Path.home() / ".census_api_key"
OUTPUT_FILE = Path(__file__).resolve().parent / "census_zip_codes.csv"

# The Census Bureau's code for each number, and the column it gets in the file
CENSUS_NUMBERS = {
    "B01003_001E": "residents",                 # total population
    "B11001_001E": "households",                # used to combine the income medians of several ZIP codes
    "B25003_003E": "renter_households",         # renter-occupied homes, used to combine the rent medians
    "B19013_001E": "median_household_income",   # in dollars a year
    "B25064_001E": "median_rent",               # median gross rent (rent plus utilities), dollars a month
}

# The Census Bureau caps these medians: 250001 means "$250,000 or more" and 3501 means "$3,500 or more"
CAPPED_VALUES = {"median_household_income": "250001", "median_rent": "3501"}


def census_key() -> str:
    """The Census key, from the CENSUS_API_KEY environment variable or the key file."""
    key = os.environ.get("CENSUS_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not key:
        sys.exit(f"No Census key: set CENSUS_API_KEY or save the key in {KEY_FILE}.")
    return key


def number_or_blank(value: str) -> str:
    """The Census Bureau writes a missing estimate as a large negative number; keep it blank instead."""
    try:
        return value if int(value) >= 0 else ""
    except (TypeError, ValueError):
        return ""


def main() -> None:
    nyc_zip_codes = {row["postcode"] for row in area_table()}
    print(f"NYC ZIP codes the housing tools use: {len(nyc_zip_codes)}")

    reply = requests.get(CENSUS_URL, params={
        "get": ",".join(CENSUS_NUMBERS),
        "for": "zip code tabulation area:*",   # every ZIP code in the country, filtered to NYC below
        "key": census_key(),
    }, timeout=120)
    reply.raise_for_status()
    header, *rows = reply.json()

    zip_column = header.index("zip code tabulation area")
    kept = []
    for row in rows:
        if row[zip_column] in nyc_zip_codes:
            record = {"zip_code": row[zip_column]}
            for code, column in CENSUS_NUMBERS.items():
                record[column] = number_or_blank(row[header.index(code)])
            for column, cap in CAPPED_VALUES.items():
                record[f"{column}_at_cap"] = "yes" if record[column] == cap else ""
            kept.append(record)
    kept.sort(key=lambda record: record["zip_code"])

    cap_columns = [f"{column}_at_cap" for column in CAPPED_VALUES]
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["zip_code", *CENSUS_NUMBERS.values(), *cap_columns])
        writer.writeheader()
        writer.writerows(kept)

    missing = sorted(nyc_zip_codes - {record["zip_code"] for record in kept})
    print(f"Wrote {len(kept)} ZIP codes to {OUTPUT_FILE.name}, survey {SURVEY_YEAR - 4}-{SURVEY_YEAR}.")
    print(f"ZIP codes with no Census numbers ({len(missing)}): {', '.join(missing) or 'none'}")


if __name__ == "__main__":
    main()
