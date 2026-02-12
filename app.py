from flask import Flask, render_template, jsonify, request
import requests, random, re, html
from collections import deque
import os, json

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
SETTINGS_FILE = "settings.json"
DECK_NAME = "Japanese Review"
REINSERT_MIN_INDEX = 4
DEFAULT_MODE = "reviews"
DEFAULT_UI_SETTINGS = {
    "colors": {
        "purple": "#9f00ee",
        "purple2": "#9f00ee",
        "gray": "#e9e9e9",
        "good": "#83c700",
        "bad": "#ff0037",
    },
    "font": "modern",
}

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ---- session state ----
SESSION_QUEUE = deque()   # items: {"cardId": int, "prompt": "meaning"|"reading"}
TOTAL_CARDS = 0
COMPLETED = set()         # cardIds done (both prompts correct)
MISSED = set()            # cardIds ever missed
PASSED = {}               # cardId -> set(prompts passed)
HISTORY = []              # undo snapshots
SESSION_MODE = DEFAULT_MODE
CURRENT_DECK_NAME = DECK_NAME
LESSON_PHASE = None       # None | "study" | "quiz"
LESSON_REMAINING_IDS = []
LESSON_CHUNK_IDS = []
LESSON_STUDY_CARDS = []
UI_SETTINGS = {}

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

def _deep_copy(obj):
    return json.loads(json.dumps(obj))

def normalize_settings(raw: dict | None):
    base = _deep_copy(DEFAULT_UI_SETTINGS)
    raw = raw or {}

    colors = raw.get("colors", {}) if isinstance(raw.get("colors", {}), dict) else {}
    for key, default_value in base["colors"].items():
        value = colors.get(key, default_value)
        if isinstance(value, str) and HEX_COLOR_RE.match(value):
            base["colors"][key] = value

    font = raw.get("font", base["font"])
    font_aliases = {
        "system": "modern",
        "serif": "book",
        "mono": "clean",
    }
    if isinstance(font, str):
        font = font_aliases.get(font, font)
    if font in {"modern", "friendly", "book", "clean"}:
        base["font"] = font

    return base

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return normalize_settings(None)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return normalize_settings(data if isinstance(data, dict) else {})
    except Exception:
        return normalize_settings(None)

def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

def apply_loaded_settings():
    global UI_SETTINGS
    UI_SETTINGS = load_settings()

def template_theme_vars():
    colors = UI_SETTINGS.get("colors", {})
    return {
        "wk_purple": colors.get("purple", DEFAULT_UI_SETTINGS["colors"]["purple"]),
        "wk_purple2": colors.get("purple2", DEFAULT_UI_SETTINGS["colors"]["purple2"]),
        "wk_gray": colors.get("gray", DEFAULT_UI_SETTINGS["colors"]["gray"]),
        "wk_good": colors.get("good", DEFAULT_UI_SETTINGS["colors"]["good"]),
        "wk_bad": colors.get("bad", DEFAULT_UI_SETTINGS["colors"]["bad"]),
    }

def template_base_context():
    return {
        "ui_settings": UI_SETTINGS,
        "theme_vars": template_theme_vars(),
    }

apply_loaded_settings()


# ---- anki helpers ----
def anki_request(action, params=None):
    payload = {"action": action, "version": 6, "params": params or {}}
    r = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data["result"]

def anki_undo_safe():
    try:
        return anki_request("undo")
    except Exception as e:
        msg = str(e).lower()
        if "unsupported action" in msg or "unknown action" in msg:
            return anki_request("guiUndo")
        raise

def mode_card_ids(mode: str):
    mode = (mode or DEFAULT_MODE).lower()
    query_suffix = "is:new" if mode == "lessons" else "is:due"
    ids = anki_request("findCards", {"query": f'deck:"{CURRENT_DECK_NAME}" {query_suffix}'})
    return ids or []

def available_decks():
    decks = anki_request("deckNames")
    if not isinstance(decks, list):
        return [CURRENT_DECK_NAME]
    decks = sorted(decks)
    if CURRENT_DECK_NAME not in decks:
        decks.insert(0, CURRENT_DECK_NAME)
    return decks


# ---- reading extraction ----
BRACKET_RE = re.compile(r"\[([^\]]+)\]")
KANJI_FURIGANA_RE = re.compile(r"([一-龯々〆〤]+)\[([^\]]+)\]")
KANJI_RE = re.compile(r"[一-龯々〆〤]")

def extract_reading_kana(back_text: str) -> str:
    s = (back_text or "").strip()
    if not s:
        return ""
    # 漢字[かな] -> かな (keeps okurigana)
    while True:
        new_s = KANJI_FURIGANA_RE.sub(r"\2", s)
        if new_s == s:
            break
        s = new_s
    # 構成[こうせい] -> こうせい
    m = BRACKET_RE.search(s)
    if m:
        return m.group(1).strip()
    # strip remaining kanji/brackets/spaces
    s = BRACKET_RE.sub("", s)
    s = KANJI_RE.sub("", s)
    s = re.sub(r"\s+", "", s).strip()
    return s

def reading_display(back_text: str) -> str:
    raw = (back_text or "").strip()
    if not raw:
        return ""
    kana = extract_reading_kana(raw)
    no_brackets = BRACKET_RE.sub("", raw).strip()
    if kana and no_brackets and no_brackets != kana:
        return f"{no_brackets} ({kana})"
    return kana or no_brackets


# ---- meanings extraction ----
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

def extract_meanings(notes_text: str):
    s = (notes_text or "").strip()
    if not s:
        return []
    s = html.unescape(s)
    s = _BR_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    parts = re.split(r"[\n;,/•]\s*", s)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p.strip())
        if p:
            out.append(p)
    return out

def normalize_meaning(s: str) -> str:
    s = (s or "").strip().lower()
    s = html.unescape(s).replace("’", "'")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def canonical_meaning(s: str) -> str:
    s = normalize_meaning(s)
    if s.startswith("to "):
        s = s[3:].strip()
    words = [w for w in s.split() if w not in {"a", "an", "the"}]
    return " ".join(words).strip()

def meaning_match(user: str, meanings: list[str]) -> bool:
    u = canonical_meaning(user)
    if not u:
        return False

    for m in meanings:
        mm = canonical_meaning(m)
        if not mm:
            continue

        if u == mm:
            return True

        # allow prefix tolerance (equip vs equip with)
        if mm.startswith(u) and (len(mm) == len(u) or mm[len(u)] == " "):
            return True
        if u.startswith(mm) and (len(u) == len(mm) or u[len(mm)] == " "):
            return True

    return False


# ---- reading normalization ----
def katakana_to_hiragana(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)

def normalize_reading(s: str) -> str:
    s = html.unescape((s or "").strip())
    s = katakana_to_hiragana(s)
    s = s.lower()
    s = re.sub(r"[\s\u3000\u30fb\u3001\u3002\.,!?'\-]", "", s)
    return s

def reading_match(user: str, expected: str) -> bool:
    u = normalize_reading(user)
    e = normalize_reading(expected)
    if not u or not e:
        return False
    if u == e:
        return True

    # IME timing edge: trailing "n" before conversion should match terminal kana n.
    variants = {u}
    if u.endswith("n"):
        variants.add(u[:-1] + "\u3093")
    if "nn" in u:
        variants.add(u.replace("nn", "\u3093"))
    return e in variants


# ---- card info ----
def card_payload(card_id: int):
    info = anki_request("cardsInfo", {"cards": [card_id]})[0]
    fields = info["fields"]
    front = (fields.get("Front", {}).get("value") or "").strip()
    back = (fields.get("Back", {}).get("value") or "").strip()
    notes = (fields.get("Notes", {}).get("value") or "")
    reading = extract_reading_kana(back)
    return {
        "cardId": int(info["cardId"]),
        "front": front,
        "reading": reading,
        "readingUI": reading_display(back),
        "notes": notes,
    }


# ---- queue logic ----
def build_pair(card_id: int):
    if random.random() < 0.5:
        return [{"cardId": card_id, "prompt": "meaning"},
                {"cardId": card_id, "prompt": "reading"}]
    return [{"cardId": card_id, "prompt": "reading"},
            {"cardId": card_id, "prompt": "meaning"}]

def build_lesson_chunk(ids: list[int]):
    cards = []
    for cid in ids:
        payload = card_payload(cid)
        cards.append({
            "cardId": cid,
            "front": payload.get("front", ""),
            "reading": payload.get("readingUI", "") or payload.get("reading", ""),
            "meanings": extract_meanings(payload.get("notes", "")),
        })
    return cards

def lesson_prepare_next_chunk():
    global LESSON_PHASE, LESSON_CHUNK_IDS, LESSON_STUDY_CARDS, LESSON_REMAINING_IDS
    global SESSION_QUEUE, PASSED, HISTORY

    if not LESSON_REMAINING_IDS:
        LESSON_PHASE = None
        LESSON_CHUNK_IDS = []
        LESSON_STUDY_CARDS = []
        SESSION_QUEUE.clear()
        PASSED.clear()
        HISTORY.clear()
        return

    LESSON_CHUNK_IDS = LESSON_REMAINING_IDS[:5]
    LESSON_REMAINING_IDS = LESSON_REMAINING_IDS[5:]
    LESSON_STUDY_CARDS = build_lesson_chunk(LESSON_CHUNK_IDS)
    LESSON_PHASE = "study"
    SESSION_QUEUE.clear()
    PASSED.clear()
    HISTORY.clear()

def lesson_start_quiz_phase():
    global LESSON_PHASE, SESSION_QUEUE, HISTORY, PASSED
    if not LESSON_CHUNK_IDS:
        return

    pairs = [build_pair(cid) for cid in LESSON_CHUNK_IDS]
    random.shuffle(pairs)
    SESSION_QUEUE = deque([x for pair in pairs for x in pair])
    LESSON_PHASE = "quiz"
    PASSED.clear()
    HISTORY.clear()

def reset_session():
    global SESSION_QUEUE, TOTAL_CARDS, COMPLETED, MISSED, PASSED, HISTORY
    global LESSON_PHASE, LESSON_REMAINING_IDS, LESSON_CHUNK_IDS, LESSON_STUDY_CARDS
    SESSION_QUEUE = deque()
    TOTAL_CARDS = 0
    COMPLETED = set()
    MISSED = set()
    PASSED = {}
    HISTORY = []
    LESSON_PHASE = None
    LESSON_REMAINING_IDS = []
    LESSON_CHUNK_IDS = []
    LESSON_STUDY_CARDS = []

def configure_session(mode: str | None = None, deck_name: str | None = None):
    global SESSION_MODE, CURRENT_DECK_NAME
    new_mode = (mode or SESSION_MODE or DEFAULT_MODE).lower()
    if new_mode not in {"lessons", "reviews"}:
        new_mode = DEFAULT_MODE
    new_deck = (deck_name or CURRENT_DECK_NAME or DECK_NAME).strip()
    changed = (new_mode != SESSION_MODE) or (new_deck != CURRENT_DECK_NAME)
    SESSION_MODE = new_mode
    CURRENT_DECK_NAME = new_deck
    if changed:
        reset_session()

def start_session_if_needed():
    global SESSION_QUEUE, TOTAL_CARDS, COMPLETED, MISSED, PASSED, HISTORY
    global LESSON_PHASE, LESSON_REMAINING_IDS, LESSON_CHUNK_IDS, LESSON_STUDY_CARDS

    if SESSION_MODE == "lessons":
        if LESSON_PHASE is None and not LESSON_CHUNK_IDS and not LESSON_REMAINING_IDS:
            ids = mode_card_ids("lessons")
            TOTAL_CARDS = len(ids)
            LESSON_REMAINING_IDS = list(ids)
            COMPLETED.clear()
            MISSED.clear()
            PASSED.clear()
            HISTORY.clear()
            lesson_prepare_next_chunk()
        elif LESSON_PHASE == "quiz" and not SESSION_QUEUE:
            lesson_prepare_next_chunk()
        return

    if SESSION_QUEUE:
        return

    ids = mode_card_ids("reviews")
    TOTAL_CARDS = len(ids)
    pairs = [build_pair(cid) for cid in ids]
    random.shuffle(pairs)
    SESSION_QUEUE = deque([x for pair in pairs for x in pair])
    COMPLETED.clear()
    MISSED.clear()
    PASSED.clear()
    HISTORY.clear()

def remaining_cards():
    return max(0, TOTAL_CARDS - len(COMPLETED))

def completed_cards():
    return len(COMPLETED)

def remove_prompts_for_card(card_id: int):
    global SESSION_QUEUE
    SESSION_QUEUE = deque([x for x in SESSION_QUEUE if x["cardId"] != card_id])

def remove_prompt_instance(card_id: int, prompt: str):
    """Remove any existing queued instance of this exact prompt for this card."""
    global SESSION_QUEUE
    SESSION_QUEUE = deque([
        x for x in SESSION_QUEUE
        if not (x["cardId"] == card_id and x["prompt"] == prompt)
    ])

def insert_item_later(item: dict):
    """
    Reinsert a SINGLE prompt item later in the queue (not immediate).
    item looks like {"cardId": int, "prompt": "meaning"|"reading"}
    """
    global SESSION_QUEUE

    card_id = item["cardId"]
    prompt = item["prompt"]

    # Ensure we don't duplicate the same prompt multiple times
    remove_prompt_instance(card_id, prompt)

    qlen = len(SESSION_QUEUE)
    min_index = min(REINSERT_MIN_INDEX, qlen)  # keep it from coming back immediately

    if qlen <= min_index:
        SESSION_QUEUE.append(item)
        return

    idx = random.randint(min_index, qlen)
    newq = list(SESSION_QUEUE)
    newq.insert(idx, item)
    SESSION_QUEUE = deque(newq)

def insert_pair_later(card_id: int):
    global SESSION_QUEUE  # <-- THIS is the missing piece

    pair = build_pair(card_id)
    remove_prompts_for_card(card_id)

    qlen = len(SESSION_QUEUE)
    min_index = min(REINSERT_MIN_INDEX, qlen)  # avoid immediate repeat

    if qlen <= min_index:
        SESSION_QUEUE.extend(pair)
        return

    idx = random.randint(min_index, qlen)
    newq = list(SESSION_QUEUE)
    newq[idx:idx] = pair
    SESSION_QUEUE = deque(newq)


def snapshot(did_anki: bool):
    return {
        "queue": list(SESSION_QUEUE),
        "total": TOTAL_CARDS,
        "completed": list(COMPLETED),
        "missed": list(MISSED),
        "passed": {cid: list(v) for cid, v in PASSED.items()},
        "did_anki": bool(did_anki),
    }

def restore_snapshot(snap):
    global SESSION_QUEUE, TOTAL_CARDS, COMPLETED, MISSED, PASSED
    SESSION_QUEUE = deque(snap.get("queue", []))
    TOTAL_CARDS = int(snap.get("total", 0))
    COMPLETED = set(snap.get("completed", []))
    MISSED = set(snap.get("missed", []))
    PASSED = {int(cid): set(v) for cid, v in snap.get("passed", {}).items()}

def submit_to_anki(card_id: int, force_learned: bool = False):
    ease = 3 if force_learned else (1 if card_id in MISSED else 3)
    anki_request("answerCards", {"answers": [{"cardId": card_id, "ease": ease}]})

def api_error(route: str, err: Exception):
    return jsonify({"ok": False, "error": f"{route} failed: {err}"}), 200


# ---- routes ----
@app.route("/")
def splash():
    reset_session()
    ctx = template_base_context()
    return render_template("splash.html", **ctx)

@app.route("/study/<mode>")
def study(mode):
    configure_session(mode=mode)
    title_mode = "Lessons" if SESSION_MODE == "lessons" else "Reviews"
    ctx = template_base_context()
    return render_template("index.html", study_mode=title_mode, deck_name=CURRENT_DECK_NAME, **ctx)

@app.route("/settings")
def settings_page():
    ctx = template_base_context()
    return render_template("settings.html", **ctx)

@app.route("/api/settings")
def get_settings():
    return jsonify({"ok": True, "settings": UI_SETTINGS}), 200

@app.route("/api/settings", methods=["POST"])
def update_settings():
    global UI_SETTINGS
    try:
        data = request.json or {}
        settings = normalize_settings(data if isinstance(data, dict) else {})
        save_settings(settings)
        UI_SETTINGS = settings
        return jsonify({"ok": True, "settings": UI_SETTINGS}), 200
    except Exception as e:
        return api_error("/api/settings", e)

@app.route("/api/settings/reset", methods=["POST"])
def reset_settings():
    global UI_SETTINGS
    try:
        settings = normalize_settings(None)
        save_settings(settings)
        UI_SETTINGS = settings
        return jsonify({"ok": True, "settings": UI_SETTINGS}), 200
    except Exception as e:
        return api_error("/api/settings/reset", e)

@app.route("/api/splash")
def splash_data():
    try:
        reviews_available = len(mode_card_ids("reviews"))
        lessons_available = len(mode_card_ids("lessons"))
        return jsonify({
            "ok": True,
            "ankiConnected": True,
            "deck": CURRENT_DECK_NAME,
            "reviewsAvailable": reviews_available,
            "lessonsAvailable": lessons_available,
            "decks": available_decks(),
        }), 200
    except Exception as e:
        return jsonify({
            "ok": True,
            "ankiConnected": False,
            "deck": CURRENT_DECK_NAME,
            "reviewsAvailable": 0,
            "lessonsAvailable": 0,
            "decks": [CURRENT_DECK_NAME],
            "error": str(e),
            "instructions": [
                "Open Anki on this computer.",
                "Install AnkiConnect add-on code 2055492159 (Tools -> Add-ons -> Get Add-ons).",
                "Restart Anki after installing.",
                "Keep Anki running, then refresh this page.",
            ],
        }), 200

@app.route("/set_deck", methods=["POST"])
def set_deck():
    try:
        data = request.json or {}
        deck = (data.get("deck") or "").strip()
        if not deck:
            return jsonify({"ok": False, "error": "Missing deck"}), 200
        configure_session(deck_name=deck)
        return jsonify({"ok": True, "deck": CURRENT_DECK_NAME}), 200
    except Exception as e:
        return api_error("/set_deck", e)

@app.route("/lesson/start_quiz", methods=["POST"])
def lesson_start_quiz():
    try:
        configure_session(mode="lessons")
        start_session_if_needed()
        if LESSON_PHASE != "study":
            return jsonify({"ok": False, "error": "Lesson study phase not active"}), 200
        lesson_start_quiz_phase()
        return jsonify({"ok": True}), 200
    except Exception as e:
        return api_error("/lesson/start_quiz", e)

@app.route("/next")
def next_card():
    try:
        configure_session()
        start_session_if_needed()

        if SESSION_MODE == "lessons" and LESSON_PHASE == "study":
            return jsonify({
                "done": False,
                "mode": "lessons",
                "lessonPhase": "study",
                "chunk": LESSON_STUDY_CARDS,
                "remaining": remaining_cards(),
                "completed": completed_cards(),
                "total": TOTAL_CARDS,
                "deck": CURRENT_DECK_NAME
            }), 200

        if not SESSION_QUEUE:
            return jsonify({
                "done": True,
                "remaining": 0,
                "completed": completed_cards(),
                "total": TOTAL_CARDS,
                "mode": SESSION_MODE,
                "deck": CURRENT_DECK_NAME
            })

        item = SESSION_QUEUE[0]
        cid = item["cardId"]
        payload = card_payload(cid)
        meanings = extract_meanings(payload.get("notes", ""))

        return jsonify({
            "done": False,
            "card": payload,
            "meanings": meanings,
            "prompt": item["prompt"],
            "remaining": remaining_cards(),
            "completed": completed_cards(),
            "total": TOTAL_CARDS,
            "mode": SESSION_MODE,
            "deck": CURRENT_DECK_NAME
        }), 200
    except Exception as e:
        return api_error("/next", e)

@app.route("/answer", methods=["POST"])
def answer():
    try:
        configure_session()
        start_session_if_needed()
        data = request.json or {}
        card_id = int(data.get("cardId"))
        user = (data.get("answer") or "").strip()

        if not SESSION_QUEUE or SESSION_QUEUE[0]["cardId"] != card_id:
            return jsonify({"ok": False, "error": "Out of sync"}), 200

        prompt = SESSION_QUEUE[0]["prompt"]
        payload = card_payload(card_id)
        meanings = extract_meanings(payload.get("notes", ""))

        # Snapshot before mutating
        HISTORY.append(snapshot(did_anki=False))

        # consume this prompt
        SESSION_QUEUE.popleft()

        if prompt == "reading":
            expected = payload.get("reading", "").strip()
            ideal = payload.get("readingUI", "").strip() or expected
            correct = reading_match(user, expected)
        else:
            expected = ", ".join(meanings) if meanings else "(no meanings in Notes)"
            ideal = meanings[0] if meanings else expected
            correct = meaning_match(user, meanings)

        if not correct:
            MISSED.add(card_id)
            COMPLETED.discard(card_id)

            # Reinsert ONLY the prompt that was missed (meaning OR reading)
            insert_item_later({"cardId": card_id, "prompt": prompt})

            return jsonify({
                "ok": True,
                "correct": False,
                "prompt": prompt,
                "expected": expected,
                "ideal": ideal,
                "remaining": remaining_cards(),
                "completed": completed_cards(),
                "total": TOTAL_CARDS
            }), 200

        # correct: record pass
        passed = PASSED.get(card_id, set())
        passed.add(prompt)
        PASSED[card_id] = passed

        did_anki = False
        if "meaning" in passed and "reading" in passed:
            submit_to_anki(card_id, force_learned=(SESSION_MODE == "lessons"))
            did_anki = True
            COMPLETED.add(card_id)

        HISTORY[-1]["did_anki"] = did_anki

        return jsonify({
            "ok": True,
            "correct": True,
            "prompt": prompt,
            "expected": expected,
            "ideal": ideal,
            "remaining": remaining_cards(),
            "completed": completed_cards(),
            "total": TOTAL_CARDS
        }), 200

    except Exception as e:
        return api_error("/answer", e)

@app.route("/undo", methods=["POST"])
def undo():
    try:
        configure_session()
        start_session_if_needed()
        if not HISTORY:
            return jsonify({
                "ok": True,
                "remaining": remaining_cards(),
                "completed": completed_cards(),
                "total": TOTAL_CARDS
            }), 200

        snap = HISTORY.pop()
        if snap.get("did_anki"):
            anki_undo_safe()
        restore_snapshot(snap)

        return jsonify({
            "ok": True,
            "remaining": remaining_cards(),
            "completed": completed_cards(),
            "total": TOTAL_CARDS
        }), 200
    except Exception as e:
        return api_error("/undo", e)

if __name__ == "__main__":
    app.run(debug=True)
