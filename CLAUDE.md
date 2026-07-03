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

## 5. Files

- `wendy.py` — the forecast engine. `python3 wendy.py weekly` (7-day Sunday planner, best_match blend) or `python3 wendy.py daily` (next-3-day HARMONIE lookout). Fetches multi-model wind + ICON-EU ensemble + EWAM waves/sea-temp, applies the good-day rule, and prints a human summary plus delimited blocks: `<!--SUBJECT_START-->`, `<!--EMAIL_HTML_START-->`, `<!--JSON_START-->`. The scheduled agent runs it, then passes the subject as the event title and the HTML as the event description to `create_event`.
- `reference/` — research notes on forecast sources, spots, skill-level bands.
- `logs/` — run logs / forecast history, to debug and dedupe alerts.
- `.claude/skills/` — project-specific skills, if any get built.

**Email rendering caveat:** the HTML is all inline styles (no external CSS) so it survives email clients. Gmail renders the rich table + color tags when Simon opens the calendar event; the invitation *email* preview itself may show a simplified version. If inbox rendering ever disappoints, fall back to the linked-dashboard option (a hosted forecast page linked from a short invite).

---

## 6. Notes / gotchas

- Confirm the active GitHub account before any git remote ops (Simon's personal is SD4444; the Evolute account can't see personal repos and 404s look like "repo missing").
- Never use em dashes in anything user-facing (Simon's standing rule).
- Keep alerts terse and specific: spot, time window, wind speed + direction. No filler.
