#!/usr/bin/env python3
"""
Wendy Surf - surf-trip forecast engine for the French Atlantic coast (Soulac to Biarritz).

Usage:
  python3 surf.py            -> 7-day outlook for all 36 spots, ranked per day

Outputs to stdout (same delimiter convention as wendy.py):
  - a human summary
  - <!--SUBJECT_START--> ... <!--SUBJECT_END-->        one-line verdict for the morning ping
  - <!--JSON_START--> ... <!--JSON_END-->              today's standouts (top 5) + tomorrow preview
  - <!--SPOTS_START--> ... <!--SPOTS_END-->            spot metadata (cams, links, notes)
  - <!--GRID_START--> ... <!--GRID_END-->              per spot/day rows for the dashboard
  - <!--EMAIL_HTML_START--> ... <!--EMAIL_HTML_END-->  inline-styled HTML for the calendar invite

Data (all Open-Meteo, no key, CC BY 4.0):
  Marine best_match (MFWAM near / ECMWF-WAM far): wave height, period, direction, swell
  components, tide height (sea_level_height_msl), sea temp. ECMWF-WAM 0.25 as a second
  opinion on swell height. Wind: Meteo-France AROME HD 1.5km (~2 days), then Meteo-France
  seamless (ARPEGE), then best_match; merged per hour, best model wins.

Rider: lifelong wave surfer. Wants anything waist-high and up, relatively clean.
Spot list + cam/report/forecast links come from Simon's sheet
"Atlantic_France_Surf_Cams_and_Forecasts" (checked 2026-09-02).
"""

import sys, os, json, math, urllib.request, urllib.error
from datetime import datetime, date as ddate

TZ = "Europe/Paris"
FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE   = "https://marine-api.open-meteo.com/v1/marine"

TRIP_START, TRIP_END = "2026-09-14", "2026-10-04"

# ---- thresholds (significant wave height in m at the beach, see eff_height) ----
HS_MIN      = 0.7    # below this it's knee-high mush, SKIP
HS_PRIME_LO = 1.0    # chest-high and up
HS_PRIME_HI = 2.0    # up to a bit overhead
HS_HEAVY    = 2.6    # open beach breaks get heavy / closey above this
PERIOD_JUNK = 6.5    # s, pure windswell
GLASS_KT    = 6      # under this any direction is glassy
OFF_MAX_KT  = 18     # offshore stronger than this makes it hard to get in
ONSHORE_BLOWN = 14   # kt onshore = blown out, hard SKIP
WINDOW_HRS  = 3      # a session-length window

GO_SCORE, MAYBE_SCORE = 5.5, 3.5

DIRS16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
def dir16(deg):
    return DIRS16[round((deg % 360) / 22.5) % 16]

# ---- spots ----
# lat/lon = the beach itself. face = compass bearing from the sand out to open sea.
# shelter 0 = fully open beach break, up to 0.7 = well protected (Le Prevent). Sheltered
# spots read smaller than the open coast and hold when the open beaches close out.
# Links/notes: Simon's sheet, 2026-09-02.
SPOTS = [
 {"n":1,"name":"Soulac-sur-Mer","dept":"Gironde","sector":"Médoc / Soulac","lat":45.512,"lon":-1.135,"face":275,"shelter":0,
  "cam":"https://www.mairie-soulac.fr/en-un-clic/webcam/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/soulac/584204204e65fad6a770902e",
  "rel":"High","note":"Official town beach camera. Good northern Médoc visual reference."},
 {"n":2,"name":"L'Amélie","dept":"Gironde","sector":"Médoc / Soulac","lat":45.483,"lon":-1.150,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/15744-france-aquitaine-soulac-sur-mer-la-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/l-amelie/584204204e65fad6a770902d",
  "rel":"Medium","note":"Use the Soulac camera as the closest dependable visual check."},
 {"n":3,"name":"Le Gurp","dept":"Gironde","sector":"Médoc / Soulac","lat":45.435,"lon":-1.155,"face":275,"shelter":0,
  "cam":"https://www.vendays-montalivet.fr/pratique/webcam/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-gurp/584204204e65fad6a770902f",
  "rel":"Medium","note":"No dependable dedicated camera; compare Soulac and Montalivet."},
 {"n":4,"name":"Montalivet","dept":"Gironde","sector":"Médoc / Montalivet","lat":45.378,"lon":-1.152,"face":275,"shelter":0,
  "cam":"https://www.vendays-montalivet.fr/pratique/webcam/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/montalivet/584204204e65fad6a7709030",
  "rel":"High","note":"Official beach stream; GoSurf also carries Plage Centrale."},
 {"n":5,"name":"Le Pin Sec","dept":"Gironde","sector":"Médoc / Hourtin","lat":45.302,"lon":-1.162,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/ville/vue/11106-france-aquitaine-hourtin-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-pin-sec/584204204e65fad6a7709031",
  "rel":"Medium","note":"Remote beach without a dependable dedicated feed; Hourtin is the nearest camera."},
 {"n":6,"name":"Hourtin-Plage","dept":"Gironde","sector":"Médoc / Hourtin","lat":45.223,"lon":-1.172,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/ville/vue/11106-france-aquitaine-hourtin-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/hourtin-plage/584204204e65fad6a7709032",
  "rel":"Medium","note":"Beach camera is useful; do not confuse it with the lake camera."},
 {"n":7,"name":"Carcans-Plage","dept":"Gironde","sector":"Médoc / Carcans","lat":45.085,"lon":-1.190,"face":275,"shelter":0,
  "cam":"https://m.viewsurf.com/univers/surf/vue/1255-1202898780-france-aquitaine-carcans-la-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/carcans/584204204e65fad6a7709034",
  "rel":"Medium","note":"If the feed is stale, use Lacanau only 9 km south as a regional check."},
 {"n":8,"name":"Lacanau-Océan","dept":"Gironde","sector":"Lacanau","lat":45.001,"lon":-1.203,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/9/Lacanau-Plage-de-Lacanau-Ocean","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/lacanau/5842041f4e65fad6a7708c8d",
  "rel":"High","note":"Excellent coverage: Surf Club, Centrale, Nord and Supersud angles."},
 {"n":9,"name":"Le Porge-Océan","dept":"Gironde","sector":"Le Porge","lat":44.885,"lon":-1.222,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-porge/584204204e65fad6a7708fe2",
  "rel":"High","note":"Official 4K panoramic camera at Plage du Gressier."},
 {"n":10,"name":"La Jenny","dept":"Gironde","sector":"Le Porge","lat":44.835,"lon":-1.230,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/la-jenny/584204204e65fad6a7708fe3",
  "rel":"Medium","note":"No dedicated camera; Le Porge is the best nearby visual reference."},
 {"n":11,"name":"Grand Crohot","dept":"Gironde","sector":"Cap Ferret","lat":44.740,"lon":-1.245,"face":275,"shelter":0,
  "cam":"https://barrelsurfing.fr/grand-crohot/","report":"https://barrelsurfing.fr/grand-crohot/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"High","note":"Local cam page includes wind, a 10-day forecast and Cap Ferret context."},
 {"n":12,"name":"Le Truc Vert","dept":"Gironde","sector":"Cap Ferret","lat":44.705,"lon":-1.250,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-truc-vert/584204204e65fad6a7708fe5",
  "rel":"Medium","note":"TV Cap Ferret routes to the local Truc Vert and Grand Crohot feeds."},
 {"n":13,"name":"La Garonne / Le Petit Train","dept":"Gironde","sector":"Cap Ferret","lat":44.670,"lon":-1.253,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Medium","note":"Use Truc Vert as the closest camera; banks can differ significantly."},
 {"n":14,"name":"L'Horizon / Les Dunes / La Pointe","dept":"Gironde","sector":"Cap Ferret","lat":44.640,"lon":-1.255,"face":280,"shelter":0.1,
  "cam":"https://www.surf-forecast.com/breaks/Cap-Ferret/webcams/latest","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Low–Medium","note":"No consistently dependable dedicated ocean cam for every south-peninsula beach."},
 {"n":15,"name":"La Salie Nord / Sud","dept":"Gironde","sector":"Arcachon / La Salie","lat":44.585,"lon":-1.240,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/18468-france-aquitaine-la-teste-de-buch-plage-de-la-salie","report":"https://www.surf-forecast.com/breaks/La-Salie/webcams/latest","forecast":"https://www.surfline.com/surf-report/la-salie/6418e0f89702724989875c99",
  "rel":"Low–Medium","note":"Viewsurf feed showed maintenance on 2026-09-02; check the Surf-Forecast page."},
 {"n":16,"name":"Biscarrosse","dept":"Landes","sector":"North Landes","lat":44.448,"lon":-1.255,"face":275,"shelter":0,
  "cam":"https://www.biscagrandslacs.co.uk/discover/all-our-webcams","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Biscarosse-Plage/forecasts/latest/six_day",
  "rel":"High","note":"Five useful angles including Sud, Centrale, Nord and Le Vivier."},
 {"n":17,"name":"Mimizan","dept":"Landes","sector":"North Landes","lat":44.212,"lon":-1.298,"face":275,"shelter":0,
  "cam":"https://www.mimizan-tourisme.com/en/webcams/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Mimizan/forecasts/latest/six_day",
  "rel":"High","note":"Official panoramic, north, west and south views refresh every few minutes."},
 {"n":18,"name":"Contis","dept":"Landes","sector":"Central Landes","lat":44.092,"lon":-1.325,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/163/Contis-Plage-de-Contis","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"Useful regional reference for the isolated central Landes beaches."},
 {"n":19,"name":"Cap de l'Homy","dept":"Landes","sector":"Central Landes","lat":44.040,"lon":-1.335,"face":275,"shelter":0,
  "cam":"https://www.surf-forecast.com/breaks/Cap-de-l-Homy/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/lit-et-mixe/cap-de-lhomy","forecast":"https://www.surfline.com/surf-report/cap-de-l-homy-plage/584204204e65fad6a7708fdb",
  "rel":"Low","note":"Surf Sentinel reports the dedicated camera as missing; compare Contis."},
 {"n":20,"name":"Saint-Girons / La Lette Blanche","dept":"Landes","sector":"Central Landes","lat":43.955,"lon":-1.355,"face":275,"shelter":0,
  "cam":"https://fr.surf-forecast.com/breaks/Saint-Girons/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/vielle-saint-girons/saint-girons-plage","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Low","note":"Use Contis or Moliets for a broad visual read, then inspect on arrival."},
 {"n":21,"name":"Moliets","dept":"Landes","sector":"Central Landes","lat":43.850,"lon":-1.385,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/186/Moliets-Plage-Nord","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"GoSurf also carries Centrale and Sud angles when those feeds are up."},
 {"n":22,"name":"Messanges","dept":"Landes","sector":"Central Landes","lat":43.818,"lon":-1.395,"face":275,"shelter":0,
  "cam":"https://www.landesatlantiquesud.com/webcams/messanges/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://fr.surf-forecast.com/breaks/Messanges/forecasts/latest/six_day",
  "rel":"Medium","note":"Camera availability varies; Vieux-Boucau is the most dependable neighbour."},
 {"n":23,"name":"Vieux-Boucau / Soustons","dept":"Landes","sector":"South Landes","lat":43.788,"lon":-1.415,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/85/Vieux-Boucau-Plage-de-Vieux-Boucau","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Very useful around the Courant de Soustons, where banks change fast."},
 {"n":24,"name":"Seignosse – Le Penon","dept":"Landes","sector":"South Landes","lat":43.712,"lon":-1.435,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/49/Seignosse-Plage-du-Penon","report":"https://seignosse.info/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Seignosse.info adds tides and skill-level ratings in one screen."},
 {"n":25,"name":"Seignosse – Bourdaines / Estagnots","dept":"Landes","sector":"South Landes","lat":43.690,"lon":-1.442,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/79/Seignosse-Plage-des-Bourdaines-Plage-des-Estagnots","report":"https://www.yadusurf.com/","forecast":"https://www.surfline.com/surf-report/les-estagnots/5842041f4e65fad6a7708c8f",
  "rel":"High","note":"YaDuSurf gives exceptionally clear written daily summaries for Estagnots."},
 {"n":26,"name":"Hossegor – Centrale / Gravière / Nord","dept":"Landes","sector":"South Landes","lat":43.672,"lon":-1.445,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/21/Hossegor-La-Centrale","report":"https://www.plages-landes.info/en/hossegor-en/surf-report-hossegor/","forecast":"https://www.surfline.com/surf-report/la-graviere/5842041f4e65fad6a7708c8e",
  "rel":"High","note":"Use the camera heavily: models cannot tell which bank is working. Heavy when big."},
 {"n":27,"name":"Capbreton – Santocha / La Piste","dept":"Landes","sector":"South Landes","lat":43.655,"lon":-1.448,"face":275,"shelter":0.2,
  "cam":"https://gosurf.fr/webcam/fr/83/Capbreton-Plage-du-Santosha-de-La-Piste","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"Often useful when Hossegor is too heavy or closing out."},
 {"n":28,"name":"Capbreton – Le Prévent","dept":"Landes","sector":"South Landes","lat":43.642,"lon":-1.447,"face":280,"shelter":0.6,
  "cam":"https://gosurf.fr/webcam/fr/19/Capbreton-Plage-du-Prevent","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"A different and often more sheltered view than Santocha. Holds bigger swell."},
 {"n":29,"name":"Labenne-Océan","dept":"Landes","sector":"South Landes","lat":43.595,"lon":-1.470,"face":275,"shelter":0,
  "cam":"https://www.landesatlantiquesud.com/en/webcams/labenne/","report":"https://www.plages-landes.info/en/labenne-en/","forecast":"https://www.surfline.com/surf-report/labenne-ocean/584204204e65fad6a7708ff2",
  "rel":"Medium","note":"Official local feed; the Sud Landes aggregator is a useful backup."},
 {"n":30,"name":"Ondres-Océan","dept":"Landes","sector":"South Landes","lat":43.565,"lon":-1.485,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/5892-france-aquitaine-ondres-la-plage","report":"https://www.plages-landes.info/en/ondres-en/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Official 4K panoramic images captured roughly every few minutes."},
 {"n":31,"name":"Tarnos – Le Métro / La Digue","dept":"Landes","sector":"South Landes","lat":43.537,"lon":-1.512,"face":280,"shelter":0.1,
  "cam":"https://www.surf-report.com/webcams/le-metro-tarnos-s1201.html","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/tarnos-plage/584204204e65fad6a7708ff3",
  "rel":"Medium","note":"Transitional zone between open Landes beaches and the Adour jetties."},
 {"n":32,"name":"Anglet – La Barre / Cavaliers / Océan","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.520,"lon":-1.535,"face":295,"shelter":0.1,
  "cam":"https://www.anglet-tourisme.com/en/webcams-of-anglet-beaches/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/anglet/5842041f4e65fad6a7708bce",
  "rel":"High","note":"The official hub covers nearly the entire Anglet beachfront."},
 {"n":33,"name":"Anglet – Madrague / Marinella / Sables d'Or","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.505,"lon":-1.540,"face":295,"shelter":0.1,
  "cam":"https://gosurf.fr/webcam/en/153/Anglet-Plage-de-Marinella-Sables-d-Or","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/marinella/584204204e65fad6a7708ff4",
  "rel":"High","note":"Best Anglet sector for comparing several adjacent peaks visually."},
 {"n":34,"name":"Anglet – VVF / Le Club / Chambre d'Amour","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.493,"lon":-1.548,"face":300,"shelter":0.4,
  "cam":"https://www.anglet-tourisme.com/en/webcams-of-anglet-beaches/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/anglet/5842041f4e65fad6a7708bce",
  "rel":"High","note":"Often more shelter than northern Anglet under some wind and swell directions."},
 {"n":35,"name":"Biarritz – Grande Plage","dept":"Pyrénées-Atlantiques","sector":"Biarritz","lat":43.485,"lon":-1.559,"face":325,"shelter":0.4,
  "cam":"https://www.destination-biarritz.fr/en/pratique/webcams-biarritz/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/biarritz/5842041f4e65fad6a7708bca",
  "rel":"High","note":"Very tide-dependent and busy; check the live view immediately before going."},
 {"n":36,"name":"Biarritz – Côte des Basques","dept":"Pyrénées-Atlantiques","sector":"Biarritz","lat":43.477,"lon":-1.567,"face":290,"shelter":0.5,
  "cam":"https://gosurf.fr/webcam/fr/7/Biarritz-La-Cote-des-Basques","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/la-cote-des-basques/5842041f4e65fad6a7708bcf",
  "rel":"High","note":"Often mellower, but the usable beach and access shrink at high tide."},
]

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent":"wendy-foils/surf/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def try_json(url):
    try:
        return get_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        sys.stderr.write(f"WARN fetch failed: {e} :: {url[:100]}\n")
        return None

# ---- fetch ----
def fetch_spot(spot, days=7):
    lat, lon = spot["lat"], spot["lon"]
    murl = (f"{MARINE}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}"
            "&hourly=wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,"
            "swell_wave_direction,wind_wave_height,sea_level_height_msl,sea_surface_temperature")
    marine = try_json(murl)
    alt = try_json(f"{MARINE}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}"
                   "&hourly=wave_height,swell_wave_period&models=ecmwf_wam025")
    wurl = (f"{FORECAST}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}&wind_speed_unit=kn"
            "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m"
            "&daily=sunrise,sunset&models=meteofrance_arome_france_hd,meteofrance_seamless,best_match")
    wind = try_json(wurl)
    if not wind or "hourly" not in wind:
        wind = try_json(f"{FORECAST}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}&wind_speed_unit=kn"
                        "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m&daily=sunrise,sunset")
    return marine, alt, wind

WIND_PREF = [("meteofrance_arome_france_hd","AROME"), ("meteofrance_seamless","ARPEGE"), ("best_match","blend")]

def merge_wind(wind):
    """Per hour, take the best available model. Returns {time: {kt,gust,deg,air,model}}."""
    H = wind["hourly"]; out = {}
    single = "wind_speed_10m" in H   # fallback single-model response
    for i, t in enumerate(H["time"]):
        if single:
            if H["wind_speed_10m"][i] is None: continue
            out[t] = {"kt":H["wind_speed_10m"][i], "gust":H["wind_gusts_10m"][i], "deg":H["wind_direction_10m"][i],
                      "air":H["temperature_2m"][i], "model":"blend"}
            continue
        for key, label in WIND_PREF:
            s = H.get(f"wind_speed_10m_{key}", [None])[i] if i < len(H.get(f"wind_speed_10m_{key}", [])) else None
            if s is None: continue
            out[t] = {"kt":s, "gust":H.get(f"wind_gusts_10m_{key}",[None]*len(H["time"]))[i],
                      "deg":H.get(f"wind_direction_10m_{key}",[None]*len(H["time"]))[i],
                      "air":H.get(f"temperature_2m_{key}",[None]*len(H["time"]))[i], "model":label}
            break
    return out

def sun_times(wind):
    D = wind.get("daily", {})
    if not D: return {}
    def pick(name):
        for k in D:
            if k.startswith(name): return D[k]
        return None
    sr, ss = pick("sunrise"), pick("sunset")
    if not sr or not ss: return {}
    return {d: (int(sr[i][11:13]) + int(sr[i][14:16])/60, int(ss[i][11:13]) + int(ss[i][14:16])/60)
            for i, d in enumerate(D["time"])}

# ---- scoring ----
def ang_diff(a, b):
    d = abs((a - b + 180) % 360 - 180)
    return d

def wind_relation(spot, deg, kt):
    if kt is None or deg is None: return "unknown"
    if kt < GLASS_KT: return "glassy"
    d = ang_diff(deg, spot["face"])          # 0 = blowing straight onshore (from the sea)
    if d >= 120: return "offshore"
    if d <= 60: return "onshore"
    return "cross"

def eff_height(spot, hs):
    if hs is None: return None
    return hs * (1 - 0.45 * spot["shelter"])

def size_words(h):
    if h is None: return "no data"
    if h < 0.5: return "flat"
    if h < 0.7: return "knee-high"
    if h < 0.9: return "waist-high"
    if h < 1.15: return "chest-high"
    if h < 1.5: return "head-high"
    if h < 2.1: return "overhead"
    if h < 2.8: return "well overhead"
    return "big"

def hour_score(spot, hs, per, w):
    """0-10. Size first, then period, then wind. Hard-fail on blown-out onshore."""
    if hs is None: return None, "no data"
    eff = eff_height(spot, hs)
    if eff < 0.5: s = 0
    elif eff < HS_MIN: s = 1.5
    elif eff < HS_PRIME_LO: s = 3.5
    elif eff <= HS_PRIME_HI: s = 5.5 + 1.5 * (1 - abs(eff - 1.4) / 0.6)   # peaks ~1.4m
    elif eff <= HS_HEAVY: s = 5
    elif eff <= 3.3: s = 2.5 + 2 * spot["shelter"]
    else: s = 1 + 2 * spot["shelter"]
    if per is not None:
        if per < PERIOD_JUNK: s -= 2
        elif per < 8: s -= 0.7
        elif per >= 13: s += 1.5
        elif per >= 10: s += 1
    rel = "unknown"; kt = None
    if w and w.get("kt") is not None:
        kt = w["kt"]; rel = wind_relation(spot, w["deg"], kt)
        if rel == "glassy": s += 1.5
        elif rel == "offshore":
            s += 1.5 if kt <= 12 else (0.7 if kt <= OFF_MAX_KT else -0.8)
        elif rel == "cross":
            s -= 0.5 if kt <= 10 else (1.5 if kt <= 16 else 3)
        elif rel == "onshore":
            if kt >= ONSHORE_BLOWN: return 0, "blown"
            s -= 1 if kt <= 9 else 2.5
    return max(0, min(10, s)), rel

def tide_extremes(series):
    """series: list of (hour, height) for one day, hourly. Returns highs/lows as [(h, height)]."""
    hi, lo = [], []
    for i in range(1, len(series) - 1):
        h0, v0 = series[i]
        if v0 is None or series[i-1][1] is None or series[i+1][1] is None: continue
        if v0 >= series[i-1][1] and v0 > series[i+1][1]: hi.append((h0, v0))
        if v0 <= series[i-1][1] and v0 < series[i+1][1]: lo.append((h0, v0))
    return hi, lo

def analyse(spot, marine, alt, wind):
    M = marine["hourly"]; W = merge_wind(wind) if wind and "hourly" in wind else {}
    suns = sun_times(wind) if wind else {}
    A = {}
    if alt and "hourly" in alt:
        A = dict(zip(alt["hourly"]["time"], alt["hourly"]["wave_height"]))
    by_day = {}
    for i, t in enumerate(M["time"]):
        d = t[:10]; h = int(t[11:13])
        w = W.get(t)
        hs, per = M["wave_height"][i], M["swell_wave_period"][i] or M["wave_period"][i]
        sc, rel = hour_score(spot, hs, per, w)
        by_day.setdefault(d, []).append({
            "t":t, "h":h, "hs":hs, "swh":M["swell_wave_height"][i], "per":per, "wper":M["wave_period"][i],
            "sdeg":M["swell_wave_direction"][i] if M["swell_wave_direction"][i] is not None else M["wave_direction"][i],
            "wwh":M["wind_wave_height"][i], "tide":M["sea_level_height_msl"][i], "sst":M["sea_surface_temperature"][i],
            "kt":w["kt"] if w else None, "gust":w["gust"] if w else None, "wdeg":w["deg"] if w else None,
            "air":w["air"] if w else None, "wmodel":w["model"] if w else None,
            "rel":rel, "score":sc, "alt":A.get(t)})
    rows = []
    for di, d in enumerate(sorted(by_day)):
        hrs = by_day[d]
        sr, ss = suns.get(d, (7.5, 20.3))
        day_hrs = [x for x in hrs if sr - 0.5 <= x["h"] <= ss - 0.5 and x["score"] is not None]
        # tide extremes over the full 24h
        his, los = tide_extremes([(x["h"], x["tide"]) for x in hrs])
        tides = {"high":[[h, round(v,2)] for h,v in his], "low":[[h, round(v,2)] for h,v in los]}
        # mid-tide nudge: hours in the middle 40% of the day's range score +0.5
        tv = [x["tide"] for x in hrs if x["tide"] is not None]
        if tv and max(tv) - min(tv) > 0.5:
            lo_t, rng = min(tv), max(tv) - min(tv)
            for x in day_hrs:
                if x["tide"] is not None and 0.3 <= (x["tide"] - lo_t) / rng <= 0.7:
                    x["score"] = min(10, x["score"] + 0.5)
        best = None
        for i in range(0, max(0, len(day_hrs) - WINDOW_HRS + 1)):
            win = day_hrs[i:i+WINDOW_HRS]
            if any(x["rel"] == "blown" for x in win): continue
            m = sum(x["score"] for x in win) / len(win)
            if best is None or m > best["m"]: best = {"m":m, "win":win}
        if best is None and day_hrs:
            win = day_hrs[:WINDOW_HRS] if len(day_hrs) >= WINDOW_HRS else day_hrs
            best = {"m":0, "win":win}
        if best is None:
            continue
        win = best["win"]; score = round(best["m"], 1)
        def mean(k):
            v = [x[k] for x in win if x[k] is not None]
            return sum(v)/len(v) if v else None
        hs, per, kt = mean("hs"), mean("per"), mean("kt")
        sdeg = circ_mean([x["sdeg"] for x in win if x["sdeg"] is not None])
        wdeg = circ_mean([x["wdeg"] for x in win if x["wdeg"] is not None])
        rels = [x["rel"] for x in win]
        rel = max(set(rels), key=rels.count) if rels else "unknown"
        blown_hrs = sum(1 for x in day_hrs if x["rel"] == "blown")
        eff = eff_height(spot, hs) if hs is not None else None
        if score >= GO_SCORE: verdict = "GO"
        elif score >= MAYBE_SCORE: verdict = "MAYBE"
        else: verdict = "SKIP"
        if eff is not None and eff < HS_MIN: verdict = "SKIP"
        # alt-model spread on wave height across the window
        alts = [x["alt"] for x in win if x["alt"] is not None]
        alt_hs = sum(alts)/len(alts) if alts else None
        conf = "single-model"
        if alt_hs is not None and hs is not None:
            conf = "high (wave models agree)" if abs(alt_hs - hs) <= 0.3 else f"low (ECMWF-WAM reads {alt_hs:.1f}m)"
        if di >= 3: conf = conf.replace("high", "medium") + ", far out"
        why = build_why(spot, d, win, hs, eff, per, sdeg, kt, wdeg, rel, tides, blown_hrs, verdict, conf)
        sst = next((x["sst"] for x in hrs if x["sst"] is not None), None)
        airs = [x["air"] for x in day_hrs if x["air"] is not None]
        hourly = None
        if di <= 2:
            hourly = [{"h":x["h"], "hs":r1(x["hs"]), "per":r1(x["per"]), "sdeg":x["sdeg"],
                       "kt":r1(x["kt"]), "wdeg":x["wdeg"], "rel":x["rel"], "tide":r2(x["tide"]),
                       "sc":r1(x["score"]), "day":(sr - 0.5 <= x["h"] <= ss - 0.5)} for x in hrs]
        rows.append({"date":d, "spot":spot["name"], "n":spot["n"], "dept":spot["dept"], "sector":spot["sector"],
                     "verdict":verdict, "score":score,
                     "hs":r1(hs), "eff":r1(eff), "per":r1(per), "sdeg":round(sdeg) if sdeg is not None else None,
                     "sdir":dir16(sdeg) if sdeg is not None else None,
                     "kt":r1(kt), "wdeg":round(wdeg) if wdeg is not None else None,
                     "wdir":dir16(wdeg) if wdeg is not None else None, "rel":rel,
                     "win":[win[0]["h"], win[-1]["h"] + 1], "tides":tides,
                     "water":r1(sst), "air":r1(max(airs)) if airs else None,
                     "size":size_words(eff), "conf":conf, "alt":r1(alt_hs),
                     "wmodel":win[0]["wmodel"], "sun":[round(sr,2), round(ss,2)],
                     "why":why, "hourly":hourly, "daymax":r1(max((x["hs"] for x in hrs if x["hs"] is not None), default=None))})
    return rows

def r1(v): return None if v is None else round(v, 1)
def r2(v): return None if v is None else round(v, 2)

def circ_mean(degs):
    if not degs: return None
    xs = sum(math.sin(math.radians(d)) for d in degs); ys = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(xs, ys)) % 360

def fmt_h(h):
    return f"{int(h):02d}:00"

def tide_words(tides):
    bits = []
    for h, v in tides.get("low", []): bits.append(f"low {fmt_h(h)}")
    for h, v in tides.get("high", []): bits.append(f"high {fmt_h(h)}")
    return ", ".join(sorted(bits, key=lambda s: int(s.split()[1][:2]))) if bits else "tide n/a"

def build_why(spot, d, win, hs, eff, per, sdeg, kt, wdeg, rel, tides, blown_hrs, verdict, conf):
    t0, t1 = win[0]["h"], win[-1]["h"] + 1
    if hs is None: return "no wave data"
    size = size_words(eff)
    swell = f"{hs:.1f}m @ {per:.0f}s {dir16(sdeg) if sdeg is not None else ''}".strip()
    if spot["shelter"] >= 0.3: swell += f" (~{eff:.1f}m in here)"
    windtxt = "wind n/a"
    if kt is not None:
        wd = dir16(wdeg) if wdeg is not None else ""
        windtxt = {"glassy":f"glassy {kt:.0f}kt", "offshore":f"offshore {wd} {kt:.0f}kt",
                   "cross":f"cross-shore {wd} {kt:.0f}kt", "onshore":f"onshore {wd} {kt:.0f}kt",
                   "blown":f"blown out {wd} {kt:.0f}kt"}.get(rel, f"{wd} {kt:.0f}kt")
    lead = f"{fmt_h(t0)}-{fmt_h(t1)} {size}: {swell}, {windtxt}"
    tail = f"; {tide_words(tides)}; confidence {conf}"
    if verdict == "SKIP":
        if eff is not None and eff < HS_MIN:
            return f"too small, {size} ({swell}){tail}"
        if rel in ("onshore", "blown") or blown_hrs >= 6:
            return f"{lead}; onshore mess most of the day{tail}"
        if per is not None and per < PERIOD_JUNK:
            return f"{lead}; short-period windswell, junky{tail}"
        if eff is not None and eff > HS_HEAVY and spot["shelter"] < 0.3:
            return f"{lead}; too big for an open beach, look at the sheltered spots{tail}"
        return f"{lead}; not clean enough{tail}"
    quality = []
    if rel == "glassy": quality.append("glassy")
    elif rel == "offshore": quality.append("groomed offshore")
    elif rel == "cross": quality.append("a bit of side wind")
    elif rel == "onshore": quality.append("light onshore texture")
    if per is not None and per >= 12: quality.append("long-period groundswell")
    elif per is not None and per >= 10: quality.append("solid period")
    if eff is not None and eff > HS_HEAVY: quality.append("heavy, sheltered spots hold better")
    q = ", ".join(quality)
    return f"{lead}{'; ' + q if q else ''}{tail}"

# ---- report ----
def weekday_name(d):
    return datetime.fromisoformat(d + "T00:00").strftime("%a %d %b")

def stars(score):
    v = min(5, max(0, round(score / 2 * 2) / 2))
    full = int(v); half = 1 if v - full >= 0.5 else 0
    return "★" * full + ("½" if half else "") + "☆" * (5 - full - half)

def standouts(rows, d, k=5):
    day = [r for r in rows if r["date"] == d and r["verdict"] != "SKIP"]
    day.sort(key=lambda r: (-r["score"], r["n"]))
    return day[:k]

TAG_COLOR = {"GO":"#1a9850","MAYBE":"#f0a020","SKIP":"#999999"}

def build_html(rows, dates, today, spot_by_name):
    css = "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.5;"
    p = [f'<div style="{css}max-width:640px">']
    p.append('<h2 style="margin:0 0 4px">🏄 Wendy Surf - today\'s five</h2>')
    p.append(f'<div style="color:#666;font-size:13px;margin-bottom:14px">{weekday_name(today)} · Soulac to Biarritz · '
             f'<a href="https://sd4444.github.io/wendy-foils/surf.html">dashboard</a></div>')
    top = standouts(rows, today)
    if not top:
        p.append('<div style="background:#f2f2f2;border-left:4px solid #999;padding:12px 14px;border-radius:6px;margin-bottom:16px">'
                 '<strong>Nothing clean and waist-high today.</strong> Coast is either too small or blown out. Check tomorrow below.</div>')
    else:
        p.append('<ol style="padding-left:20px;margin:0 0 16px">')
        for r in top:
            s = spot_by_name[r["spot"]]
            c = TAG_COLOR[r["verdict"]]
            p.append(f'<li style="margin-bottom:10px"><strong>{r["spot"]}</strong> '
                     f'<span style="background:{c};color:#fff;padding:1px 7px;border-radius:10px;font-size:12px">{r["verdict"]}</span> '
                     f'{stars(r["score"])}<br><span style="font-size:14px;color:#444">{r["why"].split(";")[0]}; {tide_words(r["tides"])}</span><br>'
                     f'<span style="font-size:12px"><a href="{s["cam"]}">cam</a> · <a href="{s["report"]}">report</a> · <a href="{s["forecast"]}">forecast</a></span></li>')
        p.append('</ol>')
    # tomorrow preview
    if len(dates) > 1:
        tm = standouts(rows, dates[1], 3)
        if tm:
            p.append(f'<div style="font-size:14px;margin-bottom:14px"><strong>Tomorrow ({weekday_name(dates[1])}):</strong> ' +
                     " · ".join(f'{r["spot"]} {r["verdict"]} ({r["why"].split(":")[0]}, {r["size"]})' for r in tm) + '</div>')
        else:
            p.append(f'<div style="font-size:14px;margin-bottom:14px"><strong>Tomorrow ({weekday_name(dates[1])}):</strong> nothing clean yet.</div>')
    # water / air
    w = [r["water"] for r in rows if r["date"] == today and r["water"] is not None]
    a = [r["air"] for r in rows if r["date"] == today and r["air"] is not None]
    if w or a:
        p.append('<div style="font-size:13px;color:#555;margin-bottom:14px">' +
                 (f'Water {min(w):.0f}-{max(w):.0f}C' if w else '') + (', ' if w and a else '') +
                 (f'air up to {max(a):.0f}C' if a else '') + '.</div>')
    p.append('<div style="margin-top:16px;font-size:12px;color:#777">Source: Open-Meteo marine best_match (MFWAM / ECMWF-WAM) + '
             'Meteo-France AROME HD wind (CC BY 4.0). Cams and reports from your spot sheet. Rules: waist-high+ (0.7m+ at the beach), '
             'period 8s+ preferred, offshore or glassy best, onshore 14kt+ = blown out.</div></div>')
    return "\n".join(p)

def build_subject(rows, today):
    top = standouts(rows, today)
    if not top: return f"🏄 {weekday_name(today)}: nothing clean today"
    b = top[0]
    return (f"🏄 {weekday_name(today)}: {b['verdict']} {b['spot'].split(' – ')[0]} {b['size']}, "
            f"{fmt_h(b['win'][0])}-{fmt_h(b['win'][1])}, {len(top)} spots rideable")

def main():
    all_rows = []
    for spot in SPOTS:
        marine, alt, wind = fetch_spot(spot)
        if not marine or "hourly" not in marine:
            sys.stderr.write(f"no marine data for {spot['name']}\n"); continue
        all_rows += analyse(spot, marine, alt, wind)
    if not all_rows:
        sys.stderr.write("no data at all\n"); print("=== SURF ===\nno data"); return
    dates = sorted({r["date"] for r in all_rows})
    today = dates[0]
    spot_by_name = {s["name"]: s for s in SPOTS}

    print("=== SURF ===")
    for d in dates:
        print(f"\n{weekday_name(d)}")
        for r in sorted([r for r in all_rows if r["date"] == d], key=lambda r: (-r["score"], r["n"])):
            print(f"  {r['verdict']:<5} {r['score']:>4}  {r['spot']:<40} {r['why']}")

    flagged = {"today": today, "standouts": [{k: r[k] for k in ("date","spot","verdict","score","size","why","win")} for r in standouts(all_rows, today)],
               "tomorrow": [{k: r[k] for k in ("date","spot","verdict","score","size","why","win")} for r in standouts(all_rows, dates[1], 3)] if len(dates) > 1 else [],
               "trip": [TRIP_START, TRIP_END]}
    meta = [{k: s[k] for k in ("n","name","dept","sector","lat","lon","face","shelter","cam","report","forecast","rel","note")} for s in SPOTS]
    print(f"\n<!--SUBJECT_START-->{build_subject(all_rows, today)}<!--SUBJECT_END-->")
    print(f"<!--JSON_START-->{json.dumps(flagged, ensure_ascii=False)}<!--JSON_END-->")
    print(f"<!--SPOTS_START-->{json.dumps(meta, ensure_ascii=False)}<!--SPOTS_END-->")
    print(f"<!--GRID_START-->{json.dumps(all_rows, ensure_ascii=False)}<!--GRID_END-->")
    print(f"<!--EMAIL_HTML_START-->\n{build_html(all_rows, dates, today, spot_by_name)}\n<!--EMAIL_HTML_END-->")

if __name__ == "__main__":
    main()
