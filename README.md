# New in NYC: a research agent for settling into New York

Ask one question about settling into New York City and a small team of agents researches it in parallel and writes you a cited report. It compares neighborhoods on housing records, crime, rent and income, checks single buildings, finds free events and giveaways nearby, and checks what furnishing a room costs.

**Live app:** https://ieor4570-project2-git-770026520963.us-east1.run.app (sign in with a Columbia Google account if prompted)

A three-student IEOR 4570 project (Project 2: A Data Exploration Agent, path: Deep Research). Authors: usm2104, xz2843, sz3410.

## Why we built this

We are three students who came to New York, and settling in meant three decisions that each depend on a different public dataset. Where do I live? What is there to do nearby without spending much? What does it cost to set up a room? The city publishes the housing records, but they are scattered across datasets nobody reads before signing a lease. Free events are spread over park, city and brand listings. Prices change daily.

A chatbot with no tools knows none of this live, and it answers anyway. Asked for a studio rent in Astoria, the same model we use answered with a range "as of mid-2024" from memory and no source. So we built a research desk instead: a Lead that plans, one researcher per data source (each one of us owns one), and a Writer that reports with a source link on every fact. It shows the evidence and what each choice trades off, says what the data cannot tell you, and does not tell you where to live.

## Who it is for

Anyone choosing where to live or settling in: a student who just arrived, a last-semester student deciding where to stay after graduating, or anyone moving to a new neighborhood. It answers questions like "which of these neighborhoods has better-kept buildings and more free things to do?" and "how is this building?". It shows the evidence and what it cannot tell you. It does not tell you which place to pick.

## How it works (Deep Research)

```
You (one chat box)
  -> Lead         asks you one question if the request is too vague, otherwise plans the research
      -> Housing researcher   NYC housing records            \
      -> Events researcher    free events and giveaways       } run in parallel, each in a fresh context
      -> Shopping researcher  Amazon furniture and its size  /
      <- findings; if a gap is left the Lead sends researchers out again (up to 3 rounds)
  -> Writer       one report, every fact linked to its source, plus what the data cannot tell you
```

- `agents.py`: the Lead, the researcher loop, the Writer, and the parallel fan-out (a thread per researcher). The turn caps are `MAX_LEAD_ROUNDS = 3` and `MAX_RESEARCHER_ROUNDS = 5`, and no new work starts after 240 seconds, because graders wait up to 5 minutes.
- Each researcher is a dict (`name`, `description`, `instructions`, `tools`, `tool_map`): `HOUSING_RESEARCHER` in `apartment.py`, `EVENTS_RESEARCHER` in `events.py`, `SHOPPING_RESEARCHER` in `shopping.py`. The Lead reads each `description` to decide who gets a task.
- `app.py`: the FastAPI server. `POST /chat` takes `{message, session_id}` and returns `{response, session_id, tool_calls}`. Every entry in `tool_calls` is `{agent, name, args, result}`: the Lead's own calls (`research`, `ask_user`) have `agent: "lead"`, and each researcher's tool calls carry its name (`housing`, `events`, `shopping`).
- `index.html`: the front end.

## Data

Most of it is read live by tools. The only files we ship are the Census figures and the whole-city comparison numbers in `data/` (see `data/README.md` for how they are built), so the live site does not depend on a Census key. The model does not know any of it: the events change daily, the housing and crime records are updated by the city continuously, and the Census tables are specific figures per ZIP code.

| Source | Used for | How it is read |
|---|---|---|
| NYC Open Data: Housing Maintenance Code Violations (`wvxf-dwi5`), Complaints and Problems (`ygpa-z7cr`), Rodent Inspection (`p937-wjvj`), Bedbug Reporting (`wz6d-d3jb`), Multiple Dwelling Registrations (`tesw-yqqr`), Registration Contacts (`feu5-w2e2`), PLUTO tax lots (`64uk-42ks`), 311 Service Requests (`erm2-nwe9`) | Building and neighborhood condition, owner, noise | Socrata API, `https://data.cityofnewyork.us/resource/<id>.json`, no key |
| NYC Open Data: NYPD Complaint Data Current Year To Date (`5uac-w243`) | Crimes and felonies per 1,000 residents | Socrata API, no key |
| US Census Bureau, American Community Survey 5-year 2020-2024 (tables B01003, B11001, B25003, B19013, B25064) | Typical rent, household income, residents per ZIP code | Built once into `data/census_zip_codes.csv` by `data/build_census_zip_codes.py` |
| NYS Open Data: MTA Subway Stations (`39hk-dx4f`) | Nearby subway | `https://data.ny.gov/resource/39hk-dx4f.json` |
| NYC Parks Events feed | Free Parks events | `https://www.nycgovparks.org/xml/events_300_rss.json` |
| [NYC for FREE](https://www.nycforfree.co/events) | Pop-ups, giveaways, free food | Their public events page, read lightly and cached for 30 minutes, credited and linked back |
| Open-Meteo | Forecasts for day plans | Public API, no key |
| Amazon search through SerpApi | Furniture prices and listed sizes | Needs `SERPAPI_API_KEY` |

Wait times, itineraries and the curbside-find score are our own estimates, not data, and the agent labels them that way. We did not use What is this line for? because its terms ban automated access.

## Tools by researcher

- **Housing** (`apartment.py`): `check_building` (open violations, tenant problems, rats, bedbugs), `check_landlord` (owner and their other buildings), `check_neighborhood` (noise and subway), `compare_neighborhoods` (a scorecard for one to three neighborhoods: building upkeep, pests, safety and cost of living, each figure next to NYC as a whole with the comparison in words, and how the neighborhoods differ). Every result names its datasets with links and says what the records cannot show.
- **Events** (`events.py`): `events_near_neighborhoods` (counts free Parks events and NYC for FREE listings within about 1.5 km of up to three neighborhoods), `find_free_events`, `find_freebies`, `get_forecast`, `build_itinerary`, `estimate_wait_time`, `curb_hunt_score`, `freebie_checklist`.
- **Shopping** (`shopping.py`): `search_products_that_fit` (Amazon search under a budget, then checks each product's listed size against the space).

Tools return errors as plain messages with a hint instead of raising, so the model can recover.

## Sample queries

The data was read on 2026-11-17, and "this weekend" is Nov 21-22, 2026. City records change, so exact numbers may differ when you run these. For each query the "no tools" answer is the same model (`gemini-3.5-flash-lite`) with no system prompt and no tools.

### 1. Comparing two neighborhoods

> Compare Astoria and Morningside Heights for a student: housing records and free things to do this weekend.

**Expected answer and where it comes from**

| | Astoria | Morningside Heights | Source |
|---|---|---|---|
| Open class C violations per 1,000 apartments | 92.4 (NYC 158.7) | 266.7 | Housing Maintenance Code Violations (`wvxf-dwi5`), counted over the neighborhood's ZIP codes |
| Tenant problems per 1,000 apartments (12 months) | 181.2 (NYC 266.2) | 462.4 | Complaints and Problems (`ygpa-z7cr`) |
| Buildings with bedbug filings | 1.6% | 5.0% | Bedbug Reporting (`wz6d-d3jb`) |
| Rat inspections finding rats | 31.7% | 12.7% | Rodent Inspection (`p937-wjvj`) |
| Crimes per 1,000 residents, Jan 1 to Sep 30, 2026 | 35.7 (NYC 50.3) | 74.2 | NYPD Complaint Data (`5uac-w243`) and Census population |
| Typical rent a month, all apartment sizes | $2,153 (NYC $1,821) | $1,531 | Census ACS 2020-2024, table B25064 |
| Household income a year | $91,473 | $59,587 | Census ACS 2020-2024, table B19013 |
| Free listings within 1.5 km, Nov 21-22 | 1 (Yummy Dips Chicken Giveaway, Nov 21, 1.0 km) | 0 | NYC Parks Events feed and nycforfree.co/events |

It should also say that Morningside Heights is described by ZIP 10027, which mostly covers its neighbors, and that rent is pooled across all apartment sizes and is usually below today's asking rent.

**Agent answer** (30 s; the Lead sends the housing and events researchers out at the same time, and the Writer builds a cited table of the figures above, the closest event with its link, the ZIP code note, and a "What the data can't tell us" section).

**Same model, no tools:** a long general write-up of each neighborhood's vibe, housing stock, commute and typical prices. It has no numbers from city records, no events for this weekend and no sources, and it does not say that it has no access to current data.

### 2. One building

> How is the building at 600 W 113th St, Manhattan? Any heat or pest problems, and who owns it?

**Expected answer and where it comes from**
- Owner: Trustees of Columbia University, which has 155 registered buildings with 1,505 open violations (Multiple Dwelling Registrations `tesw-yqqr`, Registration Contacts `feu5-w2e2`).
- 6 open violations at the building (3 class A, 3 class B), such as defective floor tiles in public halls and a missing annual bedbug report (Housing Maintenance Code Violations `wvxf-dwi5`).
- 0 tenant problems reported in the last 12 months (Complaints and Problems `ygpa-z7cr`).
- Rat inspections on the tax lot in the last 12 months all passed (Rodent Inspection `p937-wjvj`).
- Latest bedbug report, July 3, 2023: 1 infested unit out of 294 (Bedbug Reporting `wz6d-d3jb`).
- It should say that no heat records were found and that an empty record does not prove nothing is wrong.

**Agent answer** (46 s; housing researcher calls `check_building`, `check_landlord` and `check_neighborhood`): the facts above, each linked to its dataset, with the limits of the records.

**Same model, no tools:** says it has no access to building records, then lists websites to check (HPD Online, DOB BIS, Who Owns What). It gives no facts about the building.

### 3. Free events near a neighborhood

> What free events and giveaways are near Morningside Heights this weekend?

**Expected answer and where it comes from:** no free Parks events or NYC for FREE giveaways within 1.5 km of Morningside Heights on Nov 21-22. A few miles north there are Parks events such as Washington Heights Street Tree Care (Nov 21, Roger Morris Park) (NYC Parks Events feed and nycforfree.co/events). The listings change every week, so a run on another day can show more or fewer events; the point is that it reports what is there and says when nothing is nearby.

**Agent answer** (8 s, only the events researcher is sent out): says nothing was found within 1.5 km, lists the two upper Manhattan events it did find with links, and says what the counts cannot show.

**Same model, no tools:** says it cannot see live events and suggests checking the Columbia events calendar, local libraries and neighborhood sites. It names no actual event.

### Bonus: a question the data only half answers

> What is the typical monthly rent for a studio in Astoria?

**Expected answer:** none of our sources has studio rents or asking rents. The Census figure is pooled across all apartment sizes ($2,153 a month, table B25064), so the agent should say it cannot give a studio rent, give the pooled figure with its source, and say it is usually below today's asking rent.

**Agent answer** (24 s): says the tools do not give studio-specific rents, then gives the $2,153 pooled figure (18% above NYC's $1,821) with the Census link, the household income, and the upkeep, pest and crime figures, and a "What the data can't tell us" section that says the rent is not specific to studios.

**Same model, no tools:** answers confidently with a range of $1,900 to $2,500 "as of mid-2024" from memory, with no source.

## Who built what

- **Housing researcher** (Twyla, xz2843): `apartment.py`, `neighborhoods.py`, `buildings.py`, `open_data.py` and `data/`: the building, landlord and neighborhood tools, the scorecard with crime, rent and income next to NYC, and the Cloud Run deployment.
- **Events researcher** (usm2104): `events.py`: free Parks events and giveaways, forecasts and day plans, and neighborhood event counts.
- **Shopping researcher** (Alisa, sz3410): `shopping.py`: Amazon search under a budget with a size-fit check.
- **Lead, researcher loop, Writer, server and front end** (usm2104): `agents.py`, `app.py`, `index.html`, and this README.

## Run it locally

1. A GCP project with billing and the Vertex AI API enabled.
2. `gcloud auth application-default login`
3. `export GOOGLE_CLOUD_PROJECT=your-project VERTEXAI_PROJECT=your-project`
4. Optional, for the shopping researcher: `export SERPAPI_API_KEY=your-key` (never commit the key)
5. `uv run app.py`, then open http://localhost:8000

## Deployment

Google Cloud Run, built from the `Dockerfile`, with continuous deploy from the `main` branch of this repo. The service needs the `SERPAPI_API_KEY` environment variable for the shopping researcher, and its service account needs the Vertex AI User role for Gemini. A full research run takes 10 to 110 seconds, inside Cloud Run's default 300-second request timeout, and the agent stops starting new work after 240 seconds.
