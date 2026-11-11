# New in NYC: a research agent for settling into New York

Ask one question about settling into New York City and a small team of agents researches it in parallel and writes you a cited report. It compares neighborhoods and buildings using the city's housing records, finds free events and giveaways nearby, and checks what furnishing a room costs.

**Live app:** DEPLOY_URL_GOES_HERE (sign in with a Columbia Google account if prompted)

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

All of it is read live by tools, not stored in the repo, so nothing needs to be loaded to run the app. The model does not know it: the events change daily and the housing records are updated by the city continuously.

| Source | Used for | How it is read |
|---|---|---|
| NYC Open Data: Housing Maintenance Code Violations (`wvxf-dwi5`), Complaints and Problems (`ygpa-z7cr`), Rodent Inspection (`p937-wjvj`), Bedbug Reporting (`wz6d-d3jb`), Multiple Dwelling Registrations (`tesw-yqqr`), Registration Contacts (`feu5-w2e2`), PLUTO tax lots (`64uk-42ks`), 311 Service Requests (`erm2-nwe9`) | Building and neighborhood condition, owner, noise | Socrata API, `https://data.cityofnewyork.us/resource/<id>.json`, no key |
| NYS Open Data: MTA Subway Stations (`39hk-dx4f`) | Nearby subway | `https://data.ny.gov/resource/39hk-dx4f.json` |
| NYC Parks Events feed | Free Parks events | `https://www.nycgovparks.org/xml/events_300_rss.json` |
| [NYC for FREE](https://www.nycforfree.co/events) | Pop-ups, giveaways, free food | Their public events page, read lightly and cached for 30 minutes, credited and linked back |
| Open-Meteo | Forecasts for day plans | Public API, no key |
| Amazon search through SerpApi | Furniture prices and listed sizes | Needs `SERPAPI_API_KEY` |

Wait times, itineraries and the curbside-find score are our own estimates, not data, and the agent labels them that way. We did not use What is this line for? because its terms ban automated access.

## Tools by researcher

- **Housing** (`apartment.py`): `check_building` (open violations, tenant problems, rats, bedbugs), `check_landlord` (owner and their other buildings), `check_neighborhood` (noise and subway), `compare_neighborhoods` (per-1,000-apartment counts, bedbug share and rat share over a neighborhood's ZIP codes). Every result names its datasets with links and says what the records cannot show.
- **Events** (`events.py`): `events_near_neighborhoods` (counts free Parks events and NYC for FREE listings within about 1.5 km of up to three neighborhoods), `find_free_events`, `find_freebies`, `get_forecast`, `build_itinerary`, `estimate_wait_time`, `curb_hunt_score`, `freebie_checklist`.
- **Shopping** (`shopping.py`): `search_products_that_fit` (Amazon search under a budget, then checks each product's listed size against the space).

Tools return errors as plain messages with a hint instead of raising, so the model can recover.

## Sample queries

The data was read on 2026-11-10, and "this weekend" is Nov 14-15, 2026. City records change, so exact numbers may differ when you run these. For each query the "no tools" answer is the same model (`gemini-3.5-flash-lite`) with no system prompt and no tools.

### 1. Comparing two neighborhoods

> Compare Astoria and Morningside Heights for a student: housing records and free things to do this weekend.

**Expected answer and where it comes from**

| | Astoria | Morningside Heights | Source |
|---|---|---|---|
| Open class C violations per 1,000 apartments | 92.1 | 265.8 | Housing Maintenance Code Violations (`wvxf-dwi5`), counted over the neighborhood's ZIP codes |
| Tenant problems per 1,000 apartments (12 months) | 178.4 | 457.1 | Complaints and Problems (`ygpa-z7cr`) |
| Buildings with bedbug filings | 1.6% | 4.9% | Bedbug Reporting (`wz6d-d3jb`) |
| Rat inspections finding rats | 31.9% of 897 | 12.9% of 4,423 | Rodent Inspection (`p937-wjvj`) |
| Free NYC Parks events within 1.5 km, Nov 14-15 | 1 | 5 | NYC Parks Events feed |
| NYC for FREE listings within 1.5 km | 0 | 0 | nycforfree.co/events |

It should also say that Morningside Heights is described by ZIP 10027, which mostly covers its neighbors, and that fewer listings can mean fewer published events, not fewer events.

**Agent answer** (35 s; the Lead sends the housing and events researchers out at the same time, and the Writer builds a cited table of the figures above, the closest events with links, and a "What the data can't tell us" section).

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

**Expected answer and where it comes from:** 5 free NYC Parks events within 1.5 km on Nov 14-15, including Winterization Workday (Nov 15, 0.3 km), Outdoor Skills: Survival 101 (Nov 14, 0.6 km) and It's My Park at Bloomingdale Playground (Nov 15, 1.2 km), and no NYC for FREE giveaways listed nearby (NYC Parks Events feed and nycforfree.co/events).

**Agent answer** (about 10 s, only the events researcher is sent out): the counts and the three closest events, each with its link, and what the counts cannot show.

**Same model, no tools:** says it cannot see live events and suggests checking the Columbia events calendar, local libraries and neighborhood sites. It names no actual event.

### Bonus: a question the data cannot answer

> What is the typical monthly rent for a studio in Astoria?

**Expected answer:** none of our sources contains rents or listings, so the agent should say it cannot answer and offer what it can do.

**Agent answer:** the Lead sends no researcher out. It says its researchers cannot find rents and offers housing conditions, free events or furnishing cost instead.

**Same model, no tools:** answers confidently with a range of $1,900 to $2,500 "as of mid-2024" from memory, with no source.

## Run it locally

1. A GCP project with billing and the Vertex AI API enabled.
2. `gcloud auth application-default login`
3. `export GOOGLE_CLOUD_PROJECT=your-project VERTEXAI_PROJECT=your-project`
4. Optional, for the shopping researcher: `export SERPAPI_API_KEY=your-key` (never commit the key)
5. `uv run app.py`, then open http://localhost:8000

## Deployment

Google Cloud Run, built from the `Dockerfile`, with continuous deploy from the `main` branch of this repo. The service needs the `SERPAPI_API_KEY` environment variable for the shopping researcher, and its service account needs the Vertex AI User role for Gemini. A full research run takes 10 to 110 seconds, inside Cloud Run's default 300-second request timeout, and the agent stops starting new work after 240 seconds.
