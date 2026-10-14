import time
import random
import json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
APP_URL = "https://zmine.si/app"

def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=2.0, max_s=4.5):
    time.sleep(random.uniform(min_s, max_s))

def human_type(page, selector, text):
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.05, 0.18))

def load_accounts():
    accounts = []
    try:
        with open(ACCOUNTS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    accounts.append(json.loads(line))
    except FileNotFoundError:
        log("init", "No accounts file found. Run register_zmine.py first.")
    return accounts

def sign_in(page, login_key):
    """Handle the sign-in flow. Returns True if signed in successfully."""
    log("signin", "Checking sign-in state...")
    random_sleep(2.0, 3.0)

    # Check if we are already logged in (the "Start mining" button would be visible)
    try:
        page.wait_for_selector('button:has-text("Start mining")', timeout=5000)
        log("signin", "✅ Already signed in (Start mining button visible)")
        return True
    except PWTimeout:
        pass

    # Look for a sign-in input field
    log("signin", "Sign-in form not auto-detected, looking for login input...")
    sign_in_selectors = [
        'input[placeholder*="login" i]',
        'input[placeholder*="key" i]',
        'input[name="loginKey"]',
        'input[name="key"]',
        'input[type="text"]',
    ]

    for sel in sign_in_selectors:
        try:
            inp = page.locator(sel).first
            inp.wait_for(state="visible", timeout=3000)
            log("signin", f"Found login input via: {sel}")
            human_type(page, sel, login_key)
            random_sleep(0.5, 1.5)

            # Click sign-in button
            for btn_text in ["Sign in", "Log in", "Login", "Continue"]:
                try:
                    page.click(f'button:has-text("{btn_text}")', timeout=2000)
                    log("signin", f"✅ Clicked '{btn_text}' button")
                    random_sleep(4.0, 6.0)
                    return True
                except PWTimeout:
                    continue

            raise Exception("Could not find a sign-in button after entering key")
        except PWTimeout:
            continue
        except Exception as e:
            log("signin", f"⚠️ {e}")
            continue

    raise Exception("Could not find sign-in form. Check page source.")

def start_mining(page):
    """Click Start mining and confirm in modal."""
    log("mine", "Waiting for 'Start mining' button...")
    page.wait_for_selector('button:has-text("Start mining")', timeout=20000)
    log("mine", "✅ Button found")

    # Check if already mining
    body_text = page.inner_text("body").lower()
    if "session on" in body_text:
        log("mine", "Already mining — no action needed")
        return True

    log("mine", "Clicking 'Start mining'...")
    page.click('button:has-text("Start mining")')
    random_sleep(2.0, 4.0)

    # Wait for modal
    log("mine", "Waiting for modal...")
    try:
        # The modal contains "START MINING" text and Start/Cancel buttons
        page.wait_for_selector('text=START MINING', timeout=10000)
        log("mine", "✅ Modal appeared")

        # Click the confirm Start button inside the modal
        # The modal's Start button is typically distinct — search within modal container
        try:
            page.click('button:has-text("Start")', timeout=5000)
            log("mine", "✅ Clicked 'Start' in modal")
        except PWTimeout:
            # Fallback: press Enter or click any button with "Start"
            page.keyboard.press("Enter")
            log("mine", "⚠️ No Start button found, pressed Enter")
    except PWTimeout:
        log("mine", "⚠️ Modal did not appear — mining may already be running")

    random_sleep(4.0, 6.0)

    # Verify mining started
    final_body = page.inner_text("body").lower()
    if "session on" in final_body or "mining" in final_body or "in progress" in final_body:
        log("mine", "🟢 Mining verified!")
        return True
    else:
        log("mine", "⚠️ Could not verify mining status — dumping visible text:")
        log("mine", final_body[:500])
        return False

def farm_account(browser, account):
    display_name = account["display_name"]
    login_key = account["login_key"]
    log("farm", f"🚜 Farming: {display_name} ({login_key[:12]}...)")

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
        log("farm", f"Navigating to {APP_URL}")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        random_sleep(2.0, 4.0)

        # Sign in
        sign_in(page, login_key)
        random_sleep(3.0, 5.0)

        # Start mining
        start_mining(page)

    except Exception as e:
        log("farm", f"❌ Failed to farm {display_name}: {e}")
        try:
            print(page.content()[:3000], flush=True)
        except Exception:
            pass
    finally:
        context.close()

def main():
    accounts = load_accounts()
    if not accounts:
        log("init", "No accounts to farm. Exiting.")
        return

    log("init", f"Loaded {len(accounts)} accounts. Shuffling...")
    random.shuffle(accounts)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        try:
            for idx, account in enumerate(accounts, 1):
                log("main", f"=== Farming {idx}/{len(accounts)}: {account['display_name']} ===")
                farm_account(browser, account)
                random_sleep(8.0, 15.0)
        finally:
            browser.close()
            log("done", "✅ All accounts processed")

if __name__ == "__main__":
    main()
