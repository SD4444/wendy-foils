#!/usr/bin/env python3
"""
Copernicus Marine IBI wave forecast -> data/copernicus.json

Pulls the hourly 1/36 deg (~3 km) MFWAM forecast for the French Atlantic coast
(product IBI_ANALYSISFORECAST_WAV_005_005, dataset cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i)
in ONE request covering all surf spots, snaps every spot to its nearest ocean cell, and
writes per-spot hourly series in local time (Europe/Paris) so surf.py can join them to the
Open-Meteo hours.

Needs the `copernicusmarine` toolbox (pip install copernicusmarine) and a free Copernicus
Marine account. Credentials come from env COPERNICUS_USERNAME / COPERNICUS_PASSWORD; for
local runs the script also reads them from a `.dev.vars` file next to it (gitignored).

surf.py itself stays pure stdlib: it only reads the JSON this script writes, and falls back
to the three Open-Meteo wave models if the file is missing or stale.

Usage:  python3 fetch_copernicus.py [data/copernicus.json]
"""
import os, sys, json, math, tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = "cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i"
VARS = ["VHM0", "VTPK", "VTM10", "VMDR", "VHM0_SW1", "VTM01_SW1", "VMDR_SW1", "VHM0_WW"]
TZ = ZoneInfo("Europe/Paris")
DAYS = 7


def load_dev_vars():
    p = os.path.join(HERE, ".dev.vars")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "copernicus.json")
    load_dev_vars()
    user, pw = os.environ.get("COPERNICUS_USERNAME"), os.environ.get("COPERNICUS_PASSWORD")
    if not user or not pw:
        sys.exit("COPERNICUS_USERNAME / COPERNICUS_PASSWORD not set")

    import copernicusmarine  # heavy import, keep it inside main
    import xarray as xr
    import numpy as np
    sys.path.insert(0, HERE)
    from surf import SPOTS, BUOYS

    lats = [s["lat"] for s in SPOTS]; lons = [s["lon"] for s in SPOTS]
    # generous margin so every beach has ocean cells to its west
    bbox = dict(minimum_longitude=min(lons) - 0.25, maximum_longitude=max(lons) + 0.08,
                minimum_latitude=min(lats) - 0.08, maximum_latitude=max(lats) + 0.08)
    # start at local midnight today so day 1 in the JSON matches Open-Meteo's day 1
    start_local = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=DAYS)

    tmpdir = tempfile.mkdtemp()
    fname = "ibi_wave.nc"
    copernicusmarine.subset(
        dataset_id=DATASET, variables=VARS,
        start_datetime=start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
        end_datetime=end_utc.strftime("%Y-%m-%dT%H:%M:%S"),
        output_directory=tmpdir, output_filename=fname,
        username=user, password=pw, overwrite=True, disable_progress_bar=True, **bbox)
    ds = xr.open_dataset(os.path.join(tmpdir, fname))

    glat = ds.latitude.values; glon = ds.longitude.values
    ocean = ~np.isnan(ds["VHM0"].isel(time=0).values)  # (lat, lon)
    times = [str(t)[:19] for t in ds.time.values]
    times_local = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%Y-%m-%dT%H:%M")
                   for t in times]

    def nearest_ocean(lat, lon):
        best = None
        for i, la in enumerate(glat):
            for j, lo in enumerate(glon):
                if not ocean[i, j]:
                    continue
                d = math.hypot((la - lat) * 111.0, (lo - lon) * 111.0 * math.cos(math.radians(lat)))
                if best is None or d < best[0]:
                    best = (d, i, j)
        return best

    def series(var, i, j):
        v = ds[var].isel(latitude=i, longitude=j).values
        return [None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), 2) for x in v]

    spots = {}
    for s in SPOTS:
        hit = nearest_ocean(s["lat"], s["lon"])
        if hit is None:
            continue
        d, i, j = hit
        spots[s["name"]] = {
            "grid_lat": round(float(glat[i]), 3), "grid_lon": round(float(glon[j]), 3), "dist_km": round(d, 1),
            "hs": series("VHM0", i, j), "tp": series("VTPK", i, j), "tm": series("VTM10", i, j),
            "dir": series("VMDR", i, j), "swh": series("VHM0_SW1", i, j), "swp": series("VTM01_SW1", i, j),
            "swd": series("VMDR_SW1", i, j), "wwh": series("VHM0_WW", i, j),
        }
    buoys = {}
    for key, b in BUOYS.items():
        hit = nearest_ocean(b["lat"], b["lon"])
        if hit:
            d, i, j = hit
            buoys[key] = {"dist_km": round(d, 1), "hs": series("VHM0", i, j), "tp": series("VTPK", i, j)}
    out = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "dataset": DATASET,
           "source": "Copernicus Marine IBI_ANALYSISFORECAST_WAV_005_005 (MFWAM 1/36 deg, hourly)",
           "time": times_local, "spots": spots, "buoys": buoys}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    far = [n for n, v in spots.items() if v["dist_km"] > 6]
    sys.stderr.write(f"copernicus: {len(spots)} spots, {len(times)} hours, {times_local[0]}..{times_local[-1]}"
                     + (f"; >6km from ocean cell: {', '.join(far)}" if far else "") + "\n")


if __name__ == "__main__":
    main()
