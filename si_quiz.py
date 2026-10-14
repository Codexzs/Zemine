import os
import time
import random
import json
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from groq import Groq

# ============================================================
#   CONFIGURATION
# ============================================================
ACCOUNTS_FILE = "zmine_accounts.jsonl"
SI_URL = "https://zmine.si/app/si"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MAX_QUESTIONS = 12

# ============================================================
#   HELPERS
# ============================================================
def log(step, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)

def random_sleep(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))

def load_accounts():
    accounts = []
    with open(ACCOUNTS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                accounts.append(json.loads(line))
    return accounts

def discover_models(client):
    try:
        resp = client.models.list()
        all_models = [m.id for m in resp.data]
        skip_keywords = [
            "whisper", "tts", "guard", "embed", "orpheus", "canopylabs",
            "playai", "synthesize", "audio", "speech", "voice",
            "safeguard", "prompt-guard"
        ]
        chat_models = [m for m in all_models if not any(k in m.lower() for k in skip_keywords)]
        priority = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "allam-2-7b"]
        def rank(m):
            for i, p in enumerate(priority):
                if p in m:
                    return i
            return 999
        chat_models.sort(key=rank)
        log("llm", f"📋 Available chat models: {chat_models}")
        return chat_models
    except Exception as e:
        log("llm", f"⚠️ Model discovery failed: {str(e)[:120]}")
        return ["qwen/qwen3.8-27b", "allam-2-7b"]

def ask_llm(client, models, question, options):
    prompt = f"""Answer this quiz question. Reply with ONLY the number (1, 2, 3, or 4) of the correct option.

Question: {question}

Options:
{chr(10).join(f'{i+1}. {opt}' for i, opt in enumerate(options))}

Answer number:"""
    for model in models:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=2000,
            )
            raw = r.choices[0].message.content.strip()
            log("llm", f"   {model} raw: {raw[:100]}")
            matches = re.findall(r"\d+", raw)
            for candidate in reversed(matches):
                n = int(candidate)
                if 1 <= n <= len(options):
                    log("llm", f"✅ {model} → option {n}")
                    return n
        except Exception as e:
            log("llm", f"⚠️ {model} failed: {str(e)[:150]}")
            continue
    log("llm", "❌ All models failed, defaulting to option 1")
    return 1

def sign_in(page, login_key):
    random_sleep(2.0, 3.0)
    body = page.inner_text("body")
    if "TASKS" in body and ("DIFFICULTY" in body or "Done for today" in body):
        return True
    for sel in ['input[placeholder*="login" i]', 'input[placeholder*="key" i]',
                'input[name="loginKey"]', 'input[type="text"]']:
        try:
            inp = page.locator(sel).first
            inp.wait_for(state="visible", timeout=3000)
            inp.click()
            for ch in login_key:
                page.keyboard.type(ch)
                time.sleep(random.uniform(0.05, 0.15))
            random_sleep(0.5, 1.5)
            for btn in ["Sign in", "Log in", "Login", "Continue"]:
                try:
                    page.click(f'button:has-text("{btn}")', timeout=2000)
                    log("signin", "✅ Signed in")
                    random_sleep(4.0, 6.0)
                    return True
                except PWTimeout:
                    continue
        except PWTimeout:
            continue
    return False

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

def is_question_text(text):
    if not text or len(text) < 20:
        return False
    if re.fullmatch(r"\d+\s+LEFT\s+TODAY", text.upper().strip()):
        return False
    if re.fullmatch(r"\d+", text.strip()):
        return False
    if text.upper().strip() in ["TASKS", "TASK", "DIFFICULTY", "VERIFY", "CHOOSE"]:
        return False
    low = text.lower()
    bad_starts = ["left today", "tasks", "running", "per answer", "accuracy",
                  "next expiry", "verify", "choose", "difficulty"]
    if any(low.startswith(b) for b in bad_starts):
        return False
    bad_contains = ["x account", "handle", "post this", "tweet", "x tasks",
                    "expires in", "not linked", "left today"]
    if any(b in low for b in bad_contains):
        return False
    return True

def parse_question(page):
    try:
        body = page.inner_text("body")
        if "X TASKS" in body:
            body = body.split("X TASKS")[0]

        question = None
        lines = [l.strip() for l in body.split("\n") if l.strip()]

        for i, line in enumerate(lines):
            if "DIFFICULTY" in line and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if is_question_text(candidate):
                    question = candidate
                    break

        if not question:
            for line in lines:
                if len(line) > 25 and (line.endswith("?") or line.endswith(".")):
                    if is_question_text(line):
                        question = line
                        break

        if not question:
            for line in lines:
                low = line.lower()
                if any(kw in low for kw in ["how many", "what is", "which of",
                                             "an assistant claims", "calculate",
                                             "is it true", "true or false"]):
                    if is_question_text(line):
                        question = line
                        break

        if not question:
            return None, None

        skip = ["start mining", "boost", "sign in", "log in", "copy", "post it",
                "verify my handle", "get a new code", "cancel", "start", "next",
                "confirm", "close", "rig", "boosts", "si", "wallet",
                "leaderboard", "earn hashpower", "advisor", "auto-pilot",
                "x tasks", "x account", "handle", "tweet"]

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
    except Exception:
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

def answer_question(page, llm_client, models, question, options):
    num = ask_llm(llm_client, models, question, options)
    log("quiz", f"LLM chose {num}: {options[num-1][:80]}")
    target = options[num - 1]
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
        page.keyboard.press(str(num))
        log("quiz", f"⚠️ Pressed key '{num}'")

    random_sleep(2.0, 3.5)
    for _ in range(15):
        nb = get_next_button(page)
        if nb:
            try:
                nb.click()
                log("quiz", "✅ Clicked Next")
                random_sleep(2.5, 4.0)
                return True
            except Exception:
                pass
        time.sleep(1)
    return False

def run_quiz(page, llm_client, models):
    answered = 0
    consecutive_fails = 0
    for i in range(MAX_QUESTIONS):
        log("quiz", f"--- Question {i+1}/{MAX_QUESTIONS} ---")
        if detect_done(page):
            log("quiz", "✅ Done for today")
            break

        question, options = None, None
        for attempt in range(3):
            question, options = parse_question(page)
            if question:
                break
            log("quiz", f"⚠️ Parse attempt {attempt+1}/3 failed, waiting...")
            random_sleep(2.5, 4.0)

        if not question:
            log("quiz", "❌ Could not detect question after 3 attempts")
            try:
                body = page.inner_text("body")
                log("quiz", f"Body dump: {body[:400]}")
            except Exception:
                pass
            consecutive_fails += 1
            if consecutive_fails >= 2:
                log("quiz", "❌ Too many failures, stopping")
                break
            nb = get_next_button(page)
            if nb:
                try:
                    nb.click()
                    random_sleep(3.0, 5.0)
                    continue
                except Exception:
                    pass
            page.reload(wait_until="domcontentloaded")
            random_sleep(4.0, 6.0)
            continue

        consecutive_fails = 0
        log("quiz", f"Q: {question[:120]}")
        answer_question(page, llm_client, models, question, options)
        answered += 1
        random_sleep(1.5, 3.0)
        if detect_done(page):
            break
    log("quiz", f"✅ Finished: {answered} questions")
    return answered

def run_for_account(llm_client, models, account):
    log("account", f"📚 {account['display_name']}")
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
            page.goto(SI_URL, wait_until="domcontentloaded", timeout=60000)
            random_sleep(2.0, 4.0)
            sign_in(page, account["login_key"])
            random_sleep(2.0, 4.0)
            if "/si" not in page.url:
                page.goto(SI_URL, wait_until="domcontentloaded", timeout=60000)
                random_sleep(2.0, 4.0)
            if detect_done(page):
                log("account", "Already done for today")
                return 0
            return run_quiz(page, llm_client, models)
        except Exception as e:
            log("account", f"❌ {e}")
            return 0
        finally:
            context.close()

def main():
    if not GROQ_API_KEY:
        log("init", "❌ GROQ_API_KEY missing")
        return
    llm = Groq(api_key=GROQ_API_KEY)
    models = discover_models(llm)
    accounts = load_accounts()
    random.shuffle(accounts)
    total = 0
    for idx, acc in enumerate(accounts, 1):
        log("main", f"=== {idx}/{len(accounts)}: {acc['display_name']} ===")
        total += run_for_account(llm, models, acc)
        random_sleep(10.0, 20.0)
    log("done", f"✅ Total answered: {total}")

if __name__ == "__main__":
    main()
