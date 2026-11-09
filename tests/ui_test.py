"""End-to-end UI test in a phone-sized Chromium against the dev server (tests/devserver.mjs).
Run: python3 tests/ui_test.py  (the dev server must be running on :8765)"""
import os, sys, time, json, subprocess
from playwright.sync_api import sync_playwright

URL = os.environ.get("CC_URL", "http://localhost:8765/")
SHOTS = os.environ.get("CC_SHOTS", "/tmp/cc-shots")
os.makedirs(SHOTS, exist_ok=True)
errors = []


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name + ".png"))


def wait_text(page, sel, text, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if text in page.locator(sel).first.inner_text():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for {text!r} in {sel}: {page.locator(sel).first.inner_text()[:300]!r}")


def wait_engine(page, expr, timeout=400):
    t0 = time.time()
    while not page.evaluate(f"() => !!({expr})") and time.time() - t0 < 20:
        time.sleep(0.2)
    while page.evaluate(f"() => !!({expr})") and time.time() - t0 < timeout:
        time.sleep(0.5)


def view(page, tab):
    return page.locator(f'section.view[data-tab="{tab}"]')


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 412, "height": 892}, device_scale_factor=1, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
        page.goto(URL)
        page.wait_for_selector(".bottomnav")
        time.sleep(1.5)
        # a restore question may appear at start: answer No
        for _ in range(3):
            if page.locator(".modal-back").count():
                btn = page.locator(".modal-back .btn").first
                btn.click()
                time.sleep(0.5)
        shot(page, "01_start")
        V = view(page, "simple")
        V.get_by_role("button", name="Choose video").click()
        page.wait_for_selector(".media-item")
        page.locator(".media-item").first.click()
        page.wait_for_function("() => { const m = document.querySelector('section.view.on .stage-msg'); return m && m.hidden; }", timeout=60000)
        shot(page, "02_movie")
        # parts
        V.locator(".row", has_text="Number of parts").locator("input").fill("3")
        V.locator(".row", has_text="Number of parts").locator("input").dispatch_event("change")
        V.get_by_role("button", name="Make parts").click()
        wait_text(page, 'section.view[data-tab="simple"] .panel', "3 of 3 parts")
        shot(page, "03_parts")
        # colour
        V.locator(".chip", has_text="Colour").click()
        nf = V.locator(".nf", has_text="Exposure").locator("input.num")
        nf.fill("40"); nf.dispatch_event("change")
        nf = V.locator(".nf", has_text="Vignette").locator("input.num")
        nf.fill("50"); nf.dispatch_event("change")
        time.sleep(2.5)
        shot(page, "04_colour")
        # precision mode: fine slider + step buttons
        V.get_by_role("button", name="Precision slider").click()
        row = V.locator(".pfield", has_text="Exposure")
        before = float(row.locator("input.num").input_value())
        row.get_by_role("button", name="+0.1").click()
        row.get_by_role("button", name="+1").click()
        after = float(row.locator("input.num").input_value())
        assert abs(after - (before + 1.1)) < 0.06, (before, after)
        shot(page, "04b_precision")
        n = row.locator("input.num"); n.fill("40"); n.dispatch_event("change")
        # drag mode: drag right on the pad changes the selected control, drag down selects the next one
        V.get_by_role("button", name="Drag to adjust").click()
        V.locator(".cchips .chip", has_text="Temperature").click()
        pad = V.locator(".cd-pad")
        bb = pad.bounding_box()
        cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 60, cy, steps=6); page.mouse.up()
        v1 = V.locator(".cd-val").inner_text()
        assert v1.startswith("+") and int(v1) > 10, v1
        page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx, cy + 40, steps=6); page.mouse.up()
        assert V.locator(".cd-name").inner_text().lower().startswith("tint"), V.locator(".cd-name").inner_text()
        # drag directly on the preview picture
        cv = V.locator("canvas.preview-canvas").bounding_box()
        px, py = cv["x"] + cv["width"] / 2, cv["y"] + cv["height"] / 2
        page.mouse.move(px, py); page.mouse.down(); page.mouse.move(px - 50, py, steps=6); page.mouse.up()
        v2 = V.locator(".cd-val").inner_text()
        assert v2.startswith("-"), v2
        shot(page, "04c_drag")
        V.get_by_role("button", name="Sliders").click()
        # crop: 9:16 blur
        V.locator(".chip", has_text="Crop").click()
        V.locator(".row", has_text="Output ratio").locator("select").select_option("9:16")
        time.sleep(2.5)
        shot(page, "05_crop")
        # text with part number
        V.locator(".chip", has_text="Text").click()
        V.get_by_role("button", name="+ Add text").click()
        ta = V.locator("textarea")
        ta.fill("Part 1 नमस्ते दोस्तों")
        ta.dispatch_event("input")
        V.get_by_role("button", name="Make selected number = part number").click()
        assert "{n}" in ta.input_value(), ta.input_value()
        V.get_by_role("button", name="Center on screen").click()
        time.sleep(2.5)
        shot(page, "06_text")
        # overlay
        V.locator(".chip", has_text="Overlay").click()
        V.get_by_role("button", name="+ Add photo / video").click()
        page.wait_for_selector(".media-item")
        page.locator(".media-item", has_text="logo.png").first.click()
        time.sleep(2.5)
        shot(page, "07_overlay")
        # drag the overlay on the preview
        cv = V.locator("canvas.preview-canvas")
        box = cv.bounding_box()
        boxes = page.evaluate("() => window.ccApp.simple.last.boxes")
        ov = [x for x in boxes if x["kind"] == "overlay"][0]
        W = page.evaluate("() => window.ccApp.simple.last.W")
        k = box["width"] / W
        sx, sy = box["x"] + (ov["x"] + ov["w"] / 2) * k, box["y"] + (ov["y"] + ov["h"] / 2) * k
        page.mouse.move(sx, sy); page.mouse.down(); page.mouse.move(sx - 60, sy + 80, steps=6); page.mouse.up()
        time.sleep(2)
        it = page.evaluate("() => window.ccApp.simple.items.find(i => i.kind === 'overlay')")
        assert it["pos"] == "Custom", it
        shot(page, "08_dragged")
        # export: fast settings for the test machine
        V.locator(".chip", has_text="Export").click()
        V.locator(".row", has_text="Resolution").locator("select").select_option("480p")
        V.locator(".row", has_text="Codec").locator("select").select_option("H.264 (CPU)")
        V.locator(".row", has_text="Quality (encoder").locator("select").select_option("Fast (phone)")
        V.locator(".part input[type=checkbox]").nth(0)  # parts panel not shown here
        page.evaluate("() => { const s = window.ccApp.simple; s.parts[1].on = false; s.parts[2].on = false; s.sil.on = true; }")
        # Simple Edit = editing only: no Silence / Dialogue tabs, no cutting switches, no "cut silence" ticks
        names = page.evaluate("() => [...document.querySelectorAll('section.view[data-tab=simple] .chips .chip')].map(c => c.textContent)")
        assert "Silence" not in names and "Dialogue" not in names and "Export" in names and "Colour" in names, names
        assert V.locator(".check", has_text="Cut silent pauses").count() == 0
        assert V.locator(".check", has_text="Apply only to the first").count() == 0
        V.get_by_role("button", name="EXPORT SELECTED PARTS").click()
        wait_engine(page, "window.ccApp.simple.eng")
        wait_text(page, 'section.view[data-tab="simple"] .panel .status', "Done", timeout=60)
        shot(page, "09_exported")
        log = V.locator(".panel .log").inner_text()
        assert "Saved:" in log and "Silence" not in log and "dialogue" not in log.lower(), log[-800:]
        # the cutting tools are in AI Clipping
        page.locator(".navbtn", has_text="AI Clipping").click()
        ai_names = page.evaluate("() => [...document.querySelectorAll('section.view[data-tab=ai] .chips .chip')].map(c => c.textContent)")
        assert "Silence" in ai_names and "Dialogue" in ai_names, ai_names
        page.locator(".navbtn", has_text="Simple Edit").click()
        # project save as
        page.locator(".topbar .btn", has_text="Save").click()
        page.wait_for_selector(".modal input")
        page.locator(".modal input").fill("ui test project")
        page.locator(".modal .btn", has_text="OK").click()
        time.sleep(1.5)
        assert "ui test project" in page.locator(".proj-name").inner_text()
        # change something then reopen: the saved state must come back
        page.evaluate("() => { window.ccApp.simple.cfg.exposure = 0.9; }")
        time.sleep(3.5)
        assert "*" in page.locator(".proj-name").inner_text()
        page.locator(".topbar .btn", has_text="☰").click()
        page.get_by_role("button", name="Open project ...").click()
        page.wait_for_selector(".modal .btn")
        page.locator(".modal .btn", has_text="Don't save").click()
        page.wait_for_selector(".media-item")
        page.locator(".media-item", has_text="ui test project").click()
        time.sleep(4)
        st = page.evaluate("() => ({exp: window.ccApp.simple.cfg.exposure, parts: window.ccApp.simple.parts.length, items: window.ccApp.simple.items.length, aspect: window.ccApp.simple.cfg.aspect})")
        assert abs(st["exp"] - 0.4) < 1e-6 and st["parts"] == 3 and st["items"] == 2 and st["aspect"] == "9:16", st
        shot(page, "11_reopened")
        # auto short: stop after the first short, then continue
        page.locator(".navbtn", has_text="Auto Short").click()
        A = view(page, "auto")
        time.sleep(1)
        page.evaluate("() => { const o = window.ccApp.auto.o; o.min_len = 20; o.max_len = 30; o.end = '120'; o.scan_picture = false; window.ccApp.auto.buildSettings(); }")
        A.get_by_role("button", name="CREATE AUTO SHORTS").click()
        t0 = time.time()
        while time.time() - t0 < 300:
            if A.locator(".results .out-item").count() >= 1:
                break
            time.sleep(1)
        A.get_by_role("button", name="Stop").click()
        t0 = time.time()
        while page.evaluate("() => window.ccApp.auto.running") and time.time() - t0 < 120:
            time.sleep(0.5)
        shot(page, "12_auto_stopped")
        assert not A.get_by_role("button", name="Continue").is_disabled(), "Continue should be enabled"
        first = A.locator(".results .out-item").count()
        A.get_by_role("button", name="Continue").click()
        t0 = time.time()
        time.sleep(2)
        while page.evaluate("() => window.ccApp.auto.running") and time.time() - t0 < 600:
            time.sleep(1)
        nums = sorted(page.evaluate("() => [...document.querySelectorAll('section.view[data-tab=auto] .results .out-item .mi-name')].map(e => parseInt(e.textContent.split(' ')[1]))"))
        shot(page, "13_auto_done")
        alog = A.locator("pre.log").inner_text()
        assert "Continuing from" in alog, alog[-600:]
        print("auto short numbers:", nums, "first run:", first)
        assert nums == list(range(1, len(nums) + 1)) and len(nums) >= 3, nums
        # timeline
        page.locator(".navbtn", has_text="Timeline").click()
        T = view(page, "timeline")
        T.get_by_role("button", name="Choose video").click()
        page.wait_for_selector(".media-item")
        page.locator(".media-item").first.click()
        time.sleep(3)
        T.locator(".chip", has_text="Add").click()
        T.get_by_role("button", name="+ Text").click()
        page.wait_for_selector(".modal textarea")
        page.locator(".modal textarea").fill("Timeline text")
        page.locator(".modal textarea").dispatch_event("input")
        page.locator(".modal .btn", has_text="Save").click()
        time.sleep(2)
        T.get_by_role("button", name="+", exact=True).click()
        T.locator(".btn", has_text="Fit all").click()
        shot(page, "14_timeline")
        T.locator(".chip", has_text="Export").click()
        T.locator(".row", has_text="To (sec)").locator("input").fill("8")
        T.locator(".row", has_text="To (sec)").locator("input").dispatch_event("change")
        T.locator(".row", has_text="Resolution").locator("select").select_option("480p")
        T.locator(".row", has_text="Codec").locator("select").select_option("H.264 (CPU)")
        T.get_by_label("Quality", exact=True).select_option("Fast (phone)")
        T.locator(".btn.big", has_text="EXPORT").click()
        wait_engine(page, "window.ccApp.timeline.eng")
        wait_text(page, 'section.view[data-tab="timeline"] .panel .status', "Done", timeout=300)
        shot(page, "15_timeline_export")
        b.close()
    bad = [e for e in errors if "favicon" not in e]
    print("console errors:", json.dumps(bad[:20], indent=1))
    print("UI TEST PASSED" if not bad else "UI TEST PASSED WITH CONSOLE ERRORS")


if __name__ == "__main__":
    main()
