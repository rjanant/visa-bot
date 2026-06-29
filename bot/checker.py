"""
VFS Global Italy Visa Slot Checker (Edinburgh)
Monitors appointment availability and sends Gmail notification when a slot opens.
"""

import os
import time
import logging
import asyncio
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from bot.notifier import send_email_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration (loaded from environment variables) ──────────────────────────
VFS_URL = os.environ.get(
    "VFS_URL",
    "https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment",
)
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "120"))
HEADLESS = os.environ.get("HEADLESS", "true").lower() == "true"

# VFS credentials (required to reach the appointment page)
VFS_EMAIL = os.environ["VFS_EMAIL"]
VFS_PASSWORD = os.environ["VFS_PASSWORD"]

# ── Selectors (update if VFS changes their markup) ─────────────────────────────
SEL_EMAIL_INPUT    = 'input[type="email"], input[name="email"], input[placeholder*="email" i]'
SEL_PASSWORD_INPUT = 'input[type="password"]'
SEL_LOGIN_BTN      = 'button[type="submit"], button:has-text("Sign in"), button:has-text("Login")'
SEL_NO_SLOTS_TEXT  = [
    "no appointment",
    "no slots",
    "no available",
    "currently unavailable",
    "appointments are not",
    "no date",
    "no time",
]
SEL_SLOT_INDICATORS = [
    'button:has-text("Book")',
    'button:has-text("Select")',
    ".slot-available",
    ".appointment-available",
    'td.available',
    'div[class*="available"]',
]


async def login(page) -> bool:
    """Attempt to log in to VFS Global. Returns True on success."""
    log.info("Navigating to VFS Global login page …")
    await page.goto(VFS_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3_000)  # let JS settle

    # Fill email
    try:
        await page.wait_for_selector(SEL_EMAIL_INPUT, timeout=15_000)
        await page.fill(SEL_EMAIL_INPUT, VFS_EMAIL)
        log.info("Filled email field.")
    except PlaywrightTimeout:
        log.warning("Email field not found – may already be on appointment page.")

    # Fill password
    try:
        await page.wait_for_selector(SEL_PASSWORD_INPUT, timeout=5_000)
        await page.fill(SEL_PASSWORD_INPUT, VFS_PASSWORD)
        log.info("Filled password field.")
        await page.click(SEL_LOGIN_BTN)
        await page.wait_for_load_state("networkidle", timeout=30_000)
        log.info("Logged in successfully.")
    except PlaywrightTimeout:
        log.info("Password field not found – assuming already logged in or not required.")

    return True


async def check_for_slots(page) -> bool:
    """
    Returns True if an open appointment slot is detected.

    Strategy:
      1. Look for known slot-indicator elements (buttons, calendar cells).
      2. Scan page text for 'no slots' phrases — if found, return False.
      3. If neither, return False conservatively.
    """
    await page.wait_for_timeout(4_000)  # allow dynamic content to render

    page_text = (await page.inner_text("body")).lower()

    # Positive check: clickable slot elements present
    for selector in SEL_SLOT_INDICATORS:
        try:
            elements = await page.query_selector_all(selector)
            if elements:
                log.info("Slot indicator found via selector: %s (%d element(s))", selector, len(elements))
                return True
        except Exception:
            pass

    # Negative check: explicit 'no slots' language
    for phrase in SEL_NO_SLOTS_TEXT:
        if phrase in page_text:
            log.info("No-slot phrase detected: '%s'", phrase)
            return False

    # Ambiguous: log a snippet for debugging
    snippet = page_text[:300].replace("\n", " ")
    log.info("Slot status ambiguous. Page snippet: %s", snippet)
    return False


async def navigate_to_appointment_page(page) -> None:
    """After login, navigate to the Edinburgh appointment selection page."""
    # VFS uses a multi-step wizard. We try to reach the calendar step.
    # The URL already points at the appointment booking page; after login the
    # session cookie keeps us authenticated.
    current_url = page.url
    log.info("Current URL after login: %s", current_url)

    # If redirected away from the booking page, go back
    if "book-an-appointment" not in current_url:
        log.info("Redirecting to appointment booking URL …")
        await page.goto(VFS_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3_000)

    # Try clicking through the appointment wizard steps
    wizard_next_selectors = [
        'button:has-text("Continue")',
        'button:has-text("Next")',
        'button:has-text("Proceed")',
        'a:has-text("Continue")',
    ]
    for sel in wizard_next_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                log.info("Clicking wizard step: %s", sel)
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=15_000)
                await page.wait_for_timeout(2_000)
        except Exception:
            pass


async def run_check_loop() -> None:
    slot_found_already_notified = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-GB",
        )
        page = await context.new_page()

        # Suppress automation detection
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        log.info("Browser launched. Starting monitoring loop …")

        try:
            while True:
                try:
                    log.info("─── Check cycle starting at %s ───", datetime.now().strftime("%H:%M:%S"))

                    await login(page)
                    await navigate_to_appointment_page(page)

                    slot_available = await check_for_slots(page)

                    if slot_available:
                        log.info("✅  SLOT AVAILABLE!")
                        if not slot_found_already_notified:
                            send_email_notification(
                                subject="🇮🇹 Italy Visa Slot Available in Edinburgh!",
                                body=(
                                    "An appointment slot for the Italy visa application in Edinburgh "
                                    f"appears to be available!\n\n"
                                    f"👉 Book now: {VFS_URL}\n\n"
                                    f"Detected at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                    "The bot will keep checking and notify you again if more slots open."
                                ),
                            )
                            slot_found_already_notified = True
                    else:
                        log.info("❌  No slots available.")
                        # Reset flag so we notify again next time slots appear
                        slot_found_already_notified = False

                except PlaywrightTimeout as exc:
                    log.error("Playwright timeout during check: %s", exc)
                except Exception as exc:
                    log.exception("Unexpected error during check: %s", exc)
                    # Restart browser context on hard errors
                    try:
                        await page.close()
                        page = await context.new_page()
                        await page.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                        )
                    except Exception:
                        pass

                log.info("Sleeping %d seconds before next check …", CHECK_INTERVAL_SECONDS)
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_check_loop())
