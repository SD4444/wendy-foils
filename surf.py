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
from datetime import datetime, date as ddate

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
  "rel":"Medium","note":"Beach camera is useful; do not confuse it with the lake camera.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":7,"name":"Carcans-Plage","dept":"Gironde","sector":"Médoc / Carcans","lat":45.085,"lon":-1.190,"face":275,"shelter":0,
  "cam":"https://m.viewsurf.com/univers/surf/vue/1255-1202898780-france-aquitaine-carcans-la-plage","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/carcans/584204204e65fad6a7709034",
  "rel":"Medium","note":"If the feed is stale, use Lacanau only 9 km south as a regional check.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":8,"name":"Lacanau-Océan","dept":"Gironde","sector":"Lacanau","lat":45.001,"lon":-1.203,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/9/Lacanau-Plage-de-Lacanau-Ocean","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/lacanau/5842041f4e65fad6a7708c8d",
  "rel":"High","note":"Excellent coverage: Surf Club, Centrale, Nord and Supersud angles.","tide_pref":"any","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":9,"name":"Le Porge-Océan","dept":"Gironde","sector":"Le Porge","lat":44.885,"lon":-1.222,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-porge/584204204e65fad6a7708fe2",
  "rel":"High","note":"Official 4K panoramic camera at Plage du Gressier.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":10,"name":"La Jenny","dept":"Gironde","sector":"Le Porge","lat":44.835,"lon":-1.230,"face":275,"shelter":0,
  "cam":"https://www.medocpleinsud.com/organiser/webcam-le-porge-ocean/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/la-jenny/584204204e65fad6a7708fe3",
  "rel":"Medium","note":"No dedicated camera; Le Porge is the best nearby visual reference.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":11,"name":"Grand Crohot","dept":"Gironde","sector":"Cap Ferret","lat":44.740,"lon":-1.245,"face":275,"shelter":0,
  "cam":"https://barrelsurfing.fr/grand-crohot/","report":"https://barrelsurfing.fr/grand-crohot/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"High","note":"Local cam page includes wind, a 10-day forecast and Cap Ferret context.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":12,"name":"Le Truc Vert","dept":"Gironde","sector":"Cap Ferret","lat":44.705,"lon":-1.250,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/le-truc-vert/584204204e65fad6a7708fe5",
  "rel":"Medium","note":"TV Cap Ferret routes to the local Truc Vert and Grand Crohot feeds.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":13,"name":"La Garonne / Le Petit Train","dept":"Gironde","sector":"Cap Ferret","lat":44.670,"lon":-1.253,"face":275,"shelter":0,
  "cam":"https://tvcapferret.com/les-webcams-du-cap-ferret/","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Medium","note":"Use Truc Vert as the closest camera; banks can differ significantly.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":14,"name":"L'Horizon / Les Dunes / La Pointe","dept":"Gironde","sector":"Cap Ferret","lat":44.640,"lon":-1.255,"face":280,"shelter":0.1,
  "cam":"https://www.surf-forecast.com/breaks/Cap-Ferret/webcams/latest","report":"https://www.surf-report.com/meteo-surf/france/gironde/","forecast":"https://www.surfline.com/surf-report/cap-ferret/584204204e65fad6a7708fe7",
  "rel":"Low–Medium","note":"No consistently dependable dedicated ocean cam for every south-peninsula beach.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":15,"name":"La Salie Nord / Sud","dept":"Gironde","sector":"Arcachon / La Salie","lat":44.585,"lon":-1.240,"face":275,"shelter":0,
  "cam":"https://viewsurf.com/univers/surf/vue/18468-france-aquitaine-la-teste-de-buch-plage-de-la-salie","report":"https://www.surf-forecast.com/breaks/La-Salie/webcams/latest","forecast":"https://www.surfline.com/surf-report/la-salie/6418e0f89702724989875c99",
  "rel":"Low–Medium","note":"Viewsurf feed showed maintenance on 2026-09-02; check the Surf-Forecast page.","tide_pref":"mid","buoy":"cap_ferret","shom":"ARCACHON_EYRAC"},
 {"n":16,"name":"Biscarrosse","dept":"Landes","sector":"North Landes","lat":44.448,"lon":-1.255,"face":275,"shelter":0,
  "cam":"https://www.biscagrandslacs.co.uk/discover/all-our-webcams","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Biscarosse-Plage/forecasts/latest/six_day",
  "rel":"High","note":"Five useful angles including Sud, Centrale, Nord and Le Vivier.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":17,"name":"Mimizan","dept":"Landes","sector":"North Landes","lat":44.212,"lon":-1.298,"face":275,"shelter":0,
  "cam":"https://www.mimizan-tourisme.com/en/webcams/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/breaks/Mimizan/forecasts/latest/six_day",
  "rel":"High","note":"Official panoramic, north, west and south views refresh every few minutes.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":18,"name":"Contis","dept":"Landes","sector":"Central Landes","lat":44.092,"lon":-1.325,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/163/Contis-Plage-de-Contis","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"Useful regional reference for the isolated central Landes beaches.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":19,"name":"Cap de l'Homy","dept":"Landes","sector":"Central Landes","lat":44.040,"lon":-1.335,"face":275,"shelter":0,
  "cam":"https://www.surf-forecast.com/breaks/Cap-de-l-Homy/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/lit-et-mixe/cap-de-lhomy","forecast":"https://www.surfline.com/surf-report/cap-de-l-homy-plage/584204204e65fad6a7708fdb",
  "rel":"Low","note":"Surf Sentinel reports the dedicated camera as missing; compare Contis.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":20,"name":"Saint-Girons / La Lette Blanche","dept":"Landes","sector":"Central Landes","lat":43.955,"lon":-1.355,"face":275,"shelter":0,
  "cam":"https://fr.surf-forecast.com/breaks/Saint-Girons/webcams/latest","report":"https://www.surf-sentinel.com/surf-report/france/landes/vielle-saint-girons/saint-girons-plage","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Low","note":"Use Contis or Moliets for a broad visual read, then inspect on arrival.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":21,"name":"Moliets","dept":"Landes","sector":"Central Landes","lat":43.850,"lon":-1.385,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/186/Moliets-Plage-Nord","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"Medium","note":"GoSurf also carries Centrale and Sud angles when those feeds are up.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":22,"name":"Messanges","dept":"Landes","sector":"Central Landes","lat":43.818,"lon":-1.395,"face":275,"shelter":0,
  "cam":"https://www.landesatlantiquesud.com/webcams/messanges/","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://fr.surf-forecast.com/breaks/Messanges/forecasts/latest/six_day",
  "rel":"Medium","note":"Camera availability varies; Vieux-Boucau is the most dependable neighbour.","tide_pref":"mid","buoy":"cap_ferret","shom":"CAPBRETON"},
 {"n":23,"name":"Vieux-Boucau / Soustons","dept":"Landes","sector":"South Landes","lat":43.788,"lon":-1.415,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/85/Vieux-Boucau-Plage-de-Vieux-Boucau","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Very useful around the Courant de Soustons, where banks change fast.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":24,"name":"Seignosse – Le Penon","dept":"Landes","sector":"South Landes","lat":43.712,"lon":-1.435,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/49/Seignosse-Plage-du-Penon","report":"https://seignosse.info/","forecast":"https://www.surf-forecast.com/regions/Landes",
  "rel":"High","note":"Seignosse.info adds tides and skill-level ratings in one screen.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":25,"name":"Seignosse – Bourdaines / Estagnots","dept":"Landes","sector":"South Landes","lat":43.690,"lon":-1.442,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/79/Seignosse-Plage-des-Bourdaines-Plage-des-Estagnots","report":"https://www.yadusurf.com/","forecast":"https://www.surfline.com/surf-report/les-estagnots/5842041f4e65fad6a7708c8f",
  "rel":"High","note":"YaDuSurf gives exceptionally clear written daily summaries for Estagnots.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":26,"name":"Hossegor – Centrale / Gravière / Nord","dept":"Landes","sector":"South Landes","lat":43.672,"lon":-1.445,"face":275,"shelter":0,
  "cam":"https://gosurf.fr/webcam/fr/21/Hossegor-La-Centrale","report":"https://www.plages-landes.info/en/hossegor-en/surf-report-hossegor/","forecast":"https://www.surfline.com/surf-report/la-graviere/5842041f4e65fad6a7708c8e",
  "rel":"High","note":"Use the camera heavily: models cannot tell which bank is working. Heavy when big.","tide_pref":"incoming","buoy":"anglet","shom":"CAPBRETON"},
 {"n":27,"name":"Capbreton – Santocha / La Piste","dept":"Landes","sector":"South Landes","lat":43.655,"lon":-1.448,"face":275,"shelter":0.2,
  "cam":"https://gosurf.fr/webcam/fr/83/Capbreton-Plage-du-Santosha-de-La-Piste","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"Often useful when Hossegor is too heavy or closing out.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
 {"n":28,"name":"Capbreton – Le Prévent","dept":"Landes","sector":"South Landes","lat":43.642,"lon":-1.447,"face":280,"shelter":0.6,
  "cam":"https://gosurf.fr/webcam/fr/19/Capbreton-Plage-du-Prevent","report":"https://www.surf-report.com/meteo-surf/france/landes/","forecast":"https://www.surfline.com/surf-report/capbreton/584204204e65fad6a7708ff0",
  "rel":"High","note":"A different and often more sheltered view than Santocha. Holds bigger swell.","tide_pref":"mid","buoy":"anglet","shom":"CAPBRETON"},
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
  "rel":"High","note":"Often more shelter than northern Anglet under some wind and swell directions.","tide_pref":"mid","buoy":"anglet","shom":"BOUCAU-BAYONNE"},
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
def fetch_buoys():
    """Latest reading per buoy + the model's Hs at the buoy for the same hour -> bias ratio.
    Returns {key: {..reading.., "model_hs", "bias"}} ; missing/stale buoys are dropped."""
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc)
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
               "sst":lr.get("water_temperature"), "age_min":round(age), "time":lr["time"], "model_hs":None, "bias":None}
        # model Hs at the buoy, same hour (Paris local time series)
        m = try_json(f"{MARINE}?latitude={b['lat']}&longitude={b['lon']}&timezone={TZ}&forecast_days=2&hourly=wave_height")
        if m and "hourly" in m:
            local = ts.astimezone(timezone(timedelta(hours=2)))  # CEST during the trip
            key_t = local.strftime("%Y-%m-%dT%H:00")
            H = m["hourly"]
            if key_t in H["time"]:
                mh = H["wave_height"][H["time"].index(key_t)]
                if mh is not None and hs >= 0.3:
                    rec["model_hs"] = mh; rec["bias"] = round(mh / hs, 2)
        out[key] = rec
    return out

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

def face_height(spot, hs, per, swh, swp, corr=1.0):
    """Breaking face at the spot: Komar-Gaughan breaker from the dominant component, reduced for
    shelter, times the same-day buoy correction. Swell partition is used when it carries the
    energy, otherwise the total sea with its mean period."""
    if hs is None: return None
    if swh is not None and swp is not None and swh >= 0.6 * hs:
        hb = breaker(swh, swp)
        # add the wind-sea on top in quadrature so a 1 m windswell over a 0.4 m swell still counts
        rest = max(0.0, hs * hs - swh * swh) ** 0.5
        if rest > 0.2 and per: hb = (hb * hb + breaker(rest, min(per, 7)) ** 2) ** 0.5
    else:
        hb = breaker(hs, per) if per else hs * 1.3
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
    corr_today = 1.0
    if ob and ob.get("bias"):
        corr_today = max(BIAS_CLAMP[0], min(BIAS_CLAMP[1], 1.0 / ob["bias"]))
    today_str = M["time"][0][:10]
    suns = sun_times(wind) if wind else {}
    A = {}
    if alt and "hourly" in alt:
        A = dict(zip(alt["hourly"]["time"], alt["hourly"]["wave_height"]))
    by_day = {}
    for i, t in enumerate(M["time"]):
        d = t[:10]; h = int(t[11:13])
        w = W.get(t)
        hs, per = M["wave_height"][i], M["swell_wave_period"][i] or M["wave_period"][i]
        corr = corr_today if d == today_str else 1.0
        face = face_height(spot, hs, M["wave_period"][i], M["swell_wave_height"][i], M["swell_wave_period"][i], corr)
        sc, rel = hour_score(spot, face, per, w)
        by_day.setdefault(d, []).append({
            "t":t, "h":h, "hs":hs, "face":face, "swh":M["swell_wave_height"][i], "per":per, "wper":M["wave_period"][i],
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
        # alt-model spread on wave height across the window
        alts = [x["alt"] for x in win if x["alt"] is not None]
        alt_hs = sum(alts)/len(alts) if alts else None
        conf = "single-model"
        if alt_hs is not None and hs is not None:
            conf = "high (wave models agree)" if abs(alt_hs - hs) <= 0.3 else f"low (ECMWF-WAM reads {alt_hs:.1f}m)"
        if di >= 3: conf = conf.replace("high", "medium") + ", far out"
        obs_note = ""
        if ob and d == today_str:
            obs_note = (f"; live buoy {ob['name']} {ob['hs']:.1f}m @ {ob['tp']:.0f}s" if ob.get("tp") else f"; live buoy {ob['name']} {ob['hs']:.1f}m")
            if ob.get("bias") and abs(ob["bias"] - 1) >= 0.15:
                obs_note += f", models read {'high' if ob['bias'] > 1 else 'low'} x{ob['bias']:.2f}, sized {'down' if ob['bias'] > 1 else 'up'} today"
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
    p.append('<div style="margin-top:16px;font-size:12px;color:#777">Source: Open-Meteo marine best_match (MFWAM / ECMWF-WAM) + '
             'Meteo-France AROME HD wind (CC BY 4.0); live Candhis buoys (Cerema) via thesurfkit.com; face height per Komar-Gaughan. '
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
    buoys = fetch_buoys()
    for b in buoys.values():
        sys.stderr.write(f"buoy {b['name']} {b['hs']}m @ {b['tp']}s age {b['age_min']}min model {b['model_hs']} bias {b['bias']}\n")
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
    meta = [{k: s[k] for k in ("n","name","dept","sector","lat","lon","face","shelter","cam","report","forecast","rel","note","tide_pref","buoy","shom")} for s in SPOTS]
    meta_buoys = buoys
    print(f"\n<!--SUBJECT_START-->{build_subject(all_rows, today)}<!--SUBJECT_END-->")
    print(f"<!--JSON_START-->{json.dumps(flagged, ensure_ascii=False)}<!--JSON_END-->")
    print(f"<!--SPOTS_START-->{json.dumps(meta, ensure_ascii=False)}<!--SPOTS_END-->")
    print(f"<!--BUOYS_START-->{json.dumps(meta_buoys, ensure_ascii=False)}<!--BUOYS_END-->")
    print(f"<!--GRID_START-->{json.dumps(all_rows, ensure_ascii=False)}<!--GRID_END-->")
    print(f"<!--EMAIL_HTML_START-->\n{build_html(all_rows, dates, today, spot_by_name)}\n<!--EMAIL_HTML_END-->")

if __name__ == "__main__":
    main()
