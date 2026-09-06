#!/usr/bin/env python3
"""
Daily webcam health check -> data/cam_status.json

For every camera URL in surf.py (best cam + alternates, 73 URLs) it records:
  - http:   status code of the page (0 = could not connect)
  - frame_age_h: for Viewsurf-hosted cameras, age in hours of the newest still the page
                 exposes (films*.viewsurf.com/<stream>/media.jpg, Last-Modified header).
                 A page can return 200 while the camera has been frozen for days
                 (Soulac, Sep 2026), so reachability alone is not enough.
  - state:  "live" | "stale" (frame older than STALE_H) | "down" (page unreachable) | "unknown"

gen_surf_dashboard.py reads this file and shows "feed down at last check" on the cam button
and card when the spot's best cam is stale or down. Runs in the GitHub Action before the
dashboard build; on any failure the previous file is kept.

Usage: python3 check_cams.py [data/cam_status.json]
"""
import os, sys, json, re, time, ssl, concurrent.futures as cf
import urllib.request, urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from surf import SPOTS

STALE_H = 24
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}
CTX = ssl.create_default_context()
FRAME_RE = re.compile(r"https?://films[a-z0-9]*\.viewsurf\.com/[A-Za-z0-9_./-]+?\.jpe?g", re.I)
STREAM_RE = re.compile(r"films[a-z0-9]*\.viewsurf\.com/([A-Za-z0-9_-]+)", re.I)
MEDIA_RE = re.compile(r"https?://[A-Za-z0-9_./-]+\.(?:mp4|jpe?g)(?:\?[^\"' ]*)?", re.I)   # other hosts (Barrel Surfing mp4, Skaping stills)
# visible timestamps: "06-09-2026 09:39:06" (Barrel Surfing), "06/09/2026 09h45" (Skaping), "06/09 09:14" (Viewsurf latest)
TEXT_TS_RE = re.compile(r"\b(\d{2})[-/](\d{2})[-/](\d{4})[ T](\d{2})[:h](\d{2})")


def fetch(url, method="GET", timeout=20):
    req = urllib.request.Request(url, headers=UA, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        body = r.read(400_000) if method == "GET" else b""
        return r.status, dict(r.headers), body.decode("utf-8", "ignore")


def text_age_hours(page_html):
    """Newest dd-mm-yyyy hh:mm timestamp printed on the page (Paris time), in hours."""
    from zoneinfo import ZoneInfo
    best = None
    for d, m, y, hh, mm in TEXT_TS_RE.findall(page_html):
        try:
            ts = datetime(int(y), int(m), int(d), int(hh), int(mm), tzinfo=ZoneInfo("Europe/Paris"))
        except ValueError:
            continue
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age < -2: continue          # a date in the future is not a frame time
        best = age if best is None else min(best, age)
    return best


def frame_age_hours(page_html, page_url=""):
    """Newest camera frame the page exposes, in hours. Viewsurf stills first; else any mp4/jpg the
    page hosts itself (Barrel Surfing clips, Skaping stills); else a printed timestamp. None if nothing."""
    cands = set(FRAME_RE.findall(page_html))
    # pv.viewsurf.com players reference the stream name; the poster still is <stream>/media.jpg
    for st in STREAM_RE.findall(page_html):
        cands.add(f"https://films.viewsurf.com/{st}/media.jpg")
    if not cands:
        # other hosts: only files that look like camera output, never the site's static images
        host = re.sub(r"^https?://([^/]+).*$", r"\1", page_url)
        camlike = re.compile(r"cam|video|live|solarmov|media|snapshot|capture|image_|/img/[^/]*\d{6,}", re.I)
        cands = {u for u in MEDIA_RE.findall(page_html) if host and host in u and camlike.search(u) and not re.search(r"logo|icon|sprite|thumb|banner|bg[-_.]", u, re.I)}
    best = None
    for u in list(cands)[:6]:
        try:
            st, hdr, _ = fetch(u, "HEAD", 12)
            lm = hdr.get("Last-Modified")
            if not lm:
                continue
            age = (datetime.now(timezone.utc) - parsedate_to_datetime(lm)).total_seconds() / 3600
            best = age if best is None else min(best, age)
        except Exception:
            continue
    # a printed "last update" timestamp counts as evidence too; the newest evidence wins
    t = text_age_hours(page_html)
    if t is not None: best = t if best is None else min(best, t)
    return None if best is None else round(best, 1)


def check(url):
    rec = {"url": url, "http": 0, "frame_age_h": None, "state": "unknown"}
    try:
        try:
            st, hdr, html = fetch(url)
        except (TimeoutError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError): raise
            time.sleep(2); st, hdr, html = fetch(url)     # one retry: a slow host is not a dead camera
        rec["http"] = st
    except urllib.error.HTTPError as e:
        rec["http"] = e.code; rec["state"] = "down" if e.code in (404, 410, 500, 502, 503) else "unknown"
        return rec
    except Exception:
        rec["state"] = "down"; return rec
    if "maintenance en cours" in html.lower():
        rec["state"] = "stale"; rec["note"] = "maintenance"; return rec
    age = frame_age_hours(html, url)
    rec["frame_age_h"] = age
    if age is not None:
        rec["state"] = "stale" if age > STALE_H else "live"
    elif st == 200:
        rec["state"] = "unknown"   # reachable, but the page gives no frame we can date (video-only players, non-Viewsurf hosts)
    return rec


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "cam_status.json")
    urls = []
    for s in SPOTS:
        urls.append(s["cam"]); urls += [a["url"] for a in s.get("cam_alts", [])]
    urls = list(dict.fromkeys(urls))
    with cf.ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(check, urls))
    status = {r["url"]: r for r in recs}
    out = {"checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stale_hours": STALE_H, "cams": status}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(out, open(out_path, "w"), indent=1)
    by = {}
    for r in recs: by[r["state"]] = by.get(r["state"], 0) + 1
    bad = [f"{s['name']}: {status[s['cam']]['state']}" + (f" ({status[s['cam']]['frame_age_h']:.0f}h)" if status[s['cam']].get("frame_age_h") else "")
           for s in SPOTS if status[s["cam"]]["state"] in ("stale", "down")]
    sys.stderr.write(f"cams: {len(urls)} urls, {by}" + (f"; best cam not live for: {'; '.join(bad)}" if bad else "") + "\n")


if __name__ == "__main__":
    main()
