import time
import random
import json
import subprocess
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
APP_URL = "https://zmine.si/app"
HOME_URL = "https://zmine.si/"
SI_URL = "https://zmine.si/app/si"

def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=2.0, max_s=4.5):
    time.sleep(random.uniform(min_s, max_s))

def load_accounts():
    accounts = []
    with open(ACCOUNTS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                accounts.append(json.loads(line))
    return accounts

def human_type(page, selector, text):
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.05, 0.15))

def wait_for_page_ready(page, timeout=30000):
    """Wait for the Next.js app to finish rendering."""
    try:
        # Wait for at least one interactive element to appear
        page.wait_for_function(
            """() => {
                const buttons = document.querySelectorAll('button, a, input');
                return buttons.length > 3;
            }""",
            timeout=timeout
        )
        return True
    except PWTimeout:
        return False

def is_signed_in(page):
    """Check if the page shows a logged-in state (Rig, Start mining, etc.)."""
    try:
        body = page.inner_text("body").lower()
        if "start mining" in body or "session off" in body or "session on" in body:
            return True
        if "earn hashpower" in body or "mining pool" in body:
            return True
    except Exception:
        pass
    return False

def click_log_in_link(page):
    """Find and click a 'Log in' link on the welcome/home page."""
    selectors = [
        'text="Log in"',
        'text="Sign in"',
        'text="Login"',
        'a:has-text("Log in")',
        'a:has-text("Sign in")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
    ]
    for sel in selectors:
        try:
            link = page.locator(sel).first
            if link.is_visible(timeout=2000):
                link.click()
                log("signin", f"✅ Clicked '{sel}'")
                return True
        except Exception:
            continue
    return False

def find_login_input(page):
    """Find the identity/login key input field."""
    selectors = [
        'input[placeholder*="login" i]',
        'input[placeholder*="key" i]',
        'input[placeholder*="identity" i]',
        'input[name="loginKey"]',
        'input[name="key"]',
        'input[name="identity"]',
        'input[type="text"]',
    ]
    for sel in selectors:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=2000):
                return inp, sel
        except Exception:
            continue
    return None, None

def sign_in(page, login_key):
    """Robust sign-in flow for the Next.js SPA."""
    log("signin", "Navigating to app...")
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
    random_sleep(3.0, 5.0)

    log("signin", "Waiting for page to fully render...")
    if not wait_for_page_ready(page, timeout=30000):
        log("signin", "⚠️ Page did not render in 30s")

    # Check if already signed in
    random_sleep(2.0, 3.0)
    if is_signed_in(page):
        log("signin", "✅ Already signed in")
        return True

    # Try clicking a Log in link
    log("signin", "Looking for Log in link...")
    if not click_log_in_link(page):
        log("signin", "No Log in link found — checking if login form is already present...")
    else:
        random_sleep(2.0, 3.5)
        wait_for_page_ready(page, timeout=15000)

    # Now look for the input field
    log("signin", "Looking for login key input...")
    inp, sel = find_login_input(page)
    if not inp:
        # Last resort: navigate to homepage and try again
        log("signin", "⚠️ No input found on /app, trying homepage...")
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        random_sleep(3.0, 4.0)
        wait_for_page_ready(page, timeout=15000)
        if not click_log_in_link(page):
            log("signin", "❌ Could not find Log in link on homepage")
            return False
        random_sleep(2.0, 3.5)
        wait_for_page_ready(page, timeout=15000)
        inp, sel = find_login_input(page)
        if not inp:
            log("signin", "❌ Could not find login key input")
            return False

    log("signin", f"✅ Found input via '{sel}'")
    inp.click()
    human_type(page, sel, login_key)
    random_sleep(0.5, 1.5)

    # Click the Log in / Sign in / Confirm button
    for btn_text in ["Log in", "Sign in", "Login", "Continue", "Confirm"]:
        try:
            page.click(f'button:has-text("{btn_text}")', timeout=2500)
            log("signin", f"✅ Clicked '{btn_text}' button")
            random_sleep(4.0, 6.0)
            return True
        except Exception:
            continue

    # Fallback: press Enter
    try:
        page.keyboard.press("Enter")
        log("signin", "⚠️ Pressed Enter as fallback")
        random_sleep(4.0, 6.0)
        return True
    except Exception:
        pass

    log("signin", "❌ Could not click any sign-in button")
    return False

def start_mining(page):
    log("mine", "Waiting for Rig page...")
    try:
        page.wait_for_selector('button:has-text("Start mining")', timeout=25000)
    except PWTimeout:
        log("mine", "❌ 'Start mining' button never appeared")
        return False

    body = page.inner_text("body").lower()
    if "session on" in body:
        log("mine", "Already mining")
        return True

    log("mine", "Clicking 'Start mining'...")
    page.click('button:has-text("Start mining")')
    random_sleep(2.0, 4.0)

    # Handle modal
    modal_handled = False
    try:
        page.wait_for_selector('[role="dialog"]', timeout=8000)
        log("mine", "Modal detected")
        start_btn = page.locator('[role="dialog"] button:has-text("Start")').first
        start_btn.click(timeout=5000)
        log("mine", "✅ Clicked 'Start' inside modal")
        modal_handled = True
        random_sleep(3.0, 5.0)
    except Exception as e:
        log("mine", f"⚠️ Modal: {str(e)[:80]}")

    if not modal_handled:
        try:
            page.keyboard.press("Enter")
            random_sleep(2.0, 3.0)
        except Exception:
            pass

    random_sleep(3.0, 5.0)

    # Verify
    verify = page.inner_text("body").lower()
    if "session on" in verify or ("mining" in verify and "idle" not in verify):
        log("mine", "🟢 Mining VERIFIED")
        return True

    random_sleep(5.0, 8.0)
    verify = page.inner_text("body").lower()
    if "session on" in verify or "mining" in verify:
        log("mine", "🟢 Mining verified after delay")
        return True

    log("mine", "❌ Could not verify mining")
    return False

def farm_account(browser, account):
    display_name = account["display_name"]
    login_key = account["login_key"]
    log("farm", f"🚜 {display_name}")

    context = browser.new_context(
        viewport={"width": 412, "height": 915},
        user_agent=(
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
    )
    page = context.new_page()
    try:
        signed_in = sign_in(page, login_key)
        if not signed_in:
            log("farm", f"❌ Could not sign in for {display_name}")
            return
        random_sleep(3.0, 5.0)
        start_mining(page)
    except Exception as e:
        log("farm", f"❌ {display_name}: {e}")
    finally:
        context.close()

def main():
    accounts = load_accounts()
    if not accounts:
        log("init", "No accounts found.")
        return

    log("init", f"Loaded {len(accounts)} accounts. Shuffling...")
    random.shuffle(accounts)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        try:
            for idx, acc in enumerate(accounts, 1):
                log("main", f"=== {idx}/{len(accounts)}: {acc['display_name']} ===")
                farm_account(browser, acc)
                random_sleep(8.0, 15.0)
        finally:
            browser.close()
            log("done", "✅ All accounts processed")

if __name__ == "__main__":
    main()
