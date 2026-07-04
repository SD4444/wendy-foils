#!/usr/bin/env python3
"""Regenerate docs/index.html from a wendy.py output file's GRID block.

Usage: python3 gen_dashboard.py data/weekly.out.txt docs/index.html
The GitHub Action runs this after each fetch so the hosted page is always current.
Edit the design in TEMPLATE below; never hand-edit docs/index.html (it is generated).
"""
import sys, json, re
from datetime import datetime

WIND_MIN, WIND_MAX, GUST_MAX = 13, 22, 25
SPOT_SUB = {
    "Muiderberg": ("IJmeer", "inland flat", "~20 min"),
    "Almere Muiderzand": ("IJmeer", "inland flat", "~25 min"),
    "Schellinkhout": ("Markermeer", "inland flat", "~45 min"),
    "Loosdrecht": ("Loosdrechtse Plassen", "inland flat", "~30 min"),
    "Wijk aan Zee": ("North Sea", "coast / waves", "~40 min"),
}
BAND = {"lo": WIND_MIN, "hi": WIND_MAX, "ideal_lo": 15, "ideal_hi": 20, "gustmax": GUST_MAX}
SOURCES = [
    "KNMI HARMONIE-AROME · NL 2 km anchor",
    "ICON-D2 · 2 km near-term check",
    "ECMWF IFS · GFS · ICON-EU spread",
    "ICON-D2 / ECMWF ensemble · probability",
    "EWAM · waves + sea temp",
]

def daylabel(date):
    return datetime.fromisoformat(date+"T00:00").strftime("%a %-d")

def dlong(date):
    return datetime.fromisoformat(date+"T00:00").strftime("%A %-d %b")

def cell_val(r):
    if r["type"] == "coast":
        return f"{r['wave']:.1f}m" if r.get("wave") is not None else "flat"
    if r.get("avg") is not None:
        return f"{r['avg']:.0f}"
    if r["verdict"] == "MAYBE" and r.get("hotpeak"):
        return f"{r['hotpeak']:.0f}"
    if r["verdict"] == "SKIP" and r.get("gust",0) > GUST_MAX and r.get("peak",0) >= WIND_MIN-1:
        return f"{r['peak']:.0f}g{r['gust']:.0f}"
    return f"{r.get('peak',0):.0f}"

def cell_q(r):
    if r["type"] == "coast": return 0.06
    v = r["verdict"]
    if v == "GO":    return round(min(1.0, 0.82 + r.get("score",3)/40), 2)
    if v == "MAYBE": return 0.56
    if r.get("gust",0) > GUST_MAX and r.get("peak",0) >= WIND_MIN-1: return 0.2
    hp = r.get("hotpeak", r.get("peak",0))
    return round(max(0.05, min(0.4, (hp-6)/(15-6)*0.4)), 2)

def wind_str(r):
    if r["type"] == "coast":
        return (f"{r['wave']:.1f} m" if r.get("wave") is not None else "flat"), "sea"
    if r.get("avg") is not None: return f"{r['avg']:.0f}", "kt avg"
    if r["verdict"] == "MAYBE" and r.get("hotpeak") and r.get("peak") and r["hotpeak"] > r["peak"]:
        return f"{r['peak']:.0f}–{r['hotpeak']:.0f}", "kt (models split)"
    return f"{r.get('hotpeak', r.get('peak',0)):.0f}", "kt peak"

def build_data(grid):
    dates = sorted({r["date"] for r in grid})
    days = [daylabel(d) for d in dates]
    spot_order = []
    for r in grid:
        if r["spot"] not in spot_order: spot_order.append(r["spot"])
    spots = [{"name": s, "sub": " · ".join(SPOT_SUB.get(s, ("",))[:2]).strip(" ·"),
              "drive": SPOT_SUB.get(s, ("","",""))[2]} for s in spot_order]
    by = {(r["spot"], r["date"]): r for r in grid}
    matrix = {}
    for s in spot_order:
        row = []
        for d in dates:
            r = by.get((s, d))
            if r is None: row.append(["skip", "–", 0, ""]); continue
            title = (r.get("why") or "").split("|")[0].strip()
            row.append([r["verdict"].lower(), cell_val(r), cell_q(r), title])
        matrix[s] = row

    gm = [r for r in grid if r["verdict"] in ("GO", "MAYBE")]
    gm.sort(key=lambda r: (-r.get("score",0), r["date"]))
    best = None
    feature = None
    pool = gm if gm else sorted([r for r in grid if r["type"] != "coast"],
                                key=lambda r: (-(r.get("hotpeak") or 0), r["date"]))
    if pool:
        b = pool[0]
        best = {"spot": b["spot"], "day": dates.index(b["date"])}
        w, wsub = wind_str(b)
        obs = b.get("obs") or None
        deg = b.get("deg")
        if deg is None and obs: deg = obs.get("deg")
        feature = {
            "label": {"GO": "BEST DAY", "MAYBE": "ONE TO WATCH"}.get(b["verdict"], "CLOSEST THIS WEEK"),
            "verdict": b["verdict"], "q": cell_q(b),
            "day": dlong(b["date"]), "spot": b["spot"],
            "sub": " · ".join(SPOT_SUB.get(b["spot"], ("",))[:2]).strip(" ·"),
            "wind": w, "windsub": wsub,
            "dir": b.get("dir") or (obs.get("dir") if obs else None) or "–",
            "deg": deg,
            "window": (f"{b['win'][0]:02d}:00–{b['win'][1]:02d}:00" if b.get("win") else "your hours"),
            "gust": (f"{b['gust']:.0f} kt" if b.get("gust") else "–"),
            "air": (f"{b['air']:.0f}°" if b.get("air") is not None else "–"),
            "water": (f"{b['water']:.0f}°" if b.get("water") is not None else "–"),
            "wetsuit": b.get("wetsuit") or "",
            "prob": (round(b["prob"]*100) if b.get("prob") is not None else None),
            "obs": ({"kt": f"{obs['kt']:.0f}", "gust": f"{obs['gust']:.0f}", "dir": obs.get("dir") or "–",
                     "station": obs["station"], "km": obs["km"]} if obs else None),
            "note": (b.get("why") or "").split("|")[0].strip(),
        }

    gos = [r for r in gm if r["verdict"] == "GO"]
    maybes = [r for r in gm if r["verdict"] == "MAYBE"]
    def dayname(d): return datetime.fromisoformat(d+"T00:00").strftime("%A")
    if gos:
        b = gos[0]
        headline = f"{dayname(b['date'])}'s on."
        verdict = (f"<strong>{dlong(b['date'])} at {b['spot']}</strong> is the pick — "
                   f"{(b.get('why') or '').split('|')[0].strip()}. The rest of the week's ranked below.")
    elif maybes:
        days_txt = ", ".join(daylabel(d) for d in sorted({r["date"] for r in maybes}))
        b = maybes[0]
        headline = f"{dayname(b['date'])}'s playing hard to get."
        verdict = (f"The models split on {days_txt}: my high-res near-term read is light, the global models "
                   f"run foilable over open water. <strong>{b['spot']}</strong> is the one to watch — "
                   f"commit only if the stronger model firms up. I'll flag it the second it does. "
                   f"Coast stays parked until you're foil-stable.")
    else:
        headline = "Flat and lazy out there."
        verdict = ("No steady wind in your hours all week, and every model agrees. Rest those arms — "
                   "I'm still watching, and I don't miss a good day.")

    airs = [r["air"] for r in grid if r.get("air") is not None]
    waters = [r["water"] for r in grid if r.get("water") is not None]
    conf = "Split (global models hotter)" if (maybes and not gos) else ("Firm" if gos else "Low — all models light")
    peaks = [r.get("hotpeak") for r in grid if r["type"] != "coast" and r.get("hotpeak")]
    tiles = []
    if feature:
        tiles.append(["Best window", f"{feature['day'].split()[0]} {feature['spot'].split()[0]}", feature["window"]])
    if peaks:
        tiles.append(["Wind range", f"{min(peaks):.0f}–{max(peaks):.0f}", "kt across the week"])
    if airs and waters:
        wt = max(set(waters), key=waters.count)
        tiles.append(["Air / water", f"{min(airs):.0f}–{max(airs):.0f}° / {wt:.0f}°", "°C"])
    tiles.append(["Confidence", conf, "model agreement"])

    # hourly breakdown for the near days, keyed "spot|date" (only present day-of to +2)
    hourly = {}
    for r in grid:
        if r.get("hourly"):
            hourly[f"{r['spot']}|{r['date']}"] = r["hourly"]
    daylong = {d: dlong(d) for d in dates}

    weeklabel = datetime.fromisoformat(dates[0]+"T00:00").strftime("Week of %-d %b %Y")
    return {"days": days, "dates": dates, "daylong": daylong, "spots": spots, "grid": matrix,
            "best": best, "feature": feature, "headline": headline, "verdict": verdict,
            "tiles": tiles, "sources": SOURCES, "weeklabel": weeklabel,
            "hourly": hourly, "band": BAND}

def main():
    src, dest = sys.argv[1], sys.argv[2]
    txt = open(src, encoding="utf-8").read()
    m = re.search(r"<!--GRID_START-->(.*?)<!--GRID_END-->", txt, re.S)
    if not m:
        sys.stderr.write("no GRID block in "+src+"\n"); sys.exit(1)
    data = build_data(json.loads(m.group(1)))
    html = TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(data) + ";")
    open(dest, "w", encoding="utf-8").write(html)
    print(f"wrote {dest} ({len(data['days'])} days, {len(data['spots'])} spots)")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wendy Foils — Wind outlook</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --bg:#050d12; --bg2:#081820; --panel:#0c1c24; --panel2:#0f232c;
    --ink:#eef6f7; --soft:#93b0b7; --faint:#5f7a82; --hair:#183038; --hair2:#1f3b45;
    --accent:#39d7df; --accent-dim:#1c9aa2;
    --go:#3fd29a; --go-bg:rgba(63,210,154,.13);
    --maybe:#f4b73f; --maybe-bg:rgba(244,183,63,.13);
    --skip:#6f8990; --skip-bg:rgba(111,137,144,.10);
    --disp:"IBM Plex Sans Condensed",system-ui,sans-serif;
    --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
    --maxw:1120px;
  }
  html{-webkit-text-size-adjust:100%}
  body{background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6;
    -webkit-font-smoothing:antialiased;overflow-x:hidden;letter-spacing:.002em}
  .wrap{max-width:var(--maxw);margin:0 auto;padding:0 clamp(30px,7.5vw,56px)}
  .mono{font-family:var(--mono)}
  ::selection{background:rgba(57,215,223,.28)}

  /* hero */
  .hero{position:relative;overflow:hidden;border-bottom:1px solid var(--hair)}
  .hero::before{content:"";position:absolute;inset:0;z-index:0;
    background:
      radial-gradient(120% 90% at 82% -10%, rgba(57,215,223,.16), transparent 55%),
      radial-gradient(90% 80% at 10% 0%, rgba(28,154,162,.12), transparent 60%),
      linear-gradient(180deg,#071820,var(--bg));}
  #wind{position:absolute;inset:0;width:100%;height:100%;display:block;z-index:1;opacity:.9}
  .hero-in{position:relative;z-index:2;padding-block:clamp(40px,7vw,68px) clamp(30px,5vw,44px)}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.24em;text-transform:uppercase;
    color:var(--accent);margin:0 0 22px;display:flex;align-items:center;gap:11px;flex-wrap:wrap}
  .eyebrow .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex:none;
    box-shadow:0 0 0 4px rgba(57,215,223,.18),0 0 14px 2px rgba(57,215,223,.6)}
  .eyebrow .sep{color:var(--faint)}
  h1{font-family:var(--disp);font-size:clamp(38px,7.5vw,76px);line-height:.98;margin:0 0 20px;
    font-weight:700;letter-spacing:-.015em;text-wrap:balance;max-width:16ch;color:#fff}
  .verdict{font-size:clamp(15px,2.3vw,18px);color:var(--soft);max-width:60ch;margin:0}
  .verdict strong{color:var(--ink);font-weight:600}

  /* hero grid: feature card + tiles */
  .herogrid{display:grid;grid-template-columns:1.15fr .85fr;gap:22px;
    margin-top:clamp(30px,4vw,44px);align-items:stretch}
  .feature{position:relative;border:1px solid var(--hair2);border-radius:18px;padding:26px 28px;
    background:linear-gradient(160deg,rgba(18,42,50,.9),rgba(10,26,32,.75));
    backdrop-filter:blur(6px);overflow:hidden}
  .feature .flabel{font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;
    color:var(--accent);display:flex;align-items:center;gap:10px;margin-bottom:16px}
  .pill{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.08em;
    padding:3px 9px;border-radius:20px}
  .pill.go{background:var(--go-bg);color:var(--go);box-shadow:inset 0 0 0 1px rgba(63,210,154,.3)}
  .pill.maybe{background:var(--maybe-bg);color:var(--maybe);box-shadow:inset 0 0 0 1px rgba(244,183,63,.3)}
  .pill.skip{background:var(--skip-bg);color:var(--soft);box-shadow:inset 0 0 0 1px var(--hair2)}
  .feat-main{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}
  .bigwind{font-family:var(--disp);font-weight:700;line-height:.9;letter-spacing:-.02em}
  .bigwind .n{font-size:clamp(52px,9vw,84px);color:#fff}
  .bigwind .u{font-family:var(--mono);font-size:13px;font-weight:500;color:var(--soft);
    letter-spacing:.04em;display:block;margin-top:6px}
  .gauge{flex:none}
  .feat-where{margin-top:18px}
  .feat-where .spot{font-family:var(--disp);font-size:23px;font-weight:600;color:var(--ink)}
  .feat-where .when{color:var(--soft);font-size:14px;margin-top:2px}
  .feat-row{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:18px;padding-top:16px;
    border-top:1px solid var(--hair);font-family:var(--mono);font-size:12.5px;color:var(--soft)}
  .feat-row b{color:var(--ink);font-weight:600}
  .feat-note{margin-top:14px;font-size:13px;color:var(--faint);line-height:1.5}
  .ens{font-family:var(--mono);font-size:10px;font-weight:600;color:var(--accent);
    background:rgba(57,215,223,.1);padding:2px 8px;border-radius:12px;letter-spacing:.03em}
  .feat-where .spot{display:flex;align-items:center;gap:10px}
  .compass{flex:none}
  .live{display:flex;align-items:flex-start;gap:9px;margin-top:15px;padding-top:14px;
    border-top:1px dashed var(--hair);font-family:var(--mono);font-size:12px;color:var(--soft)}
  .live .lt{flex:1;line-height:1.5}
  .live .ld{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:none;margin-top:5px;
    box-shadow:0 0 9px var(--accent);animation:pulse 2.4s ease-in-out infinite}
  .live b{color:var(--ink);font-weight:600}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

  .tiles{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-content:start}
  .tile{border:1px solid var(--hair);border-radius:14px;padding:16px 18px;background:var(--panel);
    display:flex;flex-direction:column;gap:6px;min-height:104px;justify-content:center}
  .tile .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
  .tile .v{font-family:var(--disp);font-size:23px;font-weight:600;color:var(--ink);line-height:1.05}
  .tile .s{font-family:var(--mono);font-size:11.5px;color:var(--soft)}

  /* sections */
  section{padding-block:clamp(38px,6vw,60px)}
  .shead{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:6px}
  .shead h2{font-family:var(--disp);font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.01em}
  .shead .legend{font-family:var(--mono);font-size:11.5px;color:var(--faint);display:flex;align-items:center;gap:8px}
  .shead .swatch{display:inline-block;width:30px;height:6px;border-radius:3px;
    background:linear-gradient(90deg,rgba(57,215,223,.25),var(--accent))}
  .snote{font-size:13.5px;color:var(--soft);margin:0 0 26px;max-width:70ch}

  /* outlook matrix */
  .matrix{display:grid;grid-template-columns:200px repeat(var(--ndays,7),minmax(0,1fr));gap:8px}
  .mhead,.srow{display:contents}
  .corner{border-bottom:1px solid var(--hair)}
  .dh{font-family:var(--mono);font-size:11px;letter-spacing:.05em;text-transform:uppercase;
    color:var(--faint);font-weight:500;padding:2px 6px 14px;border-bottom:1px solid var(--hair)}
  .sname{padding:18px 14px 18px 2px;border-bottom:1px solid var(--hair);align-self:stretch;
    display:flex;flex-direction:column;justify-content:center}
  .sname .nm{font-family:var(--disp);font-weight:600;font-size:17px;color:var(--ink)}
  .sname .sub{font-family:var(--mono);font-size:11px;color:var(--faint);margin-top:3px;letter-spacing:.01em}
  .cell{position:relative;border:1px solid var(--hair);border-radius:12px;padding:14px 12px;
    display:flex;flex-direction:column;gap:10px;align-items:flex-start;
    background:rgba(255,255,255,.012);transition:transform .15s ease,border-color .15s ease}
  .cell:hover{transform:translateY(-2px);border-color:var(--hair2)}
  .dlabel{display:none}
  .cell .tag{font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:.07em;
    padding:3px 8px;border-radius:16px}
  .go .tag{background:var(--go-bg);color:var(--go)}
  .maybe .tag{background:var(--maybe-bg);color:var(--maybe)}
  .skip .tag{background:var(--skip-bg);color:var(--soft)}
  .cell .val{font-family:var(--disp);font-weight:600;font-size:24px;line-height:1;color:var(--ink)}
  .cell .val .kt{font-family:var(--mono);font-size:11px;font-weight:500;color:var(--faint);margin-left:3px}
  .go .val{color:#fff} .maybe .val{color:#fff} .skip .val{color:var(--soft)}
  .qbar{width:100%;height:4px;border-radius:3px;background:rgba(255,255,255,.06);overflow:hidden}
  .qbar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent-dim),var(--accent))}
  .cell.best{border-color:rgba(57,215,223,.5);box-shadow:0 0 0 1px rgba(57,215,223,.25),0 6px 26px -12px rgba(57,215,223,.6)}
  .cell.best::after{content:"WATCH";position:absolute;top:-8px;right:10px;font-family:var(--mono);
    font-size:9px;letter-spacing:.12em;color:var(--accent);background:var(--bg);padding:1px 6px;border-radius:8px}

  /* rules cards */
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
  .card{border:1px solid var(--hair);border-radius:16px;padding:22px 22px 24px;background:var(--panel);
    transition:transform .15s ease,border-color .15s ease}
  .card:hover{transform:translateY(-2px);border-color:var(--hair2)}
  .card .ic{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;margin-bottom:14px;
    background:rgba(57,215,223,.1);color:var(--accent);font-size:17px}
  .card h3{font-family:var(--mono);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;
    color:var(--soft);font-weight:600;margin:0 0 8px}
  .card p{font-size:14px;color:var(--ink);line-height:1.6}
  .card .big{font-family:var(--disp);font-weight:600}

  footer{border-top:1px solid var(--hair);padding:34px 0 clamp(44px,8vw,64px)}
  .srcgrid{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}
  .srcgrid .s{font-family:var(--mono);font-size:11.5px;color:var(--soft);border:1px solid var(--hair);
    border-radius:20px;padding:5px 12px;background:var(--panel)}
  .fmeta{font-size:12.5px;color:var(--faint);line-height:1.8}
  .fmeta a{color:var(--accent);text-decoration:none} .fmeta a:hover{text-decoration:underline}

  a:focus-visible,button:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
  /* clickable day cells */
  .cell.clickable{cursor:pointer}
  .cell .exp{position:absolute;bottom:9px;right:10px;color:var(--faint);font-size:12px;line-height:1;
    opacity:.6;transition:opacity .15s ease,color .15s ease}
  .cell.clickable:hover .exp{opacity:1;color:var(--accent)}
  /* day detail modal */
  .modal{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;
    padding:clamp(16px,4vw,40px);background:rgba(3,9,12,.72);backdrop-filter:blur(5px)}
  .modal.open{display:flex}
  .sheet{position:relative;width:100%;max-width:620px;max-height:92vh;overflow:auto;
    background:linear-gradient(165deg,var(--panel2),var(--panel));border:1px solid var(--hair2);
    border-radius:20px;padding:clamp(20px,3.5vw,28px);
    box-shadow:0 30px 80px -30px rgba(0,0,0,.8);transform:translateY(10px);opacity:0;
    transition:transform .28s cubic-bezier(.2,.7,.2,1),opacity .22s ease}
  .modal.open .sheet{transform:none;opacity:1}
  .sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:6px}
  .sheet-head .sk{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
  .sheet-head h3{font-family:var(--disp);font-size:clamp(20px,3.6vw,26px);font-weight:600;margin:2px 0 0;color:#fff}
  .sheet-head .sd{font-family:var(--mono);font-size:12px;color:var(--soft);margin-top:3px}
  .xbtn{flex:none;width:34px;height:34px;border-radius:9px;border:1px solid var(--hair2);
    background:transparent;color:var(--soft);font-size:17px;cursor:pointer;line-height:1;
    display:grid;place-items:center;transition:background .15s,color .15s}
  .xbtn:hover{background:rgba(255,255,255,.06);color:var(--ink)}
  .chartwrap{margin:18px 0 6px}
  .chartwrap svg{display:block;width:100%;height:auto}
  .chlegend{display:flex;flex-wrap:wrap;gap:8px 16px;font-family:var(--mono);font-size:11px;color:var(--soft);margin-top:4px}
  .chlegend i{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:5px}
  .sheet-note{font-size:13.5px;color:var(--soft);line-height:1.6;margin-top:14px;padding-top:14px;border-top:1px solid var(--hair)}
  .sheet-note b{color:var(--ink);font-weight:600}
  @media (max-width:560px){
    /* stay centered mid-screen on mobile, not a bottom sheet */
    .modal{padding:18px;align-items:center}
    .sheet{max-width:none;max-height:88vh;border-radius:18px}
  }
  .reveal{opacity:0;transform:translateY(14px)}
  .reveal.in{opacity:1;transform:none;transition:opacity .6s ease,transform .6s cubic-bezier(.2,.7,.2,1)}
  @media (prefers-reduced-motion:reduce){#wind{display:none}.reveal{opacity:1;transform:none}.live .ld{animation:none}}

  @media (max-width:860px){
    .herogrid{grid-template-columns:1fr}
  }
  @media (max-width:760px){
    .matrix{display:block}
    .mhead{display:none}
    .srow{display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:9px;
      border:1px solid var(--hair);border-radius:16px;padding:16px;margin-bottom:14px;background:var(--panel)}
    .sname{grid-column:1/-1;border-bottom:1px solid var(--hair);padding:0 0 12px;margin-bottom:4px}
    .cell{border:none;background:none;padding:2px 0;gap:7px}
    .cell:hover{transform:none}
    .cell.best{box-shadow:none;border:none} .cell.best::after{display:none}
    .dlabel{display:block;font-family:var(--mono);font-size:10.5px;color:var(--faint)}
    .tiles{grid-template-columns:1fr 1fr}
  }
  @media (max-width:430px){ .tiles{grid-template-columns:1fr} }
</style>
</head>
<body>
<header class="hero">
  <canvas id="wind"></canvas>
  <div class="wrap hero-in">
    <p class="eyebrow"><span class="dot"></span> <span id="eyebrow">Wendy Foils</span></p>
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
  <div class="shead">
    <h2>7-day outlook</h2>
    <span class="legend"><span class="swatch"></span> wind quality &middot; fuller = closer to foilable</span>
  </div>
  <p class="snote">Wind shown is the strongest credible model in your go-hours, so a day the global models like still surfaces even when the high-res model reads light. Calm-water spots first; the coast stays parked until you're foil-stable.</p>
  <div class="matrix reveal" id="matrix"></div>
</section>

<section class="wrap">
  <div class="shead"><h2>How the call is made</h2></div>
  <div class="cards">
    <div class="card reveal"><div class="ic">&#9683;</div><h3>Foilable wind</h3><p><span class="big">13&ndash;22 kt</span>, ideal 15&ndash;20. Below 13 you can't get up on the 95L.</p></div>
    <div class="card reveal"><div class="ic">&#8776;</div><h3>Steady, not spiky</h3><p>Gust minus average <span class="big">&le; 5 kt</span>. A 15-gusting-28 day is a no-go on a 5m.</p></div>
    <div class="card reveal"><div class="ic">&#10138;</div><h3>Direction</h3><p>Side-shore / side-onshore only. <span class="big">Offshore blocks</span> the spot regardless of speed.</p></div>
    <div class="card reveal"><div class="ic">&#9788;</div><h3>Your hours</h3><p>Early mornings, evenings, weekends ranked first. Coast parked until foil-stable.</p></div>
  </div>
</section>
</main>

<footer>
  <div class="wrap">
    <div class="srcgrid" id="sources"></div>
    <div class="fmeta">
      Triangulated across multiple models via <a href="https://open-meteo.com">Open-Meteo</a> (CC BY 4.0), refreshed every run.
      Cross-check on Windguru: <a href="https://www.windguru.cz/19">Muiderberg</a> &middot;
      <a href="https://www.windguru.cz/3601">Schellinkhout</a> &middot;
      <a href="https://www.windguru.cz/113">Wijk aan Zee</a>.
    </div>
  </div>
</footer>

<div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="sheet-h">
  <div class="sheet" id="sheet"></div>
</div>

<script>
/*DATA*/
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

$("#eyebrow").innerHTML = 'Wendy Foils <span class="sep">&middot;</span> ' + esc(DATA.weeklabel);
$("#h1").textContent = DATA.headline;
$("#verdict").innerHTML = DATA.verdict;

// feature card
const compass = (deg,dir) => (deg==null)? "" :
  `<svg class="compass" width="30" height="30" viewBox="0 0 30 30" role="img" aria-label="wind from ${esc(dir||"")}">
     <circle cx="15" cy="15" r="13" fill="none" stroke="var(--hair2)" stroke-width="1.5"/>
     <g transform="rotate(${deg} 15 15)"><path d="M15 4 L19 16 L15 13 L11 16 Z" fill="var(--accent)"/></g>
   </svg>`;
if (DATA.feature){
  const f = DATA.feature, r = 34, C = 2*Math.PI*r, off = C*(1-Math.max(.06,f.q));
  $("#feature").innerHTML =
    `<div class="flabel">${esc(f.label)} <span class="pill ${f.verdict.toLowerCase()}">${esc(f.verdict)}</span>${f.prob!=null?` <span class="ens">${f.prob}% in-band</span>`:""}</div>
     <div class="feat-main">
       <div class="bigwind"><span class="n">${esc(f.wind)}</span><span class="u">${esc(f.windsub)}</span></div>
       <svg class="gauge" width="84" height="84" viewBox="0 0 84 84" role="img" aria-label="wind quality ${Math.round(f.q*100)} of 100">
         <circle cx="42" cy="42" r="${r}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="7"/>
         <circle cx="42" cy="42" r="${r}" fill="none" stroke="var(--accent)" stroke-width="7" stroke-linecap="round"
           stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 42 42)"/>
         <text x="42" y="47" text-anchor="middle" font-family="var(--mono)" font-size="15" fill="var(--accent)">${Math.round(f.q*100)}</text>
       </svg>
     </div>
     <div class="feat-where">
       <div class="spot">${esc(f.spot)} ${compass(f.deg, f.dir)}</div>
       <div class="when">${esc(f.day)} &middot; ${esc(f.window)}</div>
     </div>
     <div class="feat-row">
       <span>dir <b>${esc(f.dir)}</b></span><span>gust <b>${esc(f.gust)}</b></span>
       <span>air <b>${esc(f.air)}</b></span><span>water <b>${esc(f.water)}</b></span>
     </div>
     ${f.obs?`<div class="live"><span class="ld"></span><span class="lt">Live now <b>${esc(f.obs.kt)} kt</b> gusting ${esc(f.obs.gust)} ${esc(f.obs.dir)} &middot; ${esc(f.obs.station)} ${esc(f.obs.km)} km</span></div>`:""}
     <div class="feat-note">${esc(f.wetsuit)}${f.note?(" &middot; "+esc(f.note)):""}</div>`;
} else { $("#feature").style.display="none"; }

// tiles
$("#tiles").innerHTML = DATA.tiles.map(t=>
  `<div class="tile"><span class="k">${esc(t[0])}</span><span class="v">${esc(t[1])}</span><span class="s">${esc(t[2]||"")}</span></div>`).join("");

// sources
$("#sources").innerHTML = DATA.sources.map(s=>`<span class="s">${esc(s)}</span>`).join("");

// matrix
$(".matrix").style.setProperty("--ndays", DATA.days.length);
let html = `<div class="mhead"><div class="corner"></div>`+DATA.days.map(d=>`<div class="dh">${esc(d)}</div>`).join("")+`</div>`;
html += DATA.spots.map(s=>{
  const cells = (DATA.grid[s.name]||[]).map((c,di)=>{
    const [call,val,q,title] = c;
    const isBest = (DATA.best && DATA.best.spot===s.name && di===DATA.best.day) ? " best" : "";
    const pct = Math.max(q>0?12:0, Math.round(q*100));
    const num = /^[\d.]+$/.test(val);
    const gust = /g/.test(val);
    const disp = num ? `${esc(val)}<span class="kt">kt</span>` : (gust? esc(val).replace('g','<span class="kt">g</span>') : esc(val));
    const key = s.name+"|"+(DATA.dates[di]||"");
    const clk = (DATA.hourly && DATA.hourly[key]) ? " clickable" : "";
    const attrs = clk ? ` data-key="${esc(key)}" tabindex="0" role="button" aria-label="${esc(s.name)} ${esc(DATA.days[di]||"")} hourly detail"` : "";
    return `<div class="cell ${call}${isBest}${clk}"${attrs} title="${esc(clk?"Tap for the hourly breakdown":(title||""))}">`+
      `<span class="dlabel">${esc(DATA.days[di]||"")}</span>`+
      `<span class="tag">${call.toUpperCase()}</span>`+
      `<span class="val">${disp}</span>`+
      `<div class="qbar"><i style="width:${pct}%"></i></div>`+
      (clk?`<span class="exp" aria-hidden="true">&#8942;</span>`:"")+`</div>`;
  }).join("");
  return `<div class="srow"><div class="sname"><span class="nm">${esc(s.name)}</span><span class="sub">${esc(s.sub)} &middot; ${esc(s.drive)}</span></div>${cells}</div>`;
}).join("");
$(".matrix").innerHTML = html;

// ---- day detail modal (hourly breakdown) ----
const modal = $("#modal"), sheet = $("#sheet");
function chart(hrs){
  const B=DATA.band, W=680,H=300,L=36,R=14,T=16,Bt=52;
  const pw=W-L-R, ph=H-T-Bt, n=hrs.length||1, bw=pw/n, barw=Math.min(20,bw*0.58);
  const maxV=Math.max(B.hi+4, ...hrs.map(h=>Math.max(h.s, h.g||0)));
  const maxY=Math.max(25, Math.ceil((maxV+2)/5)*5);
  const y=v=>T+ph*(1-v/maxY), base=T+ph;
  const p=[];
  p.push(`<rect x="${L}" y="${y(B.hi).toFixed(1)}" width="${pw}" height="${(y(B.lo)-y(B.hi)).toFixed(1)}" fill="var(--accent)" opacity="0.07"/>`);
  p.push(`<rect x="${L}" y="${y(B.ideal_hi).toFixed(1)}" width="${pw}" height="${(y(B.ideal_lo)-y(B.ideal_hi)).toFixed(1)}" fill="var(--accent)" opacity="0.1"/>`);
  [10,20].forEach(v=>{ if(v<maxY){ p.push(`<line x1="${L}" x2="${W-R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--hair)" stroke-width="1"/>`);
    p.push(`<text x="${(L-6)}" y="${(y(v)+3).toFixed(1)}" text-anchor="end" font-family="var(--mono)" font-size="10" fill="var(--faint)">${v}</text>`);}});
  hrs.forEach((h,i)=>{
    const cx=L+i*bw+bw/2;
    const col=(h.s<B.lo)?"var(--faint)":(((h.g!=null&&h.g>B.gustmax)||h.s>B.hi)?"var(--maybe)":"var(--accent)");
    p.push(`<rect x="${(cx-barw/2).toFixed(1)}" y="${y(h.s).toFixed(1)}" width="${barw.toFixed(1)}" height="${Math.max(0,base-y(h.s)).toFixed(1)}" rx="2" fill="${col}" opacity="0.92"/>`);
    if(h.g!=null) p.push(`<line x1="${(cx-barw/2).toFixed(1)}" x2="${(cx+barw/2).toFixed(1)}" y1="${y(h.g).toFixed(1)}" y2="${y(h.g).toFixed(1)}" stroke="var(--ink)" stroke-width="1.5" opacity="0.5"/>`);
    if((h.h-6)%3===0){
      p.push(`<text x="${cx.toFixed(1)}" y="${(base+16).toFixed(1)}" text-anchor="middle" font-family="var(--mono)" font-size="10" fill="var(--faint)">${h.h}:00</text>`);
      if(h.deg!=null) p.push(`<g transform="translate(${cx.toFixed(1)},${(base+32).toFixed(1)}) rotate(${h.deg})"><path d="M0 -5 L3 4 L0 2 L-3 4 Z" fill="var(--soft)"/></g>`);
    }
  });
  p.push(`<line x1="${L}" x2="${W-R}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}" stroke="var(--hair2)" stroke-width="1"/>`);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="hourly wind, knots">${p.join("")}</svg>`;
}
function buildSheet(key){
  const hrs=DATA.hourly[key]; if(!hrs) return;
  const [spot,date]=key.split("|");
  const di=DATA.dates.indexOf(date), cell=(DATA.grid[spot]||[])[di]||[];
  const call=(cell[0]||"skip"), title=cell[3]||"";
  sheet.innerHTML =
    `<div class="sheet-head"><div>
       <div class="sk">Hourly &middot; 06:00&ndash;22:00 kt</div>
       <h3 id="sheet-h">${esc(spot)}</h3>
       <div class="sd">${esc(DATA.daylong[date]||date)} <span class="pill ${call}">${call.toUpperCase()}</span></div>
     </div><button class="xbtn" id="xbtn" aria-label="Close">&#10005;</button></div>
     <div class="chartwrap">${chart(hrs)}</div>
     <div class="chlegend">
       <span><i style="background:var(--accent)"></i>foilable 13&ndash;22</span>
       <span><i style="background:var(--maybe)"></i>over-powered</span>
       <span><i style="background:var(--faint)"></i>too light</span>
       <span>&#124; gust</span>
       <span style="color:var(--faint)">shaded = your ideal 15&ndash;20</span>
     </div>
     ${title?`<div class="sheet-note">${esc(title)}</div>`:""}`;
  $("#xbtn").onclick=closeModal;
}
function openModal(key){ buildSheet(key); modal.classList.add("open"); document.body.style.overflow="hidden"; const x=$("#xbtn"); if(x) x.focus(); }
function closeModal(){ modal.classList.remove("open"); document.body.style.overflow=""; }
modal.addEventListener("click", e=>{ if(e.target===modal) closeModal(); });
document.addEventListener("keydown", e=>{ if(e.key==="Escape" && modal.classList.contains("open")) closeModal(); });
$(".matrix").addEventListener("click", e=>{ const c=e.target.closest(".cell.clickable"); if(c) openModal(c.dataset.key); });
$(".matrix").addEventListener("keydown", e=>{ if(e.key==="Enter"||e.key===" "){ const c=e.target.closest(".cell.clickable"); if(c){ e.preventDefault(); openModal(c.dataset.key);} } });

// reveal on scroll
const io = new IntersectionObserver((es)=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("in");io.unobserve(e.target);}}),{threshold:.12});
document.querySelectorAll(".reveal").forEach((el,i)=>{el.style.transitionDelay=(i%4*60)+"ms";io.observe(el);});

// ambient wind streaks
(function(){
  const c = $("#wind"), x = c.getContext("2d");
  let W,H,streaks=[],raf;
  const accent = ()=>getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  function size(){ W=c.width=c.offsetWidth*devicePixelRatio; H=c.height=c.offsetHeight*devicePixelRatio; }
  function seed(){ streaks=Array.from({length:40},(_,i)=>({
    y:(H/40)*i+(i*61%46), len:(90+(i*103%260))*devicePixelRatio,
    v:(0.5+((i*29)%55)/55)*devicePixelRatio, o:0.04+((i*17)%22)/240, x:null })); }
  function step(){
    x.clearRect(0,0,W,H); const col=accent();
    for(const s of streaks){
      s.x = (s.x==null? -s.len-(s.y*4%W) : s.x)+s.v*1.3;
      if(s.x>W+s.len) s.x=-s.len;
      const g=x.createLinearGradient(s.x,0,s.x+s.len,0);
      g.addColorStop(0,"transparent"); g.addColorStop(.5,col); g.addColorStop(1,"transparent");
      x.globalAlpha=s.o; x.strokeStyle=g; x.lineWidth=1.1*devicePixelRatio;
      x.beginPath(); x.moveTo(s.x,s.y); x.lineTo(s.x+s.len,s.y); x.stroke();
    }
    x.globalAlpha=1; raf=requestAnimationFrame(step);
  }
  function start(){ size(); seed(); cancelAnimationFrame(raf); step(); }
  addEventListener("resize",start); start();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
