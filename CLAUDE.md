# Wendy Foils

Simon's personal wind-forecast watchdog. (Renamed from "Wind Guru" 2026-07-03; folder is `wendy-foils`.) The job: check the wind forecast on a schedule, decide whether conditions are good for **wind foiling at Simon's skill level**, and if they are, **notify him in time to actually go**.

This file documents how the project is wired and the constraints learned the hard way. The forecast logic itself (skill level, spots, thresholds) is defined in section 3 and will be filled in as we tune it.

---

## 1. Capabilities available (what this project can use)

These are inherited from Simon's Claude account, not bundled in this repo. They work in any project once permissioned.

- **Web research** — built-in `WebSearch` and `WebFetch`. This is how forecasts get pulled (forecast APIs / sites) and how new spots or conditions get researched. No API key management needed for the fetch itself.
- **Google Calendar** (`mcp__claude_ai_Google_Calendar__*`) — create/list/delete events. This is the **working notification channel** (see section 2).
- **Gmail** (`mcp__claude_ai_Gmail__*`) — search, read, label, and **create drafts only**. See the hard constraint in section 2.
- **Google Drive** (`mcp__claude_ai_Google_Drive__*`) — read/create files, if we ever want to log forecasts or history there.
- **Scheduled cloud agents** — via the `schedule` skill (claude.ai/code/routines). This is how the check runs on a cadence without Simon doing anything. Cron under the hood.

All connectors are authorised under Simon's **personal** Google account (simon.demarmels@gmail.com), because Claude Code runs under his personal Claude account. Connecting the Evolute Google account fails (Claude-account mismatch + Workspace admin block). So: create things on the personal account, and if the destination should be the Evolute inbox/calendar, **invite/target simon@evolute.partners** and let Google forward it. Target the destination, don't fight the source.

---

## 2. Notification delivery — the hard constraint

**The Gmail connector cannot send email. It is draft-only.** This was verified on the blog-writer project. Do not design around "Claude sends Simon an email," it does not work, and Simon does not want things piling up in Drafts.

**CHOSEN CHANNEL: Google Calendar event with Simon as guest.** Create the event, add Simon as a **guest**, and put the forecast summary + go/no-go call in the title and description.

**CRITICAL delivery gotcha (verified 2026-07-03):** the connected Google account in *this* project is **simon@evolute.partners**, not the personal address CLAUDE.md originally assumed. Google does **not** email you an invitation to an event you organized for yourself — so if the only guest is simon@evolute.partners (the organizer), NO inbox email is sent, just a silent calendar entry. **The guest MUST be a different address than the organizer.** So: create the event (organizer = simon@evolute.partners) and add **simon.demarmels@gmail.com as the guest** with `notificationLevel: ALL`. That fires a real calendar-invitation email to the personal Gmail inbox. Confirm with Simon which inbox he actually watches; if he wants the alert in the Evolute inbox instead, the organizer/guest roles would need to be flipped (needs the personal account connected, which currently it is not).

**Why the calendar-invite trick works:** Google (not the Gmail connector) sends the invitation email to any guest who isn't the organizer. So one `create_event` call delivers both the inbox email *and* a calendar buzz, with no SMTP path to build. The Gmail connector's draft-only limitation is irrelevant.

Set a **useful event title** (e.g. "🌬️ Foil window: Muiderberg, Thu 16:00-18:00, 16kt SW") so the inbox subject line alone tells Simon the call. Put spot/time/wind/direction in the description.

**Not used (kept for reference):** real SMTP email (unnecessary given the above); `PushNotification` tool (untested outside a session).

---

## 3. Forecast logic (tuned 2026-07-03)

### Skill level & gear

Simon is a **brand-new wing foiler** but a **lifelong wave surfer** (strong balance, water confidence, wind/wave reading). Gear: **5m wing, 95L board.** Weight **~78 kg** (confirmed 2026-07-03). At 78kg the ~13kt foiling floor holds; don't drop it lower. The surf background compresses the learning curve but the first phase is still flat-water wing control, so the thresholds below are the strict beginner band. There's a **progression toggle** for later (see end of section): once Simon self-reports reliable upwind riding and self-rescue, widen the ceiling toward 22kt and stop penalizing small clean waves.

### Good-day rule (all must be true)

| Parameter | Rule |
|---|---|
| Wind speed (avg) | **Ideal 15-20kt.** Acceptable 13-22kt. |
| Lower limit | No-go if avg **< 13kt** (95L board + heavier rider can't get on foil). |
| Upper limit | No-go if avg **> 22kt** or gusts **> 25kt** (overpowered/dangerous on a 5m). |
| Gust spread | Good if **gust − avg ≤ ~5kt** (steady wind). Downgrade or no-go on wide spread e.g. "15 gusting 28". |
| Direction | **Side-shore / side-onshore = good. Onshore = usable but poor. Offshore = automatic no-go** regardless of speed. Computed per spot (see table). |
| Water state | Flat / sheltered standing-depth preferred (inland lakes). Chop or waves = downgrade in this phase. |
| Window | Must fall in daylight and be **sustained** (a real multi-hour window, not a 20-min gust). |

**Hard safety blocks (never alert as "go"):** offshore wind at the chosen spot; avg > 22kt or gusts > 25kt; big gust spread; meaningful North Sea swell while still in the flat-water learning phase.

### Spots (near Amsterdam, ranked for a beginner)

Tag each spot `inland` (wind only, no swell) or `coast` (wind + waves). Coordinates for the forecast pull; verify the approximate ones on a map before first live use.

| Spot | Type | Lat, Long | Good directions | Offshore — BLOCK | Drive | Notes |
|---|---|---|---|---|---|---|
| **Muiderberg** (IJmeer) | inland | 52.3291, 5.1134 | N, NW, NE, light E | **S, SW, SE** | ~20min | Closest. Standing-depth flat 300m+ out. Gusty near tree-lined launch, launch from the water. Top beginner pick. |
| **Schellinkhout** (Markermeer) | inland | 52.6167, 5.1350 *(approx)* | SW, W, S, SE | N, NE | ~45min | Safest water in region — shallow standing depth 500-800m out. |
| **Almere Muiderzand** (IJmeer) | inland | 52.3390, 5.1740 *(approx)* | N, NW, W, SW | **E** | ~25-30min | Official spot, a bit deeper. Open Apr 1-Oct 31 only. |
| **Loosdrecht** (Loosdrechtse Plassen) | inland | 52.1960, 5.0650 *(approx)* | SW, WSW, W, S, SSW, NW, N | E, ENE | ~30min | Added 2026-07-04. Shallow sheltered lake system, gusty near tree-lined shores, popular beginner spot. Windguru 26078. |
| **Wijk aan Zee** (North Sea) | coast | 52.4930, 4.5880 *(approx)* | SW, W-NW | E, SE | ~35-40min | Waves/tides/currents — **intermediate, skip until foil-stable on flat water.** |

Friesland spots (Workum, Makkum, Hindeloopen) are the region's best beginner flats but ~80-90min away — day-trip only, out of normal radius.

### Forecast source

- **Wind (all spots), primary:** Open-Meteo Forecast API with the **KNMI HARMONIE-AROME** model — the gold standard for short-range NL coastal wind (nails sea breeze). Free, no key.
  `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m&wind_speed_unit=kn&models=knmi_harmonie_arome_netherlands&timezone=Europe/Amsterdam`
  HARMONIE horizon is ~2.5 days. For the Monday week-ahead view, fall back to `models=icon_eu` or drop `models=` for `best_match` (blends in ECMWF out to ~15 days).
- **Waves (coast spots only):** Open-Meteo **Marine API**, `models=ewam` (DWD EWAM, ~5km). Params `wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,swell_wave_direction,wind_wave_height`. Skip this call entirely for inland lakes — no swell there. Coastal accuracy is limited (won't resolve surf zone/tides), so use it as an "is there meaningful swell" flag, not a surf forecast.
  `https://marine-api.open-meteo.com/v1/marine?latitude=..&longitude=..&hourly=wave_height,swell_wave_height,swell_wave_period,swell_wave_direction,wind_wave_height&models=ewam&timezone=Europe/Amsterdam`
- **Human cross-check:** link the Windguru spot page in the alert so Simon can eyeball it (IJsselmeer north `windguru.cz/19`, Wijk aan Zee `windguru.cz/113`). No clean API — for viewing only.
- Attribution: Open-Meteo is CC BY 4.0, non-commercial free tier (10k calls/day). A personal watchdog is well within limits.

**Multi-model verdict (added 2026-07-04, important):** KNMI HARMONIE is the primary, but it runs LOW over open IJsselmeer water and repeatedly under-called days that GFS (what Windguru's IJsselmeer page shows) read as foilable. The engine now also pulls ICON-EU, ECMWF, and **GFS**, and when the primary shows no in-band window but a stronger model reads foilable (>=13kt, >=3kt above primary) in the go-hours, the day is surfaced as **MAYBE "models split - watch it"** instead of a false SKIP. Every row shows the per-model go-hours peak range so the disagreement is visible. This is the never-miss-a-good-day guarantee against model spread. (Note: our spot points are the sheltered southern IJmeer/Markermeer basins, deliberately flat-water for a beginner; the open IJsselmeer proper reads windier. If Simon wants the windier open-lake spots, add them to the SPOTS table.)

**Best data sources (researched 2026-07-04).** Confirmed model set the engine triangulates via Open-Meteo: `knmi_harmonie_arome_netherlands` (2km NL anchor, ~2.5d), `icon_d2` (2km, best independent near-term second opinion — added), `icon_eu` + `ecmwf_ifs025` + `gfs_seamless` (mid/far spread), `best_match` for the week-ahead blend. Ensemble probability: `icon_d2` EPS near-term, `ecmwf_ifs025` EPS for the week-ahead. Waves: `ewam`. Triangulation principle: anchor HARMONIE near-term, use ICON-D2 as the independent check, show model spread rather than averaging it away, hand to ECMWF/best_match past ~60h. **Live obs (wired 2026-07-04, upgraded 2026-07-05):** `fetch_obs()` (Buienradar station wind, free JSON, no key) is now pooled with `fetch_w2k()` (weather2kite.nl / Soarcast — NKV kite-club + KNMI + RWS stations, free JSON) and `nearest_obs()` picks the closest station across BOTH pools per spot. This adds genuine ON-WATER points the KNMI/Buienradar network lacks: Muiderberg and Almere now read from **Pampus** (mid-IJmeer, ~5-8km) instead of a 24-27km inland land station (Schiphol/De Bilt), and Schellinkhout reads from its dedicated NKV kite station (~2km). Loosdrecht still has no on-water sensor anywhere (nearest is De Bilt ~13km inland — a real gap, no free fix exists). The dashboard shows the nearest live reading as the "Live now" line in the feature card. **weather2kite API gotcha:** endpoint `https://www.weather2kite.nl/sc/scapi.php?table=mv_measurement_location_markers&has_harmonie=true` returns an empty 200 body unless the request sends header `X-Requested-With: XMLHttpRequest` (scrape guard). Values are m/s (×1.94384 → kt); `fetch_w2k()` drops stations older than 2h or reading 0/0/0 (offline). Buienradar alone still works if weather2kite is down. **Still documented / not wired:** Rijkswaterstaat WaterWebservices for REAL Markermeer water temp (station Markermeer-Midden FL42b, compartiment OW / grootheid T) — the API is mid-migration (endpoints returned HTML/empty on 2026-07-04), so we keep the seasonal estimate; and KNMI EDR 10-min obs (free key required).

**Progression toggle (wired):** set env `WENDY_LEVEL=progressing` (default `beginner`) to widen the band once Simon rides upwind reliably and can self-rescue — ceiling 22→25kt, gust block 25→30, ideal-hi 20→22, steadiness tolerance 5→7. To flip it for the scheduled runs, add `WENDY_LEVEL=progressing` to the GitHub Action's env (both the daily fetch and the weekly dashboard fetch).

**Temps + wetsuit (added 2026-07-04):** report includes air temp (Open-Meteo `temperature_2m`) and water temp with a wetsuit call. No free lake-temp API and EWAM doesn't cover the enclosed lakes, so inland water uses a seasonal monthly estimate (`LAKE_TEMP_BY_MONTH`); coast uses real EWAM sea-surface temp.

### Cadence & lead time (Simon's chosen flow, tuned 2026-07-03)

Three delivery types, all as Calendar invites (section 2). Scope: all four spots incl. Wijk aan Zee (coast flagged intermediate/skip until foil-stable).

1. **Sunday-evening week-ahead** (~18:00 every Sunday): 7-day outlook for all spots, what wind + waves will look like, standout days flagged with why + what-makes-them-good. Goes out every week even if the verdict is "nothing" — Simon wants the weekly picture regardless. Report marginal days as "maybe", don't silently drop them. **Label confidence per day** (high inside the ~2.5-day HARMONIE horizon, lower for the back half of the week which leans on ECMWF/GFS blends).
2. **Daily safety-net scan** (every morning): re-evaluate the next ~2-3 days on short-range HARMONIE and alert on ANY good window — whether or not Sunday flagged it. This is the "never miss a good day" guarantee: it catches days that firm up mid-week (HARMONIE only sees ~2.5 days, so Sunday's back-half is low-confidence and forecasts shift). It also serves as the ~2-days-out confirmation for days Sunday did flag. Dedupe against what's already been alerted so it confirms/revises rather than spams.
3. (Legacy note) The earlier design scheduled a confirmation dynamically 2 days before each standout. Replaced by the fixed daily scan above — simpler cron, strictly safer for "never miss."

**Simon's go-hours:** early mornings, evenings, and weekends. Rank windows that fall in these first; a great midday-weekday window is low value. Don't hard-suppress on hours (surface it), just rank.

**Alert vs. report threshold:** only offshore-at-spot and overpowered (>22kt / >25kt gust / wide gust spread) hard-suppress a day. Everything else in-band gets surfaced (as GO or MAYBE) so nothing gets missed. Single source (Open-Meteo) — on a model gap, fall back HARMONIE → ICON-EU → best_match; the daily cadence means one failed pull isn't a miss.

---

## 4. How a run should work (target flow)

Two run types.

**A. Sunday-evening week-ahead run** (~18:00 every Sunday):
1. For each spot, fetch the 7-day wind outlook (Open-Meteo; HARMONIE for near days, `best_match`/`icon_eu` for the far days). For coast spots also fetch waves. Read **hourly**, not daily-max, to find the real sustained window and time-of-day (daily-max hides that the average is well below the peak).
2. Apply the good-day rule per spot per day; identify GO and MAYBE days with confidence labels.
3. Send one Calendar invite: title = terse week verdict, description = per-day wind/wave outlook, standout days called out, each with a short **why** (sea breeze, frontal SW flow, etc.) and **what makes it good**. Goes out even on a dead week.
4. Log the run and flagged days to `logs/`.

**B. Daily safety-net scan** (every morning):
1. Re-pull the next ~2-3 days for all spots on short-range HARMONIE (now inside its accurate horizon), hourly.
2. Re-apply the good-day rule. Alert on ANY GO window — new or confirming a Sunday flag.
3. Dedupe against `logs/` so it confirms/revises rather than re-sends the same day. If a previously-flagged day has fallen apart, say so briefly rather than going silent (Simon planned around it).
4. Send a Calendar invite with the day's concise wind + wave picture, best time window and spot, and the why/what-makes-it-good. Log to `logs/`.

**Content style for both:** lead with what the wind and waves will *be* (speed, direction, gust, wave height/period), concisely. Then the breakdown: why the conditions form and what makes them good for a beginner on a 5m. Terse and specific — spot, time window, wind speed + direction. No filler, no em dashes.

**Always cite the source in the email:** include a line with the model used (e.g. "Source: KNMI HARMONIE-AROME via Open-Meteo") and a clickable Windguru cross-check link for the relevant spot, so Simon can verify the call himself.

On bad-wind weeks the Monday email still goes out (Simon wants the weekly picture regardless); it just reports no standout days. Confirmation runs only exist when Monday found a standout.

---

## 5. Files & run architecture

- `wendy.py` — the forecast engine. `python3 wendy.py weekly` (7-day Sunday planner, best_match blend) or `python3 wendy.py daily` (next-3-day HARMONIE lookout). Pure stdlib (urllib). Fetches multi-model wind + ICON-EU ensemble + EWAM waves/sea-temp, applies the good-day rule, and prints a human summary plus delimited blocks: `<!--SUBJECT_START-->`, `<!--EMAIL_HTML_START-->`, `<!--JSON_START-->`.
- `.github/workflows/forecast.yml` — **GitHub Action that does the forecast FETCH.** Runs on cron (daily 03:00 UTC, Sunday 14:00 UTC, a 2h buffer before the alert routines) plus `workflow_dispatch` (input `mode`), executes `wendy.py`, and commits the full output to `data/<mode>.out.txt` + a `data/<mode>.fetched_at.txt` timestamp. Rebase-and-retry push (the cloud routine pushes to the same branch). **GitHub scheduled runs drift by hours** (verified 2026-07-05: a 04:50 cron didn't fire until 07:49, after the 05:00 alert had already gone out with stale data), which is why the buffer is 2h AND the routines self-trigger this workflow via `workflow_dispatch` + poll if the fetch is still stale (see below).
- `data/` — committed forecast output the routines read (`weekly.out.txt`, `daily.out.txt`, `*.fetched_at.txt`).
- `docs/index.html` — the linked dashboard, served by GitHub Pages at **https://sd4444.github.io/wendy-foils/** (repo is public; source = `main` /docs). **Auto-generated** by `gen_dashboard.py` from the engine's `<!--GRID_START-->` block; the Action rebuilds it every run so it always shows the current 7-day outlook. Do not hand-edit it; edit the template inside `gen_dashboard.py`.
- `gen_dashboard.py` — reads a `wendy.py` weekly output file's GRID block and writes `docs/index.html`. Usage: `python3 gen_dashboard.py data/weekly.out.txt docs/index.html`. **Click-to-expand day view:** cells for the near days (day-of to +2, where the engine emits an `hourly` 06:00-22:00 array) are clickable and open a modal with a per-hour wind bar chart (gust caps, shaded 13-22 foilable + 15-20 ideal bands, direction arrows). Far days aren't clickable (no trustworthy hourly that far out). Modal closes on X / backdrop / Esc; becomes a bottom-sheet on mobile.
- `reference/` — research notes on forecast sources, spots, skill-level bands.
- `logs/runs.md` — run log / dedupe history.
- `.claude/skills/` — project-specific skills, if any get built.

**Why the fetch lives in a GitHub Action, not the routine (verified 2026-07-04):** the Claude cloud-routine sandbox has a default-deny egress proxy. Open-Meteo hosts (`api.open-meteo.com`, `ensemble-api.open-meteo.com`, `marine-api.open-meteo.com`) return **403 host_not_allowed** inside the routine — `wendy.py` "works" but returns a false "no wind" negative. Egress is an **environment-level** setting only (claude.ai/customize/environments → Default → Network access → Custom → add the 3 domains); it is NOT settable in `.claude/settings.json` or the RemoteTrigger job body (the API silently strips a `networking` block). Rather than depend on that toggle, the fetch runs in GitHub Actions (open internet) and commits the result; **the two cloud routines only READ `data/` and send the Calendar invite** (clone + Calendar MCP both work in-sandbox). If you ever allowlist the domains in the environment, you can collapse this back to the routine running `wendy.py` directly.

Scheduled cloud routines (created via the `schedule` skill / RemoteTrigger, run as SD4444):
- `trig_01LoHfWH1ccCHDKoBnBoXTih` — Sunday week-ahead, cron `0 16 * * 0` (18:00 Amsterdam).
- `trig_012gvAFWXAhNoMLcVPkcd4aZ` — daily scan, cron `0 5 * * *` (07:00 Amsterdam), dedupes against `logs/runs.md`.
Each routine's step 1 is a **self-healing freshness gate** (updated 2026-07-05): `git pull`, then compare `data/<mode>.fetched_at.txt` (UTC date) to today. If stale, it triggers the fetch itself (`gh workflow run forecast.yml -f mode=<mode>`, curl the Actions dispatch API as fallback) and polls `git pull` for up to ~15 min until today's data lands, THEN reads `data/<mode>.out.txt` and creates the Calendar event. Only if it is STILL stale after polling does it send a "forecast stale" warning (and NOT a normal alert with an outdated dashboard link). This removes the cron race: the alert never fires on stale data, and the dashboard link always points at a page the fetch just refreshed. (Note: this depends on the routine sandbox being able to reach `api.github.com` to dispatch; if that egress is blocked, the poll still catches a late-but-eventual GitHub cron run, and the stale warning is the honest fallback.)

**Email rendering caveat:** the HTML is all inline styles (no external CSS) so it survives email clients. Gmail renders the rich table + color tags when Simon opens the calendar event; the invitation *email* preview itself may show a simplified version. If inbox rendering ever disappoints, fall back to the linked-dashboard option (a hosted forecast page linked from a short invite).

---

## 6. Notes / gotchas

- **Wendy's voice (dashboard headline + verdict line).** Persona: a laid-back local surfer girl — reads wind and water well, calls it straight, no sass/flirt. Casual, plain-spoken, first person, chill. **Clarity first:** headline stays SHORT, sub-line + all data stay plain so Simon always understands the call. Headline set (in `gen_dashboard.py` `build_data()`): GO `"<Day>'s looking good."`, split `"<Day>'s a maybe."`, dead `"Nothing this week."`. (Voice was briefly sassier 2026-07-04, then dialed to straight surfer at Simon's request.) Everything else (email report, table detail) stays terse and factual per section 4.
- Confirm the active GitHub account before any git remote ops (Simon's personal is SD4444; the Evolute account can't see personal repos and 404s look like "repo missing").
- Never use em dashes in anything user-facing (Simon's standing rule).
- Keep alerts terse and specific: spot, time window, wind speed + direction. No filler.

---

## 7. Surf side (France trip, 14 Sep - 4 Oct 2026)

Added 2026-09-05. The app has **two sides toggled by the Foil / Surf switch** at the top of every dashboard page. The foil side (sections 1-6) is unchanged. The surf side is a separate engine + page for Simon's surf trip along the French Atlantic coast, Soulac-sur-Mer to Biarritz (Gironde, Landes, Pays Basque).

**What Simon asked for (2026-09-05):** whole coast, no fixed base, "anything above waist high and relatively clean". Dashboard only, refreshed twice a day (05:00 and 12:00 local), plus ONE morning inbox ping with the five standouts. No dedupe: the ping goes out every trip morning even when the call is "nothing clean".

**Files**
- `surf.py` - surf engine. `python3 surf.py` (no args) does all 36 spots, 7 days. Same delimiter convention as wendy.py plus a `<!--SPOTS_START-->` block (spot metadata: cams, links, notes). Pure stdlib.
- `gen_surf_dashboard.py` - builds `docs/surf.html` from `data/surf.out.txt`. Usage: `python3 gen_surf_dashboard.py data/surf.out.txt docs/surf.html`. Do not hand-edit `docs/surf.html`.
- `docs/surf.html` - hosted at **https://sd4444.github.io/wendy-foils/surf.html**. Sections: headline in Wendy's voice, today's call card (size, swell, wind, tide, water/air, cam/report/forecast buttons), tiles, **Today's five** (ranked cards with cam links), 7-day matrix of all 36 spots grouped by department (click a near day for hourly size + tide curve + wind arrows), rules cards.
- `data/surf.out.txt`, `data/surf.err.txt`, `data/surf.fetched_at.txt` - committed engine output the routine reads. Output blocks: SUBJECT, JSON (today's five + tomorrow), SPOTS (metadata incl. `tide_pref`, `buoy`, `shom`), BUOYS (live readings + bias), GRID (rows incl. `face`, `obs`, `corr`), EMAIL_HTML.

**Spots.** The 36 spots, their cam / local report / detailed forecast URLs, reliability rating and notes come from Simon's sheet "Atlantic_France_Surf_Cams_and_Forecasts (1).xlsm" (personal Drive, file id `12vkaQlQENlXob1EyDgvhkc51Qt9ZeLsI`, last checked 2026-09-02). The sheet has no coordinates: the lat/lon in `surf.py` were placed by hand on the beach itself and geocoding-checked against the town, so treat them as approximate (the marine grid is ~5 km anyway). Each spot has `face` (bearing from sand to open sea, ~275 for Gironde/Landes, 295-325 for Anglet/Biarritz) and `shelter` (0 open beach break; 0.4-0.6 for Le Prevent, Chambre d'Amour, Grande Plage, Cote des Basques). Sheltered spots read smaller (`eff = hs * (1 - 0.45*shelter)`) and hold when the open beaches close out.

**Good-day rule (surf), v2 after the 2026-09-05 methodology research.** Hourly score 0-10, then the best 3-hour daylight window per spot per day:
- **Size is breaking FACE height, not offshore Hs.** `breaker(h0, t) = 0.39 g^(1/5) (t h0^2)^(2/5)` (Komar & Gaughan 1972 shoaling-only breaker height, the form Caldwell & Aucan 2007 / Surfline-style spot forecasts build on). Uses the swell partition when it carries the energy (swell_wave_height >= 0.6 Hs) with the wind-sea added in quadrature, else total Hs with mean period. Then x shelter factor `(1 - 0.45*shelter)` and x the same-day buoy correction. Rule of thumb: 1.2 m @ 10 s -> ~1.8 m face (head-high); 1.2 m @ 6 s -> ~1.4 m.
- Face thresholds: < 1.0 m SKIP (under waist). 1.0-1.4 rideable, 1.4-2.4 prime (peak ~1.9 m), 2.4-3.2 still good, > 3.2 heavy on open beaches (sheltered spots score up), > 4.0 double overhead. Size words: knee < 0.9, waist < 1.2, chest < 1.5, head < 1.9, overhead < 2.5, well overhead < 3.3.
- Period: < 6.5 s windswell junk (-2), 8-10 neutral, 10 s+ groundswell (+1), 13 s+ (+1.5).
- Wind relative to `face`: < 6 kt glassy (+1.5); offshore (E sector) +1.5 up to 12 kt, +0.7 to 18, then negative; cross-shore mild penalty; onshore penalty, and **onshore >= 14 kt = blown out, hour thrown away**.
- Tide: per-spot `tide_pref` from surf-forecast.com spot guides: `low` (Cote des Basques, -1 at high tide when the beach disappears), `incoming` (Graviere), `any` (Lacanau), `mid-high` (Grande Plage), default `mid` for beach breaks (+0.5 in the middle 40% of the range).
- Verdict: GO >= 5.5, MAYBE >= 3.5, else SKIP. Face floor overrides everything.
- Confidence: ECMWF-WAM 0.25 as a second opinion; > 0.3 m disagreement = "low". Days 4-7 "far out".

**Live buoys + same-day bias check (added 2026-09-05).** Candhis (Cerema national wave-buoy network) has three live buoys on this coast: **Cap Ferret 03302**, **Anglet 06402**, **Saint-Jean-de-Luz 06403** (Hs, Hmax, period, direction, water temp, every 30-60 min). Candhis' own API needs a key by email (candhis@cerema.fr); we read them keyless through `https://thesurfkit.com/api/v2/buoys/nearest?lat=..&lng=..` (public endpoint of labouee.app, returns `last_reading`; the list/readings endpoints need an invite-only key). `fetch_buoys()` takes each buoy's latest reading, pulls the model Hs at the buoy for the same hour, and computes `bias = model/buoy`. Today's face heights for spots mapped to that buoy (`buoy` field: Gironde + Landes north of Vieux-Boucau -> Cap Ferret, the rest -> Anglet) are multiplied by `1/bias` clamped to 0.75-1.25, and the why/dashboard show "live buoy X 0.7m @ 7s, models read high x1.4, sized down today". On 2026-09-05 the model read x1.3-1.7 high vs all three buoys (small short-period day). Readings older than 3 h are ignored.

**Tide (checked 2026-09-05).** Open-Meteo `sea_level_height_msl` comes from Meteo-France's SMOC currents/tide model at ~8 km, hourly, and Open-Meteo itself says coastal accuracy is limited. Against the official times (Vieux-Boucau reference, via surf-forecast.com; SHOM is the authority) the model extremes ran **30-60 min early** on 6 of 7 checks. So: extremes are interpolated (parabola through the hourly peak, ~10 min resolution), displayed with a `~`, and every spot links to the official SHOM page `https://maree.shom.fr/harbor/<PORT>` (`shom` field: POINTE_DE_GRAVE for Soulac/Amelie/Gurp, ARCACHON_EYRAC for the rest of Gironde, CAPBRETON for Landes, BOUCAU-BAYONNE for Anglet/Biarritz; the SHOM site is a JS app so slugs could not be verified by HTTP, fix any that show "not found"). SHOM's own API is paid. Do NOT correct the times blindly by +45 min; the offset was not constant.

**Sources considered and NOT wired (for the record):**
- **Ifremer MARC WW3-NORGAS-2MIN**: WAVEWATCH-III for the Bay of Biscay at 2 arc-min (~3.7 km), 3-hourly, 6 days, open licence, 50+ variables incl. swell partitions and water level, on THREDDS/OPeNDAP `tds1.ifremer.fr/thredds/dodsC/MARC-WW3_NORGAS_2MIN-FOR_FULL_TIME_SERIE`. Metadata loads but every data subset (even 2 time steps) timed out on 2026-09-05; the aggregation is too heavy for a cron job. Revisit via their FTP or the data request form (forms.ifremer.fr/lops-oc/marc-ww3) if wanted.
- **Copernicus Marine IBI wave forecast** (`IBI_ANALYSISFORECAST_WAV_005_005`): MFWAM at 1/36 deg (~3 km), HOURLY, 10 days, assimilates altimeter + CFOSAT, forced by ECMWF hourly wind and IBI currents, updated twice daily. Probably the best free forecast for this coast, but needs a free Copernicus account and the `copernicusmarine` Python toolbox (credentials as GitHub secrets). Worth adding if the trip shows the Open-Meteo blend is consistently off.
- **Meteo-France observations API** (portail-api.meteofrance.fr): free key since 2024, 6-min station wind (Biscarrosse, Cap Ferret, Biarritz). Would give live wind like the Dutch side has. Needs Simon to register a key.
- **Surfline** (LOLA + ML spot forecasts, the industry reference, WSL uses it): no public API; third-party scrapers exist (pysurfline, Apify) but are ToS-grey. Surf-Forecast.com, Windguru, Windy all run on the same public models we already read (ECMWF/GFS/ICON + MFWAM/WAM), so they are cross-check UIs, not extra data. Magicseaweed shut down in 2023 (merged into Surfline). Human cross-check links stay in the spot table.
- **Tide authority**: SHOM API is paid; SHOM website free. maree.info / point-maree scrape-only.

**Schedule.** `forecast.yml` gained mode `surf`: the daily 03:00 UTC run also refreshes the surf side, and extra crons `0 10 14-30 9 *` + `0 10 1-4 10 *` (12:00 Paris) do the midday refresh during the trip. Manual: `gh workflow run forecast.yml -f mode=surf` (as SD4444). Morning ping routines (RemoteTrigger, same self-healing freshness gate as the foil routines, reading `data/surf.fetched_at.txt`, calendar invite to simon.demarmels@gmail.com at 07:00 Paris, dashboard link to surf.html, logs `surf` lines to `logs/runs.md`):
- `trig_011UZB6qkSrVY9XF7nN3J3wo` - cron `30 4 14-30 9 *` (06:30 Paris, 14-30 Sep).
- `trig_01TJmtxJVGEdt7FvttCddP7H` - cron `30 4 1-4 10 *` (06:30 Paris, 1-4 Oct).
Both have a date guard and do nothing outside 14 Sep - 4 Oct. After the trip they simply never fire again; delete them at https://claude.ai/code/routines if you want the list clean.

**Voice.** Same as the foil side: headline short and straight (`"<Spot>'s the call today."`, `"Today's a maybe."`, `"Nothing clean today."`), everything else plain data. No em dashes.

**Gotcha (fixed 2026-09-05):** the workflow's "Pick mode" step compared the schedule against `50 15 * * 0`, a cron that no longer existed, so the Sunday 14:00 UTC run was being treated as `daily`. It now matches `0 14 * * 0` for weekly and `0 10 *` for surf.
