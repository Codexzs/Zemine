import time
import random
import string
import json
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# ============================================================
#   CONFIGURATION
# ============================================================
REFERRAL_CODE = "08TVR3QF"
REGISTER_URL = f"https://zmine.si/register?ref={REFERRAL_CODE}"
ACCOUNTS_FILE = "zmine_accounts.jsonl"

def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))

def generate_display_name():
    """Generate a unique-looking display name (3-24 chars)."""
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"miner_{suffix}"

def human_type(page, selector, text):
    """Type text with realistic per-character delays."""
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.05, 0.18))

def run_registration():
    display_name = generate_display_name()
    log("init", f"Registering account: {display_name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = browser.new_context(
            viewport={"width": 412, "height": 915},  # Mobile viewport
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
        )
        page = context.new_page()

        log("1/6", f"Navigating to {REGISTER_URL}")
        page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60000)
        random_sleep(2.0, 4.0)

        # --- Fill display name ---
        log("2/6", "Filling display name...")
        name_input = page.locator('input[placeholder*="leaderboard"], input[name="displayName"], input[type="text"]').first
        name_input.wait_for(state="visible", timeout=15000)
        human_type(page, 'input[placeholder*="leaderboard"], input[name="displayName"], input[type="text"]', display_name)
        random_sleep(0.5, 1.5)

        # --- Verify referral code is filled ---
        log("3/6", "Verifying referral code...")
        try:
            ref_input = page.locator('input[placeholder="ABCD1234"], input[name="referralCode"]').first
            current_ref = ref_input.input_value()
            log("3/6", f"Referral code in field: '{current_ref}'")
            if current_ref.upper() != REFERRAL_CODE.upper():
                log("3/6", f"⚠️ Ref code mismatch, setting to {REFERRAL_CODE}")
                ref_input.fill("")
                human_type(page, 'input[placeholder="ABCD1234"], input[name="referralCode"]', REFERRAL_CODE)
        except Exception as e:
            log("3/6", f"⚠️ Could not verify ref code: {e}")
        random_sleep(0.5, 1.5)

        # --- Click Generate ---
        log("4/6", "Clicking 'Generate my login keys'...")
        page.click('button:has-text("Generate my login keys")')
        random_sleep(3.0, 5.0)

        # --- Wait for keys page ---
        log("5/6", "Waiting for login keys page...")
        page.wait_for_selector('text=Your login keys', timeout=30000)
        log("5/6", "✅ Login keys page loaded")

        # --- Extract login key ---
        log("5/6", "Extracting login key...")
        page_text = page.inner_text("body")
        key_match = re.search(r"LK-[A-Z0-9-]{20,}", page_text)
        if not key_match:
            raise Exception("Could not find login key (LK-...) on page")
        login_key = key_match.group(0)
        log("5/6", f"✅ Login key: {login_key[:12]}...")

        # --- Extract recovery phrase (24 words) ---
        log("5/6", "Extracting recovery phrase...")
        recovery_phrase = ""
        try:
            # Look for numbered words 1-24
            recovery_words = re.findall(r"\b([a-z]{3,10})\b", page_text)
            # Filter for likely recovery words (24 words)
            if len(recovery_words) >= 24:
                recovery_phrase = " ".join(recovery_words[:24])
            log("5/6", f"✅ Recovery phrase captured ({len(recovery_words)} words found)")
        except Exception as e:
            log("5/6", f"⚠️ Recovery phrase extraction issue: {e}")

        # --- Check the "I have saved" checkbox ---
        log("6/6", "Checking 'I have saved' checkbox...")
        try:
            page.check('input[type="checkbox"]')
            log("6/6", "✅ Checkbox checked")
        except Exception as e:
            log("6/6", f"⚠️ Checkbox issue: {e}")
        random_sleep(0.5, 1.5)

        # --- Save account data ---
        account = {
            "display_name": display_name,
            "login_key": login_key,
            "recovery_phrase": recovery_phrase,
            "referral_code": REFERRAL_CODE,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(ACCOUNTS_FILE, "a") as f:
            f.write(json.dumps(account) + "\n")
        log("6/6", f"💾 Saved account to {ACCOUNTS_FILE}")

        browser.close()
        log("done", f"✅ Registration complete for {display_name}")
        return True

if __name__ == "__main__":
    try:
        run_registration()
    except Exception as e:
        log("error", f"❌ Registration failed: {e}")
        raise
