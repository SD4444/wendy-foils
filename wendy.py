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
Attribution: Open-Meteo CC BY 4.0.
"""

import sys, json, urllib.request, urllib.error
from datetime import datetime

# ---- rider profile ----
RIDER_KG = 78
WIND_MIN = 13          # kt avg, foiling floor for 5m/95L at 78kg
WIND_IDEAL_LO = 15
WIND_IDEAL_HI = 20
WIND_MAX = 22          # kt avg, beginner ceiling on a 5m
GUST_MAX = 25          # kt, hard block
SPREAD_OK = 5          # kt, gust - avg <= this is steady
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

# ---- go-hours: weekday early(6-9) + evening(17-21); weekend all daylight ----
def in_go_hours(ts, is_day):
    dt = datetime.fromisoformat(ts)
    h = dt.hour
    weekend = dt.weekday() >= 5
    if weekend:
        return bool(is_day)
    return (6 <= h <= 9) or (17 <= h <= 21)

def wetsuit(sst):
    if sst is None: return "wetsuit: check water temp"
    if sst >= 20: return f"water {sst:.0f}C: shorty / 3-2 or boardies"
    if sst >= 15: return f"water {sst:.0f}C: 3/2 wetsuit"
    if sst >= 11: return f"water {sst:.0f}C: 4/3 wetsuit"
    return f"water {sst:.0f}C: 5/4 + boots + gloves"

# ---- fetch everything for a spot over `days` ----
def fetch_spot(spot, days, primary_model):
    lat, lon = spot["lat"], spot["lon"]
    common = f"latitude={lat}&longitude={lon}&wind_speed_unit=kn&timezone=Europe/Amsterdam&forecast_days={days}"
    # primary wind + daylight + sun
    purl = (f"{FORECAST}?{common}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,is_day"
            f"&daily=sunrise,sunset&models={primary_model}")
    prim = try_json(purl)
    if not prim or "hourly" not in prim:
        # fallback to best_match if primary model has no data at this range
        purl = (f"{FORECAST}?{common}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,is_day"
                f"&daily=sunrise,sunset")
        prim = try_json(purl)
    # consensus models (wind speed only), aligned by time
    consensus = {}
    for m in ("icon_eu","ecmwf_ifs025"):
        u = f"{FORECAST}?{common}&hourly=wind_speed_10m&models={m}"
        j = try_json(u)
        if j and "hourly" in j:
            consensus[m] = dict(zip(j["hourly"]["time"], j["hourly"]["wind_speed_10m"]))
    # ensemble probability (ICON-EU members)
    ens = None
    eu = f"{ENSEMBLE}?latitude={lat}&longitude={lon}&wind_speed_unit=kn&timezone=Europe/Amsterdam&forecast_days={days}&hourly=wind_speed_10m&models=icon_eu"
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
def analyse(spot, prim, consensus, ens, marine):
    H = prim["hourly"]
    times = H["time"]
    ws = H["wind_speed_10m"]; gu = H["wind_gusts_10m"]; wd = H["wind_direction_10m"]
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
        qual = (not blocked and WIND_MIN <= s <= WIND_MAX and (g is None or g <= GUST_MAX)
                and spread <= SPREAD_OK + 1 and in_go_hours(t, isday[i]))
        by_day[date].append({"t":t,"h":int(t[11:13]),"s":s,"g":g,"dir":dname,"deg":d,
                             "spread":spread,"blocked":blocked,"qual":qual})
    # build best window per day
    results = []
    for date in sorted(by_day):
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

        verdict, score, why = classify_day(spot, date, hours, best, consensus, ens, marine)
        results.append({"date":date,"spot":spot["name"],"type":spot["type"],
                        "verdict":verdict,"score":score,"why":why,"best":best})
    return results

def weekday_name(date):
    return datetime.fromisoformat(date+"T00:00").strftime("%a %d %b")

def classify_day(spot, date, hours, best, consensus, ens, marine):
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
        if sst is not None: w += f"; {wetsuit(sst)}"
        return "SKIP", 0, w
    # peak wind of day for context
    peak = max((x["s"] for x in hours), default=0)
    domdir = None
    if hours:
        # dominant direction among windier hours
        windy = [x for x in hours if x["s"] >= max(6, peak*0.7)]
        if windy:
            domdir = max(set(x["dir"] for x in windy), key=lambda d:sum(1 for x in windy if x["dir"]==d))
    # any blocked offshore during windy hours?
    offshore = domdir in spot["blocked"] if domdir else False

    if best is None:
        if offshore and peak >= WIND_MIN:
            return "SKIP", 0, f"peak {peak:.0f}kt but {domdir} is offshore here - no-go direction"
        if peak < WIND_MIN:
            return "SKIP", 0, f"too light, peaks only ~{peak:.0f}kt (need {WIND_MIN}kt+ to foil)"
        # wind exists but too gusty / out of go-hours
        gpk = max((x["g"] for x in hours if x["g"] is not None), default=0)
        if gpk > GUST_MAX:
            return "SKIP", 0, f"windy (peak {peak:.0f}kt) but gusting {gpk:.0f}kt - too unstable/overpowered on a 5m"
        return "SKIP", 1, f"peaks ~{peak:.0f}kt but no steady 2h+ window in your hours"

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

    # confidence via model consensus over the window
    conf = model_confidence(run, consensus)
    # ensemble probability over window
    prob = None
    if ens:
        ps = [ens[x["t"]] for x in run if x["t"] in ens]
        if ps: prob = sum(ps)/len(ps)

    verdict = "GO" if score >= 3 and good_dir else "MAYBE"
    why = (f"{t0:02d}:00-{t1:02d}:00 ~{avg:.0f}kt {domd} (gust {gmax:.0f}), "
           f"{'steady' if spread<=5 else 'gusty'}; "
           f"{'good side-onshore dir' if good_dir else 'usable but not ideal dir'}")
    if prob is not None: why += f"; {prob*100:.0f}% ensemble chance of foilable wind"
    why += f"; confidence {conf}"
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
        days, primary = 7, "best_match"
    else:
        days, primary = 3, "knmi_harmonie_arome_netherlands"

    all_results = []
    for spot in SPOTS:
        prim, cons, ens, marine = fetch_spot(spot, days, primary)
        if not prim or "hourly" not in prim:
            sys.stderr.write(f"no data for {spot['name']}\n"); continue
        all_results += analyse(spot, prim, cons, ens, marine)

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
    print(f"\n<!--SUBJECT_START-->{subject}<!--SUBJECT_END-->")
    print(f"<!--JSON_START-->{json.dumps(flagged)}<!--JSON_END-->")
    print(f"<!--EMAIL_HTML_START-->\n{html}\n<!--EMAIL_HTML_END-->")

if __name__ == "__main__":
    main()
