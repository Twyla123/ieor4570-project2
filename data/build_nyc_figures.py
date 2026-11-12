"""Build nyc_figures.json: the same figures compare_neighborhoods gives for a neighborhood, for New York City as a whole.

compare_neighborhoods shows each neighborhood's figures next to the city's, so a newcomer can tell whether a
number is high or low. Counting the whole city takes the city's site up to 40 seconds a query, so the figures
are counted here once and shipped with the app, with the date they were counted.

The housing counts and the crime counts use the same conditions as the neighborhood counts in neighborhoods.py.
The Census figures are for New York city itself (Census place 51000 in New York State), not a sum of ZIP codes.

Run from the repo folder, with the Census key in CENSUS_API_KEY or ~/.census_api_key (see build_census_zip_codes.py):
    .venv/bin/python data/build_nyc_figures.py
Rerun when the NYPD publishes a new quarter, and after rebuilding census_zip_codes.csv.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_data import (  # noqa: E402
    BEDBUG_REPORTS, COMPLAINTS, CRIME_REPORTS, RAT_INSPECTIONS, TAX_LOTS, VIOLATIONS, city_data, one_year_ago,
)
from neighborhoods import CENSUS_SURVEY, CENSUS_SURVEY_YEAR, SERIOUS_VIOLATION_CLASS  # noqa: E402

# --- Setup ---

CITYWIDE_QUERY_SECONDS = 90     # a count over the whole city took up to 40 seconds on 2026-11-12
CENSUS_URL = f"https://api.census.gov/data/{CENSUS_SURVEY_YEAR}/acs/acs5"
NEW_YORK_CITY = {"for": "place:51000", "in": "state:36"}   # the Census Bureau's code for New York city
KEY_FILE = Path.home() / ".census_api_key"
OUTPUT_FILE = Path(__file__).resolve().parent / "nyc_figures.json"

CENSUS_NUMBERS = {
    "B01003_001E": "residents",
    "B11001_001E": "households",
    "B25003_003E": "renter_households",
    "B19013_001E": "median_household_income",
    "B25064_001E": "median_rent",
}


def count_city(dataset: str, select: str, where: str = "") -> dict:
    """One count over the whole city: {name: number} for every name in `select`."""
    params = {"$select": select}
    if where:
        params["$where"] = where
    row = city_data(dataset, params, seconds=CITYWIDE_QUERY_SECONDS)[0]
    return {name: int(float(value)) for name, value in row.items()}


def census_new_york_city() -> dict:
    """The Census figures for New York city itself."""
    key = os.environ.get("CENSUS_API_KEY") or KEY_FILE.read_text().strip()
    reply = requests.get(CENSUS_URL, params={"get": ",".join(CENSUS_NUMBERS), **NEW_YORK_CITY, "key": key}, timeout=60)
    reply.raise_for_status()
    header, row = reply.json()
    return {column: int(row[header.index(code)]) for code, column in CENSUS_NUMBERS.items()}


def main() -> None:
    since = one_year_ago()
    crimes_through = city_data(CRIME_REPORTS, {"$select": "max(rpt_dt) AS newest"})[0]["newest"][:10]

    figures = {"counted_on": date.today().isoformat(), "housing_since": since, "crimes_through": crimes_through,
               "census_survey": CENSUS_SURVEY}
    figures |= count_city(TAX_LOTS, "sum(unitsres) AS apartments")
    figures |= count_city(VIOLATIONS, "count(*) AS open_serious_violations",
                          f"violationstatus = 'Open' AND class = '{SERIOUS_VIOLATION_CLASS}'")
    figures |= count_city(COMPLAINTS, "count(*) AS tenant_problems", f"received_date > '{since}'")
    figures |= count_city(BEDBUG_REPORTS, "count(distinct building_id) AS buildings_filing, "
                          "count(distinct case(infested_dwelling_unit_count > 0, building_id)) AS buildings_with_bedbugs",
                          f"filing_date > '{since}'")
    figures |= count_city(RAT_INSPECTIONS, "count(*) AS rat_inspections, "
                          "sum(case(result like '%Rat Activity%', 1, true, 0)) AS rat_inspections_with_rats",
                          f"inspection_type = 'Initial' AND inspection_date > '{since}'")
    figures |= count_city(CRIME_REPORTS, "count(*) AS crimes, sum(case(law_cat_cd = 'FELONY', 1, true, 0)) AS felonies",
                          f"rpt_dt <= '{crimes_through}T23:59:59'")
    figures |= census_new_york_city()

    OUTPUT_FILE.write_text(json.dumps(figures, indent=1) + "\n")
    for name, value in figures.items():
        print(f"{name:28} {value:,}" if isinstance(value, int) else f"{name:28} {value}")


if __name__ == "__main__":
    main()
