#!/usr/bin/env python3
"""
Wendy Foils - wind-foil forecast engine for Simon (beginner, 5m wing / 95L / ~78kg).

Modes:
  python3 wendy.py weekly   -> 7-day Sunday planner (best_match blend for far days)
  python3 wendy.py daily    -> next-3-day short-range lookout (KNMI HARMONIE)

Outputs to stdout:
  - a human summary
  - an HTML block delimited by <!--EMAIL_HTML_START--> ... <!--EMAIL_HTML_END-->
  - a subject line delimited by <!--SUBJECT_START--> ... <!--SUBJECT_END-->
  - a JSON block (flagged days) delimited by <!--JSON_START--> ... <!--JSON_END-->

Data: Open-Meteo (KNMI HARMONIE-AROME primary, ICON-EU + ECMWF for consensus,
ICON-EU ensemble for probability, Marine/EWAM for waves + sea temp). No API key.
Live nowcast obs pooled from Buienradar + weather2kite.nl (on-water NKV/KNMI/RWS
stations); nearest station per spot. Attribution: Open-Meteo CC BY 4.0.
"""

import sys, os, json, math, urllib.request, urllib.error
from datetime import datetime, timezone

# ---- rider profile ----
RIDER_KG = 78
# Progression toggle: set WENDY_LEVEL=progressing once Simon rides upwind reliably and
# can self-rescue. It widens the ceiling toward 22-24kt and eases the steadiness/wave
# penalties. Default stays the strict beginner band. (Documented in CLAUDE.md section 3.)
LEVEL = os.environ.get("WENDY_LEVEL", "beginner").strip().lower()
PROGRESSING = LEVEL in ("progressing", "intermediate", "improver")

WIND_MIN = 13          # kt avg, foiling floor for 5m/95L at 78kg
WIND_IDEAL_LO = 15
WIND_IDEAL_HI = 20 if not PROGRESSING else 22
WIND_MAX = 22 if not PROGRESSING else 25   # kt avg ceiling on a 5m
GUST_MAX = 25 if not PROGRESSING else 30   # kt, hard block
SPREAD_OK = 5 if not PROGRESSING else 7    # kt, gust - avg <= this is steady
MIN_WINDOW_HRS = 2     # sustained window

DIRS16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]

def dir16(deg):
    return DIRS16[round((deg % 360) / 22.5) % 16]

# ---- spots ----
# blocked = offshore compass names (hard no-go). good = side/side-onshore (ideal).
SPOTS = [
    {"name":"Muiderberg","lat":52.3291,"lon":5.1134,"type":"inland",
     "blocked":{"S","SSW","SW","SSE","SE"}, "good":{"N","NNE","NE","NNW","NW"},
     "wg":"https://www.windguru.cz/19","note":"closest (~20min), standing-depth flat, launch from the water"},
    {"name":"Schellinkhout","lat":52.6167,"lon":5.1350,"type":"inland",
     "blocked":{"N","NNE","NE","NNW"}, "good":{"SW","WSW","W","S","SSW","SE","SSE"},
     "wg":"https://www.windguru.cz/3601","note":"~45min, safest water in region, huge shallow flat"},
    {"name":"Almere Muiderzand","lat":52.3390,"lon":5.1740,"type":"inland",
     "blocked":{"E","ENE","ESE"}, "good":{"N","NNW","NW","W","SW","WSW"},
     "wg":"https://www.windguru.cz/19","note":"~25min, official spot, a bit deeper"},
    {"name":"Loosdrecht","lat":52.1960,"lon":5.0650,"type":"inland",
     "blocked":{"E","ENE"}, "good":{"SW","WSW","W","S","SSW","NW","N"},
     "wg":"https://www.windguru.cz/26078","note":"~30min, shallow sheltered lake system, gusty near tree-lined shores, popular beginner spot"},
    {"name":"Wijk aan Zee","lat":52.4930,"lon":4.5880,"type":"coast",
     "blocked":{"E","ENE","ESE","SE"}, "good":{"SW","WSW","W","WNW","NW"},
     "wg":"https://www.windguru.cz/113","note":"coast/waves - PARKED until foil-stable on flat water"},
]

FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE   = "https://marine-api.open-meteo.com/v1/marine"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent":"wendy-foils/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def try_json(url):
    try:
        return get_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        sys.stderr.write(f"WARN fetch failed: {e} :: {url[:90]}\n")
        return None

BUIENRADAR = "https://data.buienradar.nl/2.0/feed/json"
MS_TO_KT = 1.94384

def haversine(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat); dl = math.radians(b_lon - a_lon)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(h))

def fetch_obs():
    """Live station wind from Buienradar (free, no key). Returns list of stations with
    wind in KNOTS. Used as a nowcast reality-check against the models in the daily scan."""
    j = try_json(BUIENRADAR)
    if not j: return []
    out = []
    for s in j.get("actual", {}).get("stationmeasurements", []):
        ws = s.get("windspeed");
        if ws is None: continue
        out.append({"name": s.get("stationname","").replace("Meetstation ","").strip(),
                    "lat": s.get("lat"), "lon": s.get("lon"),
                    "kt": ws*MS_TO_KT,
                    "gust": (s.get("windgusts") or ws)*MS_TO_KT,
                    "deg": s.get("winddirectiondegrees")})
    return out

# weather2kite.nl / Soarcast: NKV + KNMI + RWS wind stations, keyless JSON. Adds genuine
# ON-WATER points the KNMI/Buienradar network lacks near the IJmeer (esp. Pampus, mid-lake,
# ~5km off Muiderberg/Almere, which otherwise fall back to a 24-27km inland land station).
# Requires an X-Requested-With header or the server returns an empty 200 body (scrape guard).
WEATHER2KITE = ("https://www.weather2kite.nl/sc/scapi.php"
                "?table=mv_measurement_location_markers&has_harmonie=true")
W2K_MAX_AGE_S = 2 * 3600   # skip stations whose latest reading is older than 2h (offline)

def fetch_w2k():
    """Live station wind from weather2kite.nl in KNOTS. Same dict shape as fetch_obs().
    Returns [] on any failure so it can be concatenated with the Buienradar pool safely."""
    req = urllib.request.Request(WEATHER2KITE, headers={
        "User-Agent": "wendy-foils/1.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.weather2kite.nl/web/"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            j = json.load(r)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        sys.stderr.write(f"WARN weather2kite fetch failed: {e}\n")
        return []
    now = datetime.now(timezone.utc).timestamp()
    out = []
    for s in (j or []):
        ws, gs, wd = s.get("windsnelheid"), s.get("windstoot"), s.get("windrichting")
        if ws is None: continue
        t = s.get("oldest_measurement_time")
        if t is not None and now - t > W2K_MAX_AGE_S: continue   # stale/offline station
        if ws == 0 and (gs or 0) == 0 and (wd or 0) == 0: continue  # 0/0/0 offline signature
        lat, lon = s.get("n"), s.get("e")
        if lat is None or lon is None: continue
        out.append({"name": (s.get("location_name") or "").strip(),
                    "lat": lat, "lon": lon,
                    "kt": ws * MS_TO_KT,
                    "gust": (gs if gs is not None else ws) * MS_TO_KT,
                    "deg": wd})
    return out

def nearest_obs(spot, obs):
    cand = [o for o in obs if o.get("lat") is not None and o.get("lon") is not None]
    if not cand: return None
    o = min(cand, key=lambda o: haversine(spot["lat"], spot["lon"], o["lat"], o["lon"]))
    return {"station": o["name"], "kt": round(o["kt"],1), "gust": round(o["gust"],1),
            "deg": o["deg"], "dir": dir16(o["deg"]) if o["deg"] is not None else None,
            "km": round(haversine(spot["lat"], spot["lon"], o["lat"], o["lon"]))}

# ---- go-hours: weekday early(6-9) + evening(17-21); weekend all daylight ----
def in_go_hours(ts, is_day):
    dt = datetime.fromisoformat(ts)
    h = dt.hour
    weekend = dt.weekday() >= 5
    if weekend:
        return bool(is_day)
    return (6 <= h <= 9) or (17 <= h <= 21)

def suit_for(temp):
    # wetsuit thickness by water temp (C)
    if temp is None: return "check water temp"
    if temp >= 20: return "shorty / 2mm or boardies"
    if temp >= 17: return "3/2 wetsuit"
    if temp >= 13: return "4/3 wetsuit"
    if temp >= 10: return "5/4 + boots"
    return "5/4 + boots + gloves + hood"

def wetsuit(sst):
    if sst is None: return "wetsuit: check water temp"
    return f"water {sst:.0f}C: {suit_for(sst)}"

# Typical monthly IJsselmeer/Markermeer surface temp (C). No free lake-temp API, and the
# North Sea marine model doesn't cover the enclosed lakes, so use this seasonal estimate
# for inland spots. Approx, shallow lakes swing warmer than the sea in summer.
LAKE_TEMP_BY_MONTH = {1:4,2:4,3:6,4:10,5:15,6:19,7:21,8:21,9:18,10:14,11:9,12:6}
def lake_temp(date):
    return LAKE_TEMP_BY_MONTH[int(date[5:7])]

# ---- fetch everything for a spot over `days` ----
def fetch_spot(spot, days, primary_model):
    lat, lon = spot["lat"], spot["lon"]
    common = f"latitude={lat}&longitude={lon}&wind_speed_unit=kn&timezone=Europe/Amsterdam&forecast_days={days}"
    # primary wind + air temp + daylight + sun
    purl = (f"{FORECAST}?{common}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,is_day"
            f"&daily=sunrise,sunset&models={primary_model}")
    prim = try_json(purl)
    if not prim or "hourly" not in prim:
        # fallback to best_match if primary model has no data at this range
        purl = (f"{FORECAST}?{common}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,is_day"
                f"&daily=sunrise,sunset")
        prim = try_json(purl)
    # consensus models (wind speed only), aligned by time. Triangulation set (researched
    # 2026-07-04): ICON-D2 is the best independent 2km near-term check against HARMONIE;
    # ICON-EU/ECMWF/GFS give mid/far-term spread. GFS reads highest over open IJsselmeer
    # (what Windguru shows), so keeping it stops the verdict hiding behind the low member.
    consensus = {}
    for m in ("icon_d2","icon_eu","ecmwf_ifs025","gfs_seamless"):
        u = f"{FORECAST}?{common}&hourly=wind_speed_10m&models={m}"
        j = try_json(u)
        if j and "hourly" in j:
            consensus[m] = dict(zip(j["hourly"]["time"], j["hourly"]["wind_speed_10m"]))
    # ensemble probability: ICON-D2-EPS near-term (2km, ~48h), ECMWF-EPS for the week-ahead.
    ens = None
    ens_model = "ecmwf_ifs025" if days > 3 else "icon_d2"
    eu = f"{ENSEMBLE}?latitude={lat}&longitude={lon}&wind_speed_unit=kn&timezone=Europe/Amsterdam&forecast_days={days}&hourly=wind_speed_10m&models={ens_model}"
    ej = try_json(eu)
    if ej and "hourly" in ej:
        h = ej["hourly"]
        members = [k for k in h if k.startswith("wind_speed_10m")]
        if members:
            ens = {}
            for i, t in enumerate(h["time"]):
                vals = [h[m][i] for m in members if h[m][i] is not None]
                if vals:
                    foilable = sum(1 for v in vals if WIND_MIN <= v <= (WIND_MAX+2))
                    ens[t] = foilable / len(vals)
    # marine (coast only): waves + sea temp
    marine = None
    if spot["type"] == "coast":
        murl = (f"{MARINE}?latitude={lat}&longitude={lon}&timezone=Europe/Amsterdam&forecast_days={days}"
                f"&hourly=wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature&models=ewam")
        mj = try_json(murl)
        if mj and "hourly" in mj:
            h = mj["hourly"]
            marine = {t: {"wave":h["wave_height"][i],"swp":h["swell_wave_period"][i],
                          "swh":h["swell_wave_height"][i],"sst":h["sea_surface_temperature"][i]}
                      for i,t in enumerate(h["time"])}
    return prim, consensus, ens, marine

# ---- classify hours into windows per day ----
def analyse(spot, prim, consensus, ens, marine, primary_label="HARMONIE"):
    H = prim["hourly"]
    times = H["time"]
    ws = H["wind_speed_10m"]; gu = H["wind_gusts_10m"]; wd = H["wind_direction_10m"]
    air = H.get("temperature_2m", [None]*len(times))
    isday = H.get("is_day", [1]*len(times))
    # group qualifying hours by date
    by_day = {}
    for i, t in enumerate(times):
        date = t[:10]
        by_day.setdefault(date, [])
        s, g, d = ws[i], gu[i], wd[i]
        if s is None: continue
        dname = dir16(d)
        blocked = dname in spot["blocked"]
        spread = (g - s) if g is not None else 0
        ingo = in_go_hours(t, isday[i])
        qual = (not blocked and WIND_MIN <= s <= WIND_MAX and (g is None or g <= GUST_MAX)
                and spread <= SPREAD_OK + 1 and ingo)
        by_day[date].append({"t":t,"h":int(t[11:13]),"s":s,"g":g,"dir":dname,"deg":d,
                             "spread":spread,"blocked":blocked,"qual":qual,"ingo":ingo,
                             "air":air[i] if i < len(air) else None})
    # build best window per day
    results = []
    for day_idx, date in enumerate(sorted(by_day)):
        hours = by_day[date]
        # find longest run of qualifying consecutive hours
        best = None; run = []
        def flush(run):
            nonlocal best
            if len(run) >= MIN_WINDOW_HRS:
                avg = sum(x["s"] for x in run)/len(run)
                gmax = max((x["g"] for x in run if x["g"] is not None), default=avg)
                cand = {"run":run,"avg":avg,"gmax":gmax,"len":len(run)}
                if best is None or cand["len"] > best["len"] or (cand["len"]==best["len"] and abs(cand["avg"]-16.5)<abs(best["avg"]-16.5)):
                    best = cand
        for x in hours:
            if x["qual"]:
                run.append(x)
            else:
                flush(run); run = []
        flush(run)

        verdict, score, why = classify_day(spot, date, hours, best, consensus, ens, marine, primary_label)
        # raw numbers for the dashboard grid (presentation is done in the generator)
        peaks = model_gohr_peaks(hours, consensus, primary_label)
        allpeak = max((x["s"] for x in hours), default=0)
        gustmax = max((x["g"] for x in hours if x["g"] is not None), default=0)
        air_go = [x["air"] for x in hours if x["ingo"] and x["air"] is not None]
        wave = water = None
        if spot["type"] == "coast" and marine:
            dp = [v for t,v in marine.items() if t[:10]==date]
            wave = max((p["wave"] for p in dp if p["wave"] is not None), default=None)
            water = next((p["sst"] for p in dp if p["sst"] is not None), None)
        if water is None: water = lake_temp(date)
        bdir = bwin = bdeg = prob = None
        if best:
            br = best["run"]
            bdir = max(set(x["dir"] for x in br), key=lambda d: sum(1 for x in br if x["dir"]==d))
            bwin = [br[0]["h"], br[-1]["h"]+1]
            xs = sum(math.sin(math.radians(x["deg"])) for x in br)
            ys = sum(math.cos(math.radians(x["deg"])) for x in br)
            bdeg = round(math.degrees(math.atan2(xs, ys)) % 360)
            if ens:
                ps = [ens[x["t"]] for x in br if x["t"] in ens]
                if ps: prob = round(sum(ps)/len(ps), 2)
        # hourly breakdown 06:00-22:00 for the near days only (day-of to +2), where the
        # short-range models are trustworthy; powers the click-to-expand day view.
        hourly = None
        if day_idx <= 2:
            hourly = [{"h": x["h"], "s": round(x["s"],1),
                       "g": round(x["g"],1) if x["g"] is not None else None,
                       "dir": x["dir"], "deg": x["deg"]}
                      for x in sorted(hours, key=lambda x: x["h"]) if 6 <= x["h"] <= 22]
        results.append({"date":date,"spot":spot["name"],"type":spot["type"],
                        "verdict":verdict,"score":score,"why":why,"best":best,
                        "avg": round(best["avg"],1) if best else None,
                        "peak": round(allpeak,1), "gust": round(gustmax,1),
                        "hotpeak": round(max(peaks.values(), default=allpeak),1),
                        "wave": round(wave,1) if wave is not None else None,
                        "air": round(max(air_go),1) if air_go else None,
                        "water": water, "wetsuit": suit_for(water),
                        "dir": bdir, "win": bwin, "deg": bdeg, "prob": prob, "obs": None,
                        "hourly": hourly})
    return results

def weekday_name(date):
    return datetime.fromisoformat(date+"T00:00").strftime("%a %d %b")

MODEL_NAMES = {"icon_d2":"ICON-D2","icon_eu":"ICON","ecmwf_ifs025":"ECMWF","gfs_seamless":"GFS"}

def model_gohr_peaks(hours, consensus, primary_label):
    # peak wind during your go-hours, per model (primary + every consensus model).
    gohrs = [x for x in hours if x["ingo"]]
    go_ts = [x["t"] for x in gohrs]
    peaks = {}
    if gohrs:
        peaks[primary_label] = max(x["s"] for x in gohrs)
    for m, series in consensus.items():
        vals = [series[t] for t in go_ts if series.get(t) is not None]
        if vals: peaks[MODEL_NAMES.get(m, m)] = max(vals)
    return peaks

def temp_line(spot, date, hours):
    # air temp (peak of go-hours, else day) + water temp + wetsuit call
    air_go = [x["air"] for x in hours if x["ingo"] and x["air"] is not None]
    air_all = [x["air"] for x in hours if x["air"] is not None]
    airt = max(air_go) if air_go else (max(air_all) if air_all else None)
    water = lake_temp(date)  # inland; coast overrides with real sea temp elsewhere
    bits = []
    if airt is not None: bits.append(f"air {airt:.0f}C")
    bits.append(f"water ~{water}C ({suit_for(water)})")
    return ", ".join(bits)

def range_line(peaks, primary_label):
    if len(peaks) < 2: return ""
    order = [primary_label] + [n for n in ("ICON-D2","GFS","ICON","ECMWF") if n in peaks and n != primary_label]
    order += [n for n in peaks if n not in order]
    return "go-hrs peak by model: " + ", ".join(f"{n} {peaks[n]:.0f}" for n in order if n in peaks) + "kt"

def classify_day(spot, date, hours, best, consensus, ens, marine, primary_label="HARMONIE"):
    # coast is parked in the learning phase regardless
    if spot["type"] == "coast":
        sst = None; wave = None
        if marine:
            day_pts = [v for t,v in marine.items() if t[:10]==date]
            if day_pts:
                sst = next((p["sst"] for p in day_pts if p["sst"] is not None), None)
                wave = max((p["wave"] for p in day_pts if p["wave"] is not None), default=None)
        w = f"coast/wave spot - parked until you're foil-stable on flat water"
        if wave is not None: w += f"; ~{wave:.1f}m sea"
        air_go = [x["air"] for x in hours if x["ingo"] and x["air"] is not None]
        if air_go: w += f"; air {max(air_go):.0f}C"
        w += f"; {wetsuit(sst) if sst is not None else 'water ~'+str(lake_temp(date))+'C: '+suit_for(lake_temp(date))}"
        return "SKIP", 0, w

    peaks = model_gohr_peaks(hours, consensus, primary_label)
    rng = range_line(peaks, primary_label)
    tline = temp_line(spot, date, hours)
    tail = (f" | {rng} | {tline}" if rng else f" | {tline}")

    # peak wind of day for context
    peak = max((x["s"] for x in hours), default=0)
    domdir = None
    if hours:
        windy = [x for x in hours if x["s"] >= max(6, peak*0.7)]
        if windy:
            domdir = max(set(x["dir"] for x in windy), key=lambda d:sum(1 for x in windy if x["dir"]==d))
    offshore = domdir in spot["blocked"] if domdir else False

    if best is None:
        if offshore and peak >= WIND_MIN:
            return "SKIP", 0, f"peak {peak:.0f}kt but {domdir} is offshore here - no-go direction{tail}"
        # MULTI-MODEL: primary shows no window, but if a stronger model (often GFS on open
        # water) reads foilable in your hours, surface it as MAYBE so we never miss a GFS-right
        # day. This is the fix for HARMONIE running low over the IJsselmeer.
        hot_name, hot_peak = max(peaks.items(), key=lambda kv: kv[1], default=(None, 0))
        prim_peak = peaks.get(primary_label, peak)
        if not offshore and hot_name and hot_name != primary_label and hot_peak >= WIND_MIN and hot_peak - prim_peak >= 3:
            return "MAYBE", 1.5, (f"models split - {primary_label} only ~{prim_peak:.0f}kt in your hours "
                                  f"but {hot_name} shows ~{hot_peak:.0f}kt; foilable if the stronger model "
                                  f"verifies, worth watching{tail}")
        if peak < WIND_MIN:
            return "SKIP", 0, f"too light, peaks only ~{peak:.0f}kt (need {WIND_MIN}kt+ to foil){tail}"
        gpk = max((x["g"] for x in hours if x["g"] is not None), default=0)
        if gpk > GUST_MAX:
            return "SKIP", 0, f"windy (peak {peak:.0f}kt) but gusting {gpk:.0f}kt - too unstable/overpowered on a 5m{tail}"
        return "SKIP", 1, f"peaks ~{peak:.0f}kt but no steady 2h+ window in your hours{tail}"

    avg = best["avg"]; gmax = best["gmax"]; run = best["run"]
    t0 = run[0]["h"]; t1 = run[-1]["h"]+1
    domd = max(set(x["dir"] for x in run), key=lambda d:sum(1 for x in run if x["dir"]==d))
    spread = gmax - avg
    good_dir = domd in spot["good"]

    # score 0-5
    if WIND_IDEAL_LO <= avg <= WIND_IDEAL_HI: score = 3
    elif 14 <= avg < WIND_IDEAL_LO or WIND_IDEAL_HI < avg <= 20: score = 2
    else: score = 1
    if spread <= 3: score += 1
    elif spread <= 5: score += 0.5
    if good_dir: score += 1
    score = min(5, round(score*2)/2)

    conf = model_confidence(run, consensus)
    prob = None
    if ens:
        ps = [ens[x["t"]] for x in run if x["t"] in ens]
        if ps: prob = sum(ps)/len(ps)

    verdict = "GO" if score >= 3 and good_dir else "MAYBE"
    why = (f"{t0:02d}:00-{t1:02d}:00 ~{avg:.0f}kt {domd} (gust {gmax:.0f}), "
           f"{'steady' if spread<=5 else 'gusty'}; "
           f"{'good side-onshore dir' if good_dir else 'usable but not ideal dir'}")
    if prob is not None: why += f"; {prob*100:.0f}% ensemble chance of foilable wind"
    why += f"; confidence {conf}{tail}"
    return verdict, score, why

def model_confidence(run, consensus):
    if not consensus: return "single-model"
    prim_avg = sum(x["s"] for x in run)/len(run)
    means = [prim_avg]
    for m, series in consensus.items():
        vals = [series[x["t"]] for x in run if x["t"] in series and series[x["t"]] is not None]
        if vals: means.append(sum(vals)/len(vals))
    if len(means) < 2: return "single-model"
    spread = max(means) - min(means)
    return "high (models agree)" if spread <= 3 else f"low (models differ {spread:.0f}kt)"

# ---- HTML email ----
TAG_COLOR = {"GO":"#1a9850","MAYBE":"#f0a020","SKIP":"#999999"}

def stars(score):
    full = int(score); half = 1 if score-full>=0.5 else 0
    return "★"*full + ("½" if half else "") + "☆"*(5-full-half)

def build_html(mode, all_results, generated):
    # flatten to per-day best across spots for the headline
    go_maybe = [r for r in all_results if r["verdict"] in ("GO","MAYBE")]
    go_maybe.sort(key=lambda r:(-r["score"], r["date"]))
    headline = go_maybe[0] if go_maybe else None

    css = ("font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
           "color:#1a1a1a;line-height:1.5;")
    parts = [f'<div style="{css}max-width:640px">']
    title = "Week ahead" if mode=="weekly" else "Short-range lookout"
    parts.append(f'<h2 style="margin:0 0 4px">🌬️ Wendy Foils - {title}</h2>')
    parts.append(f'<div style="color:#666;font-size:13px;margin-bottom:14px">{generated} · 5m wing · 78kg · beginner</div>')

    if headline and headline["verdict"]=="GO":
        parts.append(f'<div style="background:#eafaf0;border-left:4px solid #1a9850;padding:12px 14px;border-radius:6px;margin-bottom:16px">'
                     f'<strong>Best day: {weekday_name(headline["date"])} at {headline["spot"]}</strong> {stars(headline["score"])}<br>'
                     f'<span style="font-size:14px">{headline["why"]}</span></div>')
    elif headline:
        parts.append(f'<div style="background:#fff7e6;border-left:4px solid #f0a020;padding:12px 14px;border-radius:6px;margin-bottom:16px">'
                     f'<strong>No clear GO. Best maybe: {weekday_name(headline["date"])} at {headline["spot"]}</strong> {stars(headline["score"])}<br>'
                     f'<span style="font-size:14px">{headline["why"]}</span></div>')
    else:
        parts.append('<div style="background:#f2f2f2;border-left:4px solid #999;padding:12px 14px;border-radius:6px;margin-bottom:16px">'
                     '<strong>Nothing rideable in range.</strong> No steady in-band window at your spots. Rest up.</div>')

    # table grouped by spot
    parts.append('<table style="border-collapse:collapse;width:100%;font-size:14px">')
    parts.append('<tr style="text-align:left;border-bottom:2px solid #ddd">'
                 '<th style="padding:6px 8px">Day</th><th style="padding:6px 8px">Spot</th>'
                 '<th style="padding:6px 8px">Call</th><th style="padding:6px 8px">Detail</th></tr>')
    for r in sorted(all_results, key=lambda r:(r["date"], -r["score"])):
        c = TAG_COLOR[r["verdict"]]
        tag = (f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:10px;'
               f'font-size:12px;font-weight:600">{r["verdict"]}</span>')
        sc = stars(r["score"]) if r["verdict"]!="SKIP" else ""
        parts.append(f'<tr style="border-bottom:1px solid #eee">'
                     f'<td style="padding:6px 8px;white-space:nowrap">{weekday_name(r["date"])}</td>'
                     f'<td style="padding:6px 8px">{r["spot"]}</td>'
                     f'<td style="padding:6px 8px;white-space:nowrap">{tag} {sc}</td>'
                     f'<td style="padding:6px 8px;color:#444">{r["why"]}</td></tr>')
    parts.append('</table>')

    # sources
    wg_links = " · ".join(f'<a href="{s["wg"]}">{s["name"]}</a>' for s in SPOTS)
    model = "KNMI HARMONIE-AROME" if mode=="daily" else "best-match blend (HARMONIE / ICON-EU / ECMWF)"
    parts.append(f'<div style="margin-top:16px;font-size:12px;color:#777">'
                 f'Source: {model} + ICON-EU ensemble + EWAM waves, via Open-Meteo (CC BY 4.0). '
                 f'Cross-check on Windguru: {wg_links}.<br>'
                 f'Rules: foil 13-22kt, ideal 15-20, steady (gust-avg ≤5), side-onshore only, offshore blocked, your go-hours.</div>')
    parts.append('</div>')
    return "\n".join(parts)

def build_subject(mode, all_results):
    go = [r for r in all_results if r["verdict"]=="GO"]
    maybe = [r for r in all_results if r["verdict"]=="MAYBE"]
    pre = "Week ahead" if mode=="weekly" else "Lookout"
    if go:
        go.sort(key=lambda r:(-r["score"], r["date"]))
        b = go[0]
        return f"🌬️ {pre}: GO {weekday_name(b['date'])} {b['spot']} {stars(b['score'])}"
    if maybe:
        maybe.sort(key=lambda r:(-r["score"], r["date"]))
        b = maybe[0]
        return f"🌬️ {pre}: maybe {weekday_name(b['date'])} {b['spot']}"
    return f"🌬️ {pre}: no foil window"

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    if mode == "weekly":
        days, primary, primary_label = 7, "best_match", "blend"
    else:
        days, primary, primary_label = 3, "knmi_harmonie_arome_netherlands", "HARMONIE"

    # live station wind for a nowcast reality-check (most useful in the daily scan).
    # Pool both networks: weather2kite adds on-water IJmeer/Markermeer points (Pampus,
    # NKV kite stations) the KNMI/Buienradar network lacks; nearest_obs then picks the
    # closest station across both, so lake spots get an on-water read instead of a
    # 24km inland land station. Buienradar alone still works if weather2kite is down.
    obs = fetch_obs() + fetch_w2k()

    all_results = []
    for spot in SPOTS:
        prim, cons, ens, marine = fetch_spot(spot, days, primary)
        if not prim or "hourly" not in prim:
            sys.stderr.write(f"no data for {spot['name']}\n"); continue
        rs = analyse(spot, prim, cons, ens, marine, primary_label)
        # attach the nearest live obs to this spot's today row (obs is a "now" reading)
        so = nearest_obs(spot, obs) if obs else None
        if so and rs:
            rs[0]["obs"] = so
        all_results += rs

    now = datetime.fromisoformat(SPOTS and all_results[0]["date"]+"T00:00") if all_results else None
    generated = weekday_name(sorted({r["date"] for r in all_results})[0]) if all_results else ""
    generated = f"forecast from {generated}"

    html = build_html(mode, all_results, generated)
    subject = build_subject(mode, all_results)
    flagged = [{"date":r["date"],"spot":r["spot"],"verdict":r["verdict"],"score":r["score"],"why":r["why"]}
               for r in all_results if r["verdict"] in ("GO","MAYBE")]

    # human summary
    print(f"=== {mode.upper()} ===")
    for r in sorted(all_results, key=lambda r:(r["date"], r["spot"])):
        print(f"{weekday_name(r['date'])}  {r['spot']:<18} {r['verdict']:<5} {stars(r['score']) if r['verdict']!='SKIP' else '':<7} {r['why']}")
    grid_keys = ("date","spot","type","verdict","score","avg","peak","gust","hotpeak","wave","air","water","wetsuit","why","dir","win","deg","prob","obs","hourly")
    grid = [{k: r.get(k) for k in grid_keys} for r in all_results]
    print(f"\n<!--SUBJECT_START-->{subject}<!--SUBJECT_END-->")
    print(f"<!--JSON_START-->{json.dumps(flagged)}<!--JSON_END-->")
    print(f"<!--GRID_START-->{json.dumps(grid)}<!--GRID_END-->")
    print(f"<!--EMAIL_HTML_START-->\n{html}\n<!--EMAIL_HTML_END-->")

if __name__ == "__main__":
    main()
