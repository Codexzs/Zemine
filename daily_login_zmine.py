import time
import random
import json
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
APP_URL = "https://zmine.si/app"

def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=2.0, max_s=5.0):
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
        log("farm", "Navigating to app...")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        random_sleep(2.0, 4.0)

        # --- Sign in if needed ---
        try:
            page.wait_for_selector('input[placeholder*="login"], input[name="loginKey"]', timeout=10000)
            log("farm", "Sign-in form detected, entering login key...")
            human_type(page, 'input[placeholder*="login"], input[name="loginKey"]', login_key)
            random_sleep(0.5, 1.5)
            page.click('button:has-text("Sign in")')
            log("farm", "✅ Signed in")
            random_sleep(4.0, 7.0)
        except Exception:
            log("farm", "Already signed in or no sign-in form needed")

        # --- Wait for dashboard ---
        page.wait_for_selector('text=Start mining, button:has-text("Start mining")', timeout=30000)
        log("farm", "Dashboard loaded")

        # --- Check if already mining ---
        body_text = page.inner_text("body").lower()
        if "session off" not in body_text and "idle" not in body_text:
            log("farm", "⚠️ Session may already be active, checking...")

        # --- Click Start mining ---
        log("farm", "Clicking 'Start mining'...")
        page.click('button:has-text("Start mining")')
        random_sleep(2.0, 4.0)

        # --- Confirm in modal ---
        log("farm", "Waiting for confirmation modal...")
        try:
            page.wait_for_selector('text=START MINING', timeout=10000)
            log("farm", "Modal appeared, clicking 'Start'...")
            page.click('button:has-text("Start")')
            random_sleep(3.0, 5.0)
            log("farm", "🟢 Mining session started!")
        except Exception as e:
            log("farm", f"⚠️ Modal not found: {e}")
            # Try alternative: maybe there's a direct start button
            try:
                page.click('button:has-text("Start")')
                log("farm", "🟢 Start clicked directly")
            except Exception:
                log("farm", "❌ Could not find start confirmation")

        # --- Verify ---
        random_sleep(2.0, 4.0)
        final_text = page.inner_text("body").lower()
        if "session on" in final_text or "in progress" in final_text or "mining" in final_text:
            log("farm", f"✅ {display_name}: Mining confirmed")
        else:
            log("farm", f"⚠️ {display_name}: Could not verify mining status")

    except Exception as e:
        log("farm", f"❌ Failed to farm {display_name}: {e}")
    finally:
        context.close()

def main():
    accounts = load_accounts()
    if not accounts:
        log("init", "No accounts to farm. Exiting.")
        return

    log("init", f"Loaded {len(accounts)} accounts. Shuffling for randomization...")
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
                # Human break between accounts
                random_sleep(8.0, 15.0)
        finally:
            browser.close()
            log("done", "✅ All accounts farmed")

if __name__ == "__main__":
    main()
