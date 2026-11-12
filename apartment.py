"""Housing tools: what a listing won't tell you about an NYC apartment building or neighborhood.

Four tools for the agent, all built on free NYC and New York State open data and the US Census:
- check_building: the building's age, size and type, its open housing-code violations, the problems tenants
  reported in the last 12 months, its last rat inspections and its latest bedbug report.
- check_landlord: who owns the building, and the open violations across all buildings that owner registers.
- check_neighborhood: noise complaints on the block and the subway stations within a short walk.
- compare_neighborhoods: one to three whole neighborhoods side by side on housing records, crime reports and
  Census income and rent.

This file holds what the agent sees: each tool's description, and the housing researcher, which bundles the
four tools with the instructions for using them. The tools themselves live in:
- open_data.py: asking the open data sites, dataset names and sources, finding an address
- buildings.py: the three address tools
- neighborhoods.py: compare_neighborhoods
Every result names the dataset each fact came from and links to its page, so the fact can be cited.
"""

from buildings import check_building, check_landlord, check_neighborhood
from neighborhoods import TOPICS, compare_neighborhoods


# --- What the model sees, and what the harness runs ---

ADDRESS_ARGUMENT = {
    "address": {
        "type": "string",
        "description": "NYC street address starting with the building number, e.g. '600 W 113th St, Manhattan'",
    },
}


APARTMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_building",
            "description": (
                "Look up what NYC city records say about one apartment building: its age, size and type; open "
                "housing-code violations by seriousness, with descriptions of the most serious ones; problems tenants "
                "reported in the last 12 months, such as heat or pests; the last rat inspections on the building's tax "
                "lot (a lot can include a neighboring building); and the latest bedbug report. Use it when the user "
                "asks whether a specific NYC building is in good condition or worth renting."
            ),
            "parameters": {"type": "object", "properties": ADDRESS_ARGUMENT, "required": ["address"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_landlord",
            "description": (
                "Find who owns one NYC apartment building, from its latest registration with the city's housing "
                "agency, and when that registration ended. When the owner is a company, also count the buildings "
                "registered under that company name and the open housing-code violations across all of them; owners "
                "who are people get no totals. Use it when the user asks about the landlord or owner, or how the owner "
                "treats their buildings. Can take about 20 seconds for large owners."
            ),
            "parameters": {"type": "object", "properties": ADDRESS_ARGUMENT, "required": ["address"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_neighborhood",
            "description": (
                "Describe the block around one NYC address: 311 noise complaints from the last 12 months within "
                "about a block, by type, and the subway stations within about a 10-minute walk, with their lines "
                "and walking minutes. Use it when the user cares about noise, quiet, commute or transit."
            ),
            "parameters": {"type": "object", "properties": ADDRESS_ARGUMENT, "required": ["address"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_neighborhoods",
            "description": (
                "A scorecard for one to three whole NYC neighborhoods, each figure next to the same figure for NYC "
                "as a whole, with the comparison already in words (for example \"42% lower than NYC overall\"). "
                "Four topics: building_upkeep (open class C violations and tenant problems per 1,000 apartments), "
                "pests (the percent of buildings reporting bedbugs and of rat inspections finding rats, also said as "
                "\"about 1 in 3\"), safety (crimes and felonies reported to the NYPD per 1,000 residents, this year "
                "through the latest quarter published) and cost_of_living (the typical rent current tenants pay a "
                "month and household income a year, from the US Census survey for 2020-2024). With several "
                "neighborhoods it also says how they differ on each row. Each topic comes with its meaning, one "
                "caveat and its sources, given once in about_the_topics. Use it when the user is choosing where to "
                "live and names neighborhoods, not street addresses; for one building use check_building. It lists "
                "no apartments for rent and no asking rents. The first call for a neighborhood can take up to a "
                "minute."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "neighborhoods": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One to three NYC neighborhood names as people say them, e.g. ['Astoria', 'Bushwick']. "
                            "Leave out the borough: 'Astoria', not 'Astoria, Queens'. Not street addresses and "
                            "not ZIP codes."
                        ),
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(TOPICS)},
                        "description": (
                            "Only the topics the task asks about, e.g. ['safety'] for a question about crime only, "
                            "or ['cost_of_living'] for rent or income only. Leave it out for a general question "
                            "such as where to live: then all four topics come back."
                        ),
                    },
                },
                "required": ["neighborhoods"],
            },
        },
    },
]


APARTMENT_TOOL_MAP = {
    "check_building": check_building,
    "check_landlord": check_landlord,
    "check_neighborhood": check_neighborhood,
    "compare_neighborhoods": compare_neighborhoods,
}


# --- The housing researcher: the four tools with the instructions for using them ---

HOUSING_RESEARCHER = {
    "name": "housing",
    # what a lead agent reads to decide whether a task belongs to this researcher
    "description": (
        "Looks up NYC city records, NYPD crime reports and US Census figures. For whole neighborhoods: a scorecard "
        "of building upkeep, pests, safety, typical rent and income, each next to NYC as a whole. For a street "
        "address: the building's violations, tenant complaints, rats and bedbugs, its owner and the owner's other "
        "buildings, noise on the block and nearby subway stations. Send it a task when the question is about "
        "building upkeep, pests, safety, typical rent or income in named neighborhoods, or about given addresses. "
        "It cannot find listings or the asking rent of an apartment on the market."
    ),
    # what the researcher itself is told
    "instructions": (
        "You research one task about housing in New York City, using only your tools, and report what the "
        "records say in plain words.\n"
        "- Whole neighborhoods: call compare_neighborhoods once, with every neighborhood named in the task. Pass "
        "topics only when the task asks about some of them, e.g. [\"safety\"] for crime only; for a general "
        "question such as where to live, leave topics out.\n"
        "- Reply with one bullet per topic, starting with its name in plain words: \"Building upkeep:\", "
        "\"Pests:\", \"Safety:\", \"Typical rent:\", \"Income:\". In each, give every neighborhood's figure in "
        "everyday words (use in_everyday_words where there is one), how it compares with NYC overall and, with "
        "several neighborhoods, how they differ, using the comparison words the tool returned word for word. Add "
        "the topic's caveat in a few words and end with its source as a markdown link.\n"
        "- Rent: say it is what current tenants pay, pooled across all apartment sizes (not the rent for any one "
        "size), usually below today's asking rent, from Census data, not our estimate. Where a figure is marked "
        "here_is_at_least, say \"at least\".\n"
        "- Safety: give the period the crime figures cover.\n"
        "- A street address: call check_building for the building's condition, heat or pests, check_neighborhood "
        "for noise or transit, and check_landlord for the owner. When the task compares addresses, call "
        "check_building and check_neighborhood for each of them.\n"
        "- Each tool returns the address or the ZIP codes it matched. Abbreviations are not a difference (W and "
        "WEST, St and STREET). If the matched street number or street name is a different street from the one in "
        "the task, do not describe that building: report what was matched and that the address needs confirming.\n"
        "- At most 10 bullets. End every bullet with its source as a markdown link from the tool result, for example "
        "([Housing Maintenance Code Violations](https://data.cityofnewyork.us/d/wvxf-dwi5)).\n"
        "- Use only what the tools returned. Add nothing you know yourself about a street, a neighborhood or a "
        "building, and do not guess listings or asking rents.\n"
        "- Name any part of the task the tools could not answer, and any note in the result (a ZIP code shared "
        "with a neighbor, ZIP codes left out, data that did not load).\n"
        "- After a neighborhood comparison, end with one bullet: \"Next: found an apartment? Send its address and I "
        "can check that building, its landlord and its block before you sign.\""
    ),
    "tools": APARTMENT_TOOLS,
    "tool_map": APARTMENT_TOOL_MAP,
}


# --- Quick test: run this file directly to try every tool ---

if __name__ == "__main__":
    for address in ["600 W 113th St, Manhattan", "2880 Broadway, Manhattan", "1600 Pennsylvania Ave Washington DC"]:
        for tool in (check_building, check_landlord, check_neighborhood):
            print(f"{tool.__name__}({address!r})")
            print("  ", tool(address))
    for neighborhoods in [["Astoria", "Bushwick"], ["Morningside Heights"], ["Atlantis"]]:
        print(f"compare_neighborhoods({neighborhoods!r})")
        print("  ", compare_neighborhoods(neighborhoods))
