# New in NYC: a research agent for settling into New York

Ask one question about settling into New York City and a small team of agents researches it in parallel and writes you a cited report. It compares neighborhoods on building conditions, pests, crime, rent and income, checks the city's records on a single building and its owner, finds free events and giveaways nearby, and checks what furnishing a room costs.

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
      -> Housing researcher   NYC housing, crime and Census  \
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

Most of it is read live by tools. Two small files do ship with the app, in `data/`. `census_zip_codes.csv` holds Census figures for 183 NYC ZIP codes. `nyc_figures.json` holds the scorecard's figures for New York City as a whole, so that each neighborhood can be shown next to the city. They ship with the app because the Census Bureau's site needs a key and counting the whole city takes up to 40 seconds a query. `data/README.md` explains how to rebuild both; the city file is rebuilt at least once a month. A model without tools cannot know the current figures: events change daily, most housing counts cover the last 12 months and so change every day, and the NYPD publishes a new quarter of crime reports every three months. With no tools, the model gave Astoria's rent as a range "as of mid-2024" with no source (see the bonus question).

| Source | Used for | How it is read |
|---|---|---|
| NYC Open Data: Housing Maintenance Code Violations (`wvxf-dwi5`) | Violations a city inspector issued against a building that are still open, by class: A non-hazardous, B hazardous, C immediately hazardous | `https://data.cityofnewyork.us/resource/wvxf-dwi5.json`, no key |
| NYC Open Data: Housing Maintenance Code Complaints and Problems (`ygpa-z7cr`) | Problems tenants reported to the city in the last 12 months, such as no heat or pests | `https://data.cityofnewyork.us/resource/ygpa-z7cr.json`, no key |
| NYC Open Data: Rodent Inspection (`p937-wjvj`) | Rat inspections and whether the inspector found signs of rats. The scorecard counts first visits only, not follow-ups | `https://data.cityofnewyork.us/resource/p937-wjvj.json`, no key |
| NYC Open Data: Bedbug Reporting (`wz6d-d3jb`) | The yearly bedbug report each building with 3 or more apartments files, with how many apartments had bedbugs. Each report also names the city's neighborhood area and the ZIP code, which is how a neighborhood name is matched to ZIP codes | `https://data.cityofnewyork.us/resource/wz6d-d3jb.json`, no key |
| NYC Open Data: Multiple Dwelling Registrations (`tesw-yqqr`) and Registration Contacts (`feu5-w2e2`) | The registration each apartment building files with the city's housing agency, and the owner named on it | `https://data.cityofnewyork.us/resource/tesw-yqqr.json` and `https://data.cityofnewyork.us/resource/feu5-w2e2.json`, no key |
| NYC Open Data: PLUTO tax lots (`64uk-42ks`) | One row per tax lot, a parcel of land that can hold more than one building: year built, floors and number of apartments. Every "per 1,000 apartments" figure is divided by these apartment counts | `https://data.cityofnewyork.us/resource/64uk-42ks.json`, no key |
| NYC Open Data: 311 Service Requests (`erm2-nwe9`) | Noise complaints called in to 311 within 150 meters of an address in the last 12 months | `https://data.cityofnewyork.us/resource/erm2-nwe9.json`, no key |
| NYC Open Data: NYPD Complaint Data Current, Year To Date (`5uac-w243`) | Crimes reported to the NYPD this year, published a quarter at a time; currently January 1 to September 30, 2026 | `https://data.cityofnewyork.us/resource/5uac-w243.json`, no key |
| NYC Open Data: ZIP code shapes (`efsh-h5xi`) | The crime reports carry no ZIP code. The city's site tags each report with the ZIP code shape it falls in, and this source turns that tag into a ZIP code | `https://data.cityofnewyork.us/resource/efsh-h5xi.json`, no key |
| NYC Planning Labs GeoSearch | Returns an address's coordinates and the building ID and tax lot ID used to search the city's datasets | `https://geosearch.planninglabs.nyc/v2/search?text=<address>`, no key |
| NYS Open Data: MTA Subway Stations (`39hk-dx4f`) | Stations within 800 meters of an address, with their lines; walking minutes are estimated from straight-line distance | `https://data.ny.gov/resource/39hk-dx4f.json`, no key |
| US Census Bureau, American Community Survey, 5-year estimates for 2020-2024: tables B01003 (residents), B11001 (households), B25003 (renter households), B19013 (median household income) and B25064 (median gross rent: rent plus utilities) | Residents, to turn crimes into a rate per 1,000 residents; median rent and median household income for each ZIP code; and households and renter households, to combine several ZIP codes' medians | Shipped as `data/census_zip_codes.csv` (183 NYC ZIP codes). Rebuilt by `data/build_census_zip_codes.py`, which needs a free Census key |
| The scorecard's figures, counted for New York City as a whole | NYC's figure next to every neighborhood figure | Shipped as `data/nyc_figures.json`, last counted 2026-11-12. Rebuilt at least once a month by `data/build_nyc_figures.py` |
| NYC Parks Events feed | Free Parks events | `https://www.nycgovparks.org/xml/events_300_rss.json` |
| [NYC for FREE](https://www.nycforfree.co/events) | Pop-ups, giveaways, free food | Their public events page, read lightly and cached for 30 minutes, credited and linked back |
| Open-Meteo | Forecasts for day plans | Public API, no key |
| Amazon search results and product pages, through SerpApi (`amazon` and `amazon_product` engines) | Prices, ratings, product links and listed sizes of furniture and other home items | `https://serpapi.com/search`, needs `SERPAPI_API_KEY`. Each tool call uses 1 search credit, plus up to 4 product-page credits when sizes have to be looked up |

Wait times, itineraries and the curbside-find score are our own estimates, not data, and the agent labels them that way. We did not use What is this line for? because its terms ban automated access.

## Tools by researcher

- **Housing** (`apartment.py`, `buildings.py`, `neighborhoods.py`, `open_data.py`). Three tools take one street address, such as "600 W 113th St, Manhattan"; the fourth takes neighborhood names.
  - `check_building(address)` returns the building's year built, floors, number of apartments and type; its open violations by class, with the text of up to 8, most serious first; the problems tenants reported in the last 12 months, by kind; the last 3 rat inspections on its tax lot; and its latest bedbug report.
  - `check_landlord(address)` returns the owner named on the building's latest registration and when that registration ends. When the owner is a company, it also counts the buildings registered under that exact company name and the open violations across all of them.
  - `check_neighborhood(address)` returns the 311 noise complaints within 150 meters (about a block) in the last 12 months, by type, and the subway stations within 800 meters, with their lines and walking minutes.
  - `compare_neighborhoods(neighborhoods, topics)` takes one to three neighborhood names, such as `["Astoria", "Bushwick"]`. It returns a scorecard on four topics: building upkeep, pests, safety, and rent and income. Each figure comes with NYC's figure and a written comparison, such as "42% lower than NYC overall". With two or three neighborhoods, it also compares them with each other, such as "Morningside Heights: 2.9 times as high as Astoria". `topics` limits the scorecard to the topics asked about, such as safety only.
  - **How a neighborhood name becomes numbers.** These sources have no neighborhood boundaries, so the tool works with ZIP codes. Every bedbug report names both the city's neighborhood area and a ZIP code, so counting reports shows which ZIP codes a neighborhood fills. A ZIP code counts toward the neighborhood when at least 40% of its bedbug reports are in that neighborhood; Astoria becomes ZIP codes 11102, 11103, 11105, 11106 and 11370. When the ZIP codes found hold less than a quarter of the neighborhood's reports, the tool uses the single ZIP code with the most of them and says the ZIP code is shared, as with Morningside Heights in query 1. The records are then added up over the ZIP codes. Violations and tenant problems are divided by apartments (from PLUTO) and crimes by residents (from the Census); the pest figures are shares of the buildings that filed a bedbug report and of the first rat inspections.
  - **The code does the arithmetic, not the model.** Every percent, ratio and "about 1 in 3" is computed in Python, and the researcher is told to repeat those words exactly, so the comparisons the housing researcher reports are calculated, not estimated by the model.
  - Every result lists the source of each figure with a link and says what its records cannot show, such as problems nobody reported, noise nobody called 311 about, or buildings an owner registered under another company name.
- **Events** (`events.py`): `events_near_neighborhoods` (counts free Parks events and NYC for FREE listings within about 1.5 km of up to three neighborhoods), `find_free_events`, `find_freebies`, `get_forecast`, `build_itinerary`, `estimate_wait_time`, `curb_hunt_score`, `freebie_checklist`.
- **Shopping** (`shopping.py`). One tool, `search_products_that_fit(query, max_price, max_width_in, max_depth_in, max_height_in, max_results)`. `query` (short keywords such as "narrow bookshelf") and `max_price` (dollars per item) are required. The three size limits are in inches and optional, and `max_results` is 1 to 10, default 5.
  - It searches Amazon, keeps the results at or under the budget, and checks up to 12 of them against the space. Each product comes back with its price, rating, link, listed size in inches and a fit verdict: `yes`; `maybe` (it fits on the sides the listing gives but one is missing, or the listing does not say which side is which and it fits only some ways round); `unknown` (no size listed); or `no`, which is left out of the results.
  - **How a size is found.** The tool reads it from the listing title, such as `47.2"W x 23.6"D x 28.7"H` or `120 x 60 cm` (centimeters become inches). When the title has no size, it opens the product page and reads its spec table, at most 4 times per call, and remembers each product's size so a repeat costs no credit. A bare "2 x 4" with no unit or side label is treated as a pack count, not a size. When a listing gives two numbers without labels, the longer one is taken as the width.
  - **The code checks the fit, not the model.** Each side is compared with its limit in Python, and the verdict comes back with a note that explains it, such as "width is 55 in, limit is 48 in".
  - Without measurements the tool filters by price only and says so. Given a total budget for several items, the researcher splits it across them, says how, and adds up the cheapest fitting option of each. Given no budget, it asks for one instead of guessing.
  - Every result links to each product and to the Amazon search, and says what it cannot show: prices are a snapshot before tax and shipping, sizes come from listing text and can be missing or wrong, and delivery and assembly are not checked. It searches new items on Amazon only, so when someone wants used or free furniture the Lead also sends the events researcher out for giveaways and curbside finds.

Tools return errors as plain messages with a hint instead of raising, so the model can recover.

## Sample queries

The data was read on 2026-11-17, except the housing figures in query 1 and the bonus and the Amazon results in query 4, which were read on 2026-11-18; the NYC figures next to them were counted on 2026-11-12. "This weekend" is Nov 21-22, 2026. City records change, so exact numbers may differ when you run these. For each query the "no tools" answer is the same model (`gemini-3.5-flash-lite`) with no system prompt and no tools.

### 1. Comparing two neighborhoods

> Compare Astoria and Morningside Heights for a student: housing records and free things to do this weekend.

**Expected answer and where it comes from**

Housing, each figure next to New York City as a whole:

| | Astoria | Morningside Heights | NYC overall | Source |
|---|---|---|---|---|
| Open class C (immediately hazardous) violations per 1,000 apartments | 92.5 | 266.7 | 158.7 | Housing Maintenance Code Violations (`wvxf-dwi5`); apartments from PLUTO (`64uk-42ks`) |
| Problems tenants reported per 1,000 apartments, last 12 months | 181.6 | 462.6 | 266.2 | Complaints and Problems (`ygpa-z7cr`); apartments from PLUTO (`64uk-42ks`) |
| Buildings whose yearly bedbug report listed bedbugs, last 12 months | 1.6% (about 1 in 65) | 5.0% (about 1 in 20) | 2.6% | Bedbug Reporting (`wz6d-d3jb`) |
| First rat inspections that found signs of rats, last 12 months | 31.8% (about 1 in 3) | 12.6% (about 1 in 8) | 16.2% | Rodent Inspection (`p937-wjvj`) |
| Crimes reported to the NYPD per 1,000 residents, Jan 1 to Sep 30, 2026 | 35.7 | 74.2 | 50.3 | NYPD Complaint Data Current (`5uac-w243`); residents from Census table B01003 |
| Felonies (the most serious crimes) per 1,000 residents, same period | 11.0 | 21.1 | 16.0 | Same |
| Typical rent a month that current tenants pay, all apartment sizes, rent plus utilities (2020-2024) | $2,153 | $1,531 | $1,821 | Census table B25064, median gross rent |
| Typical household income a year (2020-2024) | $91,473 | $59,587 | $80,483 | Census table B19013, median household income |

Astoria covers five ZIP codes, so its rent and income are an approximation: each ZIP code's median, averaged with weights of renter households for rent and all households for income. The tool also compares each neighborhood with NYC, such as "42% lower than NYC overall" for Astoria's violations and "97% higher than NYC overall" for its rats, and the two neighborhoods with each other, such as "Morningside Heights: 2.9 times as high as Astoria" for violations.

It should also say two things the data cannot settle. First, Morningside Heights is too small to fill a ZIP code on its own: its figures are for ZIP code 10027, which holds 61% of the neighborhood's bedbug reports, but only about 18% of that ZIP code's reports are in Morningside Heights, so the figures mostly describe its neighbors. Second, the rent is what current tenants pay across all apartment sizes, so it is not the rent of any one size and is usually below today's asking rent.

Free things to do:

| | Astoria | Morningside Heights | Source |
|---|---|---|---|
| Free listings within 1.5 km, Nov 21-22 | 1 (Yummy Dips Chicken Giveaway, Nov 21, 1.0 km) | 0 | NYC Parks Events feed and nycforfree.co/events |

**Agent answer** (30 s; the Lead sends the housing and events researchers out at the same time, and the Writer builds a cited table of the figures above, the closest event with its link, the ZIP code note, and a "What the data can't tell us" section).

**Same model, no tools:** a long general write-up of each neighborhood's vibe, housing stock, commute and typical prices. It has no numbers from city records, no events for this weekend and no sources, and it does not say that it has no access to current data.

### 2. One building

> How is the building at 600 W 113th St, Manhattan? Any heat or pest problems, and who owns it?

**Expected answer and where it comes from**
- Owner: Trustees of Columbia University, named on the building's registration with the city's housing agency. Under that exact name, the city's records list 155 registered buildings with 1,505 open violations. The count can include registrations that have lapsed, and it misses buildings the owner registered under another name (Multiple Dwelling Registrations `tesw-yqqr`, Registration Contacts `feu5-w2e2`, Housing Maintenance Code Violations `wvxf-dwi5`).
- 6 open violations, none of them class C (immediately hazardous). The 3 class B (hazardous) are broken floor tiles in the public halls of the 6th and 7th floors, from 2019, and chute doors in the public halls that must be made self-closing, from 1991. The 3 class A (non-hazardous) are notices from 2024, 2025 and 2026 for not filing the yearly bedbug report (Housing Maintenance Code Violations `wvxf-dwi5`).
- No problems of any kind reported by tenants to the city in the last 12 months, so no heat complaints (Complaints and Problems `ygpa-z7cr`).
- The last 3 rat inspections on the building's tax lot, on Sep 17, 2025, Mar 24, 2026 and Sep 23, 2026, all passed (Rodent Inspection `p937-wjvj`).
- The latest bedbug report in the city's data, filed July 3, 2023, listed 1 apartment with bedbugs out of 294 (Bedbug Reporting `wz6d-d3jb`).
- It should say that an empty record is not proof: the city's records show where an inspector went and what a tenant reported, not every problem.

**Agent answer** (46 s; housing researcher calls `check_building`, `check_landlord` and `check_neighborhood`): the facts above, each linked to its dataset, with the limits of the records.

**Same model, no tools:** says it has no access to building records, then lists websites to check (HPD Online, DOB BIS, Who Owns What). It gives no facts about the building.

### 3. Free events near a neighborhood

> What free events and giveaways are near Morningside Heights this weekend?

**Expected answer and where it comes from:** no free Parks events or NYC for FREE giveaways within 1.5 km of Morningside Heights on Nov 21-22. A few miles north there are Parks events such as Washington Heights Street Tree Care (Nov 21, Roger Morris Park) (NYC Parks Events feed and nycforfree.co/events). The listings change every week, so a run on another day can show more or fewer events; the point is that it reports what is there and says when nothing is nearby.

**Agent answer** (8 s, only the events researcher is sent out): says nothing was found within 1.5 km, lists the two upper Manhattan events it did find with links, and says what the counts cannot show.

**Same model, no tools:** says it cannot see live events and suggests checking the Columbia events calendar, local libraries and neighborhood sites. It names no actual event.

### 4. A desk that fits

> I'm furnishing a small room. I need a desk under $120 that fits a 40-inch-wide, 24-inch-deep spot. What are my options?

**Expected answer and where it comes from:** desks at or under $120 whose listed size is at most 40 inches wide and 24 inches deep, each with its price, rating, fit verdict and Amazon link, and the cheapest one named (Amazon search results through SerpApi). On 2026-11-18 the fitting options included:

| Desk | Price | Rating | Fits 40" wide x 24" deep |
|---|---|---|---|
| Pamray 32 Inch Computer Desk with 4 Drawers | $55.99 | 4.0 | yes |
| FURINNO Riau Folding Metal Frame Computer Desk | $60.99 | 4.0 | yes |
| 33" Small Computer Desk with 5 Fabric Drawers (14.2" deep) | $63.99 | 4.3 | yes |

Amazon's listings and prices change daily, so a later run will show different desks. It should also say what the search cannot show: prices before tax and shipping, sizes read from listing text, and no check of delivery or assembly.

**Agent answer** (46 s; only the shopping researcher is sent out): the three desks above, each linked to its Amazon page, the cheapest at $55.99, and a "What the data can't tell us" section.

**Same model, no tools:** calls its picks "the best options currently available", then names four desks from memory (IKEA, VASAGLE, SHW, Tribesigns) with sizes it does not source and price ranges such as "~$70 - $90", with no product links and no way to check today's price or whether a listing's size really fits 40 by 24 inches.

### Bonus: a question the data only half answers

> What is the typical monthly rent for a studio in Astoria?

**Expected answer:** none of our sources has rent by apartment size or the asking rents of apartments on the market. The Census rent is what current tenants pay across all sizes: $2,153 a month in Astoria, 18% higher than NYC's $1,821 (table B25064). So the agent should say it cannot give a studio's rent, give the all-sizes figure with its source, and say it is usually below today's asking rent.

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
