"""Compile the five region JSON files (agent research, hand-normalised) into spots_pt.py SPOTS."""
import json, glob, os, re, sys
S = os.path.dirname(os.path.abspath(__file__))
ORDER = ["north", "centre", "lisbon", "alentejo", "algarve"]
REGION_NAME = {"north": "North", "centre": "Centre", "lisbon": "Lisbon", "alentejo": "Alentejo", "algarve": "Algarve"}
TIDE = {  # tide-forecast.com slugs verified 2026-09-07 (Instituto Hidrografico tables sit behind a JS portal)
    "Viana do Castelo": "Viana-do-Castelo-Portugal", "Leixões": "Leixoes-Portugal", "Leixoes": "Leixoes-Portugal", "Aveiro": "Aveiro-Portugal",
    "Figueira da Foz": "Figueira-da-Foz-Portugal", "Nazaré": "Peniche-Portugal", "Nazare": "Peniche-Portugal", "Peniche": "Peniche-Portugal",
    "Cascais": "Cascais-Portugal", "Lisboa": "Lisbon-Portugal", "Lisbon": "Lisbon-Portugal", "Sesimbra": "Sesimbra-Portugal",
    "Sines": "Sines-Portugal", "Lagos": "Lagos-Portugal", "Sagres": "Lagos-Portugal", "Faro": "Faro-Olhao-Portugal", "Faro-Olhão": "Faro-Olhao-Portugal",
}
BUOY_KEYS = {"leixoes", "nazare", "sines", "faro"}
def buoy_for(s):
    b = (s.get("buoy") or "").lower()
    for k in BUOY_KEYS:
        if k in b or k.rstrip("e") in b: return k
    # by latitude
    la = s["lat"]
    return "leixoes" if la > 40.3 else "nazare" if la > 38.2 else "sines" if la > 37.3 else "faro"

spots, n = [], 0
for reg in ORDER:
    f = os.path.join(S, reg + ".json")
    if not os.path.exists(f): print("missing", f); continue
    for s in sorted(json.load(open(f)), key=lambda x: -x["lat"]):   # north to south inside the region
        n += 1
        port = s.get("tide_port") or ""
        slug = next((v for k, v in TIDE.items() if k.lower() in port.lower()), None)
        if not slug: print("no tide slug for", s["name"], port); slug = "Peniche-Portugal"
        alts = s.get("cam_alts") or []
        spots.append({
            "n": n, "name": s["name"], "dept": REGION_NAME[reg], "sector": f"{REGION_NAME[reg]} / {s.get('town', '')}".rstrip(" /"),
            "lat": round(float(s["lat"]), 3), "lon": round(float(s["lon"]), 3), "face": int(s["face"]), "shelter": float(s.get("shelter") or 0),
            "type": s.get("type", ""), "tide_pref": s.get("tide_pref", "mid"), "note": s.get("note", ""),
            "cam": s["cam"], "cam_shows": s.get("cam_shows", ""), "cam_type": s.get("cam_provider", ""), "cam_status": "verified 2026-09-07" if s.get("cam_verified", True) else "could not verify",
            "cam_dedicated": bool(s.get("cam_dedicated", True)), "cam_km": 0 if s.get("cam_dedicated", True) else float(s.get("cam_km") or s.get("cam_nearest_km") or 0),
            "cam_alts": [{"url": a["url"], "shows": a["shows"]} for a in alts][:3],
            "report": s.get("report") or s.get("forecast"), "forecast": s.get("forecast") or s.get("report"),
            "rel": "Medium", "buoy": buoy_for(s), "tide_url": f"https://www.tide-forecast.com/locations/{slug}/tides/latest",
        })
print(len(spots), "spots")
lines = ["SPOTS = ["]
for s in spots:
    lines.append(" " + json.dumps(s, ensure_ascii=False) + ",")
lines.append("]")
p = "/Users/simondemarmels/Projects/wendy-foils/spots_pt.py"
src = open(p).read()
src = re.sub(r"SPOTS = \[.*?\n\]|SPOTS = \[\]          # filled below by research", "\n".join(lines), src, count=1, flags=re.S)
open(p, "w").write(src)
print("wrote spots_pt.py")
