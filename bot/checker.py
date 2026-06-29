"""
VFS Global Italy Visa Slot Checker (Edinburgh)
Monitors appointment availability and sends a Gmail notification when a slot opens.

VFS Global flow (UK → Italy):
  1. Land on /gbr/en/ita/book-an-appointment  (public landing page)
  2. Click the "Start New Booking" / "Book Appointment" button
     → redirects to VFS auth (accounts.vfsglobal.com or similar)
  3. Enter email → enter password → submit
  4. Redirected back into the booking wizard
  5. Wizard step 1: select visa category  (e.g. "Schengen Visa")
  6. Wizard step 2: select visa sub-category
  7. Wizard step 3: select appointment centre  → pick "Edinburgh"
  8. Wizard step 4: calendar / slot picker — THIS is what we read
  9. If "No slots" message → no availability; if dates/times shown → SLOT FOUND
"""

import os
import logging
import asyncio
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout, Page

from bot.notifier import send_email_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
VFS_LANDING = "https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment"
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "120"))
HEADLESS = os.environ.get("HEADLESS", "true").lower() == "true"

VFS_EMAIL    = os.environ["VFS_EMAIL"]
VFS_PASSWORD = os.environ["VFS_PASSWORD"]

# ── Phrases that VFS shows when NO slots exist ─────────────────────────────────
NO_SLOT_PHRASES = [
    "no appointments available",
    "no appointment slots",
    "no slots available",
    "no available appointment",
    "appointments are not available",
    "there are no appointments",
    "no dates available",
    "currently no appointment",
    "no booking slots",
]

# ── Positive indicators that slots DO exist ────────────────────────────────────
# (calendar dates that are clickable, or explicit available-slot elements)
SLOT_SELECTORS = [
    "td.available-date",
    "td.day:not(.disabled):not(.past)",
    "button.calendar-day:not([disabled])",
    "div.available",
    ".slot-time",
    "li.time-slot",
    "td[class*='available']",
    "div[class*='available-slot']",
    "input[type='radio'][value*='slot']",
    ".mat-calendar-body-cell:not(.mat-calendar-body-disabled)",  # Angular Material
]


# ── Helpers ────────────────────────────────────────────────────────────────────

async def dump_page_state(page: Page, label: str) -> None:
    """Log current URL + first 600 chars of body text. Helps debug wizard state."""
    try:
        text = (await page.inner_text("body")).replace("\n", " ")[:600]
    except Exception:
        text = "<could not read body>"
    log.info("[%s] URL: %s", label, page.url)
    log.info("[%s] Body: %s", label, text)


async def safe_click(page: Page, selector: str, description: str, timeout: int = 8_000) -> bool:
    """Click a selector if it exists. Returns True if clicked."""
    try:
        await page.wait_for_selector(selector, timeout=timeout, state="visible")
        await page.click(selector)
        log.info("Clicked: %s", description)
        return True
    except PlaywrightTimeout:
        return False
    except Exception as exc:
        log.debug("safe_click(%s) failed: %s", description, exc)
        return False


async def wait_for_navigation_or_content(page: Page, timeout: int = 15_000) -> None:
    """Wait for network to quiet down after an action."""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeout:
        pass  # networkidle can be flaky on SPAs; just continue
    await page.wait_for_timeout(2_000)


# ── Step 1: navigate and trigger login ────────────────────────────────────────

async def navigate_and_login(page: Page) -> bool:
    """
    Go to the VFS landing page, click through to the auth page, and log in.
    Returns True if we appear to be logged in after this function completes.
    """
    log.info("── Step 1: Loading VFS landing page …")
    await page.goto(VFS_LANDING, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(4_000)
    await dump_page_state(page, "landing")

    # If we're already inside the wizard (session still alive), skip login
    if await _is_inside_wizard(page):
        log.info("Session still active — skipping login.")
        return True

    # ── Click the main CTA button to enter the booking flow ───────────────────
    cta_selectors = [
        'a:has-text("Start New Booking")',
        'a:has-text("Book Appointment")',
        'button:has-text("Start New Booking")',
        'button:has-text("Book Appointment")',
        'a[href*="book"]',
        '.book-appointment-btn',
        'a:has-text("Book an Appointment")',
    ]
    clicked_cta = False
    for sel in cta_selectors:
        if await safe_click(page, sel, f"CTA button [{sel}]", timeout=5_000):
            clicked_cta = True
            break

    if not clicked_cta:
        # Fallback: VFS sometimes puts the link in the nav
        log.warning("Primary CTA button not found. Trying nav links …")
        await dump_page_state(page, "cta-not-found")

    await wait_for_navigation_or_content(page, timeout=20_000)
    await dump_page_state(page, "after-cta")

    # ── Now we should be on the auth/login page ────────────────────────────────
    return await _do_login(page)


async def _do_login(page: Page) -> bool:
    """Fill in email + password on whatever login form VFS shows."""

    # Some VFS portals show email first, then password on the next screen.
    # Others show both on one screen.
    log.info("── Step 2: Attempting login …")

    # Email field
    email_sel = 'input[type="email"], input[name="email"], input[id*="email" i], input[placeholder*="email" i]'
    try:
        await page.wait_for_selector(email_sel, timeout=15_000, state="visible")
        await page.fill(email_sel, VFS_EMAIL)
        log.info("Filled email.")
    except PlaywrightTimeout:
        log.warning("Email input not found — may be on a different auth page.")
        await dump_page_state(page, "login-no-email")
        # Try clicking a sign-in/login link if we landed on an info page
        for link_text in ["Sign In", "Login", "Log In", "Sign in to continue"]:
            if await safe_click(page, f'a:has-text("{link_text}"), button:has-text("{link_text}")', link_text, timeout=4_000):
                await wait_for_navigation_or_content(page)
                try:
                    await page.wait_for_selector(email_sel, timeout=10_000, state="visible")
                    await page.fill(email_sel, VFS_EMAIL)
                    log.info("Filled email (after sign-in redirect).")
                    break
                except PlaywrightTimeout:
                    pass

    # Click "Next" / "Continue" if email + next is a two-step flow
    for next_text in ["Next", "Continue", "Send OTP", "Proceed"]:
        btn_sel = f'button:has-text("{next_text}"), input[value="{next_text}"]'
        # Only click if email field is no longer visible OR password not yet visible
        pw_sel = 'input[type="password"]'
        try:
            await page.wait_for_selector(pw_sel, timeout=2_000, state="visible")
            break  # password already visible, no need to click Next
        except PlaywrightTimeout:
            if await safe_click(page, btn_sel, f"login step: {next_text}", timeout=3_000):
                await wait_for_navigation_or_content(page)
                break

    # Password field
    pw_sel = 'input[type="password"]'
    try:
        await page.wait_for_selector(pw_sel, timeout=12_000, state="visible")
        await page.fill(pw_sel, VFS_PASSWORD)
        log.info("Filled password.")
    except PlaywrightTimeout:
        log.warning("Password field not found after email step.")
        await dump_page_state(page, "login-no-password")
        return False

    # Submit
    submit_sel = (
        'button[type="submit"], '
        'button:has-text("Sign In"), '
        'button:has-text("Login"), '
        'button:has-text("Log In"), '
        'button:has-text("Sign in"), '
        'input[type="submit"]'
    )
    submitted = await safe_click(page, submit_sel, "login submit button", timeout=8_000)
    if not submitted:
        # Try pressing Enter as fallback
        await page.keyboard.press("Enter")
        log.info("Pressed Enter to submit login form.")

    await wait_for_navigation_or_content(page, timeout=30_000)
    await dump_page_state(page, "after-login")

    # Check if we have an OTP / 2FA step
    otp_sel = 'input[placeholder*="OTP" i], input[placeholder*="code" i], input[name*="otp" i], input[name*="code" i]'
    try:
        await page.wait_for_selector(otp_sel, timeout=5_000, state="visible")
        log.warning(
            "⚠️  OTP / 2FA required. The bot cannot handle this automatically. "
            "Disable 2FA on your VFS account or use an account without OTP requirement."
        )
        return False
    except PlaywrightTimeout:
        pass

    # Verify login succeeded
    error_sel = '.error, .alert-danger, [class*="error-message"], [class*="login-error"]'
    try:
        err_el = await page.query_selector(error_sel)
        if err_el:
            err_text = await err_el.inner_text()
            log.error("Login error message detected: %s", err_text.strip())
            return False
    except Exception:
        pass

    log.info("Login step completed.")
    return True


async def _is_inside_wizard(page: Page) -> bool:
    """Heuristic: are we past the public landing page and inside the booking wizard?"""
    url = page.url
    inside_indicators = [
        "book-an-appointment" in url and "vfsglobal" in url,
    ]
    try:
        body = (await page.inner_text("body")).lower()
        # Wizard steps use these headings
        wizard_phrases = [
            "select appointment",
            "select category",
            "select centre",
            "select date",
            "appointment details",
            "visa category",
        ]
        inside_indicators.append(any(p in body for p in wizard_phrases))
    except Exception:
        pass
    return any(inside_indicators) and "skip to main content" not in (await page.inner_text("body")).lower()[:200]


# ── Step 3: Walk the booking wizard to the calendar ───────────────────────────

async def walk_wizard_to_calendar(page: Page) -> bool:
    """
    Navigate the multi-step VFS wizard until we reach the calendar/slot page.
    Returns True when we believe we are on the slot selection step.

    The wizard structure (may vary by VFS version):
      Step A – Select visa category → choose "Schengen Visa" or "National Visa"
      Step B – Select visa sub-category
      Step C – Select appointment centre → choose "Edinburgh"
      Step D – Calendar / slot picker  ← we want to be here
    """
    log.info("── Step 3: Walking booking wizard …")

    for attempt in range(6):  # max 6 wizard steps
        await page.wait_for_timeout(2_500)
        await dump_page_state(page, f"wizard-step-{attempt}")

        body = (await page.inner_text("body")).lower()

        # ── Are we on the calendar already? ───────────────────────────────────
        if _page_looks_like_calendar(body):
            log.info("Reached calendar/slot page at wizard step %d.", attempt)
            return True

        # ── Select appointment centre (Edinburgh) ──────────────────────────────
        if "select centre" in body or "appointment centre" in body or "select location" in body:
            log.info("Wizard: centre selection page detected.")
            selected = await _select_option_containing(page, "Edinburgh")
            if not selected:
                selected = await _select_option_containing(page, "edinburgh")
            if selected:
                await _click_wizard_next(page)
                continue
            else:
                log.warning("Could not find Edinburgh in centre list.")
                await dump_page_state(page, "centre-not-found")

        # ── Select visa category ───────────────────────────────────────────────
        if "select category" in body or "visa category" in body or "type of visa" in body:
            log.info("Wizard: visa category page detected.")
            # Try Schengen first, then National, then just pick the first option
            selected = (
                await _select_option_containing(page, "Schengen")
                or await _select_option_containing(page, "schengen")
                or await _select_first_option(page)
            )
            if selected:
                await _click_wizard_next(page)
                continue

        # ── Select visa sub-category ───────────────────────────────────────────
        if "select sub" in body or "sub-category" in body or "subcategory" in body:
            log.info("Wizard: sub-category page detected.")
            selected = await _select_first_option(page)
            if selected:
                await _click_wizard_next(page)
                continue

        # ── Generic: just try to advance the wizard ────────────────────────────
        advanced = await _click_wizard_next(page)
        if not advanced:
            log.info("No wizard-next button found at step %d — may be on calendar.", attempt)
            # One more body check
            body = (await page.inner_text("body")).lower()
            return _page_looks_like_calendar(body)

    body = (await page.inner_text("body")).lower()
    return _page_looks_like_calendar(body)


def _page_looks_like_calendar(body_text: str) -> bool:
    """Heuristic: does the page body look like the slot/calendar selection step?"""
    calendar_phrases = [
        "select date",
        "select time",
        "available dates",
        "choose a date",
        "pick a date",
        "appointment date",
        "no appointments available",
        "no slots available",
        "no available appointment",
        "there are no appointments",
        "calendar",
    ]
    return any(p in body_text for p in calendar_phrases)


async def _select_option_containing(page: Page, text: str) -> bool:
    """
    Find a dropdown option, radio button, or list item containing `text` and select/click it.
    Returns True if something was selected.
    """
    selectors_to_try = [
        f'option:has-text("{text}")',
        f'mat-option:has-text("{text}")',          # Angular Material
        f'li:has-text("{text}")',
        f'label:has-text("{text}")',
        f'div[role="option"]:has-text("{text}")',
        f'input[value*="{text}" i]',
    ]
    for sel in selectors_to_try:
        try:
            el = await page.query_selector(sel)
            if el:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "option":
                    # Select in a <select> element
                    select_el = await el.evaluate_handle("el => el.closest('select')")
                    value = await el.get_attribute("value") or text
                    await select_el.select_option(value=value)
                else:
                    await el.click()
                log.info("Selected option containing '%s' via: %s", text, sel)
                await page.wait_for_timeout(1_500)
                return True
        except Exception:
            pass
    return False


async def _select_first_option(page: Page) -> bool:
    """Fallback: select the very first available radio/option/list-item on the page."""
    fallback_selectors = [
        "mat-radio-button:first-of-type",
        "input[type='radio']:first-of-type",
        ".mat-list-item:first-of-type",
        "li.list-group-item:first-of-type a",
        'option:not([value=""]):first-of-type',
    ]
    for sel in fallback_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                log.info("Selected first available option via: %s", sel)
                await page.wait_for_timeout(1_500)
                return True
        except Exception:
            pass
    return False


async def _click_wizard_next(page: Page) -> bool:
    """Click whatever button advances the wizard. Returns True if a button was clicked."""
    next_buttons = [
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button:has-text("Proceed")',
        'button:has-text("Submit")',
        'a:has-text("Next")',
        'a:has-text("Continue")',
        'button[type="submit"]',
    ]
    for sel in next_buttons:
        if await safe_click(page, sel, f"wizard next [{sel}]", timeout=4_000):
            await wait_for_navigation_or_content(page)
            return True
    return False


# ── Step 4: Check for available slots ────────────────────────────────────────

async def check_for_slots(page: Page) -> bool:
    """
    Returns True if at least one open appointment slot is visible.
    Logs as much detail as possible for debugging.
    """
    await page.wait_for_timeout(3_000)

    body = (await page.inner_text("body")).lower()

    # Positive: specific slot elements
    for sel in SLOT_SELECTORS:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                # Filter out hidden elements
                visible = [e for e in elements if await e.is_visible()]
                if visible:
                    log.info("✅  Slot element found: %s (%d visible)", sel, len(visible))
                    return True
        except Exception:
            pass

    # Negative: explicit no-slot text
    for phrase in NO_SLOT_PHRASES:
        if phrase in body:
            log.info("No-slot phrase: '%s'", phrase)
            return False

    # Log a wider body snippet to help tune selectors
    snippet = body[:800].replace("\n", " ")
    log.info("Slot status ambiguous — body: %s", snippet)
    return False


# ── Main loop ─────────────────────────────────────────────────────────────────

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
                "--disable-extensions",
                "--disable-plugins",
            ],
        )
        context_kwargs = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # Suppress automation detection
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        log.info("Browser launched. Starting monitoring loop …")

        try:
            while True:
                log.info("═══ Check cycle: %s ═══", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                try:
                    # Always start fresh from the landing page
                    logged_in = await navigate_and_login(page)

                    if not logged_in:
                        log.error("Login failed — will retry next cycle.")
                    else:
                        on_calendar = await walk_wizard_to_calendar(page)

                        if not on_calendar:
                            log.warning("Did not reach calendar page — check logs above for wizard state.")
                            await dump_page_state(page, "end-of-wizard-walk")
                        else:
                            slot_available = await check_for_slots(page)

                            if slot_available:
                                log.info("✅  SLOT AVAILABLE — sending notification!")
                                if not slot_found_already_notified:
                                    send_email_notification(
                                        subject="🇮🇹 Italy Visa Slot Available in Edinburgh!",
                                        body=(
                                            "An appointment slot for the Italy visa application "
                                            f"in Edinburgh appears to be available!\n\n"
                                            f"👉 Book now: {VFS_LANDING}\n\n"
                                            f"Detected at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                            "The bot will keep checking and notify you again "
                                            "if more slots open."
                                        ),
                                    )
                                    slot_found_already_notified = True
                            else:
                                log.info("❌  No slots available.")
                                slot_found_already_notified = False

                except PlaywrightTimeout as exc:
                    log.error("Playwright timeout: %s", exc)
                except Exception as exc:
                    log.exception("Unexpected error: %s", exc)
                    # Hard-reset the page on unknown errors
                    try:
                        await page.close()
                        page = await context.new_page()
                        await page.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                        )
                    except Exception:
                        # Context itself broken — recreate
                        try:
                            await context.close()
                        except Exception:
                            pass
                        context = await browser.new_context(**context_kwargs)
                        page = await context.new_page()
                        await page.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                        )

                log.info("Sleeping %d s …\n", CHECK_INTERVAL_SECONDS)
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_check_loop())
