import os
import time
import random
import json
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from groq import Groq

# ============================================================
#   CONFIGURATION
# ============================================================
REFERRAL_CODE = "08TVR3QF"
REGISTER_URL = f"https://zmine.si/register?ref={REFERRAL_CODE}"
APP_URL = "https://zmine.si/app"
SI_URL = "https://zmine.si/app/si"
ACCOUNTS_FILE = "zmine_accounts.jsonl"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MAX_QUESTIONS = 12

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Edward", "Deborah", "Ronald", "Stephanie", "Timothy", "Rebecca", "Jason", "Sharon",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
]

def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))

def generate_display_name():
    return f"{random.choice(FIRST_NAMES)}{random.choice(LAST_NAMES)}{random.randint(10, 99)}"

def human_type(page, selector, text):
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.05, 0.18))

def ask_llm(client, question, options):
    prompt = f"""Answer this quiz question. Reply with ONLY the number (1, 2, 3, or 4) of the correct option.

Question: {question}

Options:
{chr(10).join(f'{i+1}. {opt}' for i, opt in enumerate(options))}

Answer number:"""
    try:
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        raw = r.choices[0].message.content.strip()
        m = re.search(r"\d+", raw)
        if m:
            n = int(m.group(0))
            if 1 <= n <= len(options):
                return n
        return 1
    except Exception as e:
        log("llm", f"⚠️ LLM failed: {e}")
        return 1

def detect_done(page):
    try:
        body = page.inner_text("body")
        if "Done for today" in body or "12 more tomorrow" in body:
            return True
        if re.search(r"12\s*/\s*12", body):
            return True
    except Exception:
        pass
    return False

def parse_question(page):
    try:
        body = page.inner_text("body")
        question = None
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "DIFFICULTY" in line and i + 1 < len(lines):
                question = lines[i + 1]
                break
        if not question or len(question) < 15:
            for line in lines:
                if len(line) > 25 and (line.endswith("?") or line.endswith(".")):
                    question = line
                    break
        if not question:
            return None, None

        skip = ["start mining", "boost", "sign in", "log in", "copy", "post it",
                "verify my handle", "get a new code", "cancel", "start", "next",
                "confirm", "close", "rig", "boosts", "si", "wallet",
                "leaderboard", "earn hashpower", "advisor", "auto-pilot"]
        options = []
        for btn in page.locator('button').all():
            try:
                txt = btn.inner_text().strip()
                if not txt or len(txt) < 2:
                    continue
                low = txt.lower()
                if any(k in low for k in skip):
                    continue
                if re.fullmatch(r"\d+", txt):
                    continue
                if len(txt) > 250:
                    continue
                options.append(txt)
            except Exception:
                continue

        seen = set()
        unique = []
        for o in options:
            if o not in seen:
                seen.add(o)
                unique.append(o)
        if len(unique) > 4:
            unique = unique[:4]
        if len(unique) < 2:
            return None, None
        return question, unique
    except Exception as e:
        log("parse", f"⚠️ {e}")
        return None, None

def get_next_button(page):
    for sel in ['button:has-text("Next")', 'button:has-text("NEXT")', 'button:has-text("Continue")']:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                return btn
        except Exception:
            continue
    return None

def answer_question(page, llm_client, question, options):
    answer_num = ask_llm(llm_client, question, options)
    log("quiz", f"LLM chose {answer_num}: {options[answer_num-1][:80]}")

    target = options[answer_num - 1]
    clicked = False
    for btn in page.locator('button').all():
        try:
            if btn.inner_text().strip() == target:
                btn.click()
                log("quiz", "✅ Clicked answer")
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        page.keyboard.press(str(answer_num))
        log("quiz", f"⚠️ Pressed key '{answer_num}'")

    random_sleep(2.0, 3.5)

    for _ in range(15):
        nb = get_next_button(page)
        if nb:
            try:
                nb.click()
                log("quiz", "✅ Clicked Next")
                random_sleep(2.0, 3.5)
                return True
            except Exception:
                pass
        time.sleep(1)
    log("quiz", "⚠️ No Next button found")
    return False

def run_quiz(page, llm_client):
    answered = 0
    for i in range(MAX_QUESTIONS):
        log("quiz", f"--- Question {i+1}/{MAX_QUESTIONS} ---")
        if detect_done(page):
            log("quiz", "✅ 'Done for today' detected — stopping")
            break

        question, options = parse_question(page)
        if not question:
            log("quiz", "⚠️ Could not detect question — stopping")
            break

        log("quiz", f"Q: {question[:120]}")
        answer_question(page, llm_client, question, options)
        answered += 1
        random_sleep(1.5, 3.0)
        if detect_done(page):
            log("quiz", "✅ All questions completed")
            break

    log("quiz", f"✅ Finished: {answered} questions")
    return answered

# ============================================================
#   STEP 1: REGISTER
# ============================================================
def step1_register(page, display_name):
    log("1/5", f"Navigating to registration for {display_name}")
    page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60000)
    random_sleep(2.0, 4.0)

    log("1/5", "Filling display name...")
    name_sel = 'input[placeholder*="leaderboard"], input[name="displayName"], input[type="text"]'
    page.locator(name_sel).first.wait_for(state="visible", timeout=15000)
    human_type(page, name_sel, display_name)
    random_sleep(0.5, 1.5)

    log("1/5", "Verifying referral code...")
    try:
        ref = page.locator('input[placeholder="ABCD1234"], input[name="referralCode"]').first
        cur = ref.input_value()
        log("1/5", f"Referral in field: '{cur}'")
        if cur.upper() != REFERRAL_CODE.upper():
            ref.fill("")
            human_type(page, 'input[placeholder="ABCD1234"], input[name="referralCode"]', REFERRAL_CODE)
    except Exception as e:
        log("1/5", f"⚠️ Ref verify: {e}")

    log("1/5", "Clicking 'Generate my login keys'...")
    page.click('button:has-text("Generate my login keys")')
    random_sleep(3.0, 5.0)

    log("1/5", "Extracting login key...")
    page.wait_for_selector('text=Your login keys', timeout=30000)
    page_text = page.inner_text("body")
    m = re.search(r"LK-[A-Z0-9-]{20,}", page_text)
    if not m:
        raise Exception("Could not find login key")
    login_key = m.group(0)
    log("1/5", f"✅ Login key: {login_key[:15]}...")

    recovery = ""
    try:
        words = re.findall(r"\b([a-z]{3,10})\b", page_text)
        if len(words) >= 24:
            recovery = " ".join(words[:24])
    except Exception:
        pass

    try:
        page.check('input[type="checkbox"]')
        log("1/5", "✅ Checkbox ticked")
    except Exception:
        pass

    return login_key, recovery

# ============================================================
#   STEP 2: SIGN IN
# ============================================================
def step2_signin(page, login_key):
    log("2/5", "Navigating to app to sign in...")
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
    random_sleep(2.0, 4.0)

    body = page.inner_text("body")
    if "Start mining" in body or "session off" in body.lower():
        log("2/5", "✅ Already signed in")
        return True

    for sel in ['input[placeholder*="login" i]', 'input[placeholder*="key" i]',
                'input[name="loginKey"]', 'input[type="text"]']:
        try:
            inp = page.locator(sel).first
            inp.wait_for(state="visible", timeout=3000)
            human_type(page, sel, login_key)
            random_sleep(0.5, 1.5)
            for btn in ["Sign in", "Log in", "Login", "Continue"]:
                try:
                    page.click(f'button:has-text("{btn}")', timeout=2000)
                    log("2/5", f"✅ Signed in via '{btn}'")
                    random_sleep(4.0, 6.0)
                    return True
                except PWTimeout:
                    continue
        except PWTimeout:
            continue
    log("2/5", "⚠️ Could not find sign-in form")
    return False

# ============================================================
#   STEP 3: START MINING (with verification + retry)
# ============================================================
def step3_start_mining(page):
    log("3/5", "Starting mining on Rig tab...")
    try:
        try:
            page.click('button:has-text("Rig"), a:has-text("Rig")', timeout=3000)
            random_sleep(1.5, 2.5)
        except Exception:
            pass

        page.wait_for_selector('button:has-text("Start mining")', timeout=20000)
        body = page.inner_text("body").lower()
        if "session on" in body or ("mining" in body and "idle" not in body):
            log("3/5", "✅ Already mining")
            return True

        page.click('button:has-text("Start mining")')
        log("3/5", "Clicked 'Start mining', waiting for modal...")
        random_sleep(2.0, 4.0)

        try:
            page.wait_for_selector('text=START MINING', timeout=10000)
            page.click('button:has-text("Start")', timeout=5000)
            log("3/5", "✅ Confirmed in modal")
        except PWTimeout:
            log("3/5", "⚠️ No modal — mining may auto-start")
        random_sleep(4.0, 6.0)

        verify = page.inner_text("body").lower()
        if "session on" in verify or ("mining" in verify and "idle" not in verify):
            log("3/5", "🟢 Mining VERIFIED")
            return True

        log("3/5", "⚠️ Retrying mining start...")
        random_sleep(2.0, 3.0)
        try:
            page.click('button:has-text("Start mining")', timeout=5000)
            random_sleep(2.0, 4.0)
            try:
                page.wait_for_selector('text=START MINING', timeout=8000)
                page.click('button:has-text("Start")', timeout=5000)
            except PWTimeout:
                pass
            random_sleep(3.0, 5.0)
        except Exception as e:
            log("3/5", f"⚠️ Retry: {e}")

        final = page.inner_text("body").lower()
        if "session on" in final or "mining" in final:
            log("3/5", "🟢 Mining verified on retry")
            return True
        log("3/5", "❌ Could not start mining")
        return False
    except PWTimeout:
        log("3/5", "❌ 'Start mining' button never appeared")
        return False

# ============================================================
#   STEP 4: QUIZ
# ============================================================
def step4_quiz(page, llm_client):
    log("4/5", "Navigating to SI quiz...")
    page.goto(SI_URL, wait_until="domcontentloaded", timeout=60000)
    random_sleep(3.0, 5.0)

    # Handle "Start free session" task if present
    try:
        body = page.inner_text("body").lower()
        if "start free session" in body:
            try:
                page.click('text=Start free session', timeout=3000)
                log("4/5", "Clicked 'Start free session'")
                random_sleep(2.0, 4.0)
                try:
                    page.click('button:has-text("Start")', timeout=3000)
                    log("4/5", "✅ Free session started")
                    random_sleep(2.0, 3.0)
                except PWTimeout:
                    pass
            except Exception as e:
                log("4/5", f"⚠️ Free session: {e}")
    except Exception:
        pass

    page.goto(SI_URL, wait_until="domcontentloaded", timeout=60000)
    random_sleep(2.0, 4.0)

    if detect_done(page):
        log("4/5", "✅ Quiz already done for today")
        return 0

    return run_quiz(page, llm_client)

# ============================================================
#   MAIN FLOW
# ============================================================
def run_full_flow(llm_client):
    display_name = generate_display_name()
    log("init", f"🚀 Full flow: {display_name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
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
            login_key, recovery = step1_register(page, display_name)
            step2_signin(page, login_key)
            mining_ok = step3_start_mining(page)
            if not mining_ok:
                log("warn", "⚠️ Mining failed, continuing to quiz anyway")
            questions = step4_quiz(page, llm_client)

            account = {
                "display_name": display_name,
                "login_key": login_key,
                "recovery_phrase": recovery,
                "referral_code": REFERRAL_CODE,
                "mining_started": mining_ok,
                "questions_answered": questions,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(ACCOUNTS_FILE, "a") as f:
                f.write(json.dumps(account) + "\n")
            log("5/5", f"💾 Saved {display_name} | Mining: {mining_ok} | Quiz: {questions} Qs")
            log("done", f"✅ Complete: {display_name}")
            return True
        except Exception as e:
            log("error", f"❌ Failed: {e}")
            return False
        finally:
            browser.close()

if __name__ == "__main__":
    if not GROQ_API_KEY:
        log("init", "❌ GROQ_API_KEY not set")
        exit(1)
    run_full_flow(Groq(api_key=GROQ_API_KEY))
