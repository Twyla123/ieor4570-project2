"""What city records say about one NYC address: the building, its landlord and its block.

The three address tools: check_building, check_landlord and check_neighborhood. Each finds the address,
asks the open data sites and returns a report with a source for every fact."""

# --- Setup: imports and settings ---

import json
import math

from open_data import (
    BEDBUG_REPORTS, COMPLAINTS, COMPLAINTS_311, CONTACTS, RAT_INSPECTIONS, RECORD_LIMITS, REGISTRATIONS,
    STATE_DATA, STATE_DATASET_PAGE, SUBWAY_STATIONS, TAX_LOTS, VIOLATIONS, city_data, counts_by,
    lookup_address, number_or_none, one_year_ago, report_or_error, source,
)

NOISE_RADIUS_METERS = 150       # about one block
SUBWAY_RADIUS_METERS = 800      # about a 10-minute walk
WALKING_METERS_PER_MINUTE = 80
EARTH_RADIUS_METERS = 6_371_000
IDS_PER_QUERY = 200             # keeps each query's web address short enough for the city's server
VIOLATIONS_SHOWN = 8            # how many open violations to describe, most serious first
RAT_INSPECTIONS_SHOWN = 3
DESCRIPTION_LENGTH = 220        # violation descriptions are long legal text; keep the start

# The first letter of the city's building class code says what kind of building it is.
BUILDING_TYPES = {
    "A": "one-family home", "B": "two-family home", "C": "walk-up apartment building",
    "D": "elevator apartment building", "E": "warehouse", "F": "factory or industrial building",
    "G": "garage", "H": "hotel", "I": "hospital or health facility", "J": "theatre", "K": "store building",
    "L": "loft building", "M": "religious building", "N": "group home or institution", "O": "office building",
    "P": "cultural or public assembly building", "Q": "outdoor recreation facility", "R": "condominium",
    "S": "mixed residential and store building", "T": "transportation facility", "U": "utility property",
    "V": "vacant land", "W": "school or educational building", "Y": "government building", "Z": "other",
}

# The city's own wording for the four classes (from the violations dataset's description).
VIOLATION_CLASSES = (
    "Class A is non-hazardous, class B is hazardous and class C is immediately hazardous. Class I is an "
    "information order, generally issued administratively rather than after an inspection; it is not a hazard level."
)

# The city files addresses that have no building number of their own under one shared ID per borough.
# Looking records up by a shared ID would return the records of every such address in the borough.
SHARED_BUILDING_IDS = {"1000000", "2000000", "3000000", "4000000", "5000000"}

NO_BUILDING_RECORD = {"error": (
    "The city has no building number on file for this address, so its housing records cannot be looked up "
    "reliably. Ask the user to check the address or to give the building's main street address."
)}


# --- Building facts ---


def open_violations(bin_id: str) -> dict:
    """Count a building's open (not yet corrected) housing-code violations by class (A, B, C, and I for information orders)."""
    rows = city_data(VIOLATIONS, {
        "$select": "class, count(*) AS n",
        "$where": f"bin = '{bin_id}' AND violationstatus = 'Open'",
        "$group": "class",
        "$order": "class",  # always A, B, C, I, so the same building reads the same on every run
    })
    return counts_by(rows, "class")


def open_violation_details(bin_id: str) -> list:
    """What the open violations are: up to 8 of them, most serious class first, newest first within a class."""
    details = []
    for violation_class in ("C", "B", "A"):
        still_needed = VIOLATIONS_SHOWN - len(details)
        if still_needed == 0:
            break
        rows = city_data(VIOLATIONS, {
            "$select": "inspectiondate, apartment, novdescription",
            "$where": f"bin = '{bin_id}' AND violationstatus = 'Open' AND class = '{violation_class}'",
            # the ID breaks ties between violations inspected on the same day, so every run returns the same ones
            "$order": "inspectiondate DESC, violationid DESC",
            "$limit": still_needed,
        })
        for row in rows:
            description = " ".join(row.get("novdescription", "").split())  # collapse line breaks and double spaces
            details.append({
                "class": violation_class,
                "inspected": row.get("inspectiondate", "")[:10],
                "apartment": row.get("apartment"),
                "description": description[:DESCRIPTION_LENGTH],
            })
    return details


def tenant_complaints(bin_id: str) -> dict:
    """Problems tenants reported to the city's housing agency in the last 12 months, by category (heat, pests...)."""
    rows = city_data(COMPLAINTS, {
        "$select": "major_category, count(*) AS n",
        "$where": f"bin = {int(bin_id)} AND received_date > '{one_year_ago()}'",
        "$group": "major_category",
        "$order": "n DESC",
    })
    by_category = counts_by(rows, "major_category")
    return {"total_problems_reported": sum(by_category.values()), "by_category": by_category}


def building_facts(bbl: str) -> dict | None:
    """Basic facts about the tax lot's building from city tax records: age, size, type and owner."""
    rows = city_data(TAX_LOTS, {
        "$select": "yearbuilt, numfloors, unitsres, unitstotal, bldgclass, ownername",
        "$where": f"bbl = {int(bbl)}",
    })
    if not rows:
        return None
    row = rows[0]
    class_code = row.get("bldgclass") or ""
    return {
        "year_built": number_or_none(row.get("yearbuilt")) or None,  # the city records an unknown year as 0
        "floors": number_or_none(row.get("numfloors")),
        "residential_units": number_or_none(row.get("unitsres")),
        "total_units": number_or_none(row.get("unitstotal")),
        "building_type": BUILDING_TYPES.get(class_code[:1], "unknown"),
        "owner_on_tax_record": row.get("ownername"),
    }


def recent_rat_inspections(bbl: str) -> list:
    """The lot's last 3 rat inspections, newest first: date, kind of inspection and result."""
    rows = city_data(RAT_INSPECTIONS, {
        "$where": f"bbl = {int(bbl)} AND inspection_date IS NOT NULL",
        "$order": "inspection_date DESC",
        "$limit": RAT_INSPECTIONS_SHOWN,
    })
    inspections = []
    for row in rows:
        inspections.append({
            "date": row["inspection_date"][:10],
            "type": row.get("inspection_type"),
            "result": row.get("result"),
        })
    return inspections


def latest_bedbug_report(bin_id: str) -> dict | None:
    """The building's most recent annual bedbug filing: infested units out of all units."""
    rows = city_data(BEDBUG_REPORTS, {
        "$where": f"bin = '{bin_id}' AND filing_date IS NOT NULL",
        "$order": "filing_date DESC",
        "$limit": 1,
    })
    if not rows:
        return None
    row = rows[0]
    return {
        "filed": row["filing_date"][:10],
        "infested_units": number_or_none(row.get("infested_dwelling_unit_count")),
        "total_units": number_or_none(row.get("of_dwelling_units")),
    }


# --- Landlord facts ---


def building_owner(bin_id: str) -> dict | None:
    """The owner named on the building's latest registration with the city, or None if it has none.

    Owners register every year, and some stop: the newest registration is used and its end date is
    returned, so the tool can say when the owner shown may be out of date. Buildings with no
    registration carry registration ID 0, a placeholder the city shares across all of them, so 0 is
    treated as "no registration".
    """
    rows = city_data(REGISTRATIONS, {"$select": "registrationid, registrationenddate", "$where": f"bin = {int(bin_id)}"})
    registrations = [row for row in rows if row.get("registrationid") not in (None, "0")]
    if not registrations:
        return None
    # a few buildings carry several registrations: take the one that ends last (the ID breaks ties)
    registrations.sort(key=lambda row: (row.get("registrationenddate", ""), int(row["registrationid"])), reverse=True)
    latest = registrations[0]
    end_date = latest.get("registrationenddate", "")[:10] or None

    contacts = city_data(CONTACTS, {
        "$select": "type, corporationname, firstname, lastname",
        "$where": f"registrationid = {latest['registrationid']}",
    })
    for contact in contacts:
        if contact["type"] == "CorporateOwner" and contact.get("corporationname"):
            return {"name": contact["corporationname"], "kind": "company", "registration_end_date": end_date}
    for contact in contacts:
        if contact["type"] in ("IndividualOwner", "JointOwner"):
            name = f"{contact.get('firstname', '')} {contact.get('lastname', '')}".strip()
            if name:
                return {"name": name, "kind": "person", "registration_end_date": end_date}
    return None


def owner_violations(company: str) -> dict:
    """How many buildings are registered under this exact company name, and their open violations by class.

    One registration usually covers one building, but some cover a whole complex of dozens of
    buildings, so buildings are counted by their building IDs, not by registrations.
    """
    safe_name = company.replace("'", "''")  # a ' inside a name would otherwise end the query's text early
    rows = city_data(CONTACTS, {
        "$select": "registrationid",
        "$where": f"type = 'CorporateOwner' AND corporationname = '{safe_name}'",
        "$limit": 5000,
    })
    unique_ids = {row["registrationid"] for row in rows}
    registration_ids = sorted(unique_ids - {"0"})  # drop the shared "no registration" placeholder

    building_ids = set()
    violation_rows = []
    for start in range(0, len(registration_ids), IDS_PER_QUERY):
        id_list = ",".join(registration_ids[start:start + IDS_PER_QUERY])
        for row in city_data(REGISTRATIONS, {
            "$select": "bin",
            "$where": f"registrationid in ({id_list})",
            "$limit": 50000,
        }):
            if row.get("bin") not in (None, "0"):
                building_ids.add(row["bin"])
        violation_rows += city_data(VIOLATIONS, {
            "$select": "class, count(*) AS n",
            "$where": f"registrationid in ({id_list}) AND violationstatus = 'Open'",
            "$group": "class",
            "$order": "class",
        })
    counts = counts_by(violation_rows, "class")
    return {
        "buildings_registered": len(building_ids),
        "open_violations_total": sum(counts.values()),
        "open_violations_by_class": counts,
    }


# --- Block facts: noise and subway ---


def noise_complaints(latitude: float, longitude: float) -> dict:
    """311 noise complaints from the last 12 months within about a block, by type, most common first."""
    rows = city_data(COMPLAINTS_311, {
        "$select": "complaint_type, count(*) AS n",
        "$where": (f"within_circle(location, {latitude}, {longitude}, {NOISE_RADIUS_METERS}) "
                   f"AND created_date > '{one_year_ago()}' AND complaint_type like 'Noise%'"),
        "$group": "complaint_type",
        "$order": "n DESC",
    })
    by_type = counts_by(rows, "complaint_type")
    return {"within_meters": NOISE_RADIUS_METERS, "total": sum(by_type.values()), "by_type": by_type}


def straight_line_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance between two points on the earth, in meters (the haversine formula)."""
    lat_change = math.radians(lat2 - lat1)
    lon_change = math.radians(lon2 - lon1)
    a = (math.sin(lat_change / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_change / 2) ** 2)
    return EARTH_RADIUS_METERS * 2 * math.asin(math.sqrt(a))


def nearby_stations(latitude: float, longitude: float) -> list:
    """Subway stations within about a 10-minute walk, closest first, with their daytime lines."""
    rows = city_data(SUBWAY_STATIONS, {
        "$select": "stop_name, daytime_routes, gtfs_latitude, gtfs_longitude",
        "$where": f"within_circle(georeference, {latitude}, {longitude}, {SUBWAY_RADIUS_METERS})",
    }, site=STATE_DATA)
    stations_with_meters = []
    for row in rows:
        meters = straight_line_meters(latitude, longitude, float(row["gtfs_latitude"]), float(row["gtfs_longitude"]))
        station = {
            "station": row["stop_name"],
            "lines": row["daytime_routes"],
            "walk_minutes": round(meters / WALKING_METERS_PER_MINUTE),
        }
        stations_with_meters.append((meters, station))
    stations_with_meters.sort(key=lambda pair: pair[0])  # closest first, by exact distance, not rounded minutes
    return [station for meters, station in stations_with_meters]


# --- The three address tools ---


def run_check(address: str, make_report, needs_building_number: bool = True) -> str:
    """The steps the three address tools share, around the one step that differs (`make_report`).

    Find the address, then build the tool's report.
    """
    building = lookup_address(address)
    if "error" in building:
        return json.dumps(building)
    if needs_building_number and building["bin"] in SHARED_BUILDING_IDS:
        return json.dumps(NO_BUILDING_RECORD)
    return report_or_error(lambda: make_report(building))


def building_report(building: dict) -> dict:
    """Everything check_building reports: the building's facts, violations, tenant problems, rats and bedbugs."""
    facts = building_facts(building["bbl"])
    violation_counts = open_violations(building["bin"])
    report = {
        "address": building["address"],
        "building": facts or "no tax record found",
        "open_violations_total": sum(violation_counts.values()),  # added up here so the model does not have to
        "open_violations_by_class": violation_counts,
        "violation_classes": VIOLATION_CLASSES,
        # only ask for the details when there is something open
        "open_violation_details": open_violation_details(building["bin"]) if violation_counts else "none",
        "tenant_complaints_last_12_months": tenant_complaints(building["bin"]),
        "recent_rat_inspections_on_tax_lot": recent_rat_inspections(building["bbl"]) or "none on record",
        "latest_bedbug_report": latest_bedbug_report(building["bin"]) or "none on record",
        "limits": RECORD_LIMITS,
        "sources": {
            "building": source(TAX_LOTS),
            "open_violations": source(VIOLATIONS),
            "tenant_complaints": source(COMPLAINTS),
            "rat_inspections": source(RAT_INSPECTIONS),
            "bedbug_report": source(BEDBUG_REPORTS),
        },
    }
    if facts and facts["residential_units"] == 0:
        report["note"] = (
            f"City tax records list no residential units at this address (building type: {facts['building_type']}), "
            "so housing records such as violations and bedbug reports may not apply. Tell the user this may not "
            "be an apartment building."
        )
    return report


def landlord_report(building: dict) -> dict:
    """Everything check_landlord reports: the owner, and a company owner's record across its buildings."""
    owner = building_owner(building["bin"])
    facts = building_facts(building["bbl"])
    owner_on_tax_record = facts["owner_on_tax_record"] if facts else None  # can be a different company
    if owner is None:
        return {
            "address": building["address"],
            "owner": "not registered with NYC's housing agency",
            "owner_on_tax_record": owner_on_tax_record,
            "note": ("This building has no current registration with NYC's housing agency, so the owner's other "
                     "buildings cannot be looked up. The owner named on the city's tax record is shown instead."),
            "sources": {"owner": source(REGISTRATIONS), "owner_on_tax_record": source(TAX_LOTS)},
        }

    registration_end = owner["registration_end_date"]
    report = {
        "address": building["address"],
        "owner": owner["name"],  # from the latest housing registration
        "registration_end_date": registration_end,
        "owner_on_tax_record": owner_on_tax_record,
        "sources": {
            "owner": source(CONTACTS),
            "registration_end_date": source(REGISTRATIONS),
            "owner_on_tax_record": source(TAX_LOTS),
        },
    }
    if registration_end and registration_end < one_year_ago():
        report["registration_note"] = (
            f"This registration ended on {registration_end} and has not been renewed in the city's records, so the "
            "owner shown may be out of date; compare it with the owner on the tax record."
        )
    if owner["kind"] == "company":
        report.update(owner_violations(owner["name"]))
        report["violation_classes"] = VIOLATION_CLASSES
        report["sources"]["buildings_registered"] = source(REGISTRATIONS)
        report["sources"]["open_violations"] = source(VIOLATIONS)
        report["note"] = ("Counts cover buildings registered under this exact company name. Landlords often use a "
                          "different company name for each building, so the true total can be higher. The list can "
                          "include registrations that have lapsed, so a few of these buildings may no longer belong "
                          "to this owner.")
    else:
        report["note"] = "The owner is a person, so their other buildings are not looked up: personal names are not unique."
    return report


def neighborhood_report(building: dict) -> dict:
    """Everything check_neighborhood reports: noise on the block and the subway stations nearby."""
    stations = nearby_stations(building["latitude"], building["longitude"])
    return {
        "address": building["address"],
        "noise_complaints_last_12_months": noise_complaints(building["latitude"], building["longitude"]),
        "subway_stations_nearby": stations or "none within about a 10-minute walk",
        "note": "Walking minutes are straight-line estimates; real walks take a little longer.",
        "limits": "Noise complaints count calls to 311, not the noise itself: a block where nobody calls looks quiet.",
        "sources": {
            "noise_complaints": source(COMPLAINTS_311),
            "subway_stations": source(SUBWAY_STATIONS, STATE_DATASET_PAGE),
        },
    }


def check_building(address: str) -> str:
    """Tool: what the city's records say about one NYC apartment building."""
    return run_check(address, building_report)


def check_landlord(address: str) -> str:
    """Tool: who owns one NYC apartment building, and their record across the buildings they register."""
    return run_check(address, landlord_report)


def check_neighborhood(address: str) -> str:
    """Tool: noise on the block and nearby subway stations for one NYC address."""
    return run_check(address, neighborhood_report, needs_building_number=False)  # it only uses the coordinates
