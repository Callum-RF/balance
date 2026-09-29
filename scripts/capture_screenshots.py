r"""Capture the README screenshots into docs/screenshots/.

Real-browser (Chromium via Playwright) captures at 2x, desktop width.

Screenshots are public, so they must only ever show demo data. Run them
against a throwaway sandbox -- never the real app -- which BALANCE_DB makes
safe (seed_demo.py wipes the tables it fills, so it must not touch app.db):

  1. Install Playwright once:
       pip install playwright
       python -m playwright install chromium
  2. Seed a demo database and serve it on :8001, away from the real app:
       set BALANCE_DB=%TEMP%\balance-demo.db
       set BALANCE_NO_BACKUP=1
       set NICEGUI_STORAGE_PATH=%TEMP%\balance-demo-storage
       python scripts/seed_demo.py
       set BALANCE_PORT=8001
       python run.py
     (In the demo's Settings: Pages -> All on, and the Dark theme.)
  3. From the project root, in another terminal:
       python scripts/capture_screenshots.py

BALANCE_URL overrides the address; it defaults to the sandbox, not :8000.
"""
import os
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BALANCE_URL", "http://127.0.0.1:8001")   # the demo sandbox
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")
WIDTH = 1360

# (filename, path, viewport_height, scroll_to_text_or_None, width_or_None)
SHOTS = [
    ("dashboard.png",    "/",             1040, None, None),
    # Narrower, so the dashboard is one column and the Money & food card fills it.
    ("money-health.png", "/",             500, "Money & food", 820),
    ("transactions.png", "/transactions", 1040, None, None),
    ("food-log.png",     "/food-log",     1040, None, None),
    ("forecast.png",     "/forecast",     1120, None, None),
    ("pantry.png",       "/pantry",       1000, None, None),
]

SCROLL_JS = """(t) => {
  const el = [...document.querySelectorAll('*')]
    .find(e => e.children.length === 0 && e.textContent.trim() === t);
  if (el) { el.scrollIntoView({block: "start"}); window.scrollBy(0, -110); }  // clear the fixed top bar
  return !!el;
}"""


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": WIDTH, "height": 1040}, device_scale_factor=2)
        page = ctx.new_page()
        for name, path, height, scroll_text, width in SHOTS:
            page.set_viewport_size({"width": width or WIDTH, "height": height})
            page.goto(BASE + path, wait_until="load")
            time.sleep(2.5)  # let NiceGUI hydrate + ECharts/ring gauges render
            # The floating dock would sit over the content in a still image.
            page.add_style_tag(content=".b-dock { display: none !important; }")
            if scroll_text:
                page.evaluate(SCROLL_JS, scroll_text)
                time.sleep(1.0)
            page.screenshot(path=os.path.join(OUT, name))
            print(f"saved {name}")
        browser.close()
    print("done")


if __name__ == "__main__":
    main()
