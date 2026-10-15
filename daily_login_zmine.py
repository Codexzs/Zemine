import time
import random
import json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
APP_URL = "https://zmine.si/app"
HOME_URL = "https://zmine.si/"
LOGIN_URLS = [
    "https://zmine.si/app",
    "https://zmine.si/",
    "https://zmine.si/login",
    "https://zmine.si/app/login",
]

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
        time.sleep(random.uniform(0.04, 0.12))

def wait_network_idle(page, timeout=15000):
    """Wait for network to be mostly idle (Next.js hydration done)."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        return True
    except PWTimeout:
        return False

def is_signed_in(page):
    """Check for signs the user is logged in."""
    try:
        body = page.inner_text("body").lower()
        for signal in ["start mining", "session off", "session on",
                       "earn hashpower", "mining pool", "rig is optimal",
                       "auto-pilot", "my sst"]:
            if signal in body:
                return True
    except Exception:
        pass
    return False

def dump_debug(page, label):
    """Dump URL and visible text on failure."""
    try:
        log("debug", f"--- {label} ---")
        log("debug", f"URL: {page.url}")
        body = page.inner_text("body")
        log("debug", f"Body preview: {body[:300].replace(chr(10), ' | ')}")
    except Exception:
        pass

def find_login_input(page):
    """Find any element that looks like a login key input."""
    selectors = [
        'textarea[placeholder*="login" i]',
        'textarea[placeholder*="key" i]',
        'textarea[placeholder*="identity" i]',
        'input[placeholder*="login" i]',
        'input[placeholder*="key" i]',
        'input[placeholder*="identity" i]',
        'input[name="loginKey"]',
        'input[name="key"]',
        'input[name="identity"]',
        'textarea',
        'input[type="text"]',
        '[contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=1500):
                return inp, sel
        except Exception:
            continue
    return None, None

def click_signin_link(page):
    """Try multiple selectors to find a clickable sign-in trigger."""
    selectors = [
        'a:has-text("Log in")',
        'a:has-text("Sign in")',
        'a:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'button:has-text("Login")',
        'text="Log in"',
        'text="Sign in"',
        '[href*="login"]',
        '[href*="signin"]',
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

def attempt_signin_from_url(page, login_key):
    """Try signing in from whatever URL we're currently on."""
    log("signin", f"Waiting for page render at {page.url}...")
    wait_network_idle(page, timeout=12000)
    random_sleep(2.5, 4.0)

    # Already signed in?
    if is_signed_in(page):
        log("signin", "✅ Already signed in")
        return True

    # Try clicking a Log in link
    if click_signin_link(page):
        log("signin", "Waiting for login form after click...")
        wait_network_idle(page, timeout=10000)
        random_sleep(3.0, 5.0)

    # Try to find the input with retries
    for attempt in range(4):
        inp, sel = find_login_input(page)
        if inp:
            log("signin", f"✅ Found input via '{sel}' (attempt {attempt+1})")
            try:
                inp.click()
                random_sleep(0.5, 1.0)
                for ch in login_key:
                    page.keyboard.type(ch)
                    time.sleep(random.uniform(0.04, 0.12))
                random_sleep(0.8, 1.5)

                # Try clicking the submit button
                for btn_text in ["Log in", "Sign in", "Login", "Continue", "Confirm", "Submit"]:
                    try:
                        page.click(f'button:has-text("{btn_text}")', timeout=2000)
                        log("signin", f"✅ Clicked '{btn_text}' button")
                        random_sleep(5.0, 7.0)
                        return True
                    except Exception:
                        continue

                # Fallback: Enter key
                page.keyboard.press("Enter")
                log("signin", "⚠️ Pressed Enter as fallback")
                random_sleep(5.0, 7.0)
                return True
            except Exception as e:
                log("signin", f"⚠️ Input interaction error: {str(e)[:100]}")

        log("signin", f"⚠️ Attempt {attempt+1}/4: input not found, waiting...")
        wait_network_idle(page, timeout=5000)
        random_sleep(3.0, 4.5)

    return False

def sign_in(page, login_key):
    """Robust sign-in: tries multiple URLs."""
    for url in LOGIN_URLS:
        log("signin", f"Trying {url}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("signin", f"⚠️ Navigation error: {str(e)[:80]}")
            continue

        random_sleep(3.0, 5.0)

        if attempt_signin_from_url(page, login_key):
            return True

        log("signin", f"❌ Failed on {url}, trying next URL...")

    log("signin", "❌ All sign-in attempts failed")
    dump_debug(page, "Final state")
    return False

def start_mining(page):
    log("mine", "Waiting for Rig page...")
    wait_network_idle(page, timeout=10000)
    random_sleep(2.0, 3.5)

    try:
        page.wait_for_selector('button:has-text("Start mining")', timeout=25000)
    except PWTimeout:
        log("mine", "❌ 'Start mining' button never appeared")
        dump_debug(page, "Start mining failure")
        return False

    body = page.inner_text("body").lower()
    if "session on" in body:
        log("mine", "Already mining")
        return True

    log("mine", "Clicking 'Start mining'...")
    page.click('button:has-text("Start mining")')
    random_sleep(2.0, 4.0)

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
            log("farm", f"❌ Sign-in failed for {display_name}")
            return

        # Navigate to Rig/app if we aren't there
        if "/app" not in page.url:
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
            random_sleep(3.0, 4.5)

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
