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

Methodology (researched 2026-09-05, see CLAUDE.md section 7):
  - Size is judged on BREAKING FACE HEIGHT, not offshore Hs. Shoaling-only breaker height per
    Komar & Gaughan (1972), the form Surfline/Caldwell (2007) use: Hb = 0.39 g^(1/5) (T H0^2)^(2/5).
    A 1.2 m swell at 10 s breaks ~1.8 m (head-high); the same 1.2 m at 6 s breaks ~1.4 m.
  - Live Candhis wave buoys (Cap Ferret 03302, Anglet 06402, Saint-Jean-de-Luz 06403) via the
    public thesurfkit.com nearest-buoy endpoint. Today's model heights are bias-checked against the
    buoy (bounded correction) and the live reading is shown.
  - Tide extremes are interpolated from the hourly model level (quadratic through the peak). The
    model runs 30-60 min early vs SHOM on this coast (checked 2026-09-05), so times are marked
    approximate and each spot links to the official SHOM harbour page.
  - Per-spot tide preference from surf-forecast.com guides (Cote des Basques low, Graviere incoming,
    Lacanau any, beach breaks default mid).

Rider: lifelong wave surfer. Wants anything waist-high and up, relatively clean.
Spot list + cam/report/forecast links come from Simon's sheet
"Atlantic_France_Surf_Cams_and_Forecasts" (checked 2026-09-02).
"""

import sys, os, json, math, urllib.request, urllib.error
from datetime import datetime, date as ddate, timezone

TZ = "Europe/Paris"
FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE   = "https://marine-api.open-meteo.com/v1/marine"

TRIP_START, TRIP_END = "2026-09-14", "2026-10-04"

# ---- thresholds on BREAKING FACE HEIGHT (m, trough to crest, see breaker()) ----
FACE_MIN      = 1.0    # waist-high. Below this, SKIP.
FACE_PRIME_LO = 1.4    # chest-high and up
FACE_PRIME_HI = 2.4    # a bit overhead
FACE_HEAVY    = 3.2    # open beach breaks get heavy / closey above this
FACE_BIG      = 4.0    # double overhead, open beaches mostly unrideable
G = 9.81
def breaker(h0, t):
    """Shoaling-only breaker (face) height from deep-water height h0 and period t.
    Komar & Gaughan (1972), k = 0.39 empirical. Caldwell & Aucan (2007) use the same form."""
    if h0 is None or t is None or h0 <= 0 or t <= 0: return None
    return 0.39 * (G ** 0.2) * ((t * h0 * h0) ** 0.4)
BUOY_MAX_AGE_MIN = 180   # ignore buoy readings older than this
BIAS_CLAMP = (0.75, 1.25)  # bounded same-day correction from buoy vs model
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
  "rel":"High","note":"Official town beach camera. Good northern Médoc visual reference.","tide_pref":"mid","buoy":"cap_ferret","shom":"POINTE_DE_GRAVE"},
 {"n":2,"name":"L'Amélie","dept":"Gironde","sector":"Médoc / Soulac","lat":45.483,"lon":-1.150,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/15744-france-aquitaine-soulac-sur-mer-la-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/l-amelie/584204204e65fad6a770902d",
  "rel":"Medium","note":"Use the Soulac camera as the closest dependable visual check.","tide_pref":"mid","buoy":"cap_ferret","shom":"POINTE_DE_GRAVE"},
 {"n":3,"name":"Le Gurp","dept":"Gironde","sector":"Médoc / Soulac","lat":45.435,"lon":-1.155,"face":275,"shelter":0,
  "cam":"https://www.vendays-montalivet.fr/pratique/webcam/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-gurp/584204204e65fad6a770902f",
  "rel":"Medium","note":"No dependable dedicated camera; compare Soulac and Montalivet.","tide_pref":"mid","buoy":"cap_ferret","shom":"POINTE_DE_GRAVE"},
 {"n":4,"name":"Montalivet","dept":"Gironde","sector":"Médoc / Montalivet","lat":45.378,"lon":-1.152,"face":275,"shelter":0,
  "cam":"https://www.vendays-montalivet.fr/pratique/webcam/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/montalivet/584204204e65fad6a7709030",
  "rel":"High","note":"Official beach stream; GoSurf also carries Plage Centrale.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":5,"name":"Le Pin Sec","dept":"Gironde","sector":"Médoc / Hourtin","lat":45.302,"lon":-1.162,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/ville/vue/11106-france-aquitaine-hourtin-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-pin-sec/584204204e65fad6a7709031",
  "rel":"Medium","note":"Remote beach without a dependable dedicated feed; Hourtin is the nearest camera.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":6,"name":"Hourtin-Plage","dept":"Gironde","sector":"Médoc / Hourtin","lat":45.223,"lon":-1.172,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/ville/vue/11106-france-aquitaine-hourtin-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/hourtin-plage/584204204e65fad6a7709032",
  "rel":"Medium","note":"Beach camera is useful; do not confuse it with the lake camera.","tide_pref":"low","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":7,"name":"Carcans-Plage","dept":"Gironde","sector":"Médoc / Carcans","lat":45.085,"lon":-1.190,"face":275,"shelter":0,
  "cam":"https://m.viewsurf.com/univers/surf/vue/1255-1202898780-france-aquitaine-carcans-la-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/carcans/584204204e65fad6a7709034",
  "rel":"Medium","note":"If the feed is stale, use Lacanau only 9 km south as a regional check.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":8,"name":"Lacanau-Océan","dept":"Gironde","sector":"Lacanau","lat":45.001,"lon":-1.203,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/9/Lacanau-Plage-de-Lacanau-Ocean","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/lacanau/5842041f4e65fad6a7708c8d",
  "rel":"High","note":"Excellent coverage: Surf Club, Centrale, Nord and Supersud angles.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":9,"name":"Le Porge-Océan","dept":"Gironde","sector":"Le Porge","lat":44.885,"lon":-1.222,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-porge/584204204e65fad6a7708fe2",
  "rel":"High","note":"Official 4K panoramic camera at Plage du Gressier.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":10,"name":"La Jenny","dept":"Gironde","sector":"Le Porge","lat":44.835,"lon":-1.230,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/la-jenny/584204204e65fad6a7708fe3",
  "rel":"Medium","note":"No dedicated camera; Le Porge is the best nearby visual reference.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":11,"name":"Grand Crohot","dept":"Gironde","sector":"Cap Ferret","lat":44.740,"lon":-1.245,"face":275,"shelter":0,
  "cam":"https://barrelsurfing.fr/grand-crohot/","report":"https://barrelsurfing.fr/grand-crohot/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"High","note":"Local cam page includes wind, a 10-day forecast and Cap Ferret context.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":12,"name":"Le Truc Vert","dept":"Gironde","sector":"Cap Ferret","lat":44.705,"lon":-1.250,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-truc-vert/584204204e65fad6a7708fe5",
  "rel":"Medium","note":"TV Cap Ferret routes to the local Truc Vert and Grand Crohot feeds.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":13,"name":"La Garonne / Le Petit Train","dept":"Gironde","sector":"Cap Ferret","lat":44.670,"lon":-1.253,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Medium","note":"Use Truc Vert as the closest camera; banks can differ significantly.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":14,"name":"L'Horizon / Les Dunes / La Pointe","dept":"Gironde","sector":"Cap Ferret","lat":44.640,"lon":-1.255,"face":280,"shelter":0.1,
  "cam":"https://www.surf-forecast.com/breaks/Cap-Ferret/webcams/latest","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Low–Medium","note":"No consistently dependable dedicated ocean cam for every south-peninsula beach.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":15,"name":"La Salie Nord / Sud","dept":"Gironde","sector":"Arcachon / La Salie","lat":44.585,"lon":-1.240,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/18468-france-aquitaine-la-teste-de-buch-plage-de-la-salie","report":"https://www.surf-forecast.com/breaks/La-Salie/webcams/latest","forecast":"https://www.surfline.com/surf-report/la-salie/6418e0f89702724989875c99",
  "rel":"Low–Medium","note":"Viewsurf feed showed maintenance on 2026-09-02; check the Surf-Forecast page.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":16,"name":"Biscarrosse","dept":"Landes","sector":"North Landes","lat":44.448,"lon":-1.255,"face":275,"shelter":0,
  "cam":"https://www.biscagrandslacs.co.uk/discover/all-our-webcams","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Biscarosse-Plage/forecasts/latest/six_day",
  "rel":"High","note":"Five useful angles including Sud, Centrale, Nord and Le Vivier.","tide_pref":"any","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":17,"name":"Mimizan","dept":"Landes","sector":"North Landes","lat":44.212,"lon":-1.298,"face":275,"shelter":0,
  "cam":"https://www.mimizan-tourisme.com/en/webcams/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Mimizan/forecasts/latest/six_day",
  "rel":"High","note":"Official panoramic, north, west and south views refresh every few minutes.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":18,"name":"Contis","dept":"Landes","sector":"Central Landes","lat":44.092,"lon":-1.325,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/163/Contis-Plage-de-Contis","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"Useful regional reference for the isolated central Landes beaches.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":19,"name":"Cap de l'Homy","dept":"Landes","sector":"Central Landes","lat":44.040,"lon":-1.335,"face":275,"shelter":0,
  "cam":"https://www.surf-forecast.com/breaks/Cap-de-l-Homy/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/lit-et-mixe/cap-de-lhomy","forecast":"https://www.surfline.com/surf-report/cap-de-l-homy-plage/584204204e65fad6a7708fdb",
  "rel":"Low","note":"Surf Sentinel reports the dedicated camera as missing; compare Contis.","tide_pref":"any","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":20,"name":"Saint-Girons / La Lette Blanche","dept":"Landes","sector":"Central Landes","lat":43.955,"lon":-1.355,"face":275,"shelter":0,
  "cam":"https://fr.surf-forecast.com/breaks/Saint-Girons/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/vielle-saint-girons/saint-girons-plage","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Low","note":"Use Contis or Moliets for a broad visual read, then inspect on arrival.","tide_pref":"any","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":21,"name":"Moliets","dept":"Landes","sector":"Central Landes","lat":43.850,"lon":-1.385,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/186/Moliets-Plage-Nord","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"GoSurf also carries Centrale and Sud angles when those feeds are up.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":22,"name":"Messanges","dept":"Landes","sector":"Central Landes","lat":43.818,"lon":-1.395,"face":275,"shelter":0,
  "cam":"https://www.landesatlantiquesud.com/webcams/messanges/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://fr.surf-forecast.com/breaks/Messanges/forecasts/latest/six_day",
  "rel":"Medium","note":"Camera availability varies; Vieux-Boucau is the most dependable neighbour.","tide_pref":"any","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":23,"name":"Vieux-Boucau / Soustons","dept":"Landes","sector":"South Landes","lat":43.788,"lon":-1.415,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/85/Vieux-Boucau-Plage-de-Vieux-Boucau","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Very useful around the Courant de Soustons, where banks change fast.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":24,"name":"Seignosse – Le Penon","dept":"Landes","sector":"South Landes","lat":43.712,"lon":-1.435,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/49/Seignosse-Plage-du-Penon","report":"https://seignosse.info/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Seignosse.info adds tides and skill-level ratings in one screen.","tide_pref":"any","buoy":"anglet","shom":"CAPBRETON"},
 {"n":25,"name":"Seignosse – Bourdaines / Estagnots","dept":"Landes","sector":"South Landes","lat":43.690,"lon":-1.442,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/79/Seignosse-Plage-des-Bourdaines-Plage-des-Estagnots","report":"https://www.yadusurf.com/","forecast":"https://www.surfline.com/surf-report/les-estagnots/5842041f4e65fad6a7708c8f",
  "rel":"High","note":"YaDuSurf gives exceptionally clear written daily summaries for Estagnots.","tide_pref":"any","buoy":"anglet","shom":"CAPBRETON"},
 {"n":26,"name":"Hossegor – Centrale / Gravière / Nord","dept":"Landes","sector":"South Landes","lat":43.672,"lon":-1.445,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/21/Hossegor-La-Centrale","report":"https://www.plages-landes.info/en/hossegor-en/surf-report-hossegor/","forecast":"https://www.surfline.com/surf-report/la-graviere/5842041f4e65fad6a7708c8e",
  "rel":"High","note":"Use the camera heavily: models cannot tell which bank is working. Heavy when big.","tide_pref":"incoming","buoy":"anglet","shom":"CAPBRETON"},
 {"n":27,"name":"Capbreton – Santocha / La Piste","dept":"Landes","sector":"South Landes","lat":43.655,"lon":-1.448,"face":275,"shelter":0.2,
  "cam":"https://gosurf.fr/webcam/fr/83/Capbreton-Plage-du-Santosha-de-La-Piste","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"Often useful when Hossegor is too heavy or closing out.","tide_pref":"mid-high","buoy":"anglet","shom":"CAPBRETON"},
 {"n":28,"name":"Capbreton – Le Prévent","dept":"Landes","sector":"South Landes","lat":43.642,"lon":-1.447,"face":280,"shelter":0.6,
  "cam":"https://gosurf.fr/webcam/fr/19/Capbreton-Plage-du-Prevent","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"A different and often more sheltered view than Santocha. Holds bigger swell.","tide_pref":"mid-high","buoy":"anglet","shom":"CAPBRETON"},
 {"n":29,"name":"Labenne-Océan","dept":"Landes","sector":"South Landes","lat":43.595,"lon":-1.470,"face":275,"shelter":0,
  "cam":"https://www.landesatlantiquesud.com/en/webcams/labenne/","report":"https://www.plages-landes.info/en/labenne-en/","forecast":"https://www.surfline.com/surf-report/labenne-ocean/584204204e65fad6a7708ff2",
  "rel":"Medium","note":"Official local feed; the Sud Landes aggregator is a useful backup.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":30,"name":"Ondres-Océan","dept":"Landes","sector":"South Landes","lat":43.565,"lon":-1.485,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/5892-france-aquitaine-ondres-la-plage","report":"https://www.plages-landes.info/en/ondres-en/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Official 4K panoramic images captured roughly every few minutes.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":31,"name":"Tarnos – Le Métro / La Digue","dept":"Landes","sector":"South Landes","lat":43.537,"lon":-1.512,"face":280,"shelter":0.1,
  "cam":"https://www.surf-report.com/webcams/le-metro-tarnos-s1201.html","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/tarnos-plage/584204204e65fad6a7708ff3",
  "rel":"Medium","note":"Transitional zone between open Landes beaches and the Adour jetties.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":32,"name":"Anglet – La Barre / Cavaliers / Océan","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.520,"lon":-1.535,"face":295,"shelter":0.1,
  "cam":"https://www.anglet-tourisme.com/en/webcams-of-anglet-beaches/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/anglet/5842041f4e65fad6a7708bce",
  "rel":"High","note":"The official hub covers nearly the entire Anglet beachfront.","tide_pref":"mid","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
 {"n":33,"name":"Anglet – Madrague / Marinella / Sables d'Or","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.505,"lon":-1.540,"face":295,"shelter":0.1,
  "cam":"https://gosurf.fr/webcam/en/153/Anglet-Plage-de-Marinella-Sables-d-Or","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/marinella/584204204e65fad6a7708ff4",
  "rel":"High","note":"Best Anglet sector for comparing several adjacent peaks visually.","tide_pref":"mid","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
 {"n":34,"name":"Anglet – VVF / Le Club / Chambre d'Amour","dept":"Pyrénées-Atlantiques","sector":"Anglet","lat":43.493,"lon":-1.548,"face":300,"shelter":0.4,
  "cam":"https://www.anglet-tourisme.com/en/webcams-of-anglet-beaches/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/anglet/5842041f4e65fad6a7708bce",
  "rel":"High","note":"Often more shelter than northern Anglet under some wind and swell directions.","tide_pref":"mid-high","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
 {"n":35,"name":"Biarritz – Grande Plage","dept":"Pyrénées-Atlantiques","sector":"Biarritz","lat":43.485,"lon":-1.559,"face":325,"shelter":0.4,
  "cam":"https://www.destination-biarritz.fr/en/pratique/webcams-biarritz/","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/biarritz/5842041f4e65fad6a7708bca",
  "rel":"High","note":"Very tide-dependent and busy; check the live view immediately before going.","tide_pref":"mid-high","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
 {"n":36,"name":"Biarritz – Côte des Basques","dept":"Pyrénées-Atlantiques","sector":"Biarritz","lat":43.477,"lon":-1.567,"face":290,"shelter":0.5,
  "cam":"https://gosurf.fr/webcam/fr/7/Biarritz-La-Cote-des-Basques","report":"https://www.surf-report.com/meteo-surf/france/pays-basque/","forecast":"https://www.surfline.com/surf-report/la-cote-des-basques/5842041f4e65fad6a7708bcf",
  "rel":"High","note":"Often mellower, but the usable beach and access shrink at high tide.","tide_pref":"low","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
]

# Live Candhis wave buoys (Cerema), relayed keyless by thesurfkit.com's public nearest-buoy endpoint.
# Positions are the buoy moorings. Gironde + north/central Landes read Cap Ferret; south Landes and
# the Basque coast read Anglet. Saint-Jean-de-Luz is fetched for context on the Biarritz rows.
# ---- webcams (researched 2026-09-06, every URL opened and the frame checked; see CLAUDE.md section 7) ----
# cam = best camera for the spot. cam_dedicated False = no camera points at this beach; cam is the nearest
# working ocean cam and cam_km its distance. cam_alts = other angles or fallbacks.
CAMS = {
 1: {"cam": "https://pv.viewsurf.com/2180/Soulac", "cam_shows": "Soulac Plage Centrale seafront: promenade, cabins, lifeguard post, ocean straight ahead", "cam_type": "live video + stills", "cam_status": "STALE: no new frame since 27 Aug 2026 on any endpoint", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/15742-france-aquitaine-soulac-sur-mer-panoramique-hd", "shows": "same camera, 180-degree panorama (also frozen)"}, {"url": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "shows": "Montalivet Plage Centrale 15 km south, working live video"}]},
 2: {"cam": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "cam_shows": "Montalivet Plage Centrale 11.5 km south, live. No cam at L'Amelie; Soulac cam (3.8 km) is frozen since 27 Aug.", "cam_type": "live video + stills", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 11.5, "cam_alts": [{"url": "https://pv.viewsurf.com/2180/Soulac", "shows": "Soulac Plage Centrale 3.8 km north, frozen since 27 Aug 2026"}]},
 3: {"cam": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "cam_shows": "Montalivet Plage Centrale 6.2 km south. No cam at Le Gurp or Euronat.", "cam_type": "live video + stills", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 6.2, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/13900-france-aquitaine-vendays-montalivet-plage-nord", "shows": "Montalivet north preset looking up the beach towards Le Gurp, stills every 3 h"}]},
 4: {"cam": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "cam_shows": "Montalivet Plage Centrale from the seafront: lifeguard hut, groyne, boardwalk, lineup straight ahead; three video presets plus a 180-degree panorama", "cam_type": "live video (frame every 10 s) + stills", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/57/Montalivet-Plage-Centrale", "shows": "same stream with swell, wind and tide widgets"}, {"url": "https://viewsurf.com/univers/surf/vue/13896-france-aquitaine-vendays-montalivet-panoramique-hd", "shows": "hourly panorama of the whole beach, best for judging peak positions"}]},
 5: {"cam": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "cam_shows": "Montalivet Plage Centrale 8.6 km north. No cam at Pin Sec.", "cam_type": "live video + stills", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 8.6, "cam_alts": []},
 6: {"cam": "https://pv.viewsurf.com/1704/Vendays-Montalivet-Plage", "cam_shows": "Montalivet Plage Centrale 17.4 km north, nearest working ocean cam. No ocean cam at Hourtin-Plage.", "cam_type": "live video + stills", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 17.4, "cam_alts": [{"url": "https://pv.viewsurf.com/410/Lacanau-Plage-Nord-Surf-club", "shows": "Lacanau Plage Nord 24.5 km south, live"}, {"url": "https://viewsurf.com/univers/plage/vue/11106-france-aquitaine-hourtin-plage", "shows": "Hourtin LAKE beach at Hourtin-Port, flat water; sky and wind only, not the ocean"}]},
 7: {"cam": "https://pv.viewsurf.com/410/Lacanau-Plage-Nord-Surf-club", "cam_shows": "Lacanau Plage Nord ocean from the surf club terrace, 9.1 km south. No ocean cam at Carcans-Plage.", "cam_type": "live video + stills every 7 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 9.1, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/656-france-aquitaine-lacanau-plage-centrale", "shows": "Lacanau Plage Centrale 9.6 km south"}, {"url": "https://viewsurf.com/univers/surf/vue/1255-france-aquitaine-carcans-la-plage", "shows": "Carcans-Maubuisson LAKE beach, flat water; sky and wind only, not the ocean"}]},
 8: {"cam": "https://viewsurf.com/univers/surf/vue/658-france-aquitaine-lacanau-lacanau-surf-club", "cam_shows": "Lacanau Surf Club, Plage Nord side (main peak); official Medoc Atlantique cam", "cam_type": "stills every 30 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/656-france-aquitaine-lacanau-plage-centrale", "shows": "Plage Centrale"}, {"url": "https://viewsurf.com/univers/surf/vue/660-france-aquitaine-lacanau-poste-de-secours-nord", "shows": "Poste de Secours Nord"}, {"url": "https://viewsurf.com/univers/surf/vue/654-france-aquitaine-lacanau-sud-du-poste-de-secours-nord", "shows": "Supersud (Plage Sud, lens often fogged)"}]},
 9: {"cam": "https://www.skaping.com/medoc-plein-sud/le-porge-ocean/live", "cam_shows": "Le Porge Ocean, Plage du Gressier, 360 panorama 15 m up over the lineup", "cam_type": "stills every 5 min + video", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.allosurf.net/meteo/live/webcam-live-le-porge-plage-centrale-live-366-850-vue-2779.html", "shows": "Plage Centrale live video, same mast"}, {"url": "https://www.allosurf.net/meteo/live/webcam-live-le-porge-plage-nord-367-849-vue-2778.html", "shows": "Plage Nord video, same mast"}]},
 10: {"cam": "https://www.skaping.com/medoc-plein-sud/le-porge-ocean/live", "cam_shows": "Le Porge Gressier, 6.6 km north. No cam at La Jenny (surf-sentinel confirms).", "cam_type": "stills every 5 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 6.6, "cam_alts": [{"url": "https://barrelsurfing.fr/grand-crohot/", "shows": "Grand Crohot 10.6 km south"}]},
 11: {"cam": "https://barrelsurfing.fr/grand-crohot/", "cam_shows": "Grand Crohot beach and lineup, solar 4G cam + anemometer", "cam_type": "video clip every 30 min, wind every 20 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": []},
 12: {"cam": "https://barrelsurfing.fr/truc-vert/", "cam_shows": "Truc Vert beach and lineup, with live wind", "cam_type": "video clip every 30 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://barrelsurfing.fr/grand-crohot/", "shows": "Grand Crohot 4 km north"}]},
 13: {"cam": "https://barrelsurfing.fr/truc-vert/", "cam_shows": "Truc Vert, 3.9 km north. No cam at La Garonne on any provider.", "cam_type": "video clip every 30 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 3.9, "cam_alts": [{"url": "https://barrelsurfing.fr/grand-crohot/", "shows": "Grand Crohot 7.8 km north"}]},
 14: {"cam": "https://barrelsurfing.fr/truc-vert/", "cam_shows": "Truc Vert, 7.2 km north. No ocean-side cam for L'Horizon / Les Dunes / La Pointe anywhere.", "cam_type": "video clip every 30 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 7.2, "cam_alts": []},
 15: {"cam": "https://viewsurf.com/univers/surf/vue/18462-france-aquitaine-la-teste-de-buch-plage-de-la-salie", "cam_shows": "Plage de la Salie (main). In maintenance since at least 2 Sep.", "cam_type": "stills every 30 min when working", "cam_status": "maintenance", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/18466-france-aquitaine-la-teste-de-buch-plage-de-la-salie-nord", "shows": "La Salie Nord (maintenance)"}, {"url": "https://www.viewsurf.com/univers/surf/vue/18464-france-aquitaine-la-teste-de-buch-plage-de-la-salie-sud", "shows": "La Salie Sud (maintenance)"}, {"url": "https://viewsurf.com/univers/surf/vue/11358-france-aquitaine-biscarrosse-live", "shows": "Biscarrosse Plage 15 km south, working fallback"}]},
 16: {"cam": "https://www.biscagrandslacs.co.uk/discover/all-our-webcams/webcam-biscarrosse-plage-centrale", "cam_shows": "Plage Centrale de Biscarrosse from the lifeguard post, over the surf zone", "cam_type": "stills every 15-30 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.biscagrandslacs.co.uk/discover/all-our-webcams/webcam-biscarrosse-live-panorama", "shows": "live panoramic video sweeping the beach (the only true live feed)"}, {"url": "https://www.biscagrandslacs.co.uk/discover/all-our-webcams/webcam-biscarrosse-plage-sud", "shows": "Plage Sud"}, {"url": "https://www.biscagrandslacs.co.uk/discover/all-our-webcams/webcam-biscarrosse-plage-nord", "shows": "Plage Nord from the north roundabout"}]},
 17: {"cam": "https://www.mimizan-tourisme.com/webcams/", "cam_shows": "Plage Remember, Mimizan central beach: panoramic, north, west and south views", "cam_type": "stills every 5 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.viewsurf.com/univers/surf/vue/3112-france-aquitaine-mimizan-panoramique-video", "shows": "live panoramic video, the only live feed"}, {"url": "https://gosurf.fr/webcam/fr/184/Mimizan-Plage-Centrale", "shows": "same camera with swell/wind/tide overlay"}]},
 18: {"cam": "https://gosurf.fr/webcam/fr/163/Contis-Plage-de-Contis", "cam_shows": "Plage de Contis, main beach at the lighthouse resort", "cam_type": "stills every 10 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.viewsurf.com/univers/surf/vue/17572-france-aquitaine-contis-plage-de-contis-vue-ouest", "shows": "west view straight out to the peaks"}, {"url": "https://www.viewsurf.com/univers/surf/vue/17344-france-aquitaine-contis-panoramique-hd", "shows": "panoramic HD of beach and lineup"}]},
 19: {"cam": "https://www.viewsurf.com/univers/surf/vue/17572-france-aquitaine-contis-plage-de-contis-vue-ouest", "cam_shows": "Contis west view, 5.8 km north on the same open beach. No cam at Cap de l'Homy.", "cam_type": "stills every 10 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 5.8, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/163/Contis-Plage-de-Contis", "shows": "Contis with forecast overlay"}]},
 20: {"cam": "https://www.viewsurf.com/univers/surf/vue/14302-france-aquitaine-moliets-et-maa-nord", "cam_shows": "Moliets looking north up the beach towards Lette Blanche, 11.8 km south. No cam at Saint-Girons.", "cam_type": "stills roughly hourly", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 11.8, "cam_alts": [{"url": "https://www.viewsurf.com/univers/surf/vue/17346-france-aquitaine-contis-plage-de-contis", "shows": "Contis 15.4 km north, refreshes every 10 min"}]},
 21: {"cam": "https://gosurf.fr/webcam/fr/187/Moliets-Plage-Centrale", "cam_shows": "Moliets central beach in front of the resort, the main peaks", "cam_type": "stills, irregular, up to 15 h old overnight", "cam_status": "verified 2026-09-06, slow refresh", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/186/Moliets-Plage-Nord", "shows": "north view"}, {"url": "https://gosurf.fr/webcam/fr/188/Moliets-Plage-Sud", "shows": "south view towards Messanges"}, {"url": "https://www.viewsurf.com/univers/surf/vue/13364-france-aquitaine-moliets-et-maa-panoramique-hd", "shows": "panoramic HD, lists all 6 Moliets cams"}]},
 22: {"cam": "https://gosurf.fr/webcam/fr/85/Vieux-Boucau-Plage-de-Vieux-Boucau", "cam_shows": "Vieux-Boucau beach 3.3 km south on the same beach. No cam at Messanges.", "cam_type": "live video", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 3.3, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/188/Moliets-Plage-Sud", "shows": "Moliets looking south towards Messanges, 3.8 km north, slow refresh"}]},
 23: {"cam": "https://gosurf.fr/webcam/fr/85/Vieux-Boucau-Plage-de-Vieux-Boucau", "cam_shows": "Vieux-Boucau central beach from a beach-club roof, looking north to the jetty of the Courant de Soustons, lineup in front", "cam_type": "live video 1080p", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/2688/Vieux-Boucau-Quiksilver", "shows": "same stream, bare player"}]},
 24: {"cam": "https://gosurf.fr/webcam/fr/49/Seignosse-Plage-du-Penon", "cam_shows": "Straight-on view of the Penon lineup and shorebreak from the lifeguard post", "cam_type": "live video 1080p", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.seignosse-tourisme.com/infos/webcams-seignosse/", "shows": "official page, switches between Bourdaines, Penon, Estagnots and panoramic presets"}, {"url": "https://www.viewsurf.com/univers/surf/vue/14378-france-aquitaine-seignosse-le-penon", "shows": "hourly still looking north along the beach"}]},
 25: {"cam": "https://gosurf.fr/webcam/fr/79/Seignosse-Plage-des-Bourdaines-Plage-des-Estagnots", "cam_shows": "Les Bourdaines lineup straight on from the post. Estagnots itself only as an hourly still from this camera panned south.", "cam_type": "live video 1080p", "cam_status": "verified live 2026-09-06 (fogged by sea mist at check)", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/2368/Seignosse-Les-Bourdaines", "shows": "Estagnots preset of the same camera, one still per hour"}, {"url": "https://www.seignosse-tourisme.com/infos/webcams-seignosse/", "shows": "official page with all Seignosse presets"}]},
 26: {"cam": "https://gosurf.fr/webcam/fr/21/Hossegor-La-Centrale", "cam_shows": "Wide view along Hossegor beach looking north from the Centrale seafront towards La Graviere, lineup with surfers. Providers disagree on which peak it is named after.", "cam_type": "live video", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/170/Hossegor-Plage-de-la-Nord", "shows": "second Hossegor camera, straight-on beach and lineup, 10-min stills; GoSurf calls it La Nord, the Departement calls it Plage Centrale"}, {"url": "https://www.viewsurf.com/univers/surf/vue/2058-france-aquitaine-soorts-hossegor-plage", "shows": "same second camera with 24h archive"}]},
 27: {"cam": "https://pv.viewsurf.com/2534/Capbreton-Santocha", "cam_shows": "From the north jetty rocks looking north along Santocha: groyne in front, whole Santocha lineup, La Piste in the far distance; 4K", "cam_type": "live video 4K", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/83/Capbreton-Plage-du-Santosha-de-La-Piste", "shows": "same stream with forecast around it"}, {"url": "https://www.landesatlantiquesud.com/webcams/capbreton/", "shows": "Santocha, Prevent and two port cams on one page"}]},
 28: {"cam": "https://pv.viewsurf.com/2536/Capbreton-Plage-du-Prevent", "cam_shows": "Plage du Prevent from the seafront steps south of the port: groyne at centre, beach running south, surfers off the groyne; 4K", "cam_type": "live video 4K", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/19/Capbreton-Plage-du-Prevent", "shows": "same stream with forecast around it"}]},
 29: {"cam": "https://www.landesatlantiquesud.com/webcams/labenne/", "cam_shows": "Labenne-Ocean central beach from the lifeguard post, straight out to sea: shorebreak and lineup", "cam_type": "live video (MJPEG)", "cam_status": "verified live 2026-09-06, one 502 outage during the check", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://www.ondres.fr/la-plage/webcam/", "shows": "Ondres 3.5 km south, fallback when the Labenne stream is down"}]},
 30: {"cam": "https://www.ondres.fr/la-plage/webcam/", "cam_shows": "Ondres-Plage central access: boardwalk in front, beach and lineup straight ahead, plus a 4K panorama", "cam_type": "stills every 5 min, panorama every 15 min, 06:00-22:00", "cam_status": "verified fresh 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://viewsurf.com/univers/surf/vue/5892-france-aquitaine-ondres-la-plage", "shows": "same stills with 24h archive"}, {"url": "https://viewsurf.com/univers/surf/vue/15934-france-aquitaine-ondres-panoramique", "shows": "panorama"}]},
 31: {"cam": "https://pv.viewsurf.com/2134/Anglet-Plage-de-La-Barre-et-embouchure-de-l-Adour", "cam_shows": "Anglet La Barre and the Adour breakwater, 1.5 km across the river. Tarnos is NOT in frame; sea-state proxy only.", "cam_type": "live video", "cam_status": "verified live 2026-09-06", "cam_dedicated": False, "cam_km": 1.5, "cam_alts": [{"url": "https://www.ondres.fr/la-plage/webcam/", "shows": "Ondres 3.8 km north, does not show Tarnos"}]},
 32: {"cam": "https://pv.viewsurf.com/1994/Anglet-Plage-des-Cavaliers", "cam_shows": "Plage des Cavaliers from the dune, looking north over the lineup to the Adour breakwater; 4K", "cam_type": "live video + still every 1-2 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/2134/Anglet-Plage-de-La-Barre-et-embouchure-de-l-Adour", "shows": "La Barre and the Adour mouth, sheltered lineup"}, {"url": "https://pv.viewsurf.com/774/Anglet-Plage-de-l-Ocean", "shows": "Plage de l'Ocean, zoomed lineup"}, {"url": "https://www.anglet.fr/outils/webcams/", "shows": "City hub with all 7 Anglet beach cams"}]},
 33: {"cam": "https://pv.viewsurf.com/2130/Anglet-Panoramique-Sables-d-Or-Marinella-Corsaires", "cam_shows": "Wide view over the Sables d'Or groyne north to Marinella and Corsaires, lineup both sides", "cam_type": "live video + still every 1-2 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/2128/Anglet-Plage-des-Sables-d-Or", "shows": "Sables d'Or peak close-up from the promenade"}, {"url": "https://pv.viewsurf.com/774/Anglet-Plage-de-l-Ocean", "shows": "Plage de l'Ocean, nearest to the Madrague end (0.7 km)"}]},
 34: {"cam": "https://pv.viewsurf.com/1922/Anglet-La-petit-chambre-d-amour", "cam_shows": "Petite Chambre d'Amour / VVF from the promenade steps, looking south over the VVF peak to the Biarritz lighthouse", "cam_type": "live video + still every 1-2 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/2126/Anglet-Plage-du-Club", "shows": "Plage du Club lineup from the pergola (lens gets wet in onshore weather)"}, {"url": "https://www.skaping.com/anglet/chambre-d-amour", "shows": "360 rooftop panorama of the whole bay, stills every 30 min, crowd and size only"}]},
 35: {"cam": "https://pv.viewsurf.com/1802/Biarritz-Grande-Plage", "cam_shows": "Whole Grande Plage from the south end looking north: main peak in front of the Casino, Hotel du Palais behind", "cam_type": "live video + still every 1-2 min, daily timelapse", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://pv.viewsurf.com/772/Biarritz-Grande-Plage", "shows": "From the north end looking south, Casino on the right"}, {"url": "https://www.biarritz.fr/les-webcams", "shows": "Official hub: Grande Plage 1 and 2, Cote des Basques, Rocher de la Vierge"}]},
 36: {"cam": "https://pv.viewsurf.com/2052/Biarritz-Cote-des-basques", "cam_shows": "Cote des Basques lineup from the cliff, straight out over the main peak, shorebreak in the foreground", "cam_type": "live video + still every 1-2 min", "cam_status": "verified live 2026-09-06", "cam_dedicated": True, "cam_km": 0, "cam_alts": [{"url": "https://gosurf.fr/webcam/fr/7/Biarritz-La-Cote-des-Basques", "shows": "same camera with GoSurf forecast around it"}, {"url": "https://pv.viewsurf.com/2398/Biarritz-Rocher-de-la-Vierge", "shows": "Rocher de la Vierge, northern edge of the bay, not a surf cam"}]},
}
for _s in SPOTS: _s.update(CAMS[_s["n"]])

BUOYS = {
  "cap_ferret": {"id":"03302","name":"Cap Ferret","lat":44.6525,"lon":-1.4467},
  "anglet":     {"id":"06402","name":"Anglet","lat":43.5322,"lon":-1.6150},
  "sjdl":       {"id":"06403","name":"Saint-Jean-de-Luz","lat":43.4083,"lon":-1.6817},
}
SURFKIT = "https://thesurfkit.com/api/v2/buoys/nearest?lat={lat}&lng={lon}"

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

# ---- live buoys ----
BIAS_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "buoy_bias.json")

def roll_bias(buoys):
    """Append today's consensus/buoy ratio (plus the per-model ratios) to data/buoy_bias.json and set
    bias_rolling = median of the last 3 days per buoy. A single reading can be a fluke; three days is
    a real tendency. The per-model ratios are the evidence for weighting the models later."""
    import statistics
    try: log = json.load(open(BIAS_LOG))
    except (OSError, ValueError): log = {}
    today = datetime.now().strftime("%Y-%m-%d")
    for k, b in buoys.items():
        if b.get("bias"): log.setdefault(k, {})[today] = {"bias": b["bias"], "models": b.get("model_bias", {})}
    for k, b in buoys.items():
        recent = [(v["bias"] if isinstance(v, dict) else v) for d, v in sorted(log.get(k, {}).items())[-3:]]
        b["bias_rolling"] = round(statistics.median(recent), 2) if recent else None
    try:
        os.makedirs(os.path.dirname(BIAS_LOG), exist_ok=True)
        json.dump(log, open(BIAS_LOG, "w"), indent=1)
    except OSError as e:
        sys.stderr.write(f"WARN cannot write bias log: {e}\n")
    return buoys

WAVE_MODELS = ("best_match", "ecmwf_wam025", "ncep_gfswave025")

def fetch_buoys():
    """Latest reading per buoy + every wave model's Hs at the buoy for the same hour.
    bias = consensus mean / buoy, i.e. the same quantity the spots are sized with.
    Returns {key: {..reading.., "models", "model_hs", "bias", "model_bias"}}; missing/stale buoys are dropped."""
    from zoneinfo import ZoneInfo
    now = datetime.now(timezone.utc)
    cop = load_copernicus_raw()
    out = {}
    for key, b in BUOYS.items():
        j = try_json(SURFKIT.format(lat=b["lat"], lon=b["lon"]))
        try:
            d = j["data"]["buoy"]; lr = d["last_reading"]
            if d.get("source_identifier") != b["id"] or d.get("distance_km", 99) > 5: continue
            ts = datetime.fromisoformat(lr["time"].replace("Z", "+00:00"))
            age = (now - ts).total_seconds() / 60
            hs = lr.get("significient_height")
            if hs is None or age > BUOY_MAX_AGE_MIN: continue
        except (TypeError, KeyError, ValueError):
            continue
        rec = {"key":key, "id":b["id"], "name":b["name"], "hs":hs, "tp":lr.get("period"), "deg":lr.get("direction"),
               "sst":lr.get("water_temperature"), "age_min":round(age), "time":lr["time"],
               "models":{}, "model_hs":None, "bias":None, "model_bias":{}}
        key_t = ts.astimezone(ZoneInfo(TZ)).strftime("%Y-%m-%dT%H:00")
        for mdl in WAVE_MODELS:
            m = try_json(f"{MARINE}?latitude={b['lat']}&longitude={b['lon']}&timezone={TZ}&forecast_days=2"
                         f"&hourly=wave_height&models={mdl}")
            H = (m or {}).get("hourly", {})
            if key_t in H.get("time", []):
                mh = H["wave_height"][H["time"].index(key_t)]
                if mh is not None and mh > 0.05: rec["models"][mdl] = mh   # 0.0 = coarse grid on land
        ib = (cop.get("buoys", {}).get(key) or {}).get("hs")
        if ib and key_t in cop.get("time", []):
            v = ib[cop["time"].index(key_t)]
            if v: rec["models"]["copernicus_ibi"] = v
        if rec["models"] and hs >= 0.3:
            rec["model_hs"] = round(sum(rec["models"].values()) / len(rec["models"]), 2)
            rec["bias"] = round(rec["model_hs"] / hs, 2)
            rec["model_bias"] = {k: round(v / hs, 2) for k, v in rec["models"].items()}
        out[key] = rec
    return out

# ---- fetch ----
COPERNICUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "copernicus.json")
COPERNICUS_MAX_AGE_H = 18

def load_copernicus_raw():
    """data/copernicus.json as written by fetch_copernicus.py, or {} if missing/stale."""
    try:
        d = json.load(open(COPERNICUS_FILE))
        age_h = (datetime.now(timezone.utc) - datetime.strptime(d["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if age_h > COPERNICUS_MAX_AGE_H:
            sys.stderr.write(f"copernicus.json is {age_h:.0f}h old, ignoring\n"); return {}
        d["_age_h"] = age_h
        return d
    except Exception as e:
        sys.stderr.write(f"no copernicus data ({e})\n"); return {}

def load_copernicus():
    """Per-spot hourly Hs from the Copernicus IBI (MFWAM 1/36 deg) forecast: {spot name: {local time: hs}}."""
    d = load_copernicus_raw()
    if not d: return {}
    out = {name: {t: h for t, h in zip(d["time"], v["hs"]) if h is not None} for name, v in d["spots"].items()}
    sys.stderr.write(f"copernicus IBI loaded for {len(out)} spots ({d['_age_h']:.1f}h old)\n")
    return out

COPERNICUS = None

def fetch_spot(spot, days=7):
    global COPERNICUS
    if COPERNICUS is None: COPERNICUS = load_copernicus()
    lat, lon = spot["lat"], spot["lon"]
    murl = (f"{MARINE}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}"
            "&hourly=wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,"
            "swell_wave_direction,wind_wave_height,sea_level_height_msl,sea_surface_temperature")
    marine = try_json(murl)
    alt = {}
    for mdl in ("ecmwf_wam025", "ncep_gfswave025"):
        j = try_json(f"{MARINE}?latitude={lat}&longitude={lon}&timezone={TZ}&forecast_days={days}"
                     f"&hourly=wave_height&models={mdl}")
        if j and "hourly" in j:
            # a coarse grid can put the beach on land and return 0.0 all week: treat as missing
            alt[mdl] = {t: (h if h is not None and h > 0.05 else None)
                        for t, h in zip(j["hourly"]["time"], j["hourly"]["wave_height"])}
    if COPERNICUS.get(spot["name"]):
        alt["copernicus_ibi"] = COPERNICUS[spot["name"]]
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

def face_height(spot, hs, per, swh, swp, corr=1.0):
    """Breaking face at the spot: Komar-Gaughan breaker from the dominant component, reduced for
    shelter, times the same-day buoy correction. Swell partition is used when it carries the
    energy, otherwise the total sea with its mean period."""
    if hs is None: return None
    hb = None
    if swh is not None and swp and swh >= 0.6 * hs:
        hb = breaker(swh, swp)
        # add the wind-sea on top in quadrature so a 1 m windswell over a 0.4 m swell still counts
        rest = max(0.0, hs * hs - swh * swh) ** 0.5
        if hb is not None and rest > 0.2 and per: hb = (hb * hb + breaker(rest, min(per, 7)) ** 2) ** 0.5
    if hb is None:
        t = per or swp
        hb = breaker(hs, t) if t else hs * 1.3
    if hb is None: return None
    return hb * (1 - 0.45 * spot["shelter"]) * corr

def size_words(f):
    """Face height (m, trough to crest) in surfer words for a ~1.8 m rider."""
    if f is None: return "no data"
    if f < 0.6: return "flat"
    if f < 0.9: return "knee-high"
    if f < 1.2: return "waist-high"
    if f < 1.5: return "chest-high"
    if f < 1.9: return "head-high"
    if f < 2.5: return "overhead"
    if f < 3.3: return "well overhead"
    return "double overhead+"

def hour_score(spot, face, per, w):
    """0-10. Size (face height) first, then period, then wind. Hard-fail on blown-out onshore."""
    if face is None: return None, "no data"
    eff = face
    if eff < 0.7: s = 0
    elif eff < FACE_MIN: s = 1.5
    elif eff < FACE_PRIME_LO: s = 3.5
    elif eff <= FACE_PRIME_HI: s = 5.5 + 1.5 * (1 - abs(eff - 1.9) / 0.5)   # peaks ~head-high
    elif eff <= FACE_HEAVY: s = 5
    elif eff <= FACE_BIG: s = 2.5 + 2 * spot["shelter"]
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
    """series: list of (hour, height), hourly, ideally with the neighbouring hours of adjacent days.
    Fits a parabola through each local extreme and its neighbours so the time lands on ~10 min,
    not on the hour. Returns highs/lows as [(hour_float, height)] for hours within [0, 24)."""
    hi, lo = [], []
    for i in range(1, len(series) - 1):
        h0, v0 = series[i]
        vm, vp = series[i-1][1], series[i+1][1]
        if v0 is None or vm is None or vp is None: continue
        is_hi = v0 >= vm and v0 > vp; is_lo = v0 <= vm and v0 < vp
        if not (is_hi or is_lo): continue
        a = (vm - 2 * v0 + vp) / 2; b = (vp - vm) / 2
        off = (-b / (2 * a)) if a else 0.0
        off = max(-1.0, min(1.0, off))
        t = h0 + off; v = v0 - (b * b) / (4 * a) if a else v0
        if not (0 <= t < 24): continue
        (hi if is_hi else lo).append((round(t, 2), round(v, 2)))
    return hi, lo

def tide_state(h, tides, rng_lo, rng):
    """'low' | 'mid' | 'high' for hour h given the day's tidal range; 'incoming'/'outgoing' via slope."""
    return None

def analyse(spot, marine, alt, wind, buoys=None):
    M = marine["hourly"]; W = merge_wind(wind) if wind and "hourly" in wind else {}
    ob = (buoys or {}).get(spot["buoy"])
    corr_today = corr_tomorrow = 1.0
    if ob and ob.get("bias_rolling"):
        corr_today = max(BIAS_CLAMP[0], min(BIAS_CLAMP[1], 1.0 / ob["bias_rolling"]))
        corr_tomorrow = corr_today ** 0.5
    today_str = M["time"][0][:10]
    tomorrow_str = M["time"][24][:10] if len(M["time"]) > 24 else ""
    suns = sun_times(wind) if wind else {}
    A = alt or {}
    def consensus(t, hs):
        vals = [hs] + [A[m][t] for m in A if A[m].get(t) is not None]
        vals = [v for v in vals if v is not None]
        if not vals: return hs, None, 0
        return sum(vals) / len(vals), (max(vals) - min(vals)), len(vals)
    by_day = {}
    for i, t in enumerate(M["time"]):
        d = t[:10]; h = int(t[11:13])
        w = W.get(t)
        hs, per = M["wave_height"][i], M["swell_wave_period"][i] or M["wave_period"][i]
        corr = corr_today if d == today_str else (corr_tomorrow if d == tomorrow_str else 1.0)
        hs_c, spread, nmod = consensus(t, hs)
        # scale the swell partition with the consensus so the period-based breaker uses the agreed size
        scale = (hs_c / hs) if (hs and hs_c) else 1.0
        swh_c = M["swell_wave_height"][i] * scale if M["swell_wave_height"][i] is not None else None
        face = face_height(spot, hs_c, M["wave_period"][i], swh_c, M["swell_wave_period"][i], corr)
        hs = hs_c
        sc, rel = hour_score(spot, face, per, w)
        by_day.setdefault(d, []).append({
            "t":t, "h":h, "hs":hs, "face":face, "swh":M["swell_wave_height"][i], "per":per, "wper":M["wave_period"][i],
            "sdeg":M["swell_wave_direction"][i] if M["swell_wave_direction"][i] is not None else M["wave_direction"][i],
            "wwh":M["wind_wave_height"][i], "tide":M["sea_level_height_msl"][i], "sst":M["sea_surface_temperature"][i],
            "kt":w["kt"] if w else None, "gust":w["gust"] if w else None, "wdeg":w["deg"] if w else None,
            "air":w["air"] if w else None, "wmodel":w["model"] if w else None,
            "rel":rel, "score":sc, "spread":spread, "nmod":nmod,
            "ibi":A.get("copernicus_ibi", {}).get(t)})
    rows = []
    for di, d in enumerate(sorted(by_day)):
        hrs = by_day[d]
        sr, ss = suns.get(d, (7.5, 20.3))
        day_hrs = [x for x in hrs if sr - 0.5 <= x["h"] <= ss - 0.5 and x["score"] is not None]
        # tide extremes over the full 24h, with the neighbouring hour of the adjacent days so a
        # 23:30 or 00:20 extreme is still found and interpolated
        days_sorted = sorted(by_day)
        prev_h = [(-1, by_day[days_sorted[di-1]][-1]["tide"])] if di > 0 else []
        next_h = [(24, by_day[days_sorted[di+1]][0]["tide"])] if di + 1 < len(days_sorted) else []
        his, los = tide_extremes(prev_h + [(x["h"], x["tide"]) for x in hrs] + next_h)
        tides = {"high":[[h, v] for h,v in his], "low":[[h, v] for h,v in los]}
        # tide preference (surf-forecast.com spot guides): default beach break = mid tide either side
        tv = [x["tide"] for x in hrs if x["tide"] is not None]
        pref = spot.get("tide_pref", "mid")
        if tv and max(tv) - min(tv) > 0.5:
            lo_t, rng = min(tv), max(tv) - min(tv)
            for x in day_hrs:
                if x["tide"] is None or x["score"] is None: continue
                frac = (x["tide"] - lo_t) / rng
                nxt = next((y["tide"] for y in hrs if y["h"] == x["h"] + 1 and y["tide"] is not None), None)
                rising = nxt is not None and nxt > x["tide"]
                bonus = 0.0
                if pref == "mid" and 0.3 <= frac <= 0.7: bonus = 0.5
                elif pref == "low" and frac <= 0.4: bonus = 0.7
                elif pref == "low" and frac >= 0.8: bonus = -1.0      # Cote des Basques: no beach at high
                elif pref == "incoming" and rising and 0.2 <= frac <= 0.8: bonus = 0.7
                elif pref == "mid-high" and 0.45 <= frac <= 0.9: bonus = 0.5
                elif pref == "any": bonus = 0.2
                x["score"] = max(0, min(10, x["score"] + bonus))
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
        face = mean("face")
        sdeg = circ_mean([x["sdeg"] for x in win if x["sdeg"] is not None])
        wdeg = circ_mean([x["wdeg"] for x in win if x["wdeg"] is not None])
        rels = [x["rel"] for x in win]
        rel = max(set(rels), key=rels.count) if rels else "unknown"
        blown_hrs = sum(1 for x in day_hrs if x["rel"] == "blown")
        eff = face
        if score >= GO_SCORE: verdict = "GO"
        elif score >= MAYBE_SCORE: verdict = "MAYBE"
        else: verdict = "SKIP"
        if eff is not None and eff < FACE_MIN: verdict = "SKIP"
        # model spread on wave height across the window (MFWAM, ECMWF-WAM, GFS-Wave, Copernicus IBI)
        sps = [x["spread"] for x in win if x.get("spread") is not None]
        nmods = [x["nmod"] for x in win if x.get("nmod")]
        nm = max(nmods) if nmods else 1
        alt_hs = None
        conf = "single-model"
        if sps:
            sp = sum(sps) / len(sps)
            conf = f"high ({nm} wave models agree)" if sp <= 0.3 else f"low (wave models differ by {sp:.1f}m)"
        if di >= 3: conf = conf.replace("high", "medium") + ", far out"
        obs_note = ""
        if ob and d == today_str:
            obs_note = (f"; live buoy {ob['name']} {ob['hs']:.1f}m @ {ob['tp']:.0f}s" if ob.get("tp") else f"; live buoy {ob['name']} {ob['hs']:.1f}m")
            br = ob.get("bias_rolling")
            if br and abs(br - 1) >= 0.15:
                obs_note += f", models read {'high' if br > 1 else 'low'} x{br:.2f} lately, sized {'down' if br > 1 else 'up'}"
        why = build_why(spot, d, win, hs, eff, per, sdeg, kt, wdeg, rel, tides, blown_hrs, verdict, conf) + obs_note
        sst = next((x["sst"] for x in hrs if x["sst"] is not None), None)
        airs = [x["air"] for x in day_hrs if x["air"] is not None]
        hourly = None
        if di <= 2:
            hourly = [{"h":x["h"], "hs":r1(x["hs"]), "face":r1(x["face"]), "per":r1(x["per"]), "sdeg":x["sdeg"],
                       "kt":r1(x["kt"]), "wdeg":x["wdeg"], "rel":x["rel"], "tide":r2(x["tide"]),
                       "sc":r1(x["score"]), "day":(sr - 0.5 <= x["h"] <= ss - 0.5)} for x in hrs]
        rows.append({"date":d, "spot":spot["name"], "n":spot["n"], "dept":spot["dept"], "sector":spot["sector"],
                     "verdict":verdict, "score":score,
                     "hs":r1(hs), "face":r1(face), "eff":r1(eff), "per":r1(per),
                     "obs":(ob if d == today_str else None), "corr":(round(corr_today,2) if d == today_str else None),
                     "tide_pref":pref, "shom":f"https://maree.shom.fr/harbor/{spot['shom']}", "sdeg":round(sdeg) if sdeg is not None else None,
                     "sdir":dir16(sdeg) if sdeg is not None else None,
                     "kt":r1(kt), "wdeg":round(wdeg) if wdeg is not None else None,
                     "wdir":dir16(wdeg) if wdeg is not None else None, "rel":rel,
                     "win":[win[0]["h"], win[-1]["h"] + 1], "tides":tides,
                     "water":r1(sst), "air":r1(max(airs)) if airs else None,
                     "size":size_words(eff), "conf":conf, "alt":r1(alt_hs), "ibi":r1(mean("ibi")),
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
    m = int(round((h - int(h)) * 60))
    if m == 60: h, m = int(h) + 1, 0
    return f"{int(h):02d}:{m:02d}"

def tide_words(tides):
    bits = []
    for h, v in tides.get("low", []): bits.append(f"low {fmt_h(h)}")
    for h, v in tides.get("high", []): bits.append(f"high {fmt_h(h)}")
    return ("~" + ", ".join(sorted(bits, key=lambda s: int(s.split()[1][:2])))) if bits else "tide n/a"

def build_why(spot, d, win, hs, eff, per, sdeg, kt, wdeg, rel, tides, blown_hrs, verdict, conf):
    t0, t1 = win[0]["h"], win[-1]["h"] + 1
    if hs is None: return "no wave data"
    size = size_words(eff)
    swell = f"{hs:.1f}m @ {per:.0f}s {dir16(sdeg) if sdeg is not None else ''}".strip()
    if eff is not None: swell += f" -> ~{eff:.1f}m faces"
    if spot["shelter"] >= 0.3: swell += " (sheltered)"
    windtxt = "wind n/a"
    if kt is not None:
        wd = dir16(wdeg) if wdeg is not None else ""
        windtxt = {"glassy":f"glassy {kt:.0f}kt", "offshore":f"offshore {wd} {kt:.0f}kt",
                   "cross":f"cross-shore {wd} {kt:.0f}kt", "onshore":f"onshore {wd} {kt:.0f}kt",
                   "blown":f"blown out {wd} {kt:.0f}kt"}.get(rel, f"{wd} {kt:.0f}kt")
    lead = f"{fmt_h(t0)}-{fmt_h(t1)} {size}: {swell}, {windtxt}"
    tail = f"; {tide_words(tides)}; confidence {conf}"
    if verdict == "SKIP":
        if eff is not None and eff < FACE_MIN:
            return f"too small, {size} ({swell}){tail}"
        if rel in ("onshore", "blown") or blown_hrs >= 6:
            return f"{lead}; onshore mess most of the day{tail}"
        if per is not None and per < PERIOD_JUNK:
            return f"{lead}; short-period windswell, junky{tail}"
        if eff is not None and eff > FACE_HEAVY and spot["shelter"] < 0.3:
            return f"{lead}; too big for an open beach, look at the sheltered spots{tail}"
        return f"{lead}; not clean enough{tail}"
    quality = []
    if rel == "glassy": quality.append("glassy")
    elif rel == "offshore": quality.append("groomed offshore")
    elif rel == "cross": quality.append("a bit of side wind")
    elif rel == "onshore": quality.append("light onshore texture")
    if per is not None and per >= 12: quality.append("long-period groundswell")
    elif per is not None and per >= 10: quality.append("solid period")
    if eff is not None and eff > FACE_HEAVY: quality.append("heavy, sheltered spots hold better")
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
    p.append('<div style="margin-top:16px;font-size:12px;color:#777">Source: Copernicus Marine IBI wave forecast (MFWAM 3km, hourly) + '
             'Open-Meteo marine best_match / ECMWF-WAM / GFS-Wave (CC BY 4.0) + Meteo-France AROME HD wind; live Candhis buoys (Cerema) via thesurfkit.com; face height per Komar-Gaughan. '
             'Tide times are model-interpolated (~), check SHOM. Cams and reports from your spot sheet. Rules: waist-high+ faces (1.0m+), '
             'period 8s+ preferred, offshore or glassy best, onshore 14kt+ = blown out.</div></div>')
    return "\n".join(p)

def build_subject(rows, today):
    top = standouts(rows, today)
    if not top: return f"🏄 {weekday_name(today)}: nothing clean today"
    b = top[0]
    return (f"🏄 {weekday_name(today)}: {b['verdict']} {b['spot'].split(' – ')[0]} {b['size']}, "
            f"{fmt_h(b['win'][0])}-{fmt_h(b['win'][1])}, {len(top)} spots rideable")

def main():
    buoys = roll_bias(fetch_buoys())
    for b in buoys.values():
        sys.stderr.write(f"buoy {b['name']} {b['hs']}m @ {b['tp']}s age {b['age_min']}min consensus {b['model_hs']} bias {b['bias']} per model {b['model_bias']}\n")
    all_rows = []
    for spot in SPOTS:
        marine, alt, wind = fetch_spot(spot)
        if not marine or "hourly" not in marine:
            sys.stderr.write(f"no marine data for {spot['name']}\n"); continue
        all_rows += analyse(spot, marine, alt, wind, buoys)
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

    flagged = {"today": today, "standouts": [{k: r[k] for k in ("date","spot","verdict","score","size","face","why","win")} for r in standouts(all_rows, today)],
               "tomorrow": [{k: r[k] for k in ("date","spot","verdict","score","size","face","why","win")} for r in standouts(all_rows, dates[1], 3)] if len(dates) > 1 else [],
               "trip": [TRIP_START, TRIP_END]}
    meta = [{k: s[k] for k in ("n","name","dept","sector","lat","lon","face","shelter","cam","cam_shows","cam_type","cam_status","cam_dedicated","cam_km","cam_alts","report","forecast","rel","note","tide_pref","buoy","shom")} for s in SPOTS]
    meta_buoys = buoys
    print(f"\n<!--SUBJECT_START-->{build_subject(all_rows, today)}<!--SUBJECT_END-->")
    print(f"<!--JSON_START-->{json.dumps(flagged, ensure_ascii=False)}<!--JSON_END-->")
    print(f"<!--SPOTS_START-->{json.dumps(meta, ensure_ascii=False)}<!--SPOTS_END-->")
    print(f"<!--BUOYS_START-->{json.dumps(meta_buoys, ensure_ascii=False)}<!--BUOYS_END-->")
    print(f"<!--GRID_START-->{json.dumps(all_rows, ensure_ascii=False)}<!--GRID_END-->")
    print(f"<!--EMAIL_HTML_START-->\n{build_html(all_rows, dates, today, spot_by_name)}\n<!--EMAIL_HTML_END-->")

if __name__ == "__main__":
    main()
