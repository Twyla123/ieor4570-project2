"""Asking NYC's and New York State's open data sites: the datasets, the queries, the sources, the dates,
and finding a street address. Shared by buildings.py and neighborhoods.py."""

# --- Setup: imports, web addresses, datasets and settings ---

import json
import time
from datetime import date, timedelta

import requests

ADDRESS_SERVICE = "https://geosearch.planninglabs.nyc/v2/search"
CITY_DATA = "https://data.cityofnewyork.us/resource/{}.json"
STATE_DATA = "https://data.ny.gov/resource/{}.json"
CITY_DATASET_PAGE = "https://data.cityofnewyork.us/d/{}"   # the web page that describes a city dataset
STATE_DATASET_PAGE = "https://data.ny.gov/d/{}"

# Open data datasets, by their IDs (city datasets on data.cityofnewyork.us, the subway list on data.ny.gov)
VIOLATIONS = "wvxf-dwi5"
RAT_INSPECTIONS = "p937-wjvj"
BEDBUG_REPORTS = "wz6d-d3jb"
REGISTRATIONS = "tesw-yqqr"
CONTACTS = "feu5-w2e2"
COMPLAINTS = "ygpa-z7cr"
TAX_LOTS = "64uk-42ks"          # one row of facts per tax lot
COMPLAINTS_311 = "erm2-nwe9"
SUBWAY_STATIONS = "39hk-dx4f"   # New York State data
CRIME_REPORTS = "5uac-w243"     # crimes reported to the NYPD this year, published a quarter at a time

# Each dataset's official name. A tool result names the datasets its facts came from, with a link to each.
DATASET_NAMES = {
    VIOLATIONS: "Housing Maintenance Code Violations",
    RAT_INSPECTIONS: "Rodent Inspection",
    BEDBUG_REPORTS: "Bedbug Reporting",
    REGISTRATIONS: "Multiple Dwelling Registrations",
    CONTACTS: "Registration Contacts",
    COMPLAINTS: "Housing Maintenance Code Complaints and Problems",
    TAX_LOTS: "Primary Land Use Tax Lot Output (PLUTO)",
    COMPLAINTS_311: "311 Service Requests from 2020 to Present",
    SUBWAY_STATIONS: "MTA Subway Stations",
    CRIME_REPORTS: "NYPD Complaint Data Current (Year To Date)",
}

QUERY_SECONDS = 8               # a normal query answers in about a second; this keeps a hanging dataset from holding the user for long
AREA_QUERY_SECONDS = 30         # a count over whole ZIP codes can take 15 seconds
RECENT_DAYS = 365               # "the last 12 months" in every tool

# The errors Python raises when a reply does not have the shape the code expects (a missing field, a wrong type).
UNEXPECTED_SHAPE = (KeyError, ValueError, TypeError, AttributeError)

# What a tool returns when it cannot build its report: what happened, and what to do next.
DATA_DOWN = {"error": "NYC's open data did not respond. Try again in a minute."}
DATA_UNREADABLE = {"error": "NYC's open data sent back records in a form that could not be read. Try again in a minute."}

# What housing records cannot show, sent with every result built on them.
RECORD_LIMITS = (
    "City records show where an inspector went and where a tenant reported a problem, not every problem: "
    "an empty or short record does not prove there is nothing wrong."
)


# --- Plumbing: asking the open data sites ---


def city_data(dataset: str, params: dict, site: str = CITY_DATA, seconds: int = QUERY_SECONDS) -> list:
    """Run one query against an open data dataset (NYC's site unless another site is given).

    The servers sometimes answer with an error, so this tries up to 3 times, waiting 2 and then
    4 seconds in between, before passing the error on to the tool that asked. Rows always come
    as a list, so any other reply is passed on as unreadable.
    """
    for attempt in range(3):
        try:
            reply = requests.get(site.format(dataset), params=params, timeout=seconds)
            reply.raise_for_status()
            rows = reply.json()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    if not isinstance(rows, list):  # rows come as a list; a single object is an error message from the site
        raise ValueError("the open data site did not send a list of rows")
    return rows


def source(dataset: str, page: str = CITY_DATASET_PAGE) -> dict:
    """Where a fact came from: the dataset's official name and the link to its page."""
    return {"dataset": DATASET_NAMES[dataset], "link": page.format(dataset)}


def one_year_ago() -> str:
    """The date where "the last 12 months" starts (RECENT_DAYS days before today), as text such as "2025-10-03"."""
    return (date.today() - timedelta(days=RECENT_DAYS)).isoformat()


def counts_by(rows: list, field: str) -> dict:
    """Add up the count column "n" of grouped query rows, one total per value of the given field."""
    counts = {}
    for row in rows:
        counts[row[field]] = counts.get(row[field], 0) + int(row["n"])
    return counts


def number_or_none(text: str | None) -> int | None:
    """The open data sites send numbers as text ("294"); turn one into a number, or None if it is missing."""
    if text in (None, ""):
        return None
    return int(float(text))


# --- Finding the building ---


def lookup_address(address: str) -> dict:
    """Turn a street address into the IDs the city's datasets are searched by.

    The address service guesses rather than saying "no match" (it turned "1600 Pennsylvania Ave
    Washington DC" into a Brooklyn address), so the street number it found must equal the first
    word typed. A different street with the same number can still slip through, which is why the
    matched address is always returned for the agent to compare with what the user typed.
    """
    if not isinstance(address, str) or not address.strip():  # the model can send a number or nothing at all
        return {"error": "No address was given. Ask the user for a street number, street name and borough."}
    try:
        reply = requests.get(ADDRESS_SERVICE, params={"text": address, "size": 1}, timeout=10)
        reply.raise_for_status()
        matches = reply.json()["features"]
    except requests.RequestException:
        return {"error": "The NYC address service is not responding. Try again in a minute."}
    except UNEXPECTED_SHAPE:
        return {"error": "The NYC address service sent back an answer that could not be read. Try again in a minute."}
    if not matches:
        return {"error": f"No NYC address matched '{address}'. Ask the user for a street number, street name and borough."}

    try:
        best = matches[0]
        props = best["properties"]
        if address.split()[0] != props.get("housenumber"):
            return {"error": f"'{address}' did not match an NYC building exactly; the closest is '{props.get('label')}'. Ask the user to confirm the street number and street."}
        longitude, latitude = best["geometry"]["coordinates"]  # the service lists longitude first
        return {
            "address": props["label"],
            "bin": props["addendum"]["pad"]["bin"],    # building ID
            "bbl": props["addendum"]["pad"]["bbl"],    # tax-lot ID (a lot can hold more than one building)
            "latitude": latitude,
            "longitude": longitude,
        }
    except UNEXPECTED_SHAPE:
        return {"error": f"'{address}' matched a place without a building record the city's datasets can be searched by. Ask the user for a full street address."}


# --- Turning a report into the tool's answer ---


def report_or_error(make_report) -> str:
    """Build a tool's report and return it as JSON text.

    When the open data sites fail, return a short message the model can act on instead, so a failure
    never reaches the user as a crash.
    """
    try:
        return json.dumps(make_report())
    except requests.RequestException:
        return json.dumps(DATA_DOWN)
    except UNEXPECTED_SHAPE:
        return json.dumps(DATA_UNREADABLE)
