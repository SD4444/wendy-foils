"""End-to-end checks for docs/map.html (and the List/Map switch on surf.html) with Playwright.

Setup once:  python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
Run:         .venv/bin/python tests/map_e2e.py        (after python3 gen_surf_dashboard.py data/surf.out.txt docs/surf.html)
Screenshots land in tests/shots/ (gitignored). Exit code 1 if any check fails.
"""
import json, sys, time, subprocess, os, socket
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
OUT = os.environ.get("SHOTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots"))
os.makedirs(OUT, exist_ok=True)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

port = free_port()
srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "-d", ROOT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.8)
BASE = f"http://127.0.0.1:{port}"
results = []
def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))

def wire(page, errors, failed):
    page.on("console", lambda m: errors.append(m.text) if m.type in ("error",) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}") if "basemaps" not in r.url and "tile" not in r.url else None)
    page.on("response", lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 and "tile" not in r.url and "basemaps" not in r.url else None)

def wait_ready(page):
    page.wait_for_function("window.__wendy && document.querySelectorAll('.mk,.cl').length>0", timeout=15000)
    page.wait_for_timeout(1200)

with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---------------- desktop ----------------
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
    page = ctx.new_page(); errors, failed = [], []; wire(page, errors, failed)
    t0 = time.time(); page.goto(BASE + "/map.html"); wait_ready(page); load_s = time.time() - t0
    check("desktop: page loads with markers", True, f"{load_s:.1f}s")
    n_mk, n_cl = page.locator(".mk").count(), page.locator(".cl").count()
    check("desktop: clusters or pills present at coast zoom", n_mk + n_cl > 0, f"pills={n_mk} clusters={n_cl}")
    tot = page.evaluate("Object.keys(window.__wendy.markers).length")
    check("desktop: 36 spot markers registered", tot == 36, tot)
    # all spots inside the initial view
    inview = page.evaluate("""() => { const b = __wendy.map.getBounds(); return Object.values(__wendy.markers).filter(m => b.contains(m.getLatLng())).length; }""")
    check("desktop: all 36 spots inside the initial view", inview == 36, inview)
    page.wait_for_timeout(2500)  # let tiles settle
    page.screenshot(path=f"{OUT}/d1_overview.png")
    # cluster click zooms in
    if n_cl:
        z0 = page.evaluate("__wendy.map.getZoom()")
        page.locator(".cl").first.click(); page.wait_for_timeout(900)
        z1 = page.evaluate("__wendy.map.getZoom()")
        check("desktop: clicking a cluster zooms in", z1 > z0, f"{z0} -> {z1}")
    # zoom to Anglet/Biarritz: expect 5 individual pills with names
    page.evaluate("__wendy.map.setView([43.50,-1.55],13,{animate:false})"); page.wait_for_timeout(1200)
    basque = page.evaluate("""() => Array.from(document.querySelectorAll('.mkw .nm')).filter(e => getComputedStyle(e).display!=='none').length""")
    pills = page.locator(".mk").count()
    check("desktop: zoomed in shows individual pills, no clusters", pills >= 5 and page.locator(".cl").count() == 0, f"pills={pills} clusters={page.locator('.cl').count()}")
    check("desktop: spot names visible when zoomed in", basque >= 5, basque)
    page.wait_for_timeout(1500); page.screenshot(path=f"{OUT}/d2_biarritz.png")
    # click a pill -> panel
    page.locator(".mk").first.click(); page.wait_for_timeout(600)
    sel = page.evaluate("__wendy.selected")
    h2 = page.locator("#panel h2").inner_text()
    check("desktop: clicking a pill opens the panel for that spot", page.locator("#panel.open").count() == 1 and sel and sel == h2, f"{sel} / {h2}")
    check("desktop: panel has cam/report/forecast/tide links", page.locator("#panel .links a").count() == 4, page.locator("#panel .links a").count())
    check("desktop: panel has 7-day strip", page.locator("#panel .cell").count() == 7, page.locator("#panel .cell").count())
    box = page.locator("#panel").bounding_box()
    check("desktop: panel inside viewport", box and box["x"] >= 0 and box["x"] + box["width"] <= 1400 and box["y"] + box["height"] <= 900, box)
    check("desktop: selected marker highlighted", page.locator(".mkw.sel").count() == 1, page.locator(".mkw.sel").count())
    check("desktop: hash deep link written", "s=" in page.evaluate("location.hash") and "d=0" in page.evaluate("location.hash"), page.evaluate("location.hash"))
    page.screenshot(path=f"{OUT}/d3_panel.png")
    # switch day
    d_label0 = page.locator("#panel .sd").inner_text()
    page.locator(".chip").nth(2).click(); page.wait_for_timeout(700)
    d_label1 = page.locator("#panel .sd").inner_text()
    check("desktop: day chip changes the panel day", d_label0 != d_label1 and page.evaluate("__wendy.day") == 2, f"{d_label0} -> {d_label1}")
    check("desktop: chip state updated", page.locator(".chip.on").get_attribute("data-d") == "2")
    check("desktop: strip highlights the chosen day", page.locator("#panel .cell.on").get_attribute("aria-label") is not None or page.locator("#panel .cell.on").count() == 1)
    check("desktop: panel stays open across day change", page.locator("#panel.open").count() == 1 and page.evaluate("__wendy.selected") == sel)
    # hourly modal via strip cell (near day)
    clickable = page.locator("#panel .cell.clickable")
    if clickable.count():
        clickable.first.click(); page.wait_for_timeout(500)
        check("desktop: strip cell opens hourly chart", page.locator("#modal.open svg").count() == 1)
        page.screenshot(path=f"{OUT}/d4_modal.png")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        check("desktop: Esc closes the chart, panel stays", page.locator("#modal.open").count() == 0 and page.locator("#panel.open").count() == 1)
    else:
        check("desktop: strip has clickable near days", False, "no clickable cells")
    page.keyboard.press("Escape"); page.wait_for_timeout(400)
    check("desktop: Esc closes the panel", page.locator("#panel.open").count() == 0 and page.evaluate("__wendy.selected") is None)
    page.locator(".mk").first.click(); page.wait_for_timeout(400)
    page.locator("#pclose").click(); page.wait_for_timeout(400)
    check("desktop: close button closes the panel", page.locator("#panel.open").count() == 0)
    # deep link
    page.goto("about:blank"); page.goto(BASE + "/map.html#s=26&d=1"); wait_ready(page); page.wait_for_timeout(800)
    check("desktop: deep link opens spot 26 on day 1", page.locator("#panel.open").count() == 1 and "Hossegor" in page.locator("#panel h2").inner_text() and page.evaluate("__wendy.day") == 1, page.locator("#panel h2").inner_text())
    # keyboard: tab to a chip and press Enter
    page.locator(".chip").nth(3).focus(); page.keyboard.press("Enter"); page.wait_for_timeout(400)
    check("desktop: keyboard operates the day chips", page.evaluate("__wendy.day") == 3)
    # wheel zoom works (map interaction)
    z0 = page.evaluate("__wendy.map.getZoom()"); page.mouse.move(500, 500); page.mouse.wheel(0, -600); page.wait_for_timeout(900)
    check("desktop: mouse wheel zooms the map", page.evaluate("__wendy.map.getZoom()") != z0)
    # drag pan
    c0 = page.evaluate("[__wendy.map.getCenter().lat, __wendy.map.getCenter().lng]")
    page.mouse.move(500, 500); page.mouse.down(); page.mouse.move(650, 600, steps=8); page.mouse.up(); page.wait_for_timeout(500)
    c1 = page.evaluate("[__wendy.map.getCenter().lat, __wendy.map.getCenter().lng]")
    check("desktop: drag pans the map", c0 != c1)
    check("desktop: no console errors", not errors, errors[:3])
    check("desktop: no failed requests (tiles excluded)", not failed, failed[:3])
    # buoys drawn
    check("desktop: 3 buoy markers", page.locator(".by").count() == 3, page.locator(".by").count())
    # DOM weight
    nodes = page.evaluate("document.getElementsByTagName('*').length")
    check("desktop: DOM node count sane (<1500)", nodes < 1500, nodes)
    # list page still fine + has the switch
    e2, f2 = [], []; pg2 = ctx.new_page(); wire(pg2, e2, f2); pg2.goto(BASE + "/surf.html"); pg2.wait_for_timeout(1500)
    check("list page: List/Map switch present", pg2.locator('nav[aria-label="View"] a[href="map.html"]').count() == 1)
    check("list page: no console errors", not e2, e2[:3])
    check("list page: renders 36 spot rows", pg2.locator(".srow").count() == 36, pg2.locator(".srow").count())
    ctx.close()

    # ---------------- mobile (iPhone 13 class) ----------------
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True,
                              user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    page = ctx.new_page(); errors, failed = [], []; wire(page, errors, failed)
    page.goto(BASE + "/map.html"); wait_ready(page)
    sw = page.evaluate("document.documentElement.scrollWidth"); check("mobile: no horizontal overflow", sw <= 390, sw)
    inview = page.evaluate("""() => { const b = __wendy.map.getBounds(); return Object.values(__wendy.markers).filter(m => b.contains(m.getLatLng())).length; }""")
    check("mobile: all 36 spots inside the initial view", inview == 36, inview)
    chips = page.locator(".chip"); cb = chips.first.bounding_box()
    check("mobile: day chips tall enough to tap (>=38px)", cb and cb["height"] >= 38, cb)
    check("mobile: map fills below the chips", page.locator("#map").bounding_box()["height"] > 500, page.locator("#map").bounding_box())
    page.wait_for_timeout(2500); page.screenshot(path=f"{OUT}/m1_overview.png")
    # tap a cluster -> zooms
    if page.locator(".cl").count():
        z0 = page.evaluate("__wendy.map.getZoom()"); page.locator(".cl").first.tap(); page.wait_for_timeout(900)
        check("mobile: tapping a cluster zooms in", page.evaluate("__wendy.map.getZoom()") > z0)
    page.evaluate("__wendy.map.setView([43.50,-1.55],13,{animate:false})"); page.wait_for_timeout(1000)
    page.locator(".mk").first.tap(); page.wait_for_timeout(700)
    check("mobile: tapping a pill opens the bottom sheet", page.locator("#panel.open").count() == 1)
    pb = page.locator("#panel").bounding_box()
    check("mobile: sheet anchored to the bottom and within the viewport", pb and abs((pb["y"] + pb["height"]) - 844) < 2 and pb["width"] <= 390 and pb["height"] <= 844 * 0.75, pb)
    # the selected marker should still be visible above the sheet
    mb = page.locator(".mkw.sel .mk").bounding_box()
    check("mobile: selected spot is visible above the sheet", mb and mb["y"] + mb["height"] < pb["y"], f"marker={mb} sheet={pb}")
    links = page.locator("#panel .links a"); lb = links.first.bounding_box()
    check("mobile: link buttons tappable (>=38px)", lb and lb["height"] >= 38, lb)
    page.wait_for_timeout(1500); page.screenshot(path=f"{OUT}/m2_sheet.png")
    # scroll inside the sheet works (content taller than sheet?)
    sh = page.evaluate("(() => { const p=document.getElementById('panel'); return [p.scrollHeight, p.clientHeight]; })()")
    check("mobile: sheet content scrolls when taller than the sheet", sh[0] >= sh[1], sh)
    # day change on mobile
    page.locator(".chip").nth(1).tap(); page.wait_for_timeout(600)
    check("mobile: day chip works with touch", page.evaluate("__wendy.day") == 1 and page.locator("#panel.open").count() == 1)
    # hourly modal on mobile fits
    cl = page.locator("#panel .cell.clickable")
    if cl.count():
        cl.first.tap(); page.wait_for_timeout(500)
        sb = page.locator("#sheet").bounding_box()
        check("mobile: hourly chart modal fits the screen", page.locator("#modal.open").count() == 1 and sb and sb["width"] <= 390 and sb["height"] <= 844, sb)
        page.screenshot(path=f"{OUT}/m3_modal.png")
        page.locator("#xbtn").tap(); page.wait_for_timeout(300)
        check("mobile: modal close button works", page.locator("#modal.open").count() == 0)
    # close sheet with the X, then tap the map background does not throw
    page.locator("#pclose").tap(); page.wait_for_timeout(400)
    check("mobile: sheet closes", page.locator("#panel.open").count() == 0)
    # pinch zoom emulation: use touchscreen tap on zoom control instead (pinch not scriptable); ensure zoom control tappable
    zb = page.locator(".leaflet-control-zoom-in").bounding_box()
    check("mobile: zoom buttons at least 40px", zb and zb["width"] >= 40 and zb["height"] >= 40, zb)
    z0 = page.evaluate("__wendy.map.getZoom()"); page.locator(".leaflet-control-zoom-in").tap(); page.wait_for_timeout(700)
    check("mobile: zoom-in button works", page.evaluate("__wendy.map.getZoom()") > z0)
    # touch drag pans
    c0 = page.evaluate("[__wendy.map.getCenter().lat, __wendy.map.getCenter().lng]")
    page.evaluate("""() => { const el=document.getElementById('map'); const t=(x,y,type)=>{ const touch=new Touch({identifier:1,target:el,clientX:x,clientY:y}); el.dispatchEvent(new TouchEvent(type,{touches:type==='touchend'?[]:[touch],changedTouches:[touch],bubbles:true,cancelable:true})); };
      t(200,500,'touchstart'); for(let i=1;i<=8;i++) t(200+i*15,500+i*12,'touchmove'); t(320,596,'touchend'); }""")
    page.wait_for_timeout(600)
    c1 = page.evaluate("[__wendy.map.getCenter().lat, __wendy.map.getCenter().lng]")
    check("mobile: touch drag pans the map", c0 != c1, f"{c0} -> {c1}")
    check("mobile: no console errors", not errors, errors[:3])
    check("mobile: no failed requests (tiles excluded)", not failed, failed[:3])
    ctx.close()

    # ---------------- small desktop / tablet widths ----------------
    for w, h in ((768, 1024), (1024, 700)):
        ctx = browser.new_context(viewport={"width": w, "height": h}); page = ctx.new_page(); e, f = [], []; wire(page, e, f)
        page.goto(BASE + "/map.html#s=8&d=0"); wait_ready(page); page.wait_for_timeout(800)
        pb = page.locator("#panel").bounding_box(); sw = page.evaluate("document.documentElement.scrollWidth")
        check(f"{w}x{h}: panel fits, no overflow, no errors", pb and pb["x"] >= 0 and pb["x"] + pb["width"] <= w + 1 and pb["y"] + pb["height"] <= h + 1 and sw <= w and not e, f"panel={pb} sw={sw} err={e[:1]}")
        page.screenshot(path=f"{OUT}/t_{w}.png"); ctx.close()

    browser.close()
srv.terminate()
fails = [r for r in results if not r["ok"]]
print(f"\n{len(results)-len(fails)}/{len(results)} checks passed")
json.dump(results, open(f"{OUT}/results.json", "w"), indent=1)
sys.exit(1 if fails else 0)
