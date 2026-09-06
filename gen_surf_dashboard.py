#!/usr/bin/env python3
"""Regenerate docs/surf.html from a surf.py output file (GRID + SPOTS + JSON blocks).

Usage: python3 gen_surf_dashboard.py data/surf.out.txt docs/surf.html
The GitHub Action runs this after each surf fetch. Edit the design in TEMPLATE below;
never hand-edit docs/surf.html (it is generated).
"""
import sys, os, json, re
from datetime import datetime, date

SOURCES = [
    "MFWAM / ECMWF-WAM · waves, swell, tide, sea temp",
    "ECMWF-WAM 0.25 · second opinion on size",
    "Candhis buoys · Cap Ferret, Anglet, St-Jean-de-Luz · live",
    "Komar-Gaughan · offshore swell to breaking face",
    "Meteo-France AROME HD 1.5 km · wind (~2 days)",
    "SHOM · official tide times (linked)",
    "Cams · checked one by one, 6 Sep 2026",
]
DEPT_SHORT = {"Gironde":"Gironde", "Landes":"Landes", "Pyrénées-Atlantiques":"Pays Basque"}

def daylabel(d): return datetime.fromisoformat(d+"T00:00").strftime("%a %-d")
def dlong(d):    return datetime.fromisoformat(d+"T00:00").strftime("%A %-d %b")
def dayname(d):  return datetime.fromisoformat(d+"T00:00").strftime("%A")
def fmt_h(h):
    m = int(round((h - int(h)) * 60))
    if m == 60: h, m = int(h) + 1, 0
    return f"{int(h):02d}:{m:02d}"

def short(name):
    return name.split(" – ")[0] if " – " in name else name

def tide_txt(tides):
    bits = []
    for h, v in tides.get("low", []):  bits.append((h, f"low {fmt_h(h)}"))
    for h, v in tides.get("high", []): bits.append((h, f"high {fmt_h(h)}"))
    return ("~" + " · ".join(b for _, b in sorted(bits))) if bits else "tide n/a"

def wind_txt(r):
    if r.get("kt") is None: return "wind n/a"
    rel = r.get("rel") or ""
    lab = {"glassy":"glassy", "offshore":"offshore", "cross":"cross-shore", "onshore":"onshore", "blown":"blown out"}.get(rel, "")
    return f"{lab} {r.get('wdir') or ''} {r['kt']:.0f} kt".replace("  ", " ").strip()

def swell_txt(r):
    if r.get("hs") is None: return "no data"
    s = f"{r['hs']:.1f} m"
    if r.get("per") is not None: s += f" @ {r['per']:.0f} s"
    if r.get("sdir"): s += f" {r['sdir']}"
    return s

def obs_txt(r):
    o = r.get("obs")
    if not o: return None
    t = f"{o['name']} buoy {o['hs']:.1f} m"
    if o.get("tp"): t += f" @ {o['tp']:.0f} s"
    if o.get("deg") is not None: t += f" {['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][round(o['deg']/22.5)%16]}"
    if o.get("sst") is not None: t += f", water {o['sst']:.0f}°"
    t += f", {o['age_min']} min ago"
    br = o.get("bias_rolling") or o.get("bias")
    if br and abs(br - 1) >= 0.15:
        t += f". Models read {'high' if br > 1 else 'low'} x{br:.2f} lately, sized {'down' if br > 1 else 'up'}"
    return t

def wind_plain(r):
    if r.get("kt") is None: return "wind unknown"
    kt = r["kt"]; rel = r.get("rel") or ""; wd = r.get("wdir") or ""
    if rel == "glassy": return f"glassy, {wd} {kt:.0f} kt"
    if rel == "offshore": return f"offshore {wd} {kt:.0f} kt"
    if rel == "cross": return f"side-shore {wd} {kt:.0f} kt"
    if rel in ("onshore", "blown"): return f"onshore {wd} {kt:.0f} kt"
    return f"{wd} {kt:.0f} kt"

def tide_plain(r):
    """One sentence relating the session window to the tide."""
    t = r.get("tides") or {}; win = r.get("win")
    ev = sorted([(h, "low") for h, v in t.get("low", [])] + [(h, "high") for h, v in t.get("high", [])])
    if not ev or not win: return "tide unknown"
    mid = (win[0] + win[1]) / 2
    before = [e for e in ev if e[0] <= mid]; after = [e for e in ev if e[0] > mid]
    if before and after:
        b, a = before[-1], after[0]
        return f"{b[1]} tide {fmt_h(b[0])}, {'coming in' if b[1]=='low' else 'going out'} until {a[1]} {fmt_h(a[0])}"
    if before:
        b = before[-1]; return f"{b[1]} tide {fmt_h(b[0])}, {'coming in' if b[1]=='low' else 'going out'} during the session"
    a = after[0]; return f"{'going out' if a[1]=='low' else 'coming in'} towards {a[1]} tide {fmt_h(a[0])}"

def heads_up(r):
    o = r.get("obs")
    bits = []
    br = (o or {}).get("bias_rolling") or (o or {}).get("bias")
    if o and br and br >= 1.15:
        bits.append(f"The {o['name']} buoy shows {o['hs']:.1f} m right now, less than the forecast. Heights here are reduced to match. Check the cam before you go.")
    elif o and br and br <= 0.85:
        bits.append(f"The {o['name']} buoy shows {o['hs']:.1f} m, more than the forecast. It may be bigger than shown.")
    conf = r.get("conf") or ""
    if conf.startswith("low"): bits.append("The wave models disagree on size today.")
    return " ".join(bits)

def plain_call(r):
    return f"{(r.get('size') or '').capitalize()}, {wind_plain(r)}, {fmt_h(r['win'][0])} to {fmt_h(r['win'][1])}." if r.get("win") else (r.get("size") or "")

SECTIONS = [("Médoc", 1, 7), ("Cap Ferret & Arcachon", 8, 15), ("North Landes", 16, 22), ("South Landes", 23, 31), ("Basque coast", 32, 36)]
def section_of(n):
    for name, a, b in SECTIONS:
        if a <= n <= b: return name
    return ""

TIDE_LABEL = {"any": "works on all tides", "low": "best low to mid", "mid": "best mid tide",
              "incoming": "best mid tide, pushing", "mid-high": "best mid to high", "high": "best around high"}

DIR_WORDS = {"N":"north","NNE":"north-north-east","NE":"north-east","ENE":"east-north-east","E":"east","ESE":"east-south-east",
             "SE":"south-east","SSE":"south-south-east","S":"south","SSW":"south-south-west","SW":"south-west","WSW":"west-south-west",
             "W":"west","WNW":"west-north-west","NW":"north-west","NNW":"north-north-west"}
def wind_from(r):
    wd = r.get("wdir"); rel = r.get("rel") or ""
    if not wd: return "direction unknown"
    lab = {"glassy":"too light to matter","offshore":"offshore","cross":"side-shore","onshore":"onshore","blown":"onshore, blown out"}.get(rel, "")
    return f"from the {DIR_WORDS.get(wd, wd)}" + (f", {lab}" if lab else "")

def build_data(grid, spots_meta, flagged, buoys=None):
    dates = sorted({r["date"] for r in grid})
    today = dates[0]
    days = [daylabel(d) for d in dates]
    meta = {s["name"]: s for s in spots_meta}
    order = [s["name"] for s in sorted(spots_meta, key=lambda s: s["n"])]
    by = {(r["spot"], r["date"]): r for r in grid}

    # matrix cells: [call, value, q, title, size]
    matrix = {}
    for s in order:
        row = []
        for d in dates:
            r = by.get((s, d))
            if r is None: row.append(["skip", "–", 0, "", ""]); continue
            val = f"{r['face']:.1f}" if r.get("face") is not None else (f"{r['hs']:.1f}" if r.get("hs") is not None else "–")
            q = round(min(1.0, max(0.04, (r.get("score") or 0) / 10)), 2)
            title = (r.get("why") or "").split(";")[0]
            row.append([r["verdict"].lower(), val, q, title, r.get("size") or ""])
        matrix[s] = row

    groups = []
    for s in order:
        m = meta[s]; g = DEPT_SHORT.get(m["dept"], m["dept"])
        if not groups or groups[-1]["dept"] != g:
            groups.append({"dept": g, "spots": []})
        groups[-1]["spots"].append({"name": s, "short": short(s), "sub": m["sector"], "cam": m["cam"], "n": m["n"], "lat": m["lat"], "lon": m["lon"],
                                    "report": m["report"], "forecast": m["forecast"], "rel": m["rel"], "note": m["note"],
                                    "cam_shows": m.get("cam_shows",""), "cam_dedicated": m.get("cam_dedicated", True), "cam_km": m.get("cam_km", 0),
                                    "cam_alts": m.get("cam_alts", []), "cam_status": m.get("cam_status",""),
                                    "shom": f"https://maree.shom.fr/harbor/{m.get('shom','CAPBRETON')}", "tide_pref": m.get("tide_pref","mid"),
                                    "tide_label": TIDE_LABEL.get(m.get("tide_pref","mid"), "best mid tide")})

    def card(r):
        m = meta[r["spot"]]
        return {"spot": r["spot"], "short": short(r["spot"]), "sector": m["sector"], "verdict": r["verdict"],
                "score": r["score"], "size": r.get("size") or "", "hs": r.get("hs"), "face": r.get("face"), "swell": swell_txt(r),
                "obs": obs_txt(r), "shom": r.get("shom") or f"https://maree.shom.fr/harbor/{m.get('shom','CAPBRETON')}",
                "plain": plain_call(r), "tide_plain": tide_plain(r), "heads_up": heads_up(r), "wind_plain": wind_plain(r),
                "tide_label": TIDE_LABEL.get(m.get("tide_pref","mid"), "best mid tide"), "wind_from": wind_from(r),
                "tide_pref": m.get("tide_pref", "mid"),
                "wind": wind_txt(r), "window": f"{fmt_h(r['win'][0])}–{fmt_h(r['win'][1])}" if r.get("win") else "",
                "tide": tide_txt(r.get("tides") or {}), "water": r.get("water"), "air": r.get("air"),
                "why": (r.get("why") or ""), "conf": r.get("conf") or "", "cam": m["cam"], "report": m["report"],
                "forecast": m["forecast"], "note": m["note"], "rel": r.get("rel"), "sdeg": r.get("sdeg"), "wdeg": r.get("wdeg"),
                "cam_shows": m.get("cam_shows",""), "cam_dedicated": m.get("cam_dedicated", True), "cam_km": m.get("cam_km", 0),
                "cam_alts": m.get("cam_alts", []), "cam_status": m.get("cam_status",""),
                "date": r["date"], "day": dlong(r["date"])}

    todays = sorted([r for r in grid if r["date"] == today], key=lambda r: (-(r.get("score") or 0), r["n"]))
    five = []
    for name, a, b in SECTIONS:
        sec = [r for r in todays if a <= r["n"] <= b]
        if sec:
            c = card(sec[0]); c["section"] = name; five.append(c)
    feature = card(todays[0]) if todays else None
    # why this spot, relative to the rest of the coast
    if feature and todays:
        b = todays[0]
        others = [r for r in todays[1:] if r.get("face") is not None]
        bigger = sum(1 for r in others if r["face"] >= (b.get("face") or 0) + 0.2)
        similar = [r for r in others if abs(r["face"] - (b.get("face") or 0)) < 0.2]
        worse_wind = sum(1 for r in similar if r.get("rel") in ("cross", "onshore", "blown") and b.get("rel") in ("glassy", "offshore"))
        if b["verdict"] == "SKIP":
            why = "Nothing clean and waist-high anywhere today. This is the least bad option."
        elif bigger == 0 and worse_wind > 0:
            why = ("Biggest waves on the coast today, and cleaner wind than the other spot of similar size." if worse_wind == 1 else
                   f"Biggest waves on the coast today, and cleaner wind than the {worse_wind} spots of similar size.")
        elif bigger == 0:
            why = "Biggest waves on the coast today with clean wind."
        elif worse_wind > 0:
            why = ("Not the biggest, but the cleanest wind: the other similar-sized spot has side or onshore wind." if worse_wind == 1 else
                   f"Not the biggest, but the cleanest wind: {worse_wind} similar-sized spots have side or onshore wind.")
        else:
            why = "Best mix of size, wind and tide on the coast today. Several spots are close."
        feature["why_best"] = why
    else:
        if feature: feature["why_best"] = ""

    # headline in Wendy's voice: short, straight
    top = feature
    if top and top["verdict"] == "GO":
        b = top
        headline = f"Best today: {b['short']}."
        verdict = (f"<strong>{b['size'].capitalize()}, {b['wind_plain']}</strong>, {b['window'].replace('–',' to ')}. "
                   f"{b['tide_plain'].capitalize()}. Water {b['water']:.0f}°." if b.get('water') is not None else
                   f"<strong>{b['size'].capitalize()}, {b['wind_plain']}</strong>, {b['window'].replace('–',' to ')}. {b['tide_plain'].capitalize()}.")
    elif top and top["verdict"] == "MAYBE":
        b = top
        headline = "Marginal today."
        verdict = (f"<strong>{b['spot']}</strong>: {b['size']}, {b['wind_plain']}, {b['window'].replace('–',' to ')}. "
                   f"{b['tide_plain'].capitalize()}. Rideable, not clean.")
    else:
        # why is nothing working
        small = all((r.get("face") or 0) < 1.0 for r in todays) if todays else True
        headline = "No good surf today."
        verdict = ("Too small everywhere, under waist-high. " if small else "There is size but the wind is onshore everywhere. ") + \
                  "Tomorrow is in the table below."
    if not (date.fromisoformat("2026-09-14") <= date.fromisoformat(today) <= date.fromisoformat("2026-10-04")):
        pass

    # tiles
    hs_all = [r["face"] if r.get("face") is not None else r["hs"] for r in grid if r.get("hs") is not None]
    waters = [r["water"] for r in grid if r["date"] == today and r.get("water") is not None]
    airs = [r["air"] for r in grid if r["date"] == today and r.get("air") is not None]
    gm = sorted([r for r in grid if r["verdict"] != "SKIP"], key=lambda r: (-(r.get("score") or 0), r["date"], r["n"]))
    tiles = []
    if gm:
        b = gm[0]
        tiles.append(["Best of the week", f"{daylabel(b['date'])} {short(b['spot'])}", f"{b.get('size','')} · {wind_txt(b)}"])
    if hs_all:
        tiles.append(["Face range", f"{min(hs_all):.1f}–{max(hs_all):.1f} m", "breaking height, 7 days"])
    if waters or airs:
        w = f"{sum(waters)/len(waters):.0f}°" if waters else "–"
        a = f"{max(airs):.0f}°" if airs else "–"
        tiles.append(["Water / air", f"{w} / {a}", "boardies or a 3/2" if waters and sum(waters)/len(waters) >= 20 else "3/2 wetsuit"])


    # every spot x day as a card, for the map panel
    cards = {f"{r['spot']}|{r['date']}": card(r) for r in grid}
    hourly = {}
    for r in grid:
        if r.get("hourly"):
            hourly[f"{r['spot']}|{r['date']}"] = r["hourly"]
    daylong = {d: dlong(d) for d in dates}
    weeklabel = datetime.fromisoformat(today+"T00:00").strftime("%-d %b %Y")
    best = {"spot": feature["spot"], "day": 0} if feature and feature["verdict"] != "SKIP" else None
    return {"days": days, "dates": dates, "daylong": daylong, "groups": groups, "grid": matrix,
            "best": best, "feature": feature, "five": five, "headline": headline, "verdict": verdict,
            "tiles": tiles, "sources": SOURCES, "weeklabel": weeklabel, "hourly": hourly, "cards": cards, "buoys": buoys or [],
            "trip": (flagged or {}).get("trip", ["2026-09-14", "2026-10-04"])}

MAP_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "surf_map.html")

def buoy_points(txt):
    """Live buoy readings (BUOYS block) joined with their positions from surf.py."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from surf import BUOYS as POS
    except Exception:
        return []
    b = re.search(r"<!--BUOYS_START-->(.*?)<!--BUOYS_END-->", txt, re.S)
    live = json.loads(b.group(1)) if b else {}
    out = []
    for key, pos in POS.items():
        r = live.get(key) or {}
        out.append({"key": key, "name": pos["name"], "lat": pos["lat"], "lon": pos["lon"],
                    "hs": r.get("hs"), "tp": r.get("tp"), "age_min": r.get("age_min")})
    return out

def render_map(data):
    """Map view: same DATA, Leaflet page. Reuses the list page's hourly chart/modal JS and CSS verbatim."""
    tpl = open(MAP_TEMPLATE, encoding="utf-8").read()
    # per-day cards carry only what changes by day; the static spot fields (cams, links, tide pref) live once in groups
    static = {"cam","cam_shows","cam_type","cam_status","cam_dedicated","cam_km","cam_alts","report","forecast","note","shom",
              "sector","short","spot","tide_label","tide_pref","date","day","section","why_best","swell","obs","tide","wind"}
    data = dict(data, cards={k: {kk: vv for kk, vv in v.items() if kk not in static} for k, v in data["cards"].items()})
    js_a = TEMPLATE.index("// hourly modal")
    js_b = TEMPLATE.index('$(".matrix").addEventListener', js_a)   # stop before the list page's own table listeners
    css_a, css_b = TEMPLATE.index("  .modal{"), TEMPLATE.index("  .reveal{")
    return (tpl.replace("/*DATA*/", "const DATA = " + json.dumps(data, ensure_ascii=False) + ";")
               .replace("/*SHARED_MODAL*/", TEMPLATE[js_a:js_b])
               .replace("/*MODAL_CSS*/", TEMPLATE[css_a:css_b]))

def main():
    src, dest = sys.argv[1], sys.argv[2]
    txt = open(src, encoding="utf-8").read()
    g = re.search(r"<!--GRID_START-->(.*?)<!--GRID_END-->", txt, re.S)
    s = re.search(r"<!--SPOTS_START-->(.*?)<!--SPOTS_END-->", txt, re.S)
    j = re.search(r"<!--JSON_START-->(.*?)<!--JSON_END-->", txt, re.S)
    if not g or not s:
        sys.stderr.write("no GRID/SPOTS block in "+src+"\n"); sys.exit(1)
    data = build_data(json.loads(g.group(1)), json.loads(s.group(1)), json.loads(j.group(1)) if j else None, buoy_points(txt))
    list_data = {k: v for k, v in data.items() if k not in ("cards", "buoys")}   # the list page does not need the per-day cards
    open(dest, "w", encoding="utf-8").write(TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(list_data, ensure_ascii=False) + ";"))
    print(f"wrote {dest} ({len(data['days'])} days, {sum(len(g['spots']) for g in data['groups'])} spots, {len(data['five'])} standouts)")
    map_dest = os.path.join(os.path.dirname(dest), "map.html")
    open(map_dest, "w", encoding="utf-8").write(render_map(data))
    print(f"wrote {map_dest} ({len(data['cards'])} cards, {len(data['buoys'])} buoys)")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wendy Surf — France trip</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --bg:#120c08; --bg2:#1c120b; --panel:#1f150d; --panel2:#261a10;
    --ink:#f7efe6; --soft:#c2ad97; --faint:#8a7460; --hair:#33261a; --hair2:#453322;
    --accent:#ff9f4a; --accent-dim:#c96f26;
    --go:#5bd39a; --go-bg:rgba(91,211,154,.14);
    --maybe:#f4c15a; --maybe-bg:rgba(244,193,90,.14);
    --skip:#8a7460; --skip-bg:rgba(138,116,96,.12);
    --sea:#4fb3c9;
    --disp:"IBM Plex Sans Condensed",system-ui,sans-serif;
    --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
    --maxw:1120px;
  }
  html{-webkit-text-size-adjust:100%}
  body{background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  .wrap{max-width:var(--maxw);margin:0 auto;padding:0 clamp(30px,7.5vw,56px)}
  ::selection{background:rgba(255,159,74,.3)}
  a{color:var(--accent)}

  .hero{position:relative;overflow:hidden;border-bottom:1px solid var(--hair)}
  .hero::before{content:"";position:absolute;inset:0;z-index:0;background:
      radial-gradient(120% 90% at 85% -10%, rgba(255,159,74,.18), transparent 55%),
      radial-gradient(90% 80% at 5% 10%, rgba(79,179,201,.12), transparent 60%),
      linear-gradient(180deg,#1d120a,var(--bg));}
  #swell{position:absolute;inset:0;width:100%;height:100%;display:block;z-index:1;opacity:.9}
  .hero-in{position:relative;z-index:2;padding-block:clamp(28px,5vw,44px) clamp(30px,5vw,44px)}
  .topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:26px}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.24em;text-transform:uppercase;color:var(--accent);
    display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin:0}
  .eyebrow .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex:none;
    box-shadow:0 0 0 4px rgba(255,159,74,.18),0 0 14px 2px rgba(255,159,74,.6)}
  .eyebrow .sep{color:var(--faint)}
  .switch{display:inline-flex;border:1px solid var(--hair2);border-radius:999px;padding:3px;background:rgba(0,0,0,.25);
    font-family:var(--mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
  .switch a{color:var(--soft);text-decoration:none;padding:6px 14px;border-radius:999px;line-height:1;display:flex;align-items:center;gap:7px}
  .switch a.on{background:var(--accent);color:#1a0f06;font-weight:600}
  .switch a:not(.on):hover{color:var(--ink)}
  h1{font-family:var(--disp);font-size:clamp(38px,7.5vw,76px);line-height:.98;margin:0 0 20px;font-weight:700;letter-spacing:-.015em;text-wrap:balance;max-width:16ch;color:#fff}
  .verdict{font-size:clamp(15px,2.3vw,18px);color:var(--soft);max-width:62ch;margin:0}
  .verdict strong{color:var(--ink);font-weight:600}

  .herogrid{display:grid;grid-template-columns:1.15fr .85fr;gap:22px;margin-top:clamp(30px,4vw,44px);align-items:stretch}
  .feature{position:relative;border:1px solid var(--hair2);border-radius:18px;padding:26px 28px;
    background:linear-gradient(160deg,rgba(58,36,20,.85),rgba(30,18,10,.75));backdrop-filter:blur(6px);overflow:hidden}
  .flabel{font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--accent);display:flex;align-items:center;gap:10px;margin-bottom:16px}
  .pill{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.08em;padding:3px 9px;border-radius:20px}
  .pill.go{background:var(--go-bg);color:var(--go);box-shadow:inset 0 0 0 1px rgba(91,211,154,.3)}
  .pill.maybe{background:var(--maybe-bg);color:var(--maybe);box-shadow:inset 0 0 0 1px rgba(244,193,90,.3)}
  .pill.skip{background:var(--skip-bg);color:var(--soft);box-shadow:inset 0 0 0 1px var(--hair2)}
  .feat-main{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}
  .bigwave{font-family:var(--disp);font-weight:700;line-height:.9;letter-spacing:-.02em}
  .bigwave .n{font-size:clamp(52px,9vw,84px);color:#fff}
  .bigwave .u{font-family:var(--mono);font-size:13px;font-weight:500;color:var(--soft);letter-spacing:.04em;display:block;margin-top:6px}
  .gauge{flex:none}
  .feat-where{margin-top:18px}
  .feat-where .spot{font-family:var(--disp);font-size:23px;font-weight:600;color:var(--ink);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .feat-where .when{color:var(--soft);font-size:14px;margin-top:2px} .feat-where .when b{color:var(--ink);font-weight:600}
  .feat-row{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:18px;padding-top:16px;border-top:1px solid var(--hair);font-family:var(--mono);font-size:12.5px;color:var(--soft)}
  .feat-row b{color:var(--ink);font-weight:600}
  .links{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
  .links a{font-family:var(--mono);font-size:11.5px;letter-spacing:.04em;text-decoration:none;color:var(--ink);
    border:1px solid var(--hair2);border-radius:999px;padding:6px 12px;background:rgba(255,255,255,.03)}
  .links a:hover{border-color:var(--accent);color:var(--accent)}
  .links a.cam{border-color:rgba(255,159,74,.5)}
  .camline{font-size:12.5px;line-height:1.5;color:var(--soft);margin:12px 0 0}
  .camline b{color:var(--ink);font-weight:600}
  .camline a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(255,159,74,.4)}
  .feat-note{margin-top:14px;font-size:13px;color:var(--faint);line-height:1.5}
  .plain{font-size:clamp(17px,2.4vw,21px);color:var(--ink);margin:16px 0 0;line-height:1.45;max-width:34ch}
  .plain.small{font-size:15px;margin:6px 0 0}
  .whybest{font-size:14px;color:var(--soft);margin:8px 0 0;line-height:1.5;max-width:44ch}
  .pick .sec{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:6px}
  .facts{display:grid;grid-template-columns:repeat(2,1fr);gap:10px 18px;margin-top:18px;padding-top:16px;border-top:1px solid var(--hair)}
  .fact{display:flex;flex-direction:column;gap:2px}
  .fact .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
  .fact .v{font-family:var(--disp);font-size:18px;font-weight:600;color:var(--ink);line-height:1.2}
  .fact .s{font-family:var(--mono);font-size:11px;color:var(--soft)}
  .live{display:flex;align-items:flex-start;gap:9px;margin-top:14px;padding-top:12px;border-top:1px dashed var(--hair);font-family:var(--mono);font-size:12px;color:var(--soft)}
  .live .lt{flex:1;line-height:1.5}
  .live .ld{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:none;margin-top:5px;box-shadow:0 0 9px var(--accent);animation:pulse 2.4s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  a.shom{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--sea);text-decoration:none;border:1px solid rgba(79,179,201,.4);border-radius:8px;padding:1px 6px;margin-left:4px;vertical-align:1px;white-space:nowrap;display:inline-block;line-height:1.5}
  a.shom:hover{background:rgba(79,179,201,.12)}
  .compass{flex:none}

  .tiles{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-content:start}
  .tile{border:1px solid var(--hair);border-radius:14px;padding:16px 18px;background:var(--panel);display:flex;flex-direction:column;gap:6px;min-height:104px;justify-content:center}
  .tile .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
  .tile .v{font-family:var(--disp);font-size:22px;font-weight:600;color:var(--ink);line-height:1.05}
  .tile .s{font-family:var(--mono);font-size:11.5px;color:var(--soft)}

  section{padding-block:clamp(38px,6vw,60px)}
  .shead{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:6px}
  .shead h2{font-family:var(--disp);font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.01em}
  .shead .legend{font-family:var(--mono);font-size:11.5px;color:var(--faint);display:flex;align-items:center;gap:8px}
  .shead .swatch{display:inline-block;width:30px;height:6px;border-radius:3px;background:linear-gradient(90deg,rgba(255,159,74,.25),var(--accent))}
  .snote{font-size:13.5px;color:var(--soft);margin:0 0 26px;max-width:70ch}

  /* today's five */
  .five{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
  .pick{border:1px solid var(--hair);border-radius:16px;padding:18px 20px;background:var(--panel);position:relative;transition:transform .15s,border-color .15s}
  .pick:hover{transform:translateY(-2px);border-color:var(--hair2)}
  .pick .rank{position:absolute;top:14px;right:16px;font-family:var(--disp);font-size:34px;font-weight:700;color:var(--hair2);line-height:1}
  .pick .ph{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:6px}
  .pick .nm{font-family:var(--disp);font-size:19px;font-weight:600;color:var(--ink)}
  .pick .sz{font-family:var(--mono);font-size:12px;color:var(--accent);letter-spacing:.04em}
  .pick .row{font-family:var(--mono);font-size:12px;color:var(--soft);display:flex;flex-wrap:wrap;gap:4px 16px;margin-top:8px}
  .pick .row b{color:var(--ink);font-weight:600}
  .pick .why{font-size:13px;color:var(--soft);margin-top:10px;line-height:1.5}
  .pick .links{margin-top:12px}
  .empty{border:1px dashed var(--hair2);border-radius:16px;padding:22px;color:var(--soft);font-size:14px}

  /* matrix */
  .matrix{display:grid;grid-template-columns:220px repeat(var(--ndays,7),minmax(0,1fr));gap:6px}
  .mhead,.srow,.ghead,.cells{display:contents}
  .corner{border-bottom:1px solid var(--hair)}
  .dh{font-family:var(--mono);font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);font-weight:500;padding:2px 6px 12px;border-bottom:1px solid var(--hair)}
  .gname{grid-column:1/-1;font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--accent);padding:26px 0 8px}
  .sname{padding:12px 12px 12px 2px;border-bottom:1px solid var(--hair);align-self:stretch;display:flex;flex-direction:column;justify-content:center}
  .sname .nm{font-family:var(--disp);font-weight:600;font-size:15.5px;color:var(--ink);line-height:1.2}
  .sname .sub{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:3px}
  .sname .sub a{color:var(--faint);text-decoration:none} .sname .sub em{font-style:normal;color:var(--soft)} .sname .sub a:hover{color:var(--accent)}
  .cell{position:relative;border:1px solid var(--hair);border-radius:10px;padding:10px 10px 9px;display:flex;flex-direction:column;gap:6px;align-items:flex-start;
    background:rgba(255,255,255,.012);transition:transform .15s,border-color .15s}
  .cell:hover{transform:translateY(-2px);border-color:var(--hair2)}
  .dlabel{display:none}
  .cell .tag{font-family:var(--mono);font-size:9.5px;font-weight:600;letter-spacing:.07em;padding:2px 7px;border-radius:16px}
  .go .tag{background:var(--go-bg);color:var(--go)} .maybe .tag{background:var(--maybe-bg);color:var(--maybe)} .skip .tag{background:var(--skip-bg);color:var(--soft)}
  .cell .val{font-family:var(--disp);font-weight:600;font-size:21px;line-height:1;color:var(--ink)}
  .cell .val .kt{font-family:var(--mono);font-size:10.5px;font-weight:500;color:var(--faint);margin-left:2px}
  .cell .sz{font-family:var(--mono);font-size:10px;color:var(--faint);letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
  .skip .val{color:var(--soft)}
  .qbar{width:100%;height:4px;border-radius:3px;background:rgba(255,255,255,.06);overflow:hidden}
  .qbar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent-dim),var(--accent))}
  .cell.best{border-color:rgba(255,159,74,.55);box-shadow:0 0 0 1px rgba(255,159,74,.25),0 6px 26px -12px rgba(255,159,74,.6)}
  .cell.best::after{content:"TODAY'S CALL";position:absolute;top:-8px;right:8px;font-family:var(--mono);font-size:8.5px;letter-spacing:.12em;color:var(--accent);background:var(--bg);padding:1px 6px;border-radius:8px}
  .cell.clickable{cursor:pointer}
  .cell .exp{position:absolute;bottom:7px;right:8px;color:var(--faint);font-size:12px;line-height:1;opacity:.6}
  .cell.clickable:hover .exp{opacity:1;color:var(--accent)}

  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
  .card{border:1px solid var(--hair);border-radius:16px;padding:22px 22px 24px;background:var(--panel)}
  .card .ic{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;margin-bottom:14px;background:rgba(255,159,74,.12);color:var(--accent);font-size:17px}
  .card h3{font-family:var(--mono);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--soft);font-weight:600;margin:0 0 8px}
  .card p{font-size:14px;color:var(--ink);line-height:1.6}
  .card .big{font-family:var(--disp);font-weight:600}

  footer{border-top:1px solid var(--hair);padding:34px 0 clamp(44px,8vw,64px)}
  .srcgrid{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}
  .srcgrid .s{font-family:var(--mono);font-size:11.5px;color:var(--soft);border:1px solid var(--hair);border-radius:20px;padding:5px 12px;background:var(--panel)}
  .fmeta{font-size:12.5px;color:var(--faint);line-height:1.8}
  .fmeta a{color:var(--accent);text-decoration:none} .fmeta a:hover{text-decoration:underline}

  .modal{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;padding:clamp(16px,4vw,40px);background:rgba(8,4,2,.74);backdrop-filter:blur(5px)}
  .modal.open{display:flex}
  .sheet{position:relative;width:100%;max-width:640px;max-height:92vh;overflow:auto;background:linear-gradient(165deg,var(--panel2),var(--panel));border:1px solid var(--hair2);border-radius:20px;padding:clamp(20px,3.5vw,28px);
    box-shadow:0 30px 80px -30px rgba(0,0,0,.8);transform:translateY(10px);opacity:0;transition:transform .28s cubic-bezier(.2,.7,.2,1),opacity .22s}
  .modal.open .sheet{transform:none;opacity:1}
  .sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:6px}
  .sheet-head .sk{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
  .sheet-head h3{font-family:var(--disp);font-size:clamp(20px,3.6vw,26px);font-weight:600;margin:2px 0 0;color:#fff}
  .sheet-head .sd{font-family:var(--mono);font-size:12px;color:var(--soft);margin-top:3px}
  .xbtn{flex:none;width:34px;height:34px;border-radius:9px;border:1px solid var(--hair2);background:transparent;color:var(--soft);font-size:17px;cursor:pointer;line-height:1;display:grid;place-items:center}
  .xbtn:hover{background:rgba(255,255,255,.06);color:var(--ink)}
  .chartwrap{margin:18px 0 6px} .chartwrap svg{display:block;width:100%;height:auto}
  .chlegend{display:flex;flex-wrap:wrap;gap:8px 16px;font-family:var(--mono);font-size:11px;color:var(--soft);margin-top:4px}
  .chlegend i{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:5px}
  .sheet-note{font-size:13.5px;color:var(--soft);line-height:1.6;margin-top:14px;padding-top:14px;border-top:1px solid var(--hair)}
  .sheet-note b{color:var(--ink);font-weight:600}

  .reveal{opacity:0;transform:translateY(14px)}
  .reveal.in{opacity:1;transform:none;transition:opacity .6s ease,transform .6s cubic-bezier(.2,.7,.2,1)}
  a:focus-visible,button:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
  @media (prefers-reduced-motion:reduce){#swell{display:none}.reveal{opacity:1;transform:none}}
  @media (max-width:860px){.herogrid{grid-template-columns:1fr}}
  @media (max-width:760px){
    .matrix{display:block} .mhead{display:none}
    .gname{padding:22px 0 10px}
    .srow{display:block;border-bottom:1px solid var(--hair);padding:12px 0 12px}
    .sname{border:none;padding:0 0 8px}
    .cells{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
    .cell{border:none;border-radius:8px;padding:6px 2px 6px;gap:3px;align-items:center;text-align:center;background:var(--skip-bg)}
    .cell.go{background:var(--go-bg)} .cell.maybe{background:var(--maybe-bg)}
    .cell:hover{transform:none}
    .cell .tag{display:none} .cell .sz{display:none} .qbar{display:none} .cell .exp{display:none}
    .cell .val{font-size:15px} .cell .val .kt{display:none}
    .go .val{color:var(--go)} .maybe .val{color:var(--maybe)} .skip .val{color:var(--soft)}
    .cell.best{box-shadow:inset 0 0 0 1px var(--accent)} .cell.best::after{display:none}
    .dlabel{display:block;font-family:var(--mono);font-size:9.5px;color:var(--faint);letter-spacing:0}
    .tiles{grid-template-columns:1fr 1fr}
    .modal{padding:18px} .sheet{max-height:88vh;border-radius:18px}
  }
  @media (max-width:430px){.tiles{grid-template-columns:1fr}}
</style>
</head>
<body>
<header class="hero">
  <canvas id="swell"></canvas>
  <div class="wrap hero-in">
    <div class="topbar">
      <p class="eyebrow"><span class="dot"></span> <span id="eyebrow">Wendy Surf</span></p>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <nav class="switch" aria-label="View"><a class="on" href="surf.html" aria-current="page">List</a><a href="map.html">Map</a></nav>
        <nav class="switch" aria-label="Mode"><a href="index.html">&#127788; Foil</a><a class="on" href="surf.html">&#127940; Surf</a></nav>
      </div>
    </div>
    <h1 id="h1"></h1>
    <p class="verdict" id="verdict"></p>
    <div class="herogrid">
      <article class="feature reveal" id="feature"></article>
      <div class="tiles reveal" id="tiles"></div>
    </div>
  </div>
</header>

<main>
<section class="wrap">
  <div class="shead"><h2>Best spot in each area today</h2></div>
  <p class="snote">North to south: Médoc, Cap Ferret and Arcachon, North Landes, South Landes, Basque coast.</p>
  <div class="five reveal" id="five"></div>
</section>

<section class="wrap">
  <div class="shead"><h2>7-day outlook</h2></div>
  <div class="matrix reveal" id="matrix"></div>
</section>

<section class="wrap">
  <div class="shead"><h2>How spots are scored</h2></div>
  <div class="cards">
    <div class="card reveal"><div class="ic">&#8767;</div><h3>Size</h3><p>Wave face at least <span class="big">1.0 m</span> (waist-high). Best between 1.4 and 2.4 m. Above 3.2 m the open beaches close out and the sheltered spots score higher. Today's heights are adjusted to the live buoys.</p></div>
    <div class="card reveal"><div class="ic">&#8776;</div><h3>Period</h3><p>Under <span class="big">6.5 s</span> is short, weak windswell and scores lower. 10 s or more is groundswell and scores higher.</p></div>
    <div class="card reveal"><div class="ic">&#10138;</div><h3>Wind</h3><p>Glassy or <span class="big">offshore (east)</span> is best. Onshore at 14 kt or more counts as unsurfable.</p></div>
    <div class="card reveal"><div class="ic">&#9788;</div><h3>Tide and daylight</h3><p>Daylight hours only. Each spot has a preferred tide (C&ocirc;te des Basques low, Gravi&egrave;re incoming, most beach breaks mid). Tide times come from a model and can be up to an hour off; the SHOM link has the official table.</p></div>
  </div>
</section>
</main>

<footer>
  <div class="wrap">
    <div class="srcgrid" id="sources"></div>
    <div class="fmeta" id="fmeta"></div>
  </div>
</footer>

<div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="sheet-h"><div class="sheet" id="sheet"></div></div>

<script>
/*DATA*/
const $ = s => document.querySelector(s);
const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const arrow = (deg, label, col) => (deg==null) ? "" :
  `<svg class="compass" width="26" height="26" viewBox="0 0 30 30" role="img" aria-label="${esc(label)}">
     <circle cx="15" cy="15" r="13" fill="none" stroke="var(--hair2)" stroke-width="1.5"/>
     <g transform="rotate(${deg} 15 15)"><path d="M15 4 L19 16 L15 13 L11 16 Z" fill="${col}"/></g></svg>`;
const camLabel = f => f.cam_dedicated ? "cam" : `nearest cam, ${Math.round(f.cam_km)} km`;
const camWarn = f => /stale|maintenance/i.test(f.cam_status||"") ? " (feed down at last check)" : "";
const linkrow = f => `<div class="links"><a class="cam" href="${esc(f.cam)}" target="_blank" rel="noopener" title="${esc(f.cam_shows)}">&#128247; ${camLabel(f)}</a><a href="${esc(f.report)}" target="_blank" rel="noopener">report</a><a href="${esc(f.forecast)}" target="_blank" rel="noopener">forecast</a></div>`;
const camline = f => f.cam_shows ? `<p class="camline"><b>${f.cam_dedicated?"Cam":"No cam here"}${camWarn(f)}:</b> ${esc(f.cam_shows.replace(/[.\s]*$/,"."))}${(f.cam_alts&&f.cam_alts.length)?` Also: ${f.cam_alts.map(a=>`<a href="${esc(a.url)}" target="_blank" rel="noopener" title="${esc(a.shows)}">${esc(altLabel(a.shows))}</a>`).join(", ")}.`:""}</p>` : "";
const altLabel = t => t.replace(/\s\d+(\.\d+)?\s*km.*$/,"").split(/[,;:(]/)[0].trim().slice(0,42);

$("#eyebrow").innerHTML = 'Wendy Surf <span class="sep">&middot;</span> Soulac &rarr; Biarritz <span class="sep">&middot;</span> ' + esc(DATA.weeklabel);
$("#h1").textContent = DATA.headline;
$("#verdict").innerHTML = DATA.verdict;

if (DATA.feature){
  const f = DATA.feature, r = 34, C = 2*Math.PI*r, q = Math.max(.05, (f.score||0)/10), off = C*(1-q);
  $("#feature").innerHTML =
    `<div class="flabel">${f.verdict==="SKIP"?"CLOSEST TODAY":"TODAY'S CALL"} <span class="pill ${f.verdict.toLowerCase()}">${esc(f.verdict)}</span></div>
     <div class="feat-where" style="margin-top:0">
       <div class="spot" style="font-size:clamp(26px,4vw,34px)">${esc(f.spot)}</div>
       <div class="when">${esc(f.day)} &middot; ${esc(f.sector)} &middot; best window <b>${esc(f.window)}</b></div>
     </div>
     <p class="plain">${esc(f.plain)}</p>
     ${f.why_best?`<p class="whybest">${esc(f.why_best)}</p>`:""}
     <div class="facts">
       <div class="fact"><span class="k">size</span><span class="v">${f.face!=null?esc(f.face.toFixed(1))+" m":"–"}</span><span class="s">${esc(f.size)} faces</span></div>
       <div class="fact"><span class="k">wind</span><span class="v">${esc(f.wind_plain)}</span><span class="s">${esc(f.wind_from)}</span></div>
       <div class="fact"><span class="k">tide</span><span class="v">${esc(f.tide_plain)}</span><span class="s">${esc(f.tide_label)} here &middot; <a class="shom" href="${esc(f.shom)}" target="_blank" rel="noopener">SHOM tide table</a></span></div>
       <div class="fact"><span class="k">water</span><span class="v">${f.water!=null?f.water.toFixed(0)+"°":"–"}</span><span class="s">air ${f.air!=null?f.air.toFixed(0)+"°":"–"}</span></div>
     </div>
     ${f.heads_up?`<div class="live"><span class="ld"></span><span class="lt">${esc(f.heads_up)}</span></div>`:""}
     ${camline(f)}
     ${linkrow(f)}`;
} else { $("#feature").style.display="none"; }

$("#tiles").innerHTML = DATA.tiles.map(t=>`<div class="tile"><span class="k">${esc(t[0])}</span><span class="v">${esc(t[1])}</span><span class="s">${esc(t[2]||"")}</span></div>`).join("");
$("#sources").innerHTML = DATA.sources.map(s=>`<span class="s">${esc(s)}</span>`).join("");
$("#fmeta").innerHTML = `Wave, tide and wind data from <a href="https://open-meteo.com">Open-Meteo</a> (CC BY 4.0). Updated 05:00 and 12:00 during the trip (${esc(DATA.trip[0])} to ${esc(DATA.trip[1])}). Cam links were checked one by one on 6 Sep 2026 (what each camera shows, whether it was live). Report and forecast links come from your spreadsheet. Foil side: <a href="index.html">Wendy Foils</a>.`;

// today's five
$("#five").innerHTML = DATA.five.length ? DATA.five.map((f,i)=>
  `<article class="pick">
     <div class="sec">${esc(f.section||"")}</div>
     <div class="ph"><span class="nm">${esc(f.spot)}</span><span class="pill ${f.verdict.toLowerCase()}">${esc(f.verdict)}</span></div>
     <p class="plain small">${esc(f.plain)}</p>
     <div class="row"><span>${esc(f.tide_plain)} <a class="shom" href="${esc(f.shom)}" target="_blank" rel="noopener">tide table</a></span></div>
     <div class="row"><span>${esc(f.tide_label)} at this break</span></div>
     ${camline(f)}
     ${linkrow(f)}</article>`).join("")
  : `<div class="empty">No data today.</div>`;

// matrix
$(".matrix").style.setProperty("--ndays", DATA.days.length);
let html = `<div class="mhead"><div class="corner"></div>`+DATA.days.map(d=>`<div class="dh">${esc(d)}</div>`).join("")+`</div>`;
DATA.groups.forEach(g=>{
  html += `<div class="ghead"><div class="gname">${esc(g.dept)}</div></div>`;
  html += g.spots.map(s=>{
    const cells = (DATA.grid[s.name]||[]).map((c,di)=>{
      const [call,val,q,title,size] = c;
      const isBest = (DATA.best && DATA.best.spot===s.name && di===DATA.best.day) ? " best" : "";
      const pct = Math.max(q>0?8:0, Math.round(q*100));
      const key = s.name+"|"+(DATA.dates[di]||"");
      const clk = (DATA.hourly && DATA.hourly[key]) ? " clickable" : "";
      const attrs = clk ? ` data-key="${esc(key)}" tabindex="0" role="button" aria-label="${esc(s.name)} ${esc(DATA.days[di]||"")} hourly detail"` : "";
      return `<div class="cell ${call}${isBest}${clk}"${attrs} title="${esc(title||"")}">`+
        `<span class="dlabel">${esc(DATA.days[di]||"")}</span><span class="tag">${call.toUpperCase()}</span>`+
        `<span class="val">${esc(val)}<span class="kt">m</span></span><span class="sz">${esc(size)}</span>`+
        `<div class="qbar"><i style="width:${pct}%"></i></div>`+(clk?`<span class="exp" aria-hidden="true">&#8942;</span>`:"")+`</div>`;
    }).join("");
    return `<div class="srow"><div class="sname"><span class="nm">${esc(s.name)}</span><span class="sub">${esc(s.sub)} &middot; <a href="${esc(s.cam)}" target="_blank" rel="noopener" title="${esc(s.cam_shows)}">${camLabel(s)}</a> &middot; <a href="${esc(s.forecast)}" target="_blank" rel="noopener">forecast</a> &middot; <a href="${esc(s.shom)}" target="_blank" rel="noopener">tide table</a> &middot; <em>${esc(s.tide_label)}</em></span></div><div class="cells">${cells}</div></div>`;
  }).join("");
});
$(".matrix").innerHTML = html;

// hourly modal: wave bars + tide curve + wind arrows
const modal = $("#modal"), sheet = $("#sheet");
function chart(hrs){
  const W=680,H=320,L=36,R=40,T=16,Bt=56, pw=W-L-R, ph=H-T-Bt, n=hrs.length||1, bw=pw/n, barw=Math.min(18,bw*0.6);
  const HV=h=>(h.face!=null?h.face:h.hs);
  const maxHs=Math.max(1.5, ...hrs.map(h=>HV(h)||0)); const maxY=Math.ceil((maxHs+0.3)*2)/2;
  const y=v=>T+ph*(1-v/maxY), base=T+ph;
  const tides=hrs.map(h=>h.tide).filter(v=>v!=null); const tmin=Math.min(...tides,0), tmax=Math.max(...tides,0.1);
  const ty=v=>T+ph*(1-(v-tmin)/((tmax-tmin)||1));
  const p=[];
  // daylight band
  const dayIdx=hrs.map((h,i)=>h.day?i:-1).filter(i=>i>=0);
  if(dayIdx.length){ const x0=L+dayIdx[0]*bw, x1=L+(dayIdx[dayIdx.length-1]+1)*bw; p.push(`<rect x="${x0.toFixed(1)}" y="${T}" width="${(x1-x0).toFixed(1)}" height="${ph}" fill="var(--accent)" opacity="0.06"/>`); }
  // rideable band: 1.0-3.2 m faces
  p.push(`<rect x="${L}" y="${y(Math.min(maxY,3.2)).toFixed(1)}" width="${pw}" height="${(y(1.0)-y(Math.min(maxY,3.2))).toFixed(1)}" fill="var(--go)" opacity="0.06"/>`);
  for(let v=0.5; v<maxY; v+=0.5){ p.push(`<line x1="${L}" x2="${W-R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--hair)" stroke-width="1"/>`);
    p.push(`<text x="${L-6}" y="${(y(v)+3).toFixed(1)}" text-anchor="end" font-family="var(--mono)" font-size="10" fill="var(--faint)">${v.toFixed(1)}</text>`); }
  hrs.forEach((h,i)=>{
    const cx=L+i*bw+bw/2;
    if(HV(h)!=null){
      const col = h.rel==="blown" ? "var(--skip)" : (h.sc>=5.5?"var(--go)":(h.sc>=3.5?"var(--maybe)":"var(--faint)"));
      p.push(`<rect x="${(cx-barw/2).toFixed(1)}" y="${y(HV(h)).toFixed(1)}" width="${barw.toFixed(1)}" height="${Math.max(0,base-y(HV(h))).toFixed(1)}" rx="2" fill="${col}" opacity="${h.day?0.92:0.35}"/>`);
    }
    if(i%3===0){
      p.push(`<text x="${cx.toFixed(1)}" y="${(base+16).toFixed(1)}" text-anchor="middle" font-family="var(--mono)" font-size="10" fill="var(--faint)">${h.h}h</text>`);
      if(h.wdeg!=null) p.push(`<g transform="translate(${cx.toFixed(1)},${(base+33).toFixed(1)}) rotate(${h.wdeg})"><path d="M0 -5 L3 4 L0 2 L-3 4 Z" fill="${h.rel==='offshore'||h.rel==='glassy'?'var(--go)':(h.rel==='onshore'||h.rel==='blown'?'var(--skip)':'var(--soft)')}"/></g>`);
      if(h.kt!=null) p.push(`<text x="${cx.toFixed(1)}" y="${(base+50).toFixed(1)}" text-anchor="middle" font-family="var(--mono)" font-size="9" fill="var(--soft)">${Math.round(h.kt)}</text>`);
    }
  });
  // tide line
  const pts=hrs.map((h,i)=>h.tide==null?null:`${(L+i*bw+bw/2).toFixed(1)},${ty(h.tide).toFixed(1)}`).filter(Boolean);
  if(pts.length>1) p.push(`<polyline points="${pts.join(" ")}" fill="none" stroke="var(--sea)" stroke-width="2" opacity="0.9"/>`);
  p.push(`<text x="${W-R+6}" y="${(ty(tmax)+4).toFixed(1)}" font-family="var(--mono)" font-size="9" fill="var(--sea)">high</text>`);
  p.push(`<text x="${W-R+6}" y="${(ty(tmin)+4).toFixed(1)}" font-family="var(--mono)" font-size="9" fill="var(--sea)">low</text>`);
  p.push(`<line x1="${L}" x2="${W-R}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}" stroke="var(--hair2)" stroke-width="1"/>`);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="hourly face height, tide and wind">${p.join("")}</svg>`;
}
function buildSheet(key){
  const hrs=DATA.hourly[key]; if(!hrs) return;
  const [spot,date]=key.split("|");
  const di=DATA.dates.indexOf(date), cell=(DATA.grid[spot]||[])[di]||[];
  const call=(cell[0]||"skip"), title=cell[3]||"";
  sheet.innerHTML =
    `<div class="sheet-head"><div><div class="sk">Hourly &middot; face height m, tide, wind kt</div><h3 id="sheet-h">${esc(spot)}</h3>
       <div class="sd">${esc(DATA.daylong[date]||date)} <span class="pill ${call}">${call.toUpperCase()}</span></div></div>
     <button class="xbtn" id="xbtn" aria-label="Close">&#10005;</button></div>
     <div class="chartwrap">${chart(hrs)}</div>
     <div class="chlegend"><span><i style="background:var(--go)"></i>good</span><span><i style="background:var(--maybe)"></i>average</span><span><i style="background:var(--faint)"></i>small or messy</span><span><i style="background:var(--sea)"></i>tide</span><span>arrows show wind direction, green = offshore</span></div>
     ${title?`<div class="sheet-note">${esc(title)}</div>`:""}`;
  $("#xbtn").onclick=closeModal;
}
function openModal(key){ buildSheet(key); modal.classList.add("open"); document.body.style.overflow="hidden"; const x=$("#xbtn"); if(x) x.focus(); }
function closeModal(){ modal.classList.remove("open"); document.body.style.overflow=""; }
modal.addEventListener("click", e=>{ if(e.target===modal) closeModal(); });
document.addEventListener("keydown", e=>{ if(e.key==="Escape" && modal.classList.contains("open")) closeModal(); });
$(".matrix").addEventListener("click", e=>{ if(e.target.closest("a")) return; const c=e.target.closest(".cell.clickable"); if(c) openModal(c.dataset.key); });
$(".matrix").addEventListener("keydown", e=>{ if(e.key==="Enter"||e.key===" "){ const c=e.target.closest(".cell.clickable"); if(c){ e.preventDefault(); openModal(c.dataset.key);} } });

const io = new IntersectionObserver((es)=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("in");io.unobserve(e.target);}}),{threshold:.08});
document.querySelectorAll(".reveal").forEach((el,i)=>{el.style.transitionDelay=(i%4*60)+"ms";io.observe(el);});

// ambient swell lines
(function(){
  const c=$("#swell"), x=c.getContext("2d"); let W,H,t=0,raf;
  function size(){ W=c.width=c.offsetWidth*devicePixelRatio; H=c.height=c.offsetHeight*devicePixelRatio; }
  function step(){
    x.clearRect(0,0,W,H); t+=0.006;
    for(let k=0;k<7;k++){
      const yb=H*(0.35+k*0.1), amp=(10+k*4)*devicePixelRatio;
      x.beginPath();
      for(let px=0;px<=W;px+=6*devicePixelRatio){ const yy=yb+Math.sin(px/(160*devicePixelRatio)+t*(1+k*0.15)+k)*amp; if(px===0) x.moveTo(px,yy); else x.lineTo(px,yy); }
      x.strokeStyle=k%2?"rgba(255,159,74,0.10)":"rgba(79,179,201,0.12)"; x.lineWidth=1.1*devicePixelRatio; x.stroke();
    }
    raf=requestAnimationFrame(step);
  }
  function start(){ size(); cancelAnimationFrame(raf); step(); }
  addEventListener("resize",start); start();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
