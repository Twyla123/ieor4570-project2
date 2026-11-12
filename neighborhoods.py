"""Whole NYC neighborhoods side by side: compare_neighborhoods, a scorecard for each neighborhood.

A neighborhood name is turned into its ZIP codes. Over those ZIP codes the tool counts city housing records,
NYPD crime reports and US Census figures, and returns four topics: building upkeep, pests, safety and cost of
living. Every figure sits next to the same figure for NYC as a whole, with the comparison in words, and each
topic carries its meaning, one caveat and its sources.

Shipped data, read from data/: census_zip_codes.csv (built by build_census_zip_codes.py) and nyc_figures.json
(built by build_nyc_figures.py).
"""

# --- Setup: imports and settings ---

import csv
import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from pathlib import Path

import requests

from open_data import (
    AREA_QUERY_SECONDS, BEDBUG_REPORTS, COMPLAINTS, CRIME_REPORTS, RAT_INSPECTIONS, TAX_LOTS, UNEXPECTED_SHAPE,
    VIOLATIONS, city_data, number_or_none, one_year_ago, report_or_error, source,
)

# The crime reports carry no ZIP code: the city's site tags each one with the ZIP code shape it falls in
ZIP_AREAS = "efsh-h5xi"         # the ZIP code shapes the city's site uses
ZIP_AREA_FIELD = ":@computed_region_efsh_h5xi"  # in the crime reports: the number of the ZIP code shape a report falls in

# Residents, income and rent per ZIP code, from the US Census Bureau's survey (one file, rebuilt once a year)
DATA_FOLDER = Path(__file__).resolve().parent / "data"
CENSUS_FILE = DATA_FOLDER / "census_zip_codes.csv"
CENSUS_SURVEY_YEAR = 2024       # the last year of the 5-year survey the file was built from (same as in the build script)
CENSUS_SURVEY = f"{CENSUS_SURVEY_YEAR - 4}-{CENSUS_SURVEY_YEAR}"
CENSUS_TABLE_PAGE = f"https://data.census.gov/table/ACSDT5Y{CENSUS_SURVEY_YEAR}." + "{}"  # the web page of one Census table
CENSUS_TABLES = {  # the Census table behind each number column of the file, and its official name
    "residents": ("B01003", "Total Population"),
    "households": ("B11001", "Household Type (Including Living Alone)"),
    "renter_households": ("B25003", "Tenure"),
    "median_household_income": ("B19013", "Median Household Income in the Past 12 Months"),
    "median_rent": ("B25064", "Median Gross Rent (Dollars)"),
}
CENSUS_CAPS = {"median_household_income": 250_000, "median_rent": 3_500}  # top values: "this much or more"
CENSUS_WEIGHTS = {"median_household_income": "households", "median_rent": "renter_households"}  # what each ZIP's median is averaged by

# The same figures for NYC as a whole, counted once and shipped (counting the whole city takes up to 40 seconds a query)
NYC_FILE = DATA_FOLDER / "nyc_figures.json"
NYC_FIGURES_MAX_AGE_DAYS = 31   # older than this, NYC's 12 months no longer match a neighborhood's, so they are not shown

# Settings for comparing. The tool's description and the researcher's instructions in apartment.py repeat the topic names.
TOPICS = ("building_upkeep", "pests", "safety", "cost_of_living")
RECORDS_SAME_PERCENT = 10       # city records and crimes within this percent of another figure are "about the same"
CENSUS_SAME_PERCENT = 5         # a rule of thumb for Census survey figures, which have a margin of error
MANY_TIMES = 2                  # from this ratio up, a gap is said as "2.4 times as high" instead of a percent
SERIOUS_VIOLATION_CLASS = "C"   # the class of open violations counted (class C is immediately hazardous)
MAX_NEIGHBORHOODS = 3           # the most neighborhoods compared in one call
MIN_ZIP_SHARE = 0.4             # a ZIP code counts toward a neighborhood when at least this share of its bedbug filings is there
MIN_SHARE_COVERED = 0.25        # when the ZIP codes found hold less than this share of the neighborhood, its main ZIP code is used instead
RATE_PER_APARTMENTS = 1000      # violations and tenant problems are given per this many apartments
RATE_PER_RESIDENTS = 1000       # crimes are given per this many residents
NAMES_SUGGESTED = 5             # how many similar names to offer when a neighborhood name is not found
ZIP_CODE_LENGTH = 5


# --- Finding a neighborhood's ZIP codes ---


def same_spelling(name: str) -> str:
    """A name in lower case with single spaces, so "Astoria  (central)" and "Astoria (Central)" read the same."""
    return " ".join(name.lower().split())


def plain_name(name: str) -> str:
    """A neighborhood name in lower case without a part in brackets: "Astoria (Central)" becomes "astoria"."""
    without_brackets = re.sub(r"\(.*?\)", "", name)
    without_spaces_at_hyphens = re.sub(r"\s*-\s*", "-", without_brackets)
    return " ".join(without_spaces_at_hyphens.lower().split())


def names_of_area(area: str) -> set:
    """The plain names one of the city's neighborhood areas answers to.

    The city joins small neighborhoods into one area with hyphens, so "Astoria (East)-Woodside (North)"
    answers to "astoria-woodside", "astoria" and "woodside".
    """
    names = {plain_name(area)}
    for part in area.split("-"):
        names.add(plain_name(part))
    return names


@lru_cache(maxsize=1)  # the areas do not change while the app runs: ask the city once, then reuse the answer
def area_table() -> list:
    """Every pairing of a ZIP code and a city neighborhood area, with the number of bedbug filings in it.

    The city divides itself into named neighborhood areas, such as "Astoria (Central)", and stamps every
    bedbug filing with its area and its ZIP code. Counting the filings by both shows which ZIP codes an
    area covers, and how much of each ZIP code lies inside it.
    """
    rows = city_data(BEDBUG_REPORTS, {
        "$select": "postcode, nta, count(*) AS n",
        "$group": "postcode, nta",
        "$limit": 5000,
    }, seconds=AREA_QUERY_SECONDS)
    # a filing without an area, or without a real ZIP code (a few carry "0"), cannot place anything
    usable_rows = []
    for row in rows:
        zip_code = row.get("postcode", "")
        if row.get("nta") and len(zip_code) == ZIP_CODE_LENGTH and zip_code.isdigit():
            usable_rows.append(row)
    return usable_rows


def similar_area_names(wanted: str) -> list:
    """Up to 5 names the city's areas answer to that contain the name asked for, or are spelled like it."""
    known_names = set()
    for row in area_table():
        known_names.update(names_of_area(row["nta"]))
    containing = sorted(name for name in known_names if wanted in name)
    spelled_alike = difflib.get_close_matches(wanted, sorted(known_names), n=NAMES_SUGGESTED)
    suggestions = []
    for name in containing + spelled_alike:
        if name not in suggestions:
            suggestions.append(name)
    return suggestions[:NAMES_SUGGESTED]


def find_zip_codes(neighborhood: str) -> dict:
    """The city areas a neighborhood name matches, and the ZIP codes counted for it.

    A name with a part in brackets, written as one of the city's areas, such as "Astoria (Central)",
    matches only that area. Any other name, such as "Astoria" or "Woodside", matches every area that
    answers to it, so "Woodside" also covers "Astoria (East)-Woodside (North)".

    ZIP codes do not follow neighborhood lines. A ZIP code counts toward the neighborhood when at least
    40% of its bedbug filings are in the matched areas (MIN_ZIP_SHARE). Some neighborhoods hold only a
    small part of every ZIP code they touch: when the ZIP codes found hold less than a quarter of the
    neighborhood's own filings (MIN_SHARE_COVERED), the neighborhood gets the one ZIP code that holds
    more of them than any other, with a note that the ZIP code is shared. The result says what share of
    the neighborhood's filings its ZIP codes hold.
    """
    wanted = plain_name(neighborhood)
    every_area = {row["nta"] for row in area_table()}
    exact_area = []
    if "(" in neighborhood:  # the name picks out one part of a neighborhood, the way the city names its areas
        exact_area = sorted(area for area in every_area if same_spelling(area) == same_spelling(neighborhood))
    if exact_area:
        matched_areas = exact_area
    else:
        matched_areas = sorted(area for area in every_area if wanted in names_of_area(area))
    if not matched_areas:
        similar = similar_area_names(wanted)
        hint = f" Names that look similar: {', '.join(similar)}." if similar else ""
        return {"error": f"The city's records have no neighborhood called '{neighborhood}'.{hint} "
                         "Ask the user which neighborhood they mean."}

    filings_in_zip = {}     # ZIP code -> bedbug filings in any area
    filings_in_match = {}   # ZIP code -> bedbug filings in the matched areas
    for row in area_table():
        zip_code = row["postcode"]
        filings = int(row["n"])
        filings_in_zip[zip_code] = filings_in_zip.get(zip_code, 0) + filings
        if row["nta"] in matched_areas:
            filings_in_match[zip_code] = filings_in_match.get(zip_code, 0) + filings

    share_in_match = {}     # ZIP code -> the share of its filings that are in the matched areas
    for zip_code, filings in filings_in_match.items():
        share_in_match[zip_code] = filings / filings_in_zip[zip_code]
    zip_codes = sorted(zip_code for zip_code, share in share_in_match.items() if share >= MIN_ZIP_SHARE)

    own_filings = sum(filings_in_match.values())
    share_covered = sum(filings_in_match[zip_code] for zip_code in zip_codes) / own_filings
    found = {"city_areas_matched": matched_areas, "zip_codes": zip_codes}
    if share_covered < MIN_SHARE_COVERED:
        main_zip = max(filings_in_match, key=filings_in_match.get)
        found["zip_codes"] = [main_zip]
        share_covered = filings_in_match[main_zip] / own_filings
        found["shared_zip_note"] = (
            f"{neighborhood} does not fill enough of any ZIP code to be counted on its own. The numbers are for "
            f"ZIP code {main_zip}, which holds more of its bedbug filings than any other ZIP code, but only about "
            f"{round(100 * share_in_match[main_zip])}% of that ZIP code's bedbug filings are in this neighborhood, "
            "so the numbers mostly describe its neighbors. Tell the user this."
        )
    found["percent_of_neighborhood_in_these_zip_codes"] = round(100 * share_covered)
    return found


# --- Counting housing records over ZIP codes ---


# What has been counted since the app started: (dataset, condition, ZIP code) -> {name: number}.
# The city's site can take 15 seconds or fail, so a ZIP code is asked for once and then reused. A condition
# holds the date where "the last 12 months" starts, so on a new day the city is asked again.
counts_kept = {}


def zip_numbers(dataset: str, zip_field: str, zip_codes: list, wanted: dict, condition: str = "") -> dict:
    """Numbers per ZIP code from one dataset, in one query: {ZIP code: {name: number}}.

    `wanted` names each number and gives the formula the open data site computes for it, for example
    {"apartments": "sum(unitsres)"}. Only rows where the condition holds are counted.
    """
    new_zip_codes = [zip_code for zip_code in zip_codes if (dataset, condition, zip_code) not in counts_kept]
    if new_zip_codes:
        formulas = ", ".join(f"{formula} AS {name}" for name, formula in wanted.items())
        quoted_zip_codes = ",".join(f"'{zip_code}'" for zip_code in new_zip_codes)
        where = f"{zip_field} in ({quoted_zip_codes})"
        if condition:
            where += f" AND {condition}"
        rows = city_data(dataset, {
            "$select": f"{zip_field}, {formulas}",
            "$where": where,
            "$group": zip_field,
        }, seconds=AREA_QUERY_SECONDS)
        row_of_zip = {row[zip_field]: row for row in rows}
        for zip_code in new_zip_codes:
            row = row_of_zip.get(zip_code, {})  # a ZIP code with no matching records gets no row: every number is 0
            counts_kept[(dataset, condition, zip_code)] = {name: number_or_none(row.get(name)) or 0 for name in wanted}
    return {zip_code: counts_kept[(dataset, condition, zip_code)] for zip_code in zip_codes}


# --- Crime reports over ZIP codes ---


zip_area_numbers = {}  # ZIP code -> the number of its ZIP code shape on the city's site (None when it has no shape)


def zip_area_numbers_for(zip_codes: list) -> dict:
    """{ZIP code: number of its ZIP code shape}, asking the city only for ZIP codes not looked up before."""
    new_zip_codes = [zip_code for zip_code in zip_codes if zip_code not in zip_area_numbers]
    if new_zip_codes:
        quoted_zip_codes = ",".join(f"'{zip_code}'" for zip_code in new_zip_codes)
        rows = city_data(ZIP_AREAS, {"$select": "_feature_id, zcta5ce10", "$where": f"zcta5ce10 in ({quoted_zip_codes})"})
        for row in rows:
            zip_area_numbers[row["zcta5ce10"]] = row["_feature_id"]
        for zip_code in new_zip_codes:
            zip_area_numbers.setdefault(zip_code, None)  # e.g. a ZIP code for one building or for post office boxes only
    return {zip_code: zip_area_numbers[zip_code] for zip_code in zip_codes}


CRIME_NAMES = ("crimes", "felonies", "misdemeanors")


@lru_cache(maxsize=1)  # asked once a day: `today` changes, so a new NYPD batch is picked up the next day
def crime_reports_through(today: str) -> str:
    """The date of the newest crime report in the NYPD's data for this year, e.g. '2026-09-30'."""
    rows = city_data(CRIME_REPORTS, {"$select": "max(rpt_dt) AS newest"})
    if not rows or not rows[0].get("newest"):
        raise ValueError("the NYPD's crime data has no reports this year")  # read by crime_part as unreadable data
    return rows[0]["newest"][:10]


def crime_numbers(zip_codes: list, through: str) -> dict:
    """Crimes reported to the NYPD this year up to `through`, per ZIP code: {ZIP code: {"crimes": n, ...} or None}.

    None means unknown: the ZIP code has no shape on the city's site, so its crimes cannot be found. The crime
    reports carry no ZIP code; the site tags each one with the ZIP code shape it falls in, so the ZIP codes are
    first turned into those shapes' numbers. Every count stops at `through`, so all of them cover one period.
    """
    new_zip_codes = [zip_code for zip_code in zip_codes if (CRIME_REPORTS, through, zip_code) not in counts_kept]
    if new_zip_codes:
        area_of_zip = zip_area_numbers_for(new_zip_codes)
        areas = [area for area in area_of_zip.values() if area]
        row_of_area = {}
        if areas:
            rows = city_data(CRIME_REPORTS, {
                "$select": (
                    f"{ZIP_AREA_FIELD} AS area, count(*) AS crimes, "
                    "sum(case(law_cat_cd = 'FELONY', 1, true, 0)) AS felonies, "
                    "sum(case(law_cat_cd = 'MISDEMEANOR', 1, true, 0)) AS misdemeanors"
                ),
                "$where": f"{ZIP_AREA_FIELD} in ({','.join(areas)}) AND rpt_dt <= '{through}T23:59:59'",
                "$group": ZIP_AREA_FIELD,
            }, seconds=AREA_QUERY_SECONDS)
            row_of_area = {row["area"]: row for row in rows}
        for zip_code in new_zip_codes:
            if area_of_zip[zip_code] is None:
                counts_kept[(CRIME_REPORTS, through, zip_code)] = None  # unknown, not zero
                continue
            row = row_of_area.get(area_of_zip[zip_code], {})  # a shape with no row had no crime report
            counts_kept[(CRIME_REPORTS, through, zip_code)] = {
                name: number_or_none(row.get(name)) or 0 for name in CRIME_NAMES
            }
    return {zip_code: counts_kept[(CRIME_REPORTS, through, zip_code)] for zip_code in zip_codes}


def crime_part(zip_codes: list) -> tuple:
    """(date counted through, crimes per ZIP code, None), or (None, {}, the reason) when the crime data fails.

    Kept apart from the housing counts, so a crime failure does not cost the housing and Census figures.
    """
    try:
        through = crime_reports_through(date.today().isoformat())
        return through, crime_numbers(zip_codes, through), None
    except requests.RequestException:
        return None, {}, "The NYPD's crime data did not respond, so the crime numbers are missing. Say so."
    except UNEXPECTED_SHAPE:
        return None, {}, "The NYPD's crime data could not be read, so the crime numbers are missing. Say so."


# --- Census figures over ZIP codes ---


@lru_cache(maxsize=1)  # the file only changes when it is rebuilt: read it once
def census_numbers() -> dict:
    """{ZIP code: {"residents": n, ..., "median_rent_at_cap": True/False}} from the Census file.

    A number the Census Bureau did not publish is None. "_at_cap" says a median is at the Census Bureau's top
    value; the file holds the Bureau's code for it (3501 for "$3,500 or more"), which is replaced here by the top
    value itself, so nothing reads it as an exact figure. Without the file, every ZIP code has no Census numbers.
    """
    if not CENSUS_FILE.exists():
        return {}
    numbers = {}
    with open(CENSUS_FILE, newline="") as f:
        for row in csv.DictReader(f):
            figures = {column: number_or_none(row[column]) for column in CENSUS_TABLES}
            for column, top_value in CENSUS_CAPS.items():
                at_cap = row[f"{column}_at_cap"] == "yes"
                figures[f"{column}_at_cap"] = at_cap
                if at_cap:
                    figures[column] = top_value
            numbers[row["zip_code"]] = figures
    return numbers


def census_figure(zip_codes: list, column: str) -> dict:
    """One Census figure for each ZIP code: {ZIP code: number}, None where the Census Bureau has none."""
    census = census_numbers()
    return {zip_code: census.get(zip_code, {}).get(column) for zip_code in zip_codes}


def census_source(column: str) -> dict:
    """Where a Census number came from: the survey, the table's name, and the link to the table."""
    code, name = CENSUS_TABLES[column]
    return {
        # "survey" rather than the official "estimates": the writer labels anything called an estimate as the team's own
        "dataset": f"US Census Bureau, American Community Survey (5-year, {CENSUS_SURVEY}), table {code}: {name}",
        "link": CENSUS_TABLE_PAGE.format(code),
    }


def weighted_average(value_of_zip: dict, weight_of_zip: dict) -> int | None:
    """One figure for a neighborhood from its ZIP codes' medians: their average, each counted by its weight."""
    pairs = [(value, weight_of_zip[zip_code]) for zip_code, value in value_of_zip.items()
             if value is not None and weight_of_zip.get(zip_code)]
    total_weight = sum(weight for _, weight in pairs)
    if not total_weight:
        return None
    return round(sum(value * weight for value, weight in pairs) / total_weight)


def area_counts(zip_codes: list, since: str, topics: list) -> dict:
    """The housing numbers the chosen topics need, for each ZIP code: {ZIP code: {name: number}}.

    The queries go to the city's site at the same time, so the tool waits for the slowest one instead of for
    all of them in a row. A topic not asked for costs no query.
    """
    with ThreadPoolExecutor() as pool:
        def ask(dataset, zip_field, wanted, condition=""):
            """Start one query without waiting for its answer."""
            return pool.submit(zip_numbers, dataset, zip_field, zip_codes, wanted, condition)

        waiting = []
        if "building_upkeep" in topics:
            waiting += [
                ask(TAX_LOTS, "zipcode", {"apartments": "sum(unitsres)"}),
                ask(VIOLATIONS, "zip", {"serious_violations": "count(*)"},
                    f"violationstatus = 'Open' AND class = '{SERIOUS_VIOLATION_CLASS}'"),
                ask(COMPLAINTS, "post_code", {"tenant_problems": "count(*)"}, f"received_date > '{since}'"),
            ]
        if "pests" in topics:
            waiting += [
                ask(BEDBUG_REPORTS, "postcode", {
                    # a building can file twice in a year, so buildings are counted, not filings
                    "buildings_filing": "count(distinct building_id)",
                    "buildings_with_bedbugs": "count(distinct case(infested_dwelling_unit_count > 0, building_id))",
                }, f"filing_date > '{since}'"),
                ask(RAT_INSPECTIONS, "zip_code", {
                    "rat_inspections": "count(*)",
                    "rat_inspections_with_rats": "sum(case(result like '%Rat Activity%', 1, true, 0))",
                }, f"inspection_type = 'Initial' AND inspection_date > '{since}'"),  # first visits, not follow-ups
            ]
        numbers = {zip_code: {} for zip_code in zip_codes}
        for job in waiting:
            for zip_code, found in job.result().items():
                numbers[zip_code].update(found)
        return numbers


def added_up(zip_codes: list, numbers: dict, names: tuple) -> dict:
    """The totals of some per-ZIP-code numbers over a neighborhood's ZIP codes."""
    return {name: sum(numbers[zip_code][name] for zip_code in zip_codes) for name in names}


# --- NYC as a whole, and comparisons in words ---


@lru_cache(maxsize=1)  # the file only changes when it is rebuilt: read it once
def nyc_figures() -> dict:
    """The same figures for New York City as a whole, from data/nyc_figures.json; empty without the file."""
    if not NYC_FILE.exists():
        return {}
    return json.loads(NYC_FILE.read_text())


def nyc_housing_figures() -> dict:
    """NYC's housing counts, or {} once they are too old to stand next to a neighborhood's latest 12 months."""
    nyc = nyc_figures()
    if not nyc or (date.today() - date.fromisoformat(nyc["counted_on"])).days > NYC_FIGURES_MAX_AGE_DAYS:
        return {}
    return nyc


def nyc_census_figures() -> dict:
    """NYC's Census figures, or {} when they come from another survey than the ZIP code file."""
    nyc = nyc_figures()
    return nyc if nyc.get("census_survey") == CENSUS_SURVEY else {}


def rate(part: int | None, whole: int | None, per: int) -> float | None:
    """How many of `part` there are for every `per` of `whole` (per=100 gives a percent), unrounded.

    Comparisons use the exact figure; it is rounded to one decimal only when shown (rounded_for_display).
    """
    if part is None or not whole:
        return None  # unknown, or nothing to divide by
    return part / whole * per


def compared(value, reference, same_percent: int, reference_name: str, value_is_at_least: bool = False) -> str:
    """How one figure compares with another, in words, e.g. "35% lower than NYC overall".

    Within `same_percent` of the other figure, worked out before any rounding, is "about the same". A figure
    that is only a lower bound can be called higher, and nothing else.
    """
    if value is None or not reference:
        return f"cannot compare with {reference_name}"
    gap_percent_times_reference = abs(value - reference) * 100  # compared without dividing, so 110 vs 100 is exactly 10%
    if value_is_at_least:
        if value > reference and gap_percent_times_reference > same_percent * reference:
            return f"higher than {reference_name}"
        return f"cannot compare with {reference_name}: this figure is a lower bound"
    if gap_percent_times_reference <= same_percent * reference:
        return f"about the same as {reference_name}"
    ratio = value / reference
    if ratio >= MANY_TIMES:
        return f"{ratio:.1f} times as high as {reference_name}"
    if ratio > 1:
        return f"{round((ratio - 1) * 100)}% higher than {reference_name}"
    return f"{round((1 - ratio) * 100)}% lower than {reference_name}"


def one_in(percent: float | None) -> str | None:
    """A percent in everyday words: 31.9 -> "about 1 in 3", 1.6 -> "about 1 in 60", 55 -> "about 6 in 10"."""
    if percent is None:
        return None
    if percent == 0:
        return "none"
    if percent >= 40:
        return f"about {round(percent / 10)} in 10"
    one_in_how_many = 100 / percent
    if one_in_how_many < 10:
        shown = round(one_in_how_many)
    elif one_in_how_many < 100:
        shown = 5 * round(one_in_how_many / 5)   # 62.5 -> 60: a rough number reads as a rough number
    else:
        shown = 10 * round(one_in_how_many / 10)
    return f"about 1 in {shown}"


def figure(value, nyc_value, same_percent: int, in_words: str | None = None, value_is_at_least: bool = False) -> dict:
    """One row of the scorecard: the neighborhood's figure, NYC's, and how they compare in words."""
    row = {"here": value}
    if in_words:
        row["in_everyday_words"] = in_words
    if value_is_at_least:
        row["here_is_at_least"] = True
    row["nyc"] = nyc_value
    row["compared_with_nyc"] = compared(value, nyc_value, same_percent, "NYC overall", value_is_at_least)
    return row


def money(amount: int) -> str:
    """Dollars as people write them: 2153 -> "$2,153"."""
    return f"${amount:,}"


def range_across_zip_codes(value_of_zip: dict, capped: set, cap: int) -> str | None:
    """The lowest and highest ZIP code median, e.g. "$2,003 to $2,245"; None for a single ZIP code."""
    shown = {zip_code: value for zip_code, value in value_of_zip.items() if value is not None}
    if len(shown) < 2:
        return None
    lowest = min(shown, key=shown.get)
    highest = max(shown, key=shown.get)
    if lowest in capped:  # the top value is the highest there is, so every ZIP code is at it
        return f"every ZIP code {money(cap)} or more"
    top = f"{money(cap)} or more" if highest in capped else money(shown[highest])
    return f"{money(shown[lowest])} to {top}"


# --- The four topics of the scorecard ---


def building_upkeep(zip_codes: list, numbers: dict) -> dict:
    """Open serious violations and tenant problems for every 1,000 apartments, next to NYC's."""
    total = added_up(zip_codes, numbers, ("apartments", "serious_violations", "tenant_problems"))
    nyc = nyc_housing_figures()
    per = RATE_PER_APARTMENTS
    return {
        f"serious_violations_per_{per}_apartments": figure(
            rate(total["serious_violations"], total["apartments"], per),
            rate(nyc.get("open_serious_violations"), nyc.get("apartments"), per), RECORDS_SAME_PERCENT),
        f"tenant_problems_per_{per}_apartments": figure(
            rate(total["tenant_problems"], total["apartments"], per),
            rate(nyc.get("tenant_problems"), nyc.get("apartments"), per), RECORDS_SAME_PERCENT),
    }


def pests(zip_codes: list, numbers: dict) -> dict:
    """The share of buildings reporting bedbugs and of rat inspections finding rats, next to NYC's."""
    total = added_up(zip_codes, numbers,
                     ("buildings_filing", "buildings_with_bedbugs", "rat_inspections", "rat_inspections_with_rats"))
    nyc = nyc_housing_figures()
    bedbugs = rate(total["buildings_with_bedbugs"], total["buildings_filing"], 100)
    rats = rate(total["rat_inspections_with_rats"], total["rat_inspections"], 100)
    return {
        "percent_of_buildings_reporting_bedbugs": figure(
            bedbugs, rate(nyc.get("buildings_with_bedbugs"), nyc.get("buildings_filing"), 100),
            RECORDS_SAME_PERCENT, one_in(bedbugs)),
        "percent_of_rat_inspections_finding_rats": figure(
            rats, rate(nyc.get("rat_inspections_with_rats"), nyc.get("rat_inspections"), 100),
            RECORDS_SAME_PERCENT, one_in(rats)),
    }


def safety(zip_codes: list, crime_of_zip: dict, crimes_through: str) -> dict:
    """Crimes and felonies reported to the NYPD for every 1,000 residents, next to NYC's, over the same ZIP codes.

    Only ZIP codes whose crimes and residents are both known are counted; the others are listed with the reason.
    """
    residents_of_zip = census_figure(zip_codes, "residents")
    counted, left_out = [], {}
    for zip_code in zip_codes:
        if crime_of_zip.get(zip_code) is None:
            left_out[zip_code] = "its crimes cannot be found: no ZIP code shape on the city's site"
        elif not residents_of_zip[zip_code]:
            left_out[zip_code] = "no Census count of its residents"
        else:
            counted.append(zip_code)
    total = {name: sum(crime_of_zip[zip_code][name] for zip_code in counted) for name in ("crimes", "felonies")}
    residents = sum(residents_of_zip[zip_code] for zip_code in counted)

    nyc = nyc_figures()
    nyc_same_period = nyc.get("crimes_through") == crimes_through  # NYC's figure only counts if it covers the same months
    per = RATE_PER_RESIDENTS
    topic = {}
    for name in ("crimes", "felonies"):
        nyc_rate = rate(nyc.get(name), nyc.get("residents"), per) if nyc_same_period else None
        topic[f"{name}_per_{per}_residents"] = figure(rate(total[name], residents, per), nyc_rate, RECORDS_SAME_PERCENT)
    if left_out:
        topic["zip_codes_left_out"] = left_out
    return topic


def cost_of_living(zip_codes: list) -> dict:
    """Typical rent current tenants pay and household income: the ZIP codes' medians averaged, next to NYC's own median."""
    nyc = nyc_census_figures()
    topic = {}
    for column, name in (("median_rent", "typical_rent_a_month"), ("median_household_income", "household_income_a_year")):
        value_of_zip = census_figure(zip_codes, column)
        capped = {zip_code for zip_code, at_cap in census_figure(zip_codes, f"{column}_at_cap").items() if at_cap}
        average = weighted_average(value_of_zip, census_figure(zip_codes, CENSUS_WEIGHTS[column]))
        row = figure(average, nyc.get(column), CENSUS_SAME_PERCENT, value_is_at_least=bool(capped))
        spread = range_across_zip_codes(value_of_zip, capped, CENSUS_CAPS[column])
        if spread:
            row["range_across_zip_codes"] = spread
        topic[name] = row
    return topic


def about_the_topics(topics: list, since: str, crimes_through: str | None) -> dict:
    """For each topic asked for, once: what its figures mean, one caveat and its sources (and for safety, its period)."""
    about = {
        "building_upkeep": {
            "meaning": (
                f"Open class {SERIOUS_VIOLATION_CLASS} (immediately hazardous) housing-code violations, and problems "
                f"tenants reported to the city since {since} (such as no heat or pests), for every "
                f"{RATE_PER_APARTMENTS:,} apartments."
            ),
            "caveat": "Records show what tenants reported and inspectors found, not every problem.",
            "sources": [source(VIOLATIONS), source(COMPLAINTS), source(TAX_LOTS)],
        },
        "pests": {
            "meaning": (
                f"Buildings with three or more apartments that reported bedbugs in a filing since {since}, and first "
                f"visits by the city's rat inspectors since {since} that found signs of rats."
            ),
            "caveat": "Rat inspectors visit some areas far more than others, so compare the percent, not the number of visits.",
            "sources": [source(BEDBUG_REPORTS), source(RAT_INSPECTIONS)],
        },
        "safety": {
            "meaning": (
                f"Crimes reported to the NYPD in the neighborhood's ZIP codes, for every {RATE_PER_RESIDENTS:,} "
                "residents; felonies are the most serious crimes among them."
            ),
            "caveat": (
                "Crimes reported to the police, not every crime; busy shopping or nightlife areas have more reports "
                "than their residents suggest. The NYPD publishes whole quarters, so the newest months are not in yet."
            ),
            "sources": [source(CRIME_REPORTS), census_source("residents")],
        },
        "cost_of_living": {
            "meaning": (
                f"US Census survey for {CENSUS_SURVEY}. Rent is what current tenants pay a month, rent plus utilities; "
                "income is household income a year. With several ZIP codes, each ZIP code's median is averaged (rent "
                "by its renter households, income by its households): an approximation, compared with NYC's own median."
            ),
            "caveat": (
                "Rent is pooled across all current leases and all apartment sizes, so it is not the rent for any one "
                "size and is usually below today's asking rent. Census data, not our estimate; as a rule of thumb, "
                f"figures less than about {CENSUS_SAME_PERCENT}% apart are about the same."
            ),
            "sources": [census_source("median_rent"), census_source("median_household_income")],
        },
    }
    nyc = nyc_figures()
    if crimes_through:
        about["safety"]["period"] = f"reported {crimes_through[:4]}-01-01 to {crimes_through}"
        if nyc.get("crimes_through") and nyc["crimes_through"] != crimes_through:
            about["safety"]["nyc_note"] = (
                f"NYC's figures were counted through {nyc['crimes_through']}, another period, so they are not shown."
            )
    if nyc and not nyc_housing_figures():
        for topic in ("building_upkeep", "pests"):
            about[topic]["nyc_note"] = (
                f"NYC's figures were counted on {nyc['counted_on']}, more than {NYC_FIGURES_MAX_AGE_DAYS} days ago, so "
                "their 12 months no longer match and they are not shown."
            )
    if nyc and not nyc_census_figures():
        about["cost_of_living"]["nyc_note"] = (
            f"NYC's Census figures come from the {nyc.get('census_survey')} survey, not {CENSUS_SURVEY}, so they are not shown."
        )
    return {topic: about[topic] for topic in topics if topic != "safety" or crimes_through}


def rounded_for_display(scorecards: list) -> None:
    """Round every rate and percent in the scorecards to one decimal, once all comparisons have been made."""
    for card in scorecards:
        for topic in TOPICS:
            for row in card.get(topic, {}).values():
                if not isinstance(row, dict):
                    continue  # e.g. the ZIP codes left out
                for key in ("here", "nyc"):
                    if isinstance(row.get(key), float):
                        row[key] = round(row[key], 1)


def coverage(place: dict) -> dict:
    """Which ZIP codes stand for the neighborhood, how much of it they cover, and how many people live in them."""
    residents = sum(n for n in census_figure(place["zip_codes"], "residents").values() if n)
    found = {
        "zip_codes": place["zip_codes"],
        "percent_of_neighborhood_in_these_zip_codes": place["percent_of_neighborhood_in_these_zip_codes"],
        "city_areas_matched": place["city_areas_matched"],
        "residents": residents or None,
    }
    if "shared_zip_note" in place:
        found["shared_zip_note"] = place["shared_zip_note"]
    return found


# --- The comparison and its tool ---

# Each scorecard row that can be compared between neighborhoods: (topic, row, how close counts as the same)
SCORECARD_ROWS = [
    ("building_upkeep", f"serious_violations_per_{RATE_PER_APARTMENTS}_apartments", RECORDS_SAME_PERCENT),
    ("building_upkeep", f"tenant_problems_per_{RATE_PER_APARTMENTS}_apartments", RECORDS_SAME_PERCENT),
    ("pests", "percent_of_buildings_reporting_bedbugs", RECORDS_SAME_PERCENT),
    ("pests", "percent_of_rat_inspections_finding_rats", RECORDS_SAME_PERCENT),
    ("safety", f"crimes_per_{RATE_PER_RESIDENTS}_residents", RECORDS_SAME_PERCENT),
    ("safety", f"felonies_per_{RATE_PER_RESIDENTS}_residents", RECORDS_SAME_PERCENT),
    ("cost_of_living", "typical_rent_a_month", CENSUS_SAME_PERCENT),
    ("cost_of_living", "household_income_a_year", CENSUS_SAME_PERCENT),
]


def differences(scorecards: list) -> dict:
    """With two or three neighborhoods: for each row, the highest against the lowest, in words."""
    found = [card for card in scorecards if "coverage" in card]
    words = {}
    for topic, row, same_percent in SCORECARD_ROWS:
        known = sorted(((card[topic][row]["here"], card["neighborhood"], card[topic][row]) for card in found
                        if row in card.get(topic, {}) and card[topic][row]["here"] is not None), key=lambda item: item[0])
        if len(known) < 2:
            continue
        (_, lowest_name, lowest), (_, highest_name, highest) = known[0], known[-1]
        lower_bound_below_top = [name for _, name, shown in known[:-1] if shown.get("here_is_at_least")]
        if lower_bound_below_top:  # its true figure could be above the others, so no order can be given
            words[row] = f"cannot compare: {lower_bound_below_top[0]}'s figure is a lower bound"
        else:
            words[row] = f"{highest_name}: " + compared(
                highest["here"], lowest["here"], same_percent, lowest_name, highest.get("here_is_at_least", False))
    return words


def chosen_topics(topics) -> tuple:
    """(the topics asked for in the scorecard's order, None), or (None, the problem). No topics means all four."""
    if topics in (None, "", []):
        return list(TOPICS), None
    if isinstance(topics, str):  # the model sometimes sends "safety, pests" instead of a list
        topics = topics.split(",")
    if not isinstance(topics, list):
        return None, f"topics must be a list of any of {list(TOPICS)}, or left out for all four."
    wanted = [str(topic).strip().lower().replace(" ", "_") for topic in topics]
    unknown = [topic for topic in wanted if topic not in TOPICS]
    if unknown:
        return None, f"Unknown topic(s) {unknown}. Use any of {list(TOPICS)}, or leave topics out for all four."
    return [topic for topic in TOPICS if topic in wanted], None


def neighborhood_comparison(neighborhoods: list, topics: list) -> dict:
    """Everything compare_neighborhoods reports: a scorecard per neighborhood and, with several, how they differ."""
    places = []  # one entry per neighborhood: its name with its ZIP codes, or with the reason it was not found
    for name in neighborhoods:
        if not isinstance(name, str) or not name.strip():  # the model can send a number or an empty name
            places.append({"neighborhood": str(name), "error": "This is not a neighborhood name. Ask the user for one."})
        else:
            places.append({"neighborhood": name.strip(), **find_zip_codes(name)})

    times_used = {}  # ZIP code -> how many of the neighborhoods it is counted in
    for place in places:
        for zip_code in place.get("zip_codes", []):
            times_used[zip_code] = times_used.get(zip_code, 0) + 1

    since = one_year_ago()
    numbers, crimes_through, crime_of_zip, crime_problem = {}, None, {}, None
    if times_used:
        zip_codes = sorted(times_used)
        with ThreadPoolExecutor(max_workers=1) as pool:
            crime_job = pool.submit(crime_part, zip_codes) if "safety" in topics else None
            numbers = area_counts(zip_codes, since, topics)  # asked while the crime counts run
            if crime_job:
                crimes_through, crime_of_zip, crime_problem = crime_job.result()

    scorecards = []
    for place in places:
        if "zip_codes" not in place:
            scorecards.append(place)  # a name that was not found keeps its error and its suggestions
            continue
        zips = place["zip_codes"]
        card = {"neighborhood": place["neighborhood"], "coverage": coverage(place)}
        if "building_upkeep" in topics:
            card["building_upkeep"] = building_upkeep(zips, numbers)
        if "pests" in topics:
            card["pests"] = pests(zips, numbers)
        if "safety" in topics and crimes_through:
            card["safety"] = safety(zips, crime_of_zip, crimes_through)
        if "cost_of_living" in topics:
            card["cost_of_living"] = cost_of_living(zips)
        scorecards.append(card)

    nyc = nyc_figures()
    report = {"topics": topics, "neighborhoods": scorecards}
    how_they_differ = differences(scorecards)  # on the exact figures, before rounding
    rounded_for_display(scorecards)
    if how_they_differ:
        report["differences"] = how_they_differ
    report["about_the_topics"] = about_the_topics(topics, since, crimes_through)
    report["nyc_figures"] = f"New York City as a whole, counted on {nyc['counted_on']}" if nyc else "not available"
    report["limits"] = (
        "ZIP codes do not follow neighborhood lines exactly; the ZIP codes used are listed under coverage. Nothing "
        "here lists apartments for rent or their asking rents."
    )
    if crime_problem:
        report["crime_note"] = crime_problem
    shared_zip_codes = sorted(zip_code for zip_code, times in times_used.items() if times > 1)
    if shared_zip_codes:
        report["shared_zip_codes_note"] = (
            f"ZIP code(s) {', '.join(shared_zip_codes)} are counted in more than one of these neighborhoods, "
            "because each of them holds a large part of that ZIP code."
        )
    return report


def compare_neighborhoods(neighborhoods: list, topics: list | None = None) -> str:
    """Tool: a scorecard for one to three whole NYC neighborhoods, each figure next to NYC's."""
    if isinstance(neighborhoods, str):  # the model sometimes sends "Astoria, Bushwick" instead of a list
        neighborhoods = neighborhoods.split(",")
    if not isinstance(neighborhoods, list) or not neighborhoods:
        return json.dumps({"error": "No neighborhood was given. Ask the user which NYC neighborhoods to compare."})
    if len(neighborhoods) > MAX_NEIGHBORHOODS:
        return json.dumps({"error": f"At most {MAX_NEIGHBORHOODS} neighborhoods can be compared in one call. "
                                    "Call again for the others."})
    chosen, problem = chosen_topics(topics)
    if problem:
        return json.dumps({"error": problem})
    return report_or_error(lambda: neighborhood_comparison(neighborhoods, chosen))
