#!/usr/bin/env python3
"""Regenerate docs/index.html from a wendy.py output file's GRID block.

Usage: python3 gen_dashboard.py data/weekly.out.txt docs/index.html
Keeps the dashboard always current: the GitHub Action runs this after each fetch.
"""
import sys, json, re
from datetime import datetime

WIND_MIN, GUST_MAX = 13, 25
SPOT_SUB = {
    "Muiderberg": "IJmeer · inland · ~20min",
    "Almere Muiderzand": "IJmeer · inland · ~25min",
    "Schellinkhout": "Markermeer · inland · ~45min",
    "Wijk aan Zee": "North Sea · coast · ~40min",
}

def daylabel(date):
    return datetime.fromisoformat(date+"T00:00").strftime("%a %-d")

def cell_val(r):
    if r["type"] == "coast":
        return f"{r['wave']:.1f}m" if r.get("wave") is not None else "—"
    if r.get("avg") is not None:
        return f"{r['avg']:.0f}kt"
    if r["verdict"] == "MAYBE" and r.get("hotpeak"):
        return f"{r['hotpeak']:.0f}kt"
    if r["verdict"] == "SKIP" and r.get("gust",0) > GUST_MAX and r.get("peak",0) >= WIND_MIN-1:
        return f"{r['peak']:.0f} g{r['gust']:.0f}"
    return f"{r.get('peak',0):.0f}kt"

def cell_q(r):
    if r["type"] == "coast":
        return 0.08
    v = r["verdict"]
    if v == "GO":    return round(min(1.0, 0.82 + r.get("score",3)/40), 2)
    if v == "MAYBE": return 0.55
    if r.get("gust",0) > GUST_MAX and r.get("peak",0) >= WIND_MIN-1:
        return 0.2  # windy but overpowered/spiky
    hp = r.get("hotpeak", r.get("peak",0))
    return round(max(0.05, min(0.4, (hp-6)/(15-6)*0.4)), 2)

def build_data(grid):
    dates = sorted({r["date"] for r in grid})
    days = [daylabel(d) for d in dates]
    spot_order = []
    for r in grid:
        if r["spot"] not in spot_order: spot_order.append(r["spot"])
    spots = [{"name": s, "sub": SPOT_SUB.get(s, "")} for s in spot_order]
    by = {(r["spot"], r["date"]): r for r in grid}
    matrix = {}
    for s in spot_order:
        row = []
        for d in dates:
            r = by.get((s, d))
            if r is None: row.append(["skip", "—", 0]); continue
            row.append([r["verdict"].lower(), cell_val(r), cell_q(r)])
        matrix[s] = row

    gm = [r for r in grid if r["verdict"] in ("GO", "MAYBE")]
    gm.sort(key=lambda r: (-r.get("score",0), r["date"]))
    best = None
    if gm:
        b = gm[0]
        best = {"spot": b["spot"], "day": dates.index(b["date"])}

    gos = [r for r in gm if r["verdict"] == "GO"]
    maybes = [r for r in gm if r["verdict"] == "MAYBE"]
    if gos:
        b = gos[0]
        headline = "Foilable window this week."
        verdict = (f"Best day: <strong>{daylabel(b['date'])} at {b['spot']}</strong>. {b['why'].split('|')[0].strip()}. "
                   f"Other days ranked below.")
        bestday = f"{daylabel(b['date'])} {b['spot']}"
    elif maybes:
        days_txt = ", ".join(sorted({daylabel(r["date"]) for r in maybes}))
        b = maybes[0]
        headline = "Models split — one to watch."
        verdict = (f"No clear GO, but the models <strong>split</strong> on {days_txt}: our primary reads light while "
                   f"GFS runs foilable over open water. {b['spot']} is the one to watch &mdash; go only if the stronger "
                   f"model firms up closer in. Coast spots parked until you're foil-stable.")
        bestday = "none clean (watch " + b["spot"] + ")"
    else:
        headline = "No foil window this week."
        verdict = ("Nothing rideable in range. Light all week at your spots, and no model shows a steady in-band "
                   "window in your hours. The daily scan keeps watching.")
        bestday = "none"

    conf = "models split (GFS hotter than HARMONIE)" if maybes and not gos else "high near-term, lower late-week"
    airs = [r["air"] for r in grid if r.get("air") is not None]
    waters = [r["water"] for r in grid if r.get("water") is not None]
    tline = ""
    if airs and waters:
        tline = f"air {min(airs):.0f}-{max(airs):.0f}C · water ~{max(set(waters), key=waters.count):.0f}C"
    meta = [["Setup", "5m · 95L · 78kg · beginner"],
            ["Best day", bestday],
            ["Spots", f"{len(spots)} checked"],
            ["Confidence", conf]]
    if tline: meta.insert(2, ["Temp", tline])
    weeklabel = datetime.fromisoformat(dates[0]+"T00:00").strftime("week of %-d %b %Y")
    return {"days": days, "spots": spots, "grid": matrix, "best": best, "headline": headline,
            "verdict": verdict, "meta": meta, "weeklabel": weeklabel}

def main():
    src, dest = sys.argv[1], sys.argv[2]
    txt = open(src, encoding="utf-8").read()
    m = re.search(r"<!--GRID_START-->(.*?)<!--GRID_END-->", txt, re.S)
    if not m:
        sys.stderr.write("no GRID block in "+src+"\n"); sys.exit(1)
    grid = json.loads(m.group(1))
    data = build_data(grid)
    html = TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(data) + ";")
    open(dest, "w", encoding="utf-8").write(html)
    print(f"wrote {dest} ({len(data['days'])} days, {len(data['spots'])} spots)")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wendy Foils — Wind outlook</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --ground:#f3f6f7; --panel:#ffffff; --ink:#0c1d26; --ink-soft:#4a5f68;
    --hair:#dbe4e6; --accent:#0a9aa2;
    --go:#1f9d63; --go-bg:#e4f4ea; --maybe:#c07d15; --maybe-bg:#fbf1de;
    --skip:#7d8c92; --skip-bg:#eef1f2; --track:#e6ebec;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    --c1:200px;
  }
  @media (prefers-color-scheme:dark){:root{
    --ground:#081720; --panel:#0f2530; --ink:#e9f2f3; --ink-soft:#8ba7af;
    --hair:#1c3846; --accent:#3fd0d8;
    --go:#43c988; --go-bg:#123227; --maybe:#e0a13a; --maybe-bg:#33260f;
    --skip:#6f858c; --skip-bg:#152a34; --track:#122a34;}}
  :root[data-theme="light"]{
    --ground:#f3f6f7; --panel:#ffffff; --ink:#0c1d26; --ink-soft:#4a5f68;
    --hair:#dbe4e6; --accent:#0a9aa2;
    --go:#1f9d63; --go-bg:#e4f4ea; --maybe:#c07d15; --maybe-bg:#fbf1de;
    --skip:#7d8c92; --skip-bg:#eef1f2; --track:#e6ebec;}
  :root[data-theme="dark"]{
    --ground:#081720; --panel:#0f2530; --ink:#e9f2f3; --ink-soft:#8ba7af;
    --hair:#1c3846; --accent:#3fd0d8;
    --go:#43c988; --go-bg:#123227; --maybe:#e0a13a; --maybe-bg:#33260f;
    --skip:#6f858c; --skip-bg:#152a34; --track:#122a34;}
  html{-webkit-text-size-adjust:100%}
  body{background:var(--ground);color:var(--ink);font-family:var(--sans);
    line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  .wrap{max-width:1180px;margin:0;padding:0 clamp(20px,5vw,80px)}
  .hero{position:relative;overflow:hidden;border-bottom:1px solid var(--hair)}
  #wind{position:absolute;inset:0;width:100%;height:100%;display:block}
  .hero-in{position:relative;z-index:2;padding:clamp(44px,9vw,64px) 0 clamp(38px,7vw,56px)}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.2em;text-transform:uppercase;
    color:var(--accent);margin:0 0 20px;display:flex;align-items:center;gap:11px;flex-wrap:wrap;line-height:1.5}
  .eyebrow .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:none;
    box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent)}
  h1{font-size:clamp(28px,7vw,52px);line-height:1.05;margin:0 0 20px;font-weight:800;
    letter-spacing:-.02em;text-wrap:balance;max-width:15ch}
  .verdict-line{font-size:clamp(15px,2.4vw,17px);color:var(--ink-soft);max-width:62ch;margin:0}
  .verdict-line strong{color:var(--ink)}
  .meta{display:flex;flex-wrap:wrap;gap:12px 30px;margin-top:30px;
    font-family:var(--mono);font-size:12.5px;color:var(--ink-soft)}
  .meta b{color:var(--ink);font-weight:600}
  section{padding:clamp(34px,7vw,52px) 0}
  .sec-h{font-family:var(--mono);font-size:12px;letter-spacing:.16em;text-transform:uppercase;
    color:var(--ink-soft);margin:0 0 8px}
  .sec-note{font-size:13px;color:var(--ink-soft);margin:0 0 24px;max-width:62ch}
  .sec-note .swatch{display:inline-block;width:26px;height:6px;border-radius:3px;vertical-align:middle;
    background:linear-gradient(90deg,color-mix(in srgb,var(--accent) 30%,transparent),var(--accent));margin:0 3px}
  .matrix{display:grid;grid-template-columns:var(--c1) repeat(var(--ndays,7),minmax(0,1fr));column-gap:6px;align-items:stretch}
  .mhead,.srow{display:contents}
  .corner{border-bottom:1px solid var(--hair)}
  .dh{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;
    color:var(--ink-soft);font-weight:600;padding:0 4px 16px;border-bottom:1px solid var(--hair)}
  .sname{font-weight:600;font-size:15px;padding:20px 12px 20px 0;border-bottom:1px solid var(--hair);align-self:center}
  .spot-sub{display:block;font-weight:400;font-size:11.5px;color:var(--ink-soft);
    font-family:var(--mono);letter-spacing:.02em;margin-top:3px}
  .cell{display:flex;flex-direction:column;gap:9px;align-items:flex-start;padding:18px 4px;border-bottom:1px solid var(--hair)}
  .dlabel{display:none;font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--ink-soft)}
  .tag{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:700;
    letter-spacing:.06em;padding:3px 7px;border-radius:5px;white-space:nowrap}
  .kt{font-family:var(--mono);font-variant-numeric:tabular-nums;font-weight:600;font-size:15px;
    line-height:1;color:var(--ink);white-space:nowrap}
  .skip .tag{background:var(--skip-bg);color:var(--skip)} .skip .kt{color:var(--ink-soft)}
  .maybe .tag{background:var(--maybe-bg);color:var(--maybe)} .maybe .kt{color:var(--maybe)}
  .go .tag{background:var(--go-bg);color:var(--go)} .go .kt{color:var(--go)}
  .qbar{width:100%;max-width:56px;height:5px;border-radius:3px;background:var(--track);overflow:hidden}
  .qbar i{display:block;height:100%;border-radius:3px;background:var(--accent)}
  .best .kt{color:var(--accent);font-weight:700}
  .best .qbar i{box-shadow:0 0 8px color-mix(in srgb,var(--accent) 70%,transparent)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-top:20px}
  .card{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:22px}
  .card h3{margin:0 0 12px;font-size:13px;font-family:var(--mono);letter-spacing:.04em;
    text-transform:uppercase;color:var(--ink-soft);font-weight:600}
  .card p{margin:0;font-size:14px;color:var(--ink);line-height:1.6}
  .card .big{font-family:var(--mono);font-weight:700;font-size:15px}
  footer{border-top:1px solid var(--hair);padding:32px 0 clamp(40px,10vw,56px);
    font-size:12.5px;color:var(--ink-soft);line-height:1.9}
  footer .src{font-family:var(--mono);margin-bottom:14px;word-break:break-word}
  footer a{color:var(--accent);text-decoration:none} footer a:hover{text-decoration:underline}
  a:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
  @media (prefers-reduced-motion:reduce){#wind{display:none}}
  @media (max-width:760px){
    .matrix{display:block}
    .mhead{display:none}
    .srow{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:10px;
      background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:16px;margin-bottom:14px}
    .sname{grid-column:1/-1;padding:0 0 4px;border-bottom:1px solid var(--hair);margin-bottom:4px}
    .cell{border-bottom:none;padding:4px 0;gap:7px}
    .dlabel{display:block}
    .qbar{max-width:none}
  }
</style>
</head>
<body>
<div class="hero">
  <canvas id="wind"></canvas>
  <div class="wrap hero-in">
    <p class="eyebrow"><span class="dot"></span> <span id="eyebrow">Wendy Foils</span></p>
    <h1 id="h1"></h1>
    <p class="verdict-line" id="verdict"></p>
    <div class="meta" id="meta"></div>
  </div>
</div>
<section class="wrap">
  <p class="sec-note">Each cell shows the call and peak wind. The <span class="swatch"></span> bar is wind quality &mdash; how close that day sits to your foilable window (fuller and brighter = better). GO days glow. Wind is the strongest credible model in your go-hours, so a GFS-hot day still shows up.</p>
  <div class="matrix" id="matrix"></div>
</section>
<section class="wrap">
  <h2 class="sec-h">How the call is made</h2>
  <div class="cards">
    <div class="card"><h3>Foilable wind</h3><p><span class="big">13&ndash;22 kt</span>, ideal 15&ndash;20. Below 13 you can't get up on the 95L.</p></div>
    <div class="card"><h3>Steady, not spiky</h3><p>Gust minus average <span class="big">&le; 5 kt</span>. A 15-gusting-28 day is a no-go on a 5m.</p></div>
    <div class="card"><h3>Direction</h3><p>Side-shore / side-onshore only. <span class="big">Offshore blocks</span> the spot regardless of speed.</p></div>
    <div class="card"><h3>Your hours</h3><p>Early mornings, evenings, weekends ranked first. Coast spots parked until foil-stable.</p></div>
  </div>
</section>
<footer class="wrap">
  <div class="src">Source: KNMI HARMONIE-AROME + ICON-EU + GFS + ECMWF + ICON-EU ensemble + EWAM waves, via Open-Meteo (CC BY 4.0).</div>
  Cross-check on Windguru:
  <a href="https://www.windguru.cz/19">Muiderberg</a> ·
  <a href="https://www.windguru.cz/3601">Schellinkhout</a> ·
  <a href="https://www.windguru.cz/113">Wijk aan Zee</a>
</footer>
<script>
/*DATA*/
document.getElementById("eyebrow").textContent = "Wendy Foils · " + DATA.weeklabel;
document.getElementById("h1").textContent = DATA.headline;
document.getElementById("verdict").innerHTML = DATA.verdict;
document.getElementById("meta").innerHTML = DATA.meta.map(m=>`<span><b>${m[0]}:</b> ${m[1]}</span>`).join("");
const esc = s => String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
document.querySelector(".matrix").style.setProperty("--ndays", DATA.days.length);
let html = `<div class="mhead"><div class="corner"></div>`+DATA.days.map(d=>`<div class="dh">${esc(d)}</div>`).join("")+`</div>`;
html += DATA.spots.map(s=>{
  const cells = (DATA.grid[s.name]||[]).map((c,di)=>{
    const [call,val,q] = c;
    const isBest = (DATA.best && DATA.best.spot===s.name && di===DATA.best.day) ? " best" : "";
    const pct = Math.max(q>0?10:0, Math.round(q*100));
    const op = (0.4 + 0.6*q).toFixed(2);
    return `<div class="cell ${call}${isBest}">`+
      `<span class="dlabel">${esc(DATA.days[di]||"")}</span>`+
      `<span class="tag">${call.toUpperCase()}</span>`+
      `<span class="kt">${esc(val)}</span>`+
      `<div class="qbar"><i style="width:${pct}%;opacity:${op}"></i></div></div>`;
  }).join("");
  return `<div class="srow"><div class="sname">${esc(s.name)}<span class="spot-sub">${esc(s.sub)}</span></div>${cells}</div>`;
}).join("");
document.querySelector(".matrix").innerHTML = html;
(function(){
  const c = document.getElementById("wind"), x = c.getContext("2d");
  let W,H,streaks=[], raf;
  const accent = ()=>getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  function size(){ W=c.width=c.offsetWidth*devicePixelRatio; H=c.height=c.offsetHeight*devicePixelRatio; }
  function seed(){ streaks = Array.from({length:34},(_,i)=>({
    y:(H/34)*i + (i*53%40), len:80+ (i*97%220), v:0.6+((i*31)%50)/60, o:0.05+((i*17)%20)/180 }));}
  function step(){
    x.clearRect(0,0,W,H); const col=accent();
    for(const s of streaks){
      s.x = (s.x==null? -s.len - (s.y*3%W) : s.x) + s.v*devicePixelRatio*1.4;
      if(s.x > W+s.len) s.x = -s.len;
      const g = x.createLinearGradient(s.x,0,s.x+s.len,0);
      g.addColorStop(0,"transparent"); g.addColorStop(.5,col); g.addColorStop(1,"transparent");
      x.globalAlpha=s.o; x.strokeStyle=g; x.lineWidth=1.2*devicePixelRatio;
      x.beginPath(); x.moveTo(s.x,s.y); x.lineTo(s.x+s.len,s.y); x.stroke();
    }
    x.globalAlpha=1; raf=requestAnimationFrame(step);
  }
  function start(){ size(); seed(); cancelAnimationFrame(raf); step(); }
  addEventListener("resize", start); start();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
