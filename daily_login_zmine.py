import time
import random
import json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
LOGIN_URL = "https://zmine.si/login"
APP_URL = "https://zmine.si/app"

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
    """Click the input and type with realistic delays."""
    page.click(selector)
    time.sleep(0.3)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.03, 0.1))

def is_signed_in(page):
    """Check for signs the user is logged in."""
    try:
        body = page.inner_text("body").lower()
        for signal in ["start mining", "session off", "session on", "mining pool",
                       "earn hashpower", "idle"]:
            if signal in body:
                return True
    except Exception:
        pass
    return False

def sign_in(page, login_key):
    """Sign in via the dedicated /login URL."""
    log("signin", f"Navigating to {LOGIN_URL}")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log("signin", f"⚠️ Navigation error: {str(e)[:80]}")
        return False

    # Wait for the login input to appear (placeholder contains "LK-")
    log("signin", "Waiting for login key input (placeholder contains 'LK-')...")
    input_selector = 'input[placeholder*="LK-"]'
    try:
        page.wait_for_selector(input_selector, timeout=25000)
    except PWTimeout:
        # Fallback selectors
        for fallback in ['input[placeholder*="Login key" i]', 'input[name*="key" i]', 'input[type="text"]']:
            try:
                page.wait_for_selector(fallback, timeout=5000)
                input_selector = fallback
                log("signin", f"✅ Using fallback selector: {fallback}")
                break
            except PWTimeout:
                continue
        else:
            log("signin", "❌ Could not find login input")
            try:
                log("signin", f"Body: {page.inner_text('body')[:200]}")
            except Exception:
                pass
            return False

    log("signin", f"✅ Found input: {input_selector}")
    random_sleep(0.5, 1.5)

    # Type the login key
    human_type(page, input_selector, login_key)
    log("signin", "✅ Typed login key")
    random_sleep(0.8, 1.5)

    # Click the "Sign in" button
    clicked = False
    for sel in [
        'button:has-text("Sign in")',
        'button:has-text("Sign In")',
        'button[type="submit"]',
        'button:has-text("Log in")',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                log("signin", f"✅ Clicked '{sel}'")
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        # Fallback: press Enter
        try:
            page.keyboard.press("Enter")
            log("signin", "⚠️ Pressed Enter as fallback")
        except Exception:
            log("signin", "❌ Could not submit login form")
            return False

    # Wait for redirect to /app
    log("signin", "Waiting for redirect to /app...")
    try:
        page.wait_for_url("**/app**", timeout=20000)
        log("signin", "✅ Redirected to /app")
    except PWTimeout:
        log("signin", "⚠️ No redirect detected, waiting anyway...")
        random_sleep(3.0, 5.0)

    # Final check
    random_sleep(2.0, 3.0)
    if is_signed_in(page):
        log("signin", "✅ Signed in successfully")
        return True

    log("signin", "⚠️ Could not confirm sign-in, but continuing anyway")
    return True  # Continue to try mining anyway

def start_mining(page):
    """Click Start mining and confirm in modal."""
    log("mine", "Waiting for Rig page...")
    random_sleep(2.0, 3.5)

    # If not on /app, navigate there
    if "/app" not in page.url:
        try:
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
            random_sleep(3.0, 4.5)
        except Exception as e:
            log("mine", f"⚠️ Could not navigate to /app: {str(e)[:80]}")

    # Check if already mining
    try:
        body = page.inner_text("body").lower()
        if "session on" in body:
            log("mine", "✅ Already mining (session on)")
            return True
    except Exception:
        pass

    # Wait for the Start mining button
    log("mine", "Waiting for 'Start mining' button...")
    try:
        page.wait_for_selector('button:has-text("Start mining")', timeout=25000)
    except PWTimeout:
        log("mine", "❌ 'Start mining' button never appeared")
        try:
            log("mine", f"URL: {page.url}")
            log("mine", f"Body: {page.inner_text('body')[:300].replace(chr(10), ' | ')}")
        except Exception:
            pass
        return False

    log("mine", "✅ Found 'Start mining' button")
    random_sleep(0.5, 1.5)
    page.click('button:has-text("Start mining")')
    log("mine", "Clicked 'Start mining'")
    random_sleep(2.0, 3.0)

    # Handle the START MINING modal (screenshot shows: Hashpower, Duration, Cost, Cancel, Start)
    log("mine", "Waiting for confirmation modal...")
    try:
        page.wait_for_selector('text="START MINING"', timeout=8000)
        log("mine", "✅ Modal detected")
    except PWTimeout:
        log("mine", "⚠️ Modal text not found, looking for Start button anyway...")

    # Click "Start" button (the modal's confirm button)
    start_clicked = False
    # Try multiple selectors for the modal's Start button
    for sel in [
        '[role="dialog"] button:has-text("Start")',
        'div:has-text("START MINING") button:has-text("Start")',
        'button:has-text("Start"):not(:has-text("Start mining"))',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                btn.click()
                log("mine", f"✅ Clicked '{sel}'")
                start_clicked = True
                break
        except Exception:
            continue

    if not start_clicked:
        log("mine", "❌ Could not click modal Start button")
        return False

    random_sleep(4.0, 6.0)

    # Verify
    try:
        verify = page.inner_text("body").lower()
        if "session on" in verify or ("mining" in verify and "idle" not in verify):
            log("mine", "🟢 Mining VERIFIED (session is now ON)")
            return True
    except Exception:
        pass

    random_sleep(5.0, 8.0)
    try:
        verify = page.inner_text("body").lower()
        if "session on" in verify or "mining" in verify:
            log("mine", "🟢 Mining verified after delay")
            return True
    except Exception:
        pass

    log("mine", "⚠️ Could not verify mining status, but Start was clicked")
    return True

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
        random_sleep(2.0, 4.0)
        start_mining(page)
    except Exception as e:
        log("farm", f"❌ {display_name}: {str(e)[:150]}")
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
