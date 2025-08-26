import os
import re
import random
from typing import List, Dict, Optional
import logging

from flask import Flask, render_template, request, session, jsonify, redirect, url_for

# External deps
import google.generativeai as genai
import jaconv
from dotenv import load_dotenv

# ----------------------------
# Config
# ----------------------------
# Load .env from the same directory as this file to avoid CWD issues
DOTENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=DOTENV_PATH, override=True)
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

# Logging
logging.basicConfig(level=logging.INFO)
app.logger.info("Loaded .env from %s (exists=%s)", DOTENV_PATH, os.path.exists(DOTENV_PATH))

# Gemini API Key (set GEMINI_API_KEY in environment)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
app.logger.info("GEMINI_API_KEY present: %s", bool(GEMINI_API_KEY))
# Handle possible BOM on key name (UTF-8 with BOM)
if not GEMINI_API_KEY:
    BOM_KEY = "\ufeffGEMINI_API_KEY"
    if os.environ.get(BOM_KEY):
        GEMINI_API_KEY = os.environ.get(BOM_KEY)
        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY  # normalize for the rest of the app
        app.logger.warning("Detected BOM on env var name; normalized GEMINI_API_KEY.")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        app.config["GEMINI_ENABLED"] = True
        app.logger.info("Gemini API key detected: enabled")
    except Exception as e:
        app.config["GEMINI_ENABLED"] = False
        app.logger.error("Failed to configure Gemini: %s", e)
else:
    app.config["GEMINI_ENABLED"] = False
    app.logger.warning("Gemini API key not found: running in fallback mode")

# Model selection
GEMINI_MODEL_EASY = "gemini-1.5-flash"
GEMINI_MODEL_HARD = "gemini-1.5-pro"

# Simple fallback wordlist (hiragana). Limited but safe.
FALLBACK_WORDS = [
    "りんご", "ごりら", "らっぱ", "ぱんだ", "だるま", "まくら", "らいおん", "んま" ,
    "すいか", "かめ", "めだか", "かさ", "さかな", "なす", "すずめ", "めろん", "のり", "りす",
    "たぬき", "きつね", "ねこ", "こあら", "らくだ", "だいこん", "こんぶ", "ぶどう", "うま",
    "まめ", "めんたいこ", "こめ", "めがね", "ねぎ", "ぎゅうにゅう", "うさぎ", "ぎんなん",
]
# Ensure all fallback are hiragana
FALLBACK_WORDS = [jaconv.kata2hira(jaconv.z2h(w, kana=True, digit=False, ascii=False)) for w in FALLBACK_WORDS]

SMALL_TO_NORMAL = {
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
    "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
}

VOWELS = set("あいうえお")

# ----------------------------
# Utilities
# ----------------------------

def normalize_kana(word: str) -> str:
    if not word:
        return ""
    w = word.strip().lower()
    # Convert zenkaku to hankaku only for kana, then katakana to hiragana
    w = jaconv.z2h(w, kana=True, digit=False, ascii=False)
    w = jaconv.kata2hira(w)
    # remove spaces and punctuation
    w = re.sub(r"[\s\-ー〜~・·\.\,、。！？!\?\(\)\[\]\{\}\"\'\/\\]", "", w)
    return w


def last_effective_char(word: str) -> Optional[str]:
    w = normalize_kana(word)
    if not w:
        return None
    # ignore trailing small 'っ'
    if w.endswith("っ") and len(w) >= 2:
        w = w[:-1]
    ch = w[-1]
    # map small kana to normal
    ch = SMALL_TO_NORMAL.get(ch, ch)
    return ch


def first_effective_char(word: str) -> Optional[str]:
    w = normalize_kana(word)
    if not w:
        return None
    ch = w[0]
    ch = SMALL_TO_NORMAL.get(ch, ch)
    return ch


def is_valid_hiragana_word(word: str) -> bool:
    if not word:
        return False
    w = normalize_kana(word)
    if not w:
        return False
    # only hiragana
    if not re.fullmatch(r"[ぁ-ゖー]+", w):
        return False
    # should not end with 'ん'
    le = last_effective_char(w)
    if le == "ん":
        return False
    return True


# ----------------------------
# Game State Helpers
# ----------------------------

def init_game(difficulty: str):
    session["difficulty"] = difficulty
    session["history"] = []  # list of dicts {player: "you"|"ai", word: str}
    session["used"] = []
    session["expect"] = None  # expected starting kana for next player
    session["status"] = "playing"
    session["loser"] = None


def add_history(player: str, word: str):
    h = session.get("history", [])
    h.append({"player": player, "word": normalize_kana(word)})
    session["history"] = h
    used = set(session.get("used", []))
    used.add(normalize_kana(word))
    session["used"] = list(used)
    session.modified = True


def get_used_set() -> set:
    return set(session.get("used", []))


# ----------------------------
# AI Turn (Gemini + Fallback)
# ----------------------------

def build_ai_system_prompt(difficulty: str) -> str:
    base_rule = (
        "あなたは日本語のしりとりゲームの相手です。出力は必ず1語のみのひらがな名詞。"
        "禁止: 末尾が『ん』、カタカナ、漢字、英字、記号、助詞、スラング、固有名詞の人名。"
        "語尾の小文字や長音は正規的に処理済みとする。重複語は使用不可。"
    )
    if difficulty == "easy":
        style = "やさしい語彙で一般的な単語を選ぶ。"
        model_hint = "短く、ひらがなのみで1語だけ出力。"
    elif difficulty == "hard":
        style = "語彙はやや難しめだが一般的に辞書掲載される名詞を選ぶ。レアすぎる語は避ける。"
        model_hint = "ひらがなのみ1語。装飾や説明は一切不要。"
    else:
        style = "標準的な語彙で自然な難易度の単語を選ぶ。"
        model_hint = "ひらがなのみ1語。"
    return f"{base_rule}{style}{model_hint}"


def ask_gemini(next_head: Optional[str], used: set, difficulty: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None
    model_name = GEMINI_MODEL_EASY if difficulty == "easy" else (
        GEMINI_MODEL_HARD if difficulty == "hard" else GEMINI_MODEL_EASY
    )
    model = genai.GenerativeModel(model_name)

    sys_prompt = build_ai_system_prompt(difficulty)
    used_list = sorted(list(used))
    head_text = next_head or "自由"

    user_prompt = (
        "しりとりで使う単語を1語だけ出力してください。\n"
        f"先頭の文字: {head_text}\n"
        f"使用済み単語: {"、".join(used_list) if used_list else "なし"}\n"
        "条件: ひらがな名詞のみ。説明や句読点、語尾助詞、余分なテキストは一切付けない。"
    )

    try:
        # Use simple text prompts to avoid SDK schema issues
        resp = model.generate_content([sys_prompt, user_prompt])
        text = resp.text.strip() if hasattr(resp, "text") and resp.text else ""
        candidate = normalize_kana(text)
        # keep only first token if model returned extra
        candidate = candidate.split()[0] if candidate else ""
        return candidate or None
    except Exception as e:
        app.logger.error("Gemini generate_content failed: %s", e)
        return None


def ai_choose_word(next_head: Optional[str], difficulty: str) -> Optional[str]:
    used = get_used_set()

    # 1) Try Gemini up to 3 attempts
    for _ in range(3):
        cand = ask_gemini(next_head, used, difficulty)
        if cand and is_valid_hiragana_word(cand):
            if cand not in used and (not next_head or first_effective_char(cand) == next_head):
                return cand
    # 2) Fallback to simple list
    candidates = [w for w in FALLBACK_WORDS if w not in used]
    if next_head:
        candidates = [w for w in candidates if first_effective_char(w) == next_head]
    if not candidates:
        return None
    # Difficulty-based behavior
    if difficulty == "easy":
        # 20% chance to pick a wrong-ending (lose intentionally) if possible
        if random.random() < 0.2:
            bad = [w for w in candidates if last_effective_char(w) == "ん"]
            if bad:
                return random.choice(bad)
    # Choose random valid
    random.shuffle(candidates)
    for w in candidates:
        if is_valid_hiragana_word(w):
            return w
    return None


# ----------------------------
# Flask Routes
# ----------------------------

@app.route("/")
def index():
    return render_template("index.html", history=session.get("history", []), status=session.get("status", "idle"), difficulty=session.get("difficulty"))


@app.route("/start", methods=["POST"]) 
def start():
    difficulty = request.form.get("difficulty", "normal")
    if difficulty not in ("easy", "normal", "hard"):
        difficulty = "normal"
    init_game(difficulty)
    return redirect(url_for("index"))


@app.route("/play", methods=["POST"]) 
def play():
    if session.get("status") != "playing":
        return jsonify({"ok": False, "error": "ゲームを開始してください。"}), 400

    user_word = request.form.get("word", "")
    user_word = normalize_kana(user_word)

    # Basic validations
    if not is_valid_hiragana_word(user_word):
        return jsonify({"ok": False, "error": "ひらがなの1語で、語尾が『ん』でない名詞を入力してください。"}), 400

    used = get_used_set()
    if user_word in used:
        return jsonify({"ok": False, "error": "そのことばは使用済みです。"}), 400

    expect = session.get("expect")
    if expect and first_effective_char(user_word) != expect:
        return jsonify({"ok": False, "error": f"先頭は『{expect}』で始めてください。"}), 400

    # Accept user's word
    add_history("you", user_word)
    next_head = last_effective_char(user_word)

    # If user ends with ん they lose, but we checked earlier; still guard
    if next_head == "ん":
        session["status"] = "ended"
        session["loser"] = "you"
        session["expect"] = None
        return jsonify({"ok": True, "result": "あなたの負け（『ん』で終了）。"})

    # AI turn
    ai_word = ai_choose_word(next_head, session.get("difficulty", "normal"))
    if not ai_word:
        session["status"] = "ended"
        session["loser"] = "ai"
        session["expect"] = None
        return jsonify({"ok": True, "ai": None, "message": "AIは続けられませんでした。あなたの勝ち！"})

    add_history("ai", ai_word)

    last = last_effective_char(ai_word)
    if last == "ん":
        session["status"] = "ended"
        session["loser"] = "ai"
        session["expect"] = None
        return jsonify({"ok": True, "ai": ai_word, "message": "AIが『ん』で終えました。あなたの勝ち！"})

    # Continue game
    session["expect"] = last
    return jsonify({"ok": True, "ai": ai_word, "next_head": last})


@app.route("/reset", methods=["POST"]) 
def reset():
    session.clear()
    return redirect(url_for("index"))


# ----------------------------
# Health check
# ----------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug/gemini")
def debug_gemini():
    return jsonify({
        "enabled": bool(app.config.get("GEMINI_ENABLED", False))
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
