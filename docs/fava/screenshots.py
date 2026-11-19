"""Regenerate the Fava extension screenshots in ``images/`` from ``example.beancount``.

Run from the repository root:

    uv run --with playwright python docs/fava/screenshots.py

(If Playwright has no browser yet, first run
``uv run --with playwright playwright install chromium``.)

It serves the example ledger with Fava on a free port, opens each extension's
page in headless Chromium and saves the page's content area as a PNG. It only
looks at pages: Batch Edit's search is previewed, never applied.
"""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).parent
LEDGER = HERE / "example.beancount"
IMAGES = HERE / "images"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            urllib.request.urlopen(url)
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.25)


# The bounds of an element's content, in page coordinates, so a screenshot covers
# all of it without the empty space below: Fava's content area fills the window
# and scrolls, so it can be taller or shorter than what's in it. The margin adds
# space to the right and below.
CONTENT_BOUNDS = """([selector, margin]) => {
  const element = document.querySelector(selector);
  const box = element.getBoundingClientRect();
  const children = [...element.children].map((child) => child.getBoundingClientRect());
  const bottom = Math.max(...children.map((child) => child.bottom)) + element.scrollTop;
  const right = Math.max(box.right, ...children.map((child) => child.right));
  const width = right - box.left + margin;
  return {x: box.left, y: box.top, width, height: bottom - box.top + margin};
}"""


def save(page: Page, name: str, selector: str = "article", margin: int = 24) -> None:
    """Save the element's content as ``images/<name>.png``."""
    bounds = page.evaluate(CONTENT_BOUNDS, [selector, margin])
    viewport = page.viewport_size
    page.set_viewport_size(
        {
            "width": max(viewport["width"], int(bounds["x"] + bounds["width"])),
            "height": max(viewport["height"], int(bounds["y"] + bounds["height"])),
        }
    )
    page.screenshot(path=IMAGES / f"{name}.png", clip=bounds, animations="disabled")
    page.set_viewport_size(viewport)
    print(f"wrote {IMAGES / name}.png")


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}/example/extension"
    fava = subprocess.Popen(
        ["fava", str(LEDGER), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(f"{base}/Checkbook/")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1300, "height": 800}, device_scale_factor=2)

            page.goto(f"{base}/Checkbook/", wait_until="networkidle")
            save(page, "checkbook")

            search = "payee_regex=sq%20%5C*corner&new_payee=%7Bplaid_payee%7D"
            page.goto(f"{base}/BatchEdit/?{search}", wait_until="networkidle")
            page.locator("#batch-edit-apply").wait_for()
            save(page, "batch-edit")

            page.goto(f"{base}/CreditCardRewards/", wait_until="networkidle")
            page.get_by_text("Icicle", exact=True).click()
            save(page, "rewards")

            page.goto(f"{base}/UpdateStatus/", wait_until="networkidle")
            save(page, "update-status")

            page.goto(f"{base}/Travel/", wait_until="networkidle")
            page.get_by_text("Icicle", exact=True).click()
            save(page, "travel")
            page.click('a[href*="chart=Over"]')
            page.wait_for_load_state("networkidle")
            save(page, "travel-over-time", "svelte-component", margin=0)

            page.goto(f"{base}/PayeeReview/", wait_until="networkidle")
            save(page, "payees")

            browser.close()
    finally:
        fava.terminate()
        fava.wait()


if __name__ == "__main__":
    main()
