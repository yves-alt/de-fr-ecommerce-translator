"""
German to French E-commerce Translator
AI-powered product localization tool for e-commerce platforms.

Author: Yves Koulle Banga
"""

import streamlit as st
import os
import re
import json
import uuid
import hmac
import tempfile
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from openpyxl import load_workbook
from openai import OpenAI

load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_FILE  = Path(__file__).parent / "translation_history.json"
TM_FILE       = Path(__file__).parent / "translation_memory.json"
GLOSSARY_FILE = Path(__file__).parent / "glossary.json"

CANDIDATE_SHEETS = ["Tabelle1", "Translations", "Sheet1"]

COLUMNS_TO_TRANSLATE = [
    "name", "colorDetail", "deliveryScope", "materialDetail",
    "otherMeasurements", "qualityDetail", "textileCompositionCover1", "variantName",
]

OPENAI_MODEL           = "gpt-4o-mini"
_INPUT_COST_PER_TOKEN  = 0.15 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000
MANUAL_SECONDS_PER_CELL = 45

DEFAULT_BATCH_SIZE  = 20
MAX_BATCH_RETRIES   = 2
API_TIMEOUT_SECONDS = 45

DEFAULT_GLOSSARY_TERMS = {
    "Bezug":         "Revêtement",
    "Gestell":       "Structure",
    "Füße":          "Pieds",
    "Bettwäsche":    "linge de lit",
    "Webstoff":      "tissu tissé",
    "Strukturstoff": "tissu structuré",
    "Samtstoff":     "tissu velours",
    "Velours":       "velours",
    "Eiche":         "chêne",
    "Buche":         "hêtre",
    "Kiefer":        "pin",
    "Nussbaum":      "noyer",
    "Ahorn":         "érable",
    "Birke":         "bouleau",
    "Massiv":        "massif",
    "Furnier":       "plaqué",
    "lackiert":      "verni",
    "geölt":         "huilé",
    "gebeizt":       "teinté",
    "dunkelgrau":    "gris foncé",
    "hellgrau":      "gris clair",
    "dunkelbraun":   "brun foncé",
    "hellbraun":     "brun clair",
    "dunkelblau":    "bleu foncé",
    "hellblau":      "bleu clair",
    "dunkelgrün":    "vert foncé",
    "hellgrün":      "vert clair",
    "Anthrazit":     "anthracite",
    "Sandbeige":     "beige sable",
    "Baumwolle":     "coton",
    "Leinen":        "lin",
    "Wolle":         "laine",
    "Sofa":          "Canapé",
    "Sessel":        "Fauteuil",
    "Ecksofa":       "Canapé d'angle",
    "Schlafsofa":    "Canapé-lit",
    "Tisch":         "Table",
    "Stuhl":         "Chaise",
    "Schrank":       "Armoire",
    "Kommode":       "Commode",
    "Regal":         "Étagère",
    "inkl.":         "inclus",
}

GERMAN_RESIDUE_WORDS = [
    "mit", "ohne", "und", "oder", "für", "aus", "inkl", "inklusive",
    "bei", "zur", "zum", "vom", "von", "samt", "sowie",
    "Maße", "Masse", "Breite", "Höhe", "Hoehe", "Tiefe", "Länge", "Laenge",
    "Bezug", "Gestell", "Füße", "Fuesse", "Fuße", "Beine",
    "Sitz", "Rücken", "Ruecken", "Armlehne", "Armlehnen",
    "Schublade", "Schubladen", "Türen", "Tueren", "Tür", "Tuer",
    "Polster", "Polsterung", "Lehne",
    "Holz", "Metall", "Kunststoff", "Stoff", "Leder", "Glas",
    "Webstoff", "Strukturstoff", "Samtstoff", "Velours",
    "Eiche", "Buche", "Kiefer", "Nussbaum", "Ahorn", "Birke",
    "Massiv", "massiv", "Furnier",
    "lackiert", "geölt", "geoelt", "gebeizt", "natur",
    "dunkelgrau", "hellgrau", "dunkelbraun", "hellbraun",
    "dunkelblau", "hellblau", "dunkelgrün", "hellgrün",
    "Sand", "sand", "Sandbeige", "Anthrazit",
    "weiß", "weiss", "schwarz", "grün", "gruen", "blau", "rot", "gelb",
    "grau", "braun", "creme", "Creme",
    "Lindgrün", "Moosgrün", "Mintgrün",
    "Bettwäsche", "Bettwasche", "Kissen", "Decke", "Matratze",
    "Baumwolle", "Leinen", "Wolle", "Seide", "Polyester",
    "Sofa", "Couch", "Sessel", "Tisch", "Stuhl", "Stühle", "Stuehle",
    "Schrank", "Bett", "Regal", "Lampe", "Kommode",
    "Sitzer", "Ecksofa", "Schlafsofa", "Longchair",
    "teilig", "Stück", "Stueck", "Set",
    "groß", "gross", "klein", "hoch", "niedrig", "breit", "schmal",
    "höhenverstellbar", "hoehenverstellbar", "ausziehbar", "klappbar",
    "Lieferumfang", "Hinweis", "Achtung", "Wichtig",
    "Zierkissen", "Dekoration",
]

FRENCH_ACCEPTABLE_WORDS = [
    "beige", "taupe", "polyester", "set", "bouclé", "boucle",
]

PROTECTED_KEYWORDS = [
    "articlenumber", "article_number", "sku", "productid", "product_id",
]

IMPORTANT_KEYWORDS = [
    "name", "color", "colour", "delivery", "measurement",
    "quality", "textile", "composition", "material", "variant",
]

TRANSLATE_ALIASES_T1 = {
    "name":                     ["name", "productname", "product_name"],
    "colorDetail":              ["colordetail", "colourdetail", "color_detail", "colour_detail"],
    "deliveryScope":            ["deliveryscope", "delivery_scope", "lieferumfang"],
    "materialDetail":           ["materialdetail", "materialdetails", "material_detail", "compositionmatiere"],
    "otherMeasurements":        ["othermeasurements", "other_measurements", "masse", "abmessungen"],
    "qualityDetail":            ["qualitydetail", "quality_detail"],
    "textileCompositionCover1": [
        "textilecompositioncover1", "textilecompositioncover",
        "textilecomposition",       "textecomposition",
        "compositioncover",         "compositioncover1",
        "textecompositioncover1",
    ],
    "variantName":              ["variantname", "variant_name", "variantenname"],
}

TRANSLATE_ALIASES_T2 = {
    "textileCompositionCover1": ["textilecomposition", "textecomposition", "textilcomposition", "textile", "textil", "composition"],
    "materialDetail":           ["material"],
    "colorDetail":              ["color", "colour"],
    "deliveryScope":            ["delivery"],
    "otherMeasurements":        ["measurement"],
    "qualityDetail":            ["quality"],
    "variantName":              ["variant"],
    "name":                     ["productname"],
}


# =============================================================================
# AUTHENTICATION
# =============================================================================

def _get_credentials() -> tuple[str, str]:
    try:
        email    = st.secrets.get("APP_USER_EMAIL", "")
        password = st.secrets.get("APP_USER_PASSWORD", "")
        if email and password:
            return str(email), str(password)
    except Exception:
        pass
    return os.environ.get("APP_USER_EMAIL", ""), os.environ.get("APP_USER_PASSWORD", "")


def verify_credentials(input_email: str, input_password: str) -> bool:
    stored_email, stored_password = _get_credentials()
    if not stored_email or not stored_password:
        return False
    email_ok    = hmac.compare_digest(input_email.strip().lower(), stored_email.strip().lower())
    password_ok = hmac.compare_digest(input_password, stored_password)
    return email_ok and password_ok


# =============================================================================
# HISTORY
# =============================================================================

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history_record(record: dict) -> None:
    history = load_history()
    history.insert(0, record)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# =============================================================================
# TRANSLATION MEMORY
# =============================================================================

def _tm_col_type(canonical: str) -> str:
    if canonical == "name":
        return "name"
    if canonical == "materialDetail":
        return "materialDetail"
    return "other"


def _tm_key(text: str, col_type: str) -> str:
    return f"{col_type}:{' '.join(text.strip().split())}"


def load_translation_memory() -> dict:
    if TM_FILE.exists():
        try:
            with open(TM_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if "entries" in data and "global_stats" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "entries": {},
        "global_stats": {
            "total_hits":            0,
            "total_misses":          0,
            "total_api_calls_saved": 0,
        },
    }


def save_translation_memory(tm: dict) -> None:
    try:
        with open(TM_FILE, "w", encoding="utf-8") as f:
            json.dump(tm, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def tm_get(tm: dict, text: str, col_type: str) -> str | None:
    key   = _tm_key(text, col_type)
    entry = tm["entries"].get(key)
    if entry is not None:
        entry["hit_count"] = entry.get("hit_count", 0) + 1
        return entry["translation"]
    return None


def tm_put(tm: dict, source: str, translation: str, col_type: str) -> None:
    key = _tm_key(source, col_type)
    if key not in tm["entries"]:
        tm["entries"][key] = {
            "translation": translation,
            "col_type":    col_type,
            "created_at":  datetime.now().isoformat(timespec="seconds"),
            "hit_count":   0,
        }


# =============================================================================
# GLOSSARY SYSTEM
# =============================================================================

def load_glossary() -> dict:
    if GLOSSARY_FILE.exists():
        try:
            with open(GLOSSARY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if "terms" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "terms": DEFAULT_GLOSSARY_TERMS.copy(),
        "stats": {"total_hits": 0, "term_counts": {}},
    }


def save_glossary(glossary: dict) -> None:
    try:
        with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
            json.dump(glossary, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _glossary_prompt_block(glossary: dict) -> str:
    terms = glossary.get("terms", {})
    if not terms:
        return ""
    lines = [f"- {de} → {fr}" for de, fr in list(terms.items())[:25]]
    return "\nAlways use these standard terms consistently:\n" + "\n".join(lines)


def count_glossary_hits(text: str, glossary: dict) -> dict:
    hits      = {}
    terms     = glossary.get("terms", {})
    text_lower = text.lower()
    for de_term in terms:
        pattern = r'\b' + re.escape(de_term.lower()) + r'\b'
        if re.search(pattern, text_lower):
            hits[de_term] = hits.get(de_term, 0) + 1
    return hits


def update_glossary_stats(glossary: dict, term_counts: dict) -> None:
    s  = glossary.setdefault("stats", {"total_hits": 0, "term_counts": {}})
    tc = s.setdefault("term_counts", {})
    for term, count in term_counts.items():
        tc[term]           = tc.get(term, 0) + count
        s["total_hits"]    = s.get("total_hits", 0) + count


# =============================================================================
# DESIGN SYSTEM — CSS
# =============================================================================

def inject_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ── Reset & Base ─────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    .stApp {
        background-color: #0a0a0f !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: #f1f0f7;
        -webkit-font-smoothing: antialiased;
    }

    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .main {
        background-color: #0a0a0f !important;
    }

    .main .block-container {
        padding: 2.5rem 2.5rem 4rem !important;
        max-width: 1080px !important;
    }

    #MainMenu, footer, header,
    div[data-testid="stDecoration"],
    [data-testid="stToolbar"] { display: none !important; visibility: hidden !important; }

    /* ── Animations ───────────────────────────────────────────── */
    @keyframes fadeUp {
        from { opacity: 0; transform: translateY(14px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes glow-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(124,92,252,0.5); }
        50%       { box-shadow: 0 0 0 7px rgba(124,92,252,0); }
    }
    @keyframes dot-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%       { opacity: 0.4; transform: scale(0.75); }
    }
    @keyframes slide-in {
        from { opacity: 0; transform: translateX(-6px); }
        to   { opacity: 1; transform: translateX(0); }
    }

    /* ── Sidebar ──────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background-color: #06060d !important;
        border-right: 1px solid rgba(255,255,255,0.05) !important;
        min-width: 216px !important;
    }
    [data-testid="stSidebarContent"] { padding: 20px 14px !important; }

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div,
    [data-testid="stSidebar"] label { color: #686880 !important; }

    [data-testid="stSidebar"] hr {
        border: none !important;
        border-top: 1px solid rgba(255,255,255,0.05) !important;
        margin: 10px 0 !important;
    }

    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        font-size: 13px !important;
        font-weight: 500 !important;
        padding: 8px 10px !important;
        border-radius: 7px !important;
        cursor: pointer !important;
        transition: color 0.15s, background 0.15s !important;
        display: block !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
        color: #f1f0f7 !important;
        background: rgba(255,255,255,0.05) !important;
    }

    [data-testid="stSidebar"] .stButton > button {
        background: transparent !important;
        color: #3a3a52 !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        border-radius: 8px !important;
        font-size: 12px !important;
        font-weight: 500 !important;
        padding: 7px 14px !important;
        box-shadow: none !important;
        letter-spacing: 0.01em !important;
        transition: color 0.15s, border-color 0.15s, background 0.15s !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        color: #f87171 !important;
        border-color: rgba(248,113,113,0.25) !important;
        background: rgba(248,113,113,0.06) !important;
        transform: none !important;
        box-shadow: none !important;
    }

    .sb-brand { padding: 6px 0 18px; }
    .sb-wordmark {
        display: flex; align-items: center; gap: 9px;
        font-size: 14px; font-weight: 700; letter-spacing: -0.02em;
        color: #f1f0f7 !important;
    }
    .sb-dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: #7c5cfc; flex-shrink: 0;
    }
    .sb-org {
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.09em; color: #28283c !important;
        margin-top: 3px; padding-left: 16px;
    }
    .sb-nav-label {
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: #28283c !important;
        padding: 0 10px; margin-bottom: 4px; display: block;
    }
    .sb-user {
        background: rgba(255,255,255,0.025);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 8px; padding: 10px 12px; margin: 6px 0;
    }
    .sb-user-label {
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.08em; color: #28283c !important; display: block;
    }
    .sb-user-email {
        font-size: 11px; color: #4a4a66 !important;
        margin-top: 4px; display: block; word-break: break-all;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
    }

    /* ── Login page ───────────────────────────────────────────── */
    .login-hero {
        text-align: center; padding: 56px 0 36px;
        animation: fadeUp 0.5s ease;
    }
    .login-lockup {
        display: inline-flex; align-items: center; gap: 9px;
        font-size: 13px; font-weight: 600; color: #3a3a52;
        letter-spacing: 0.07em; text-transform: uppercase;
        margin-bottom: 36px;
    }
    .login-lockup-dot { width: 7px; height: 7px; border-radius: 50%; background: #7c5cfc; }
    .login-title {
        font-size: 34px; font-weight: 800; color: #f1f0f7;
        letter-spacing: -0.04em; margin: 0 0 10px; line-height: 1.1;
    }
    .login-subtitle { font-size: 14px; color: #3a3a52; font-weight: 400; }
    .login-footer {
        text-align: center; font-size: 11px; color: #1e1e2e;
        margin-top: 18px; font-weight: 500;
    }

    [data-testid="stForm"] {
        background: #111118 !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 14px !important;
        padding: 32px 36px !important;
        animation: fadeUp 0.45s ease 0.08s both;
    }

    /* ── Page header ──────────────────────────────────────────── */
    .page-hd {
        padding: 2px 0 26px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        margin-bottom: 28px;
        animation: fadeUp 0.3s ease;
    }
    .page-hd-title {
        font-size: 22px; font-weight: 700; color: #f1f0f7;
        letter-spacing: -0.03em; line-height: 1.2;
    }
    .page-hd-sub { font-size: 13px; color: #3a3a52; margin-top: 4px; font-weight: 400; }

    /* ── Section label ────────────────────────────────────────── */
    .section-label {
        font-size: 11px; font-weight: 700; color: #2e2e44;
        text-transform: uppercase; letter-spacing: 0.1em;
        margin: 28px 0 12px;
    }

    /* ── Cards ────────────────────────────────────────────────── */
    .card {
        background: #111118;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px; padding: 24px; margin: 10px 0;
        animation: fadeUp 0.3s ease;
        transition: border-color 0.2s;
    }
    .card:hover { border-color: rgba(255,255,255,0.11); }
    .card-title {
        font-size: 12px; font-weight: 700; color: #3a3a52;
        text-transform: uppercase; letter-spacing: 0.09em;
        margin-bottom: 18px; padding-bottom: 14px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }

    /* ── Alert / message blocks ───────────────────────────────── */
    .alert {
        display: flex; gap: 11px; align-items: flex-start;
        padding: 13px 16px; border-radius: 9px; margin: 10px 0;
        font-size: 13px; line-height: 1.55;
        animation: fadeUp 0.3s ease;
    }
    .alert-icon { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
    .alert-info  { background: rgba(90,140,248,0.07); border: 1px solid rgba(90,140,248,0.14); color: #7a9ff5; }
    .alert-success { background: rgba(16,185,129,0.07); border: 1px solid rgba(16,185,129,0.14); color: #4fcba4; }
    .alert-warn  { background: rgba(245,158,11,0.07); border: 1px solid rgba(245,158,11,0.14); color: #c89a44; }
    .alert strong { color: #f1f0f7; font-weight: 600; }
    .alert code {
        font-family: Menlo, Monaco, monospace; font-size: 11px;
        background: rgba(255,255,255,0.07); padding: 1px 5px; border-radius: 4px;
        color: #9b9bbb;
    }

    /* ── Stat result cards ────────────────────────────────────── */
    .result-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin: 18px 0; }
    .result-card {
        background: #111118; border: 1px solid rgba(255,255,255,0.06);
        border-radius: 11px; padding: 18px 16px;
        transition: border-color 0.2s, transform 0.2s;
        animation: fadeUp 0.35s ease;
    }
    .result-card:hover { border-color: rgba(255,255,255,0.12); transform: translateY(-2px); }
    .result-card-label {
        font-size: 10px; font-weight: 700; color: #2e2e44;
        text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px;
    }
    .result-card-value {
        font-size: 28px; font-weight: 800; letter-spacing: -0.04em;
        font-variant-numeric: tabular-nums; color: #f1f0f7;
    }
    .result-card-value.accent  { color: #7c5cfc; }
    .result-card-value.success { color: #10b981; }
    .result-card-value.warn    { color: #f59e0b; }

    /* ── Column chips ─────────────────────────────────────────── */
    .chip {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 5px;
        font-size: 11px; font-weight: 600;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
        margin: 3px 3px 3px 0;
    }
    .chip-accent {
        background: rgba(124,92,252,0.1);
        border: 1px solid rgba(124,92,252,0.18);
        color: #9b7fff;
    }
    .chip-muted {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        color: #3a3a52;
    }
    .chip-arrow { color: #3a3a52; font-family: sans-serif; font-weight: 400; }

    /* ── File chip ────────────────────────────────────────────── */
    .file-chip {
        display: inline-flex; align-items: center; gap: 8px;
        background: rgba(124,92,252,0.08);
        border: 1px solid rgba(124,92,252,0.18);
        color: #9b7fff; padding: 6px 14px; border-radius: 20px;
        font-size: 12px; font-weight: 600; margin: 8px 0;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
        animation: slide-in 0.25s ease;
    }

    /* ── Progress shell ───────────────────────────────────────── */
    .prog-shell {
        background: #111118;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px; padding: 26px 28px; margin: 14px 0;
        animation: fadeUp 0.3s ease;
    }
    .prog-head {
        display: flex; align-items: center;
        justify-content: space-between; margin-bottom: 18px;
    }
    .prog-phase {
        font-size: 12px; font-weight: 700; color: #f1f0f7;
        text-transform: uppercase; letter-spacing: 0.07em;
    }
    .prog-sheet { font-size: 11px; color: #2e2e44; margin-top: 3px; }
    .prog-badge {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 20px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
        background: rgba(124,92,252,0.12);
        border: 1px solid rgba(124,92,252,0.22);
        color: #9b7fff;
    }
    .prog-badge-dot {
        width: 5px; height: 5px; border-radius: 50%; background: #7c5cfc;
        animation: dot-pulse 1.4s ease infinite;
    }
    .prog-track {
        width: 100%; height: 3px;
        background: rgba(255,255,255,0.05);
        border-radius: 2px; overflow: hidden; margin: 14px 0;
        position: relative;
    }
    .prog-bar {
        height: 3px; border-radius: 2px;
        background: linear-gradient(90deg, #7c5cfc 0%, #5a8cf8 100%);
        transition: width 0.4s ease; position: relative;
    }
    .prog-bar::after {
        content: ''; position: absolute; right: -1px; top: -2px;
        width: 7px; height: 7px; background: #9b7fff;
        border-radius: 50%; animation: glow-pulse 1.6s ease infinite;
    }
    .prog-item {
        display: flex; align-items: center; gap: 8px;
        font-size: 12px; color: #3a3a52; margin: 10px 0;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
    }
    .prog-item-dot {
        width: 5px; height: 5px; border-radius: 50%; background: #7c5cfc; flex-shrink: 0;
        animation: dot-pulse 1.4s ease infinite;
    }
    .prog-item-col { color: #9b7fff; }
    .prog-item-row { color: #2e2e44; margin-left: 6px; }
    .prog-stats {
        display: flex; gap: 28px; margin-top: 18px; padding-top: 14px;
        border-top: 1px solid rgba(255,255,255,0.04);
        flex-wrap: wrap;
    }
    .prog-stat-val {
        font-size: 15px; font-weight: 700; color: #f1f0f7;
        font-variant-numeric: tabular-nums; display: block;
    }
    .prog-stat-lbl {
        font-size: 9px; font-weight: 700; color: #2e2e44;
        text-transform: uppercase; letter-spacing: 0.09em;
        margin-top: 2px; display: block;
    }

    /* ── Quality gate ─────────────────────────────────────────── */
    .qg {
        background: #111118; border: 1px solid rgba(255,255,255,0.06);
        border-radius: 11px; overflow: hidden; margin: 14px 0;
        animation: fadeUp 0.35s ease;
    }
    .qg-row {
        display: flex; align-items: center; gap: 16px;
        padding: 13px 20px;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        font-size: 13px;
        transition: background 0.15s;
    }
    .qg-row:last-child { border-bottom: none; }
    .qg-row:hover { background: rgba(255,255,255,0.02); }
    .qg-icon { flex-shrink: 0; font-size: 13px; }
    .qg-label { font-weight: 600; color: #686880; min-width: 160px; font-size: 12px; }
    .qg-value { color: #3a3a52; font-size: 12px; font-family: Menlo, Monaco, monospace; }

    /* ── Warning detail ───────────────────────────────────────── */
    .warn-detail {
        display: flex; gap: 12px; align-items: flex-start;
        padding: 13px 16px; margin: 7px 0;
        background: rgba(245,158,11,0.04);
        border: 1px solid rgba(245,158,11,0.1);
        border-radius: 9px; font-size: 12px; color: #686880;
        animation: fadeUp 0.3s ease;
    }
    .warn-detail-dot {
        width: 5px; height: 5px; border-radius: 50%;
        background: #f59e0b; margin-top: 4px; flex-shrink: 0;
    }
    .warn-detail strong { color: #c8952a; }

    /* ── Success / completion banner ──────────────────────────── */
    .success-banner {
        display: flex; align-items: center; gap: 16px;
        padding: 20px 24px;
        background: rgba(16,185,129,0.06);
        border: 1px solid rgba(16,185,129,0.14);
        border-radius: 11px; margin: 16px 0;
        animation: fadeUp 0.3s ease;
    }
    .success-banner-icon {
        width: 36px; height: 36px; border-radius: 50%;
        background: rgba(16,185,129,0.15);
        border: 1px solid rgba(16,185,129,0.25);
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; flex-shrink: 0;
    }
    .success-banner-title { font-size: 14px; font-weight: 700; color: #10b981; }
    .success-banner-sub   { font-size: 11px; color: #2e4a40; margin-top: 3px; }

    .warn-banner {
        padding: 18px 22px;
        background: rgba(245,158,11,0.05);
        border: 1px solid rgba(245,158,11,0.12);
        border-radius: 11px; margin: 16px 0;
        animation: fadeUp 0.3s ease;
    }
    .warn-banner-title { font-size: 14px; font-weight: 700; color: #c89a44; }
    .warn-banner-sub   { font-size: 11px; color: #3a2e1a; margin-top: 3px; }

    /* ── Metric cards ─────────────────────────────────────────── */
    .kpi-row   { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin: 18px 0; }
    .kpi-row-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 10px; margin: 18px 0; }
    .kpi {
        background: #111118;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 11px; padding: 20px 18px;
        transition: border-color 0.2s, transform 0.2s;
        animation: fadeUp 0.35s ease;
    }
    .kpi:hover { border-color: rgba(255,255,255,0.12); transform: translateY(-2px); }
    .kpi-label {
        font-size: 10px; font-weight: 700; color: #2e2e44;
        text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px;
    }
    .kpi-value {
        font-size: 28px; font-weight: 800; letter-spacing: -0.04em;
        color: #f1f0f7; font-variant-numeric: tabular-nums;
    }
    .kpi-value.accent  { color: #7c5cfc; }
    .kpi-value.success { color: #10b981; }
    .kpi-value.warn    { color: #f59e0b; }
    .kpi-sub { font-size: 11px; color: #2e2e44; margin-top: 5px; }

    /* ── Hero metric ──────────────────────────────────────────── */
    .hero-kpi {
        text-align: center; padding: 52px 32px; border-radius: 14px;
        background: linear-gradient(135deg, rgba(124,92,252,0.07) 0%, rgba(90,140,248,0.07) 100%);
        border: 1px solid rgba(124,92,252,0.16); margin: 20px 0;
        animation: fadeUp 0.4s ease;
    }
    .hero-kpi-value {
        font-size: 80px; font-weight: 800; letter-spacing: -0.05em; line-height: 1;
        background: linear-gradient(135deg, #7c5cfc 0%, #5a8cf8 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        margin: 0;
    }
    .hero-kpi-label { font-size: 15px; color: #3a3a52; margin: 14px 0 0; font-weight: 500; }
    .hero-kpi-sub   { font-size: 12px; color: #22223a; margin: 6px 0 0; }

    /* ── History ──────────────────────────────────────────────── */
    .history-empty {
        text-align: center; padding: 70px 20px;
        color: #2e2e44; font-size: 14px; font-weight: 500;
    }
    .cloud-note {
        padding: 11px 15px; border-radius: 8px; margin: 14px 0;
        font-size: 11px; line-height: 1.5;
        background: rgba(90,140,248,0.06);
        border: 1px solid rgba(90,140,248,0.12);
        color: #4a6899;
    }

    /* ── Streamlit native overrides ───────────────────────────── */
    [data-testid="stTextInput"] input {
        background: #18181f !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 8px !important;
        color: #f1f0f7 !important;
        font-size: 13px !important;
        caret-color: #7c5cfc !important;
    }
    [data-testid="stTextInput"] input:focus {
        border-color: rgba(124,92,252,0.45) !important;
        box-shadow: 0 0 0 3px rgba(124,92,252,0.1) !important;
        outline: none !important;
    }
    [data-testid="stTextInput"] label p { color: #4a4a60 !important; font-size: 12px !important; font-weight: 500 !important; }

    [data-testid="stSelectbox"] > div > div {
        background: #18181f !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 8px !important;
        color: #f1f0f7 !important;
        font-size: 13px !important;
    }
    [data-testid="stSelectbox"] label p { color: #4a4a60 !important; font-size: 12px !important; }

    .stProgress { padding: 6px 0 !important; }
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #7c5cfc 0%, #5a8cf8 100%) !important;
        border-radius: 2px !important;
    }

    .stButton > button {
        background: #7c5cfc !important;
        color: #fff !important;
        border: none !important;
        border-radius: 9px !important;
        padding: 11px 26px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        letter-spacing: 0.01em !important;
        transition: background 0.15s, transform 0.15s, box-shadow 0.15s !important;
        box-shadow: 0 2px 10px rgba(124,92,252,0.35) !important;
    }
    .stButton > button:hover {
        background: #8f71ff !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 5px 18px rgba(124,92,252,0.45) !important;
    }
    .stButton > button:active { transform: translateY(0) !important; }

    .stDownloadButton > button {
        background: rgba(16,185,129,0.1) !important;
        color: #10b981 !important;
        border: 1px solid rgba(16,185,129,0.22) !important;
        border-radius: 9px !important;
        padding: 12px 26px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        box-shadow: none !important;
        transition: background 0.15s, border-color 0.15s, transform 0.15s !important;
    }
    .stDownloadButton > button:hover {
        background: rgba(16,185,129,0.16) !important;
        border-color: rgba(16,185,129,0.38) !important;
        transform: translateY(-1px) !important;
    }

    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploader"] > div {
        background: rgba(255,255,255,0.02) !important;
        border: 1.5px dashed rgba(255,255,255,0.09) !important;
        border-radius: 11px !important;
        transition: border-color 0.2s, background 0.2s !important;
    }
    [data-testid="stFileUploader"] section:hover,
    [data-testid="stFileUploader"] > div:hover {
        border-color: rgba(124,92,252,0.38) !important;
        background: rgba(124,92,252,0.03) !important;
    }
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] p { color: #3a3a52 !important; font-size: 13px !important; }
    [data-testid="stFileUploader"] small { color: #22223a !important; }
    [data-testid="stFileUploader"] button {
        background: rgba(124,92,252,0.1) !important;
        color: #9b7fff !important;
        border: 1px solid rgba(124,92,252,0.2) !important;
        border-radius: 7px !important;
        font-size: 12px !important;
        font-weight: 600 !important;
    }

    [data-testid="stExpander"] {
        background: #111118 !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        border-radius: 9px !important;
    }
    [data-testid="stExpander"] summary {
        color: #3a3a52 !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        padding: 10px 14px !important;
    }

    [data-testid="stDataFrame"] {
        border-radius: 11px !important;
        overflow: hidden !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
    }

    .site-footer {
        margin-top: 80px; padding: 22px 0;
        border-top: 1px solid rgba(255,255,255,0.04);
        display: flex; align-items: center; justify-content: space-between;
        font-size: 11px; color: #1e1e2e;
        animation: fadeUp 0.4s ease;
    }

    @media (max-width: 780px) {
        .kpi-row, .result-grid { grid-template-columns: repeat(2,1fr) !important; }
        .hero-kpi-value { font-size: 52px !important; }
        .main .block-container { padding: 1.5rem 1.2rem 3rem !important; }
    }
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# UI COMPONENTS
# =============================================================================

def render_header():
    st.markdown("""
    <div class="login-hero">
        <div class="login-lockup">
            <div class="login-lockup-dot"></div>
            DE→FR Translator
        </div>
        <h1 class="login-title">Welcome back</h1>
        <p class="login-subtitle">Sign in to access the translation workspace</p>
    </div>
    """, unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str = ""):
    sub = f'<div class="page-hd-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f"""
    <div class="page-hd">
        <div class="page-hd-title">{title}</div>
        {sub}
    </div>
    """, unsafe_allow_html=True)


def render_stats(stats: dict):
    warn = "warn" if stats["unresolved_warnings"] > 0 else "success"
    st.markdown(f"""
    <div class="result-grid">
        <div class="result-card">
            <div class="result-card-label">Cells Translated</div>
            <div class="result-card-value accent">{stats["cells_translated"]}</div>
        </div>
        <div class="result-card">
            <div class="result-card-label">Cells Skipped</div>
            <div class="result-card-value">{stats["cells_skipped"]}</div>
        </div>
        <div class="result-card">
            <div class="result-card-label">Residue Fixed</div>
            <div class="result-card-value success">{stats["residue_corrections"]}</div>
        </div>
        <div class="result-card">
            <div class="result-card-label">Warnings</div>
            <div class="result-card-value {warn}">{stats["unresolved_warnings"]}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_intelligence_stats(stats: dict):
    tm_hits      = stats.get("tm_hits", 0)
    batch_count  = stats.get("batch_count", 0)
    avg_batch    = stats.get("avg_batch_size", 0.0)
    gloss_hits   = stats.get("glossary_hits", 0)
    api_reduced  = stats.get("api_calls_reduced", 0)

    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label">TM Cache Hits</div>
            <div class="kpi-value success">{tm_hits}</div>
            <div class="kpi-sub">Served from memory</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">API Batches Sent</div>
            <div class="kpi-value accent">{batch_count}</div>
            <div class="kpi-sub">~{api_reduced} calls saved</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Avg Batch Size</div>
            <div class="kpi-value">{avg_batch}</div>
            <div class="kpi-sub">cells per request</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Glossary Matches</div>
            <div class="kpi-value">{gloss_hits}</div>
            <div class="kpi-sub">Consistent terms enforced</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def format_time(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))[2:7]


def render_column_report(classification: dict):
    to_translate    = classification["to_translate"]
    protected       = classification["protected"]
    ignored         = classification["ignored"]
    possible_missed = classification["possible_missed"]

    if to_translate:
        chips = ""
        for header, (_, canonical) in to_translate.items():
            if header == canonical:
                chips += f'<span class="chip chip-accent">{header}</span>'
            else:
                chips += (
                    f'<span class="chip chip-accent">{header}'
                    f'<span class="chip-arrow"> → {canonical}</span></span>'
                )
        will_translate_html = f"""
        <div style="margin-bottom:16px;">
            <div class="section-label" style="margin-top:0;">Will translate — {len(to_translate)} column(s)</div>
            <div>{chips}</div>
        </div>"""
    else:
        will_translate_html = """
        <div class="alert alert-warn">
            <span class="alert-icon">⚠</span>
            <span>No translatable columns detected in this sheet.</span>
        </div>"""

    prot_html = ""
    if protected:
        prot_chips = "".join(f'<span class="chip chip-muted">{h}</span>' for h in protected)
        prot_html = f"""
        <div style="margin-top:14px;">
            <div class="section-label" style="margin-top:0;">Protected — never modified</div>
            <div>{prot_chips}</div>
        </div>"""

    missed_html = ""
    if possible_missed:
        missed_chips = "".join(f'<span class="chip chip-muted">{h}</span>' for h in possible_missed)
        missed_html = f"""
        <div class="alert alert-warn" style="margin-top:14px;">
            <span class="alert-icon">⚠</span>
            <div>
                <strong>Possible missed columns:</strong><br>
                <div style="margin-top:6px;">{missed_chips}</div>
                <div style="font-size:11px;color:#5a4020;margin-top:5px;">
                    These look like translatable columns but didn't match any known pattern.
                </div>
            </div>
        </div>"""

    st.markdown(f"""
    <div class="card">
        <div class="card-title">Column detection</div>
        {will_translate_html}
        {prot_html}
        {missed_html}
    </div>
    """, unsafe_allow_html=True)

    if ignored:
        with st.expander(f"Ignored columns ({len(ignored)})"):
            st.markdown(", ".join(f"`{h}`" for h in ignored))


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("""
        <div class="sb-brand">
            <div class="sb-wordmark"><div class="sb-dot"></div>DE→FR Translator</div>
            <div class="sb-org">Home24 Internal</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<span class="sb-nav-label">Navigation</span>', unsafe_allow_html=True)

        page = st.radio(
            "Navigation",
            ["Translator", "Translation History", "Analytics", "Glossary"],
            key="nav_radio",
            label_visibility="collapsed",
        )

        st.markdown("---")

        email, _ = _get_credentials()
        st.markdown(f"""
        <div class="sb-user">
            <span class="sb-user-label">Signed in as</span>
            <span class="sb-user-email">{email}</span>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Sign out", key="logout_btn", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

    return page


def render_footer():
    st.markdown("""
    <div class="site-footer">
        <span>Built by <strong style="color:#3a3a52;">Yves Koulle Banga</strong></span>
        <span style="color:#1a1a2a;">DE→FR Translator · v4.0</span>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# VALIDATION
# =============================================================================

def validate_product_name(name: str) -> str:
    if not name:
        return name
    name = " ".join(name.split())
    name = name.replace(",", "")
    name = re.sub(r'\([^)]*\)', '', name)
    name = name.replace("(", "").replace(")", "")
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = name.replace("[", "").replace("]", "")
    name = " ".join(name.split())
    if len(name) > 40:
        truncated = name[:40]
        last_space = truncated.rfind(" ")
        name = truncated[:last_space] if last_space > 20 else truncated
    return name.strip()


def detect_german_residue(text: str) -> list[str]:
    if not text:
        return []
    detected = []
    masked = text.lower()
    for acceptable in FRENCH_ACCEPTABLE_WORDS:
        masked = masked.replace(acceptable.lower(), "X" * len(acceptable))
    for word in GERMAN_RESIDUE_WORDS:
        word_lower = word.lower()
        if word_lower in [w.lower() for w in FRENCH_ACCEPTABLE_WORDS]:
            continue
        if re.compile(r'\b' + re.escape(word_lower) + r'\b', re.IGNORECASE).search(masked):
            detected.append(word)
    return detected


# =============================================================================
# API KEY + CLIENT
# =============================================================================

def _get_api_key() -> str | None:
    try:
        key = st.secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY")


def get_openai_client():
    api_key = _get_api_key()
    if not api_key:
        st.error(
            "**OPENAI_API_KEY not configured.**\n\n"
            "- **Locally:** add `OPENAI_API_KEY=sk-...` to your `.env` file.\n"
            "- **Streamlit Cloud:** App settings → Secrets."
        )
        st.stop()
    return OpenAI(api_key=api_key)


# =============================================================================
# TRANSLATION FUNCTIONS
# =============================================================================

def _build_system_prompt(canonical: str, glossary_block: str) -> str:
    if canonical == "name":
        return (
            "You are a professional translator for Home24 France e-commerce.\n"
            "Translate the German product name to French following these STRICT rules:\n"
            "- Maximum 40 characters total\n"
            "- No commas allowed\n"
            "- No brackets or parentheses allowed\n"
            "- Natural, commercial French product name\n"
            "- \"Sofa\" must become \"Canapé\"\n"
            "- \"Sessel\" must become \"Fauteuil\"\n"
            "- \"Ecksofa\" must become \"Canapé d'angle\"\n"
            "- \"Sitzer\" must become \"places\" (e.g., \"3-Sitzer\" = \"3 places\")\n"
            "- Use only French words"
            f"{glossary_block}\n"
            "Return ONLY the translated text, nothing else."
        )
    elif canonical == "materialDetail":
        return (
            "You are a professional translator for Home24 France e-commerce.\n"
            "Translate the German material description to natural French:\n"
            "- Preserve <br> tags exactly as they appear"
            f"{glossary_block}\n"
            "Return ONLY the translated text, nothing else."
        )
    else:
        return (
            "You are a professional translator for Home24 France e-commerce.\n"
            "Translate the German text to natural French:\n"
            "- Use natural French, not literal translation\n"
            "- Remove all German traces\n"
            "- Preserve <br> tags exactly as they appear"
            f"{glossary_block}\n"
            "Return ONLY the translated text, nothing else."
        )


def translate_batch(
    client,
    texts: list[str],
    canonical: str,
    token_counter: dict,
    glossary: dict,
    glossary_run_stats: dict,
) -> list[str]:
    if not texts:
        return []

    glossary_block = _glossary_prompt_block(glossary)
    n = len(texts)

    # Track glossary hits across all source texts in this batch
    all_hits: dict[str, int] = {}
    for text in texts:
        for term, count in count_glossary_hits(text, glossary).items():
            all_hits[term] = all_hits.get(term, 0) + count
    if all_hits:
        glossary_run_stats["total_hits"] = glossary_run_stats.get("total_hits", 0) + sum(all_hits.values())
        tc = glossary_run_stats.setdefault("term_counts", {})
        for term, count in all_hits.items():
            tc[term] = tc.get(term, 0) + count

    if canonical == "name":
        batch_rules = (
            "Rules for each product name:\n"
            "- Maximum 40 characters, no commas, no brackets\n"
            "- Natural commercial French\n"
            "- \"Sofa\"→\"Canapé\", \"Sessel\"→\"Fauteuil\", "
            "\"Ecksofa\"→\"Canapé d'angle\", \"Sitzer\"→\"places\""
        )
    elif canonical == "materialDetail":
        batch_rules = "- Preserve <br> tags exactly\n- Natural French material terminology"
    else:
        batch_rules = "- Natural French, not literal\n- Remove all German traces\n- Preserve <br> tags exactly"

    system_prompt = (
        "You are a professional translator for Home24 France e-commerce.\n"
        f"Translate each German text to French.\n{batch_rules}{glossary_block}\n\n"
        f"Return ONLY a valid JSON array of exactly {n} translated strings, "
        "in the same order as the input. No other text."
    )
    user_msg = f"Translate these {n} texts:\n{json.dumps(texts, ensure_ascii=False)}"

    for attempt in range(MAX_BATCH_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.3,
                max_tokens=min(4000, n * 200),
                timeout=API_TIMEOUT_SECONDS,
            )
            if token_counter is not None and response.usage:
                token_counter["prompt_tokens"]     += response.usage.prompt_tokens
                token_counter["completion_tokens"] += response.usage.completion_tokens

            content = response.choices[0].message.content.strip()
            if not content.startswith("["):
                m = re.search(r'\[.*\]', content, re.DOTALL)
                content = m.group() if m else content

            translations = json.loads(content)
            if isinstance(translations, list) and len(translations) == n:
                return [str(t).strip() for t in translations]

        except Exception:
            pass

        if attempt < MAX_BATCH_RETRIES:
            continue
        break

    # Fallback: single-cell translation for each item
    return _fallback_single_translations(client, texts, canonical, token_counter, glossary)


def _fallback_single_translations(
    client,
    texts: list[str],
    canonical: str,
    token_counter: dict,
    glossary: dict,
) -> list[str]:
    glossary_block = _glossary_prompt_block(glossary)
    system_prompt  = _build_system_prompt(canonical, glossary_block)
    results        = []
    for text in texts:
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": f"Translate to French:\n\n{text}"},
                ],
                temperature=0.3,
                max_tokens=500,
                timeout=API_TIMEOUT_SECONDS,
            )
            if token_counter is not None and response.usage:
                token_counter["prompt_tokens"]     += response.usage.prompt_tokens
                token_counter["completion_tokens"] += response.usage.completion_tokens
            results.append(response.choices[0].message.content.strip())
        except Exception:
            results.append(text)
    return results


def fix_german_residue(client, text: str, column_name: str, token_counter: dict | None = None) -> str:
    if not text:
        return text

    extra_rules = ""
    if column_name == "name":
        extra_rules = """
- Maximum 40 characters, no commas or brackets
- "Sofa" → "Canapé" / "Sessel" → "Fauteuil" / "Sitzer" → "places\""""
    elif column_name == "materialDetail":
        extra_rules = """
- "Bezug" = "Revêtement" / "Füße" = "Pieds" / "Buche" = "hêtre" / "lackiert" = "verni"
- Preserve <br> tags exactly"""

    fix_prompt = f"""This French text still contains German words.
Rewrite it as clean, natural French for Home24 France.
Replace ALL German words with French equivalents.
{extra_rules}

Text: {text}

Return ONLY the corrected French text."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You remove German words from French texts for Home24 France e-commerce."},
                {"role": "user",   "content": fix_prompt},
            ],
            temperature=0.2,
            max_tokens=500,
            timeout=API_TIMEOUT_SECONDS,
        )
        if token_counter is not None and response.usage:
            token_counter["prompt_tokens"]     += response.usage.prompt_tokens
            token_counter["completion_tokens"] += response.usage.completion_tokens
        corrected = response.choices[0].message.content.strip()
        if column_name == "name":
            corrected = validate_product_name(corrected)
        return corrected
    except Exception:
        return text


# =============================================================================
# EXCEL PROCESSING
# =============================================================================

def detect_target_sheet(sheet_names: list) -> str | None:
    for name in CANDIDATE_SHEETS:
        if name in sheet_names:
            return name
    if len(sheet_names) == 1:
        return sheet_names[0]
    return None


def detect_columns(worksheet) -> dict:
    columns = {}
    for row in worksheet.iter_rows(min_row=1, max_row=1):
        for cell in row:
            if cell.value is not None:
                columns[str(cell.value).strip()] = cell.column
    return columns


def classify_columns(all_columns: dict) -> dict:
    to_translate    = {}
    protected       = {}
    ignored         = {}
    possible_missed = []

    for header, col_idx in all_columns.items():
        normalized = header.strip().lower()

        if any(pk in normalized for pk in PROTECTED_KEYWORDS):
            protected[header] = col_idx
            continue

        canonical = None
        for can, aliases in TRANSLATE_ALIASES_T1.items():
            if normalized in aliases:
                canonical = can
                break

        if canonical is None:
            for can, substrings in TRANSLATE_ALIASES_T2.items():
                if any(sub in normalized for sub in substrings):
                    canonical = can
                    break

        if canonical is not None:
            to_translate[header] = (col_idx, canonical)
        else:
            ignored[header] = col_idx
            if any(ik in normalized for ik in IMPORTANT_KEYWORDS):
                possible_missed.append(header)

    return {
        "to_translate":    to_translate,
        "protected":       protected,
        "ignored":         ignored,
        "possible_missed": possible_missed,
    }


def _progress_html(phase: str, sheet: str, col_header: str, row_index: int,
                   total_rows: int, pct: int, elapsed: float, eta: float,
                   translated: int, skipped: int, fixes: int) -> str:
    return f"""
    <div class="prog-shell">
        <div class="prog-head">
            <div>
                <div class="prog-phase">{phase}</div>
                <div class="prog-sheet">Sheet: {sheet}</div>
            </div>
            <span class="prog-badge">
                <span class="prog-badge-dot"></span>ACTIVE
            </span>
        </div>
        <div class="prog-track">
            <div class="prog-bar" style="width:{pct}%"></div>
        </div>
        <div class="prog-item">
            <div class="prog-item-dot"></div>
            <span class="prog-item-col">{col_header}</span>
            <span class="prog-item-row">row {row_index} / {total_rows}</span>
        </div>
        <div class="prog-stats">
            <div><span class="prog-stat-val">{translated}</span><span class="prog-stat-lbl">Translated</span></div>
            <div><span class="prog-stat-val">{skipped}</span><span class="prog-stat-lbl">Skipped</span></div>
            <div><span class="prog-stat-val">{fixes}</span><span class="prog-stat-lbl">Fixes</span></div>
            <div><span class="prog-stat-val">{format_time(elapsed)}</span><span class="prog-stat-lbl">Elapsed</span></div>
            <div><span class="prog-stat-val">~{format_time(eta)}</span><span class="prog-stat-lbl">Remaining</span></div>
            <div><span class="prog-stat-val">{pct}%</span><span class="prog-stat-lbl">Progress</span></div>
        </div>
    </div>
    """


def _batch_progress_html(phase: str, sheet: str, batch_num: int, batch_size: int,
                         total_api: int, api_done: int, elapsed: float, eta: float,
                         tm_hits: int, tm_misses: int, pct: int) -> str:
    return f"""
    <div class="prog-shell">
        <div class="prog-head">
            <div>
                <div class="prog-phase">{phase}</div>
                <div class="prog-sheet">Sheet: {sheet}</div>
            </div>
            <span class="prog-badge">
                <span class="prog-badge-dot"></span>ACTIVE
            </span>
        </div>
        <div class="prog-track">
            <div class="prog-bar" style="width:{pct}%"></div>
        </div>
        <div class="prog-item">
            <div class="prog-item-dot"></div>
            <span class="prog-item-col">Batch {batch_num}</span>
            <span class="prog-item-row">{api_done} / {total_api} cells</span>
        </div>
        <div class="prog-stats">
            <div><span class="prog-stat-val">{batch_num}</span><span class="prog-stat-lbl">Batches</span></div>
            <div><span class="prog-stat-val">{batch_size}</span><span class="prog-stat-lbl">Batch Size</span></div>
            <div><span class="prog-stat-val">{tm_hits}</span><span class="prog-stat-lbl">TM Hits</span></div>
            <div><span class="prog-stat-val">{tm_misses}</span><span class="prog-stat-lbl">API Queue</span></div>
            <div><span class="prog-stat-val">{format_time(elapsed)}</span><span class="prog-stat-lbl">Elapsed</span></div>
            <div><span class="prog-stat-val">~{format_time(eta)}</span><span class="prog-stat-lbl">Remaining</span></div>
            <div><span class="prog-stat-val">{pct}%</span><span class="prog-stat-lbl">Progress</span></div>
        </div>
    </div>
    """


def process_excel_with_progress(
    uploaded_file,
    progress_bar,
    progress_container,
    sheet_name: str,
    column_classification: dict,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[BytesIO, dict]:
    client   = get_openai_client()
    tm       = load_translation_memory()
    glossary = load_glossary()

    token_counter      = {"prompt_tokens": 0, "completion_tokens": 0}
    glossary_run_stats: dict = {"total_hits": 0, "term_counts": {}}

    stats = {
        "cells_translated":    0,
        "cells_skipped":       0,
        "residue_corrections": 0,
        "unresolved_warnings": 0,
        "warning_details":     [],
        "sheet_name":          sheet_name,
        "tm_hits":             0,
        "tm_misses":           0,
        "batch_count":         0,
        "avg_batch_size":      0.0,
        "glossary_hits":       0,
        "glossary_top_terms":  {},
        "api_calls_made":      0,
        "api_calls_reduced":   0,
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        workbook     = load_workbook(filename=tmp_path, data_only=False)
        worksheet    = workbook[sheet_name]
        to_translate = column_classification["to_translate"]

        if not to_translate:
            raise ValueError("No translatable columns found in the file.")

        total_rows = worksheet.max_row - 1
        start_time = time.time()

        # ── Phase 0: Pre-scan ─────────────────────────────────────────────────
        progress_bar.progress(0.02)
        progress_container.markdown(
            _batch_progress_html(
                "Scanning", sheet_name, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 2
            ),
            unsafe_allow_html=True,
        )

        cells_queue: list[tuple] = []
        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                cell = worksheet.cell(row=row_num, column=col_idx)
                raw  = cell.value
                if raw is None or str(raw).strip() == "":
                    stats["cells_skipped"] += 1
                else:
                    cells_queue.append((row_num, col_header, col_idx, canonical, str(raw).strip()))

        total_to_process = len(cells_queue)
        if total_to_process == 0:
            raise ValueError("All translatable cells are empty — nothing to translate.")

        # ── Phase 1: Translation Memory check ────────────────────────────────
        results: dict[tuple, str] = {}
        api_queue: list[tuple]    = []

        for row_num, col_header, col_idx, canonical, text in cells_queue:
            col_type = _tm_col_type(canonical)
            cached   = tm_get(tm, text, col_type)
            if cached is not None:
                results[(row_num, col_idx)] = cached
                stats["tm_hits"] += 1
            else:
                api_queue.append((row_num, col_header, col_idx, canonical, text))
                stats["tm_misses"] += 1

        # ── Phase 2: Batch translation ────────────────────────────────────────
        by_col_type: dict[str, list] = {}
        for item in api_queue:
            ct = _tm_col_type(item[3])
            by_col_type.setdefault(ct, []).append(item)

        total_api_cells = len(api_queue)
        api_done        = 0

        for col_type, items in by_col_type.items():
            for batch_start in range(0, len(items), batch_size):
                batch          = items[batch_start : batch_start + batch_size]
                texts          = [item[4] for item in batch]
                canonical_used = batch[0][3]

                elapsed = time.time() - start_time
                pct_api = int((api_done / max(total_api_cells, 1)) * 100)
                eta     = (elapsed / max(api_done, 1)) * (total_api_cells - api_done) if api_done else 0
                progress_bar.progress(0.05 + (api_done / max(total_api_cells, 1)) * 0.60)
                progress_container.markdown(
                    _batch_progress_html(
                        "Phase 1 — Batch Translation", sheet_name,
                        stats["batch_count"] + 1, len(batch),
                        total_api_cells, api_done,
                        elapsed, eta,
                        stats["tm_hits"], stats["tm_misses"], pct_api,
                    ),
                    unsafe_allow_html=True,
                )

                translations = translate_batch(
                    client, texts, canonical_used,
                    token_counter, glossary, glossary_run_stats,
                )

                for i, (row_num, col_header, col_idx, canonical, text) in enumerate(batch):
                    tr = str(translations[i]).strip() if i < len(translations) else text
                    if canonical == "name":
                        tr = validate_product_name(tr)
                    results[(row_num, col_idx)] = tr
                    tm_put(tm, text, tr, _tm_col_type(canonical))
                    stats["cells_translated"] += 1

                stats["batch_count"] += 1
                api_done += len(batch)

        # Count TM hits as translated
        stats["cells_translated"] += stats["tm_hits"]
        stats["avg_batch_size"] = (
            round(total_api_cells / max(stats["batch_count"], 1), 1)
            if stats["batch_count"] > 0 else 0.0
        )

        # Old approach would have sent 1 API call per cell; now we send 1 per batch + 0 for TM hits
        stats["api_calls_made"]    = stats["batch_count"]
        stats["api_calls_reduced"] = max(total_to_process - stats["batch_count"] - stats["tm_hits"], 0)

        # Persist TM
        tm["global_stats"]["total_hits"]            += stats["tm_hits"]
        tm["global_stats"]["total_misses"]          += stats["tm_misses"]
        tm["global_stats"]["total_api_calls_saved"] += stats["tm_hits"]
        save_translation_memory(tm)

        # Persist Glossary stats
        stats["glossary_hits"]      = glossary_run_stats.get("total_hits", 0)
        stats["glossary_top_terms"] = dict(
            sorted(
                glossary_run_stats.get("term_counts", {}).items(),
                key=lambda x: -x[1],
            )[:5]
        )
        update_glossary_stats(glossary, glossary_run_stats.get("term_counts", {}))
        save_glossary(glossary)

        # Write all translations back to worksheet
        for (row_num, col_idx), translation in results.items():
            worksheet.cell(row=row_num, column=col_idx).value = translation

        total_cells_for_passes = total_rows * len(to_translate)

        # ── Phase 3: Residue check ────────────────────────────────────────────
        checked = 0
        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                checked += 1
                elapsed  = time.time() - start_time
                progress = 0.65 + (checked / max(total_cells_for_passes, 1)) * 0.25
                pct      = int(progress * 100)

                progress_bar.progress(progress)
                progress_container.markdown(
                    _progress_html(
                        "Phase 2 — Residue Check", sheet_name, col_header,
                        row_num - 1, total_rows, pct, elapsed, 0,
                        stats["cells_translated"], stats["cells_skipped"],
                        stats["residue_corrections"],
                    ),
                    unsafe_allow_html=True,
                )

                cell = worksheet.cell(row=row_num, column=col_idx)
                if cell.value is None or str(cell.value).strip() == "":
                    continue

                text = str(cell.value)
                for _ in range(3):
                    detected = detect_german_residue(text)
                    if not detected:
                        break
                    text = fix_german_residue(client, text, canonical, token_counter)
                    stats["residue_corrections"] += 1
                else:
                    detected = detect_german_residue(text)
                    if detected:
                        stats["unresolved_warnings"] += 1
                        stats["warning_details"].append({
                            "row":     row_num,
                            "column":  col_header,
                            "text":    text[:50] + "..." if len(text) > 50 else text,
                            "residue": detected[:3],
                        })

                cell.value = text

        # ── Phase 4: Final pass ───────────────────────────────────────────────
        progress_bar.progress(0.98)
        elapsed = time.time() - start_time
        progress_container.markdown(
            _progress_html(
                "Phase 3 — Final Verification", sheet_name, "all columns",
                total_rows, total_rows, 98, elapsed, 0,
                stats["cells_translated"], stats["cells_skipped"],
                stats["residue_corrections"],
            ),
            unsafe_allow_html=True,
        )

        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                cell = worksheet.cell(row=row_num, column=col_idx)
                if cell.value is None or str(cell.value).strip() == "":
                    continue
                text     = str(cell.value)
                detected = detect_german_residue(text)
                if detected:
                    corrected = fix_german_residue(client, text, canonical, token_counter)
                    stats["residue_corrections"] += 1
                    if detect_german_residue(corrected):
                        already = any(
                            w["row"] == row_num and w["column"] == col_header
                            for w in stats["warning_details"]
                        )
                        if not already:
                            stats["unresolved_warnings"] += 1
                            stats["warning_details"].append({
                                "row":     row_num,
                                "column":  col_header,
                                "text":    corrected[:50] + "..." if len(corrected) > 50 else corrected,
                                "residue": detect_german_residue(corrected)[:3],
                            })
                    cell.value = corrected

        progress_bar.progress(1.0)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        workbook.close()

        elapsed_seconds = time.time() - start_time
        stats["total_time"]        = format_time(elapsed_seconds)
        stats["elapsed_seconds"]   = elapsed_seconds
        stats["prompt_tokens"]     = token_counter["prompt_tokens"]
        stats["completion_tokens"] = token_counter["completion_tokens"]

        total_tokens = token_counter["prompt_tokens"] + token_counter["completion_tokens"]
        stats["estimated_cost_usd"] = (
            round(
                token_counter["prompt_tokens"]     * _INPUT_COST_PER_TOKEN +
                token_counter["completion_tokens"] * _OUTPUT_COST_PER_TOKEN,
                4,
            ) if total_tokens > 0 else None
        )

        stats["quality_gate"] = {
            "no_residue":         stats["unresolved_warnings"] == 0,
            "protected_columns":  list(column_classification["protected"].keys()),
            "possible_missed":    column_classification["possible_missed"],
            "translated_columns": list(to_translate.keys()),
        }

        return output, stats

    finally:
        os.unlink(tmp_path)


# =============================================================================
# PAGE: LOGIN
# =============================================================================

def login_page():
    render_header()

    _, col, _ = st.columns([1, 1.6, 1])
    with col:
        with st.form("login_form"):
            st.markdown("""
            <div style="text-align:center;margin-bottom:24px;">
                <div style="font-size:19px;font-weight:700;color:#f1f0f7;letter-spacing:-0.03em;">
                    Sign in
                </div>
                <div style="font-size:12px;color:#2e2e44;margin-top:5px;">
                    Internal access · Home24 e-commerce tools
                </div>
            </div>
            """, unsafe_allow_html=True)

            email_input    = st.text_input("Email", placeholder="you@home24.de")
            password_input = st.text_input("Password", type="password", placeholder="••••••••")
            submitted      = st.form_submit_button("Continue →", use_container_width=True)

        st.markdown('<p class="login-footer">Home24 · Internal use only</p>', unsafe_allow_html=True)

        if submitted:
            _, stored_pw = _get_credentials()
            if not stored_pw:
                st.error("Credentials not configured. Check Streamlit secrets or your .env file.")
            elif verify_credentials(email_input, password_input):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid email or password.")

    render_footer()


# =============================================================================
# PAGE: TRANSLATOR
# =============================================================================

def translator_page():
    render_page_header(
        "German → French Translator",
        "Upload a German Excel file to begin translation",
    )

    if not _get_api_key():
        st.markdown("""
        <div class="alert alert-warn">
            <span class="alert-icon">⚠</span>
            <div>
                <strong>OpenAI API key not configured.</strong><br>
                Add <code>OPENAI_API_KEY</code> to your <code>.env</code> file or Streamlit secrets.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    uploaded_file = st.file_uploader(
        "Upload your German Excel file",
        type=["xlsx"],
        label_visibility="visible",
    )

    if uploaded_file is not None:
        st.markdown(f'<div class="file-chip">📄 {uploaded_file.name}</div>', unsafe_allow_html=True)

        output_filename  = f"FR-{uploaded_file.name}"
        wb_peek          = load_workbook(BytesIO(uploaded_file.getvalue()), read_only=True, data_only=True)
        available_sheets = wb_peek.sheetnames
        auto_sheet       = detect_target_sheet(available_sheets)

        if auto_sheet is not None:
            selected_sheet = auto_sheet
            st.markdown(f"""
            <div class="alert alert-info">
                <span class="alert-icon">ℹ</span>
                <span>Auto-selected sheet: <strong>{selected_sheet}</strong></span>
            </div>
            """, unsafe_allow_html=True)
        else:
            selected_sheet = st.selectbox(
                "Multiple sheets found — select the one to translate:",
                available_sheets,
                key="sheet_selector",
            )

        peek_headers   = detect_columns(wb_peek[selected_sheet])
        wb_peek.close()
        classification = classify_columns(peek_headers)

        render_column_report(classification)

        # Advanced settings
        with st.expander("Advanced settings"):
            batch_size = st.number_input(
                "Batch size (cells per API request)",
                min_value=1, max_value=50,
                value=DEFAULT_BATCH_SIZE,
                help="Higher = fewer API calls but larger requests. Default 20 is optimal for most files.",
            )

        st.markdown('<div class="section-label">Translate</div>', unsafe_allow_html=True)
        st.markdown("""
        <div class="alert alert-warn" style="margin-bottom:16px;">
            <span class="alert-icon">⚠</span>
            <span>Keep this tab open while the translation is running.</span>
        </div>
        """, unsafe_allow_html=True)

        _, btn_col, _ = st.columns([1, 2, 1])
        with btn_col:
            translate_button = st.button(
                "Run Translation →", type="primary", use_container_width=True
            )

        if translate_button:
            progress_bar       = st.progress(0)
            progress_container = st.empty()

            try:
                output_bytes, stats = process_excel_with_progress(
                    uploaded_file, progress_bar, progress_container,
                    selected_sheet, classification,
                    batch_size=int(batch_size),
                )
                progress_container.empty()
                progress_bar.empty()

                save_history_record({
                    "id":                        str(uuid.uuid4()),
                    "datetime":                  datetime.now().isoformat(timespec="seconds"),
                    "original_filename":         uploaded_file.name,
                    "output_filename":           output_filename,
                    "sheet_name":                selected_sheet,
                    "source_language":           "German",
                    "target_language":           "French",
                    "cells_translated":          stats["cells_translated"],
                    "cells_skipped":             stats["cells_skipped"],
                    "residue_corrections":       stats["residue_corrections"],
                    "unresolved_warnings":       stats["unresolved_warnings"],
                    "processing_time_seconds":   stats["elapsed_seconds"],
                    "processing_time_formatted": stats["total_time"],
                    "estimated_cost_usd":        stats.get("estimated_cost_usd"),
                    "prompt_tokens":             stats.get("prompt_tokens"),
                    "completion_tokens":         stats.get("completion_tokens"),
                    "tm_hits":                   stats.get("tm_hits", 0),
                    "tm_misses":                 stats.get("tm_misses", 0),
                    "batch_count":               stats.get("batch_count", 0),
                    "avg_batch_size":            stats.get("avg_batch_size", 0.0),
                    "api_calls_reduced":         stats.get("api_calls_reduced", 0),
                    "glossary_hits":             stats.get("glossary_hits", 0),
                })

                # ── Results ──
                st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)
                render_stats(stats)

                # ── Translation Intelligence ──
                st.markdown('<div class="section-label">Translation Intelligence</div>', unsafe_allow_html=True)
                render_intelligence_stats(stats)

                if stats.get("glossary_top_terms"):
                    top_terms_str = " · ".join(
                        f"{de} → {DEFAULT_GLOSSARY_TERMS.get(de, '?')}"
                        for de in list(stats["glossary_top_terms"].keys())[:3]
                    )
                    st.markdown(f"""
                    <div class="alert alert-info" style="margin-top:0;">
                        <span class="alert-icon">ℹ</span>
                        <span><strong>Top glossary terms used:</strong> {top_terms_str}</span>
                    </div>
                    """, unsafe_allow_html=True)

                # ── Quality gate ──
                st.markdown('<div class="section-label">Quality Gate</div>', unsafe_allow_html=True)
                qg = stats.get("quality_gate", {})
                gate_rows = [
                    ("✅" if qg.get("no_residue") else "⚠️",
                     "German residue",
                     "Clean" if qg.get("no_residue") else "Residue found — see warnings"),
                    ("✅", "Row 1 (headers)", "Untouched"),
                    ("✅" if qg.get("protected_columns") else "ℹ️",
                     "Protected columns",
                     ", ".join(qg.get("protected_columns", [])) or "None found"),
                    ("⚠️" if qg.get("possible_missed") else "✅",
                     "Missed columns",
                     ", ".join(qg.get("possible_missed", [])) or "All matched"),
                    ("✅", "Translation Memory",
                     f"{stats.get('tm_hits', 0)} hits / {stats.get('tm_misses', 0)} misses"),
                    ("✅", "Batch processing",
                     f"{stats.get('batch_count', 0)} batches · avg {stats.get('avg_batch_size', 0)} cells/req"),
                ]
                qg_rows_html = "".join(
                    f"""<div class="qg-row">
                        <span class="qg-icon">{icon}</span>
                        <span class="qg-label">{label}</span>
                        <span class="qg-value">{value}</span>
                    </div>"""
                    for icon, label, value in gate_rows
                )
                st.markdown(f'<div class="qg">{qg_rows_html}</div>', unsafe_allow_html=True)

                # ── Completion banner ──
                cost_str = (
                    f"${stats['estimated_cost_usd']:.4f}"
                    if stats.get("estimated_cost_usd") is not None
                    else "cost N/A"
                )
                processed_sheet = stats.get("sheet_name", "")

                if stats["unresolved_warnings"] == 0:
                    st.markdown(f"""
                    <div class="success-banner">
                        <div class="success-banner-icon">✓</div>
                        <div>
                            <div class="success-banner-title">Translation complete</div>
                            <div class="success-banner-sub">
                                Sheet: {processed_sheet} · {stats["cells_translated"]} cells ·
                                {stats["total_time"]} · {cost_str}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="warn-banner">
                        <div class="warn-banner-title">
                            Translation complete — {stats["unresolved_warnings"]} warning(s)
                        </div>
                        <div class="warn-banner-sub">
                            Sheet: {processed_sheet} · {stats["total_time"]} · {cost_str} ·
                            Some cells need manual review
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.expander(f"Warning details ({stats['unresolved_warnings']})"):
                        for w in stats["warning_details"]:
                            residue_str = ", ".join(w["residue"])
                            st.markdown(f"""
                            <div class="warn-detail">
                                <div class="warn-detail-dot"></div>
                                <div>
                                    <strong>Row {w["row"]}</strong> · <code>{w["column"]}</code><br>
                                    <span style="color:#3a3a52;">{w["text"]}</span><br>
                                    <span style="color:#5a4020;">Residue: <code>{residue_str}</code></span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                # ── Download ──
                st.markdown("<br>", unsafe_allow_html=True)
                _, dl_col, _ = st.columns([1, 2, 1])
                with dl_col:
                    st.download_button(
                        label=f"↓ Download {output_filename}",
                        data=output_bytes,
                        file_name=output_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

            except ValueError as e:
                st.error(f"Error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")


# =============================================================================
# PAGE: TRANSLATION HISTORY
# =============================================================================

def history_page():
    render_page_header(
        "Translation History",
        "All previous translation jobs — most recent first",
    )

    history = load_history()

    st.markdown("""
    <div class="cloud-note">
        On Streamlit Community Cloud, history resets on each redeployment (ephemeral file system).
        This is expected for this version.
    </div>
    """, unsafe_allow_html=True)

    if not history:
        st.markdown("""
        <div class="history-empty">
            No translations yet.<br>
            <span style="font-size:12px;color:#1a1a2a;">
                Go to <strong style="color:#2e2e44;">Translator</strong> to get started.
            </span>
        </div>
        """, unsafe_allow_html=True)
        return

    total_files  = len(history)
    total_cells  = sum(r.get("cells_translated", 0) for r in history)
    total_time_s = sum(r.get("processing_time_seconds", 0) for r in history)
    costs        = [r["estimated_cost_usd"] for r in history if r.get("estimated_cost_usd") is not None]
    total_cost   = sum(costs) if costs else None
    cost_display = f"${total_cost:.4f}" if total_cost is not None else "—"

    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label">Files Translated</div>
            <div class="kpi-value accent">{total_files}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Total Cells</div>
            <div class="kpi-value">{total_cells:,}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Total Time</div>
            <div class="kpi-value success">{format_time(total_time_s)}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Total Est. Cost</div>
            <div class="kpi-value warn">{cost_display}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-label">Job Log</div>', unsafe_allow_html=True)

    rows = []
    for r in history:
        dt  = r.get("datetime", "")[:16].replace("T", " ")
        c   = r.get("estimated_cost_usd")
        rows.append({
            "Date / Time":     dt,
            "File":            r.get("original_filename", ""),
            "Sheet":           r.get("sheet_name", ""),
            "Translated":      r.get("cells_translated", 0),
            "TM Hits":         r.get("tm_hits", "—"),
            "Batches":         r.get("batch_count", "—"),
            "Residue Fixes":   r.get("residue_corrections", 0),
            "Warnings":        r.get("unresolved_warnings", 0),
            "Time":            r.get("processing_time_formatted", ""),
            "Est. Cost (USD)": f"${c:.4f}" if c is not None else "—",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)


# =============================================================================
# PAGE: ANALYTICS
# =============================================================================

def analytics_page():
    render_page_header(
        "Analytics",
        "Aggregated statistics across all translation jobs",
    )

    history = load_history()

    if not history:
        st.markdown("""
        <div class="history-empty">
            No data yet.<br>
            <span style="font-size:12px;color:#1a1a2a;">
                Complete a translation to see analytics.
            </span>
        </div>
        """, unsafe_allow_html=True)
        return

    total_files      = len(history)
    total_translated = sum(r.get("cells_translated", 0) for r in history)
    total_skipped    = sum(r.get("cells_skipped", 0) for r in history)
    total_residue    = sum(r.get("residue_corrections", 0) for r in history)
    total_warnings   = sum(r.get("unresolved_warnings", 0) for r in history)
    total_time_s     = sum(r.get("processing_time_seconds", 0) for r in history)
    costs            = [r["estimated_cost_usd"] for r in history if r.get("estimated_cost_usd") is not None]
    total_cost       = sum(costs) if costs else None

    manual_time_s = total_translated * MANUAL_SECONDS_PER_CELL
    saved_s       = max(manual_time_s - total_time_s, 0)
    saved_h       = saved_s / 3600
    cost_display  = f"${total_cost:.4f}" if total_cost is not None else "—"

    # ── Hero: time saved ──
    if total_translated > 0:
        st.markdown(f"""
        <div class="hero-kpi">
            <p class="hero-kpi-value">{saved_h:.1f}h</p>
            <p class="hero-kpi-label">estimated time saved vs. manual translation</p>
            <p class="hero-kpi-sub">
                {total_translated:,} cells × {MANUAL_SECONDS_PER_CELL}s manual
                — {format_time(total_time_s)} actual
            </p>
        </div>
        """, unsafe_allow_html=True)

    # ── Volume ──
    st.markdown('<div class="section-label">Volume</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label">Files Translated</div>
            <div class="kpi-value accent">{total_files}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Cells Translated</div>
            <div class="kpi-value">{total_translated:,}</div>
            <div class="kpi-sub">→ French (FR)</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Cells Skipped</div>
            <div class="kpi-value">{total_skipped:,}</div>
            <div class="kpi-sub">Empty or unchanged</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Unresolved Warnings</div>
            <div class="kpi-value warn">{total_warnings}</div>
            <div class="kpi-sub">Need manual review</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Performance ──
    st.markdown('<div class="section-label">Performance & Cost</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row-3">
        <div class="kpi">
            <div class="kpi-label">Total Processing Time</div>
            <div class="kpi-value">{format_time(total_time_s)}</div>
            <div class="kpi-sub">Actual machine time</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Est. Manual Time</div>
            <div class="kpi-value">{format_time(manual_time_s)}</div>
            <div class="kpi-sub">@ {MANUAL_SECONDS_PER_CELL}s per cell</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Estimated API Cost</div>
            <div class="kpi-value warn">{cost_display}</div>
            <div class="kpi-sub">GPT-4o-mini pricing</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Quality ──
    st.markdown('<div class="section-label">Quality</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row-3">
        <div class="kpi">
            <div class="kpi-label">Residue Auto-fixes</div>
            <div class="kpi-value success">{total_residue}</div>
            <div class="kpi-sub">German words corrected</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Source Language</div>
            <div class="kpi-value" style="font-size:20px;">German (DE)</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Target Language</div>
            <div class="kpi-value" style="font-size:20px;">French (FR)</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Translation Memory ──
    tm = load_translation_memory()
    tm_global      = tm.get("global_stats", {})
    tm_total_hits  = tm_global.get("total_hits", 0)
    tm_total_miss  = tm_global.get("total_misses", 0)
    tm_saved_calls = tm_global.get("total_api_calls_saved", 0)
    tm_entries     = len(tm.get("entries", {}))
    # Estimate cost saved: each TM hit avoided ~500 input + 100 output tokens
    tm_cost_saved  = round(
        tm_total_hits * (500 * _INPUT_COST_PER_TOKEN + 100 * _OUTPUT_COST_PER_TOKEN), 4
    )
    hit_rate = int(tm_total_hits / max(tm_total_hits + tm_total_miss, 1) * 100)

    st.markdown('<div class="section-label">Translation Memory</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label">Memory Entries</div>
            <div class="kpi-value accent">{tm_entries:,}</div>
            <div class="kpi-sub">Unique source phrases</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Cache Hits</div>
            <div class="kpi-value success">{tm_total_hits:,}</div>
            <div class="kpi-sub">{hit_rate}% hit rate</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">API Calls Saved</div>
            <div class="kpi-value">{tm_saved_calls:,}</div>
            <div class="kpi-sub">via memory reuse</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Est. Cost Saved</div>
            <div class="kpi-value warn">${tm_cost_saved:.4f}</div>
            <div class="kpi-sub">from TM cache hits</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Batch Processing ──
    total_batches      = sum(r.get("batch_count", 0) for r in history)
    total_api_reduced  = sum(r.get("api_calls_reduced", 0) for r in history)
    avg_batch_sizes    = [r.get("avg_batch_size", 0) for r in history if r.get("avg_batch_size", 0) > 0]
    overall_avg_batch  = round(sum(avg_batch_sizes) / max(len(avg_batch_sizes), 1), 1)
    speed_multiplier   = round(overall_avg_batch, 1) if overall_avg_batch > 0 else 1.0

    st.markdown('<div class="section-label">Batch Processing</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row-3">
        <div class="kpi">
            <div class="kpi-label">Total API Batches</div>
            <div class="kpi-value accent">{total_batches:,}</div>
            <div class="kpi-sub">Requests sent to OpenAI</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Avg Batch Size</div>
            <div class="kpi-value">{overall_avg_batch}</div>
            <div class="kpi-sub">cells per request</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">API Calls Reduced</div>
            <div class="kpi-value success">{total_api_reduced:,}</div>
            <div class="kpi-sub">~{speed_multiplier}× fewer requests</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Glossary ──
    glossary      = load_glossary()
    gloss_stats   = glossary.get("stats", {})
    gloss_hits    = gloss_stats.get("total_hits", 0)
    gloss_tc      = gloss_stats.get("term_counts", {})
    gloss_terms   = len(glossary.get("terms", {}))
    top_terms     = sorted(gloss_tc.items(), key=lambda x: -x[1])[:5]

    st.markdown('<div class="section-label">Glossary</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row-3">
        <div class="kpi">
            <div class="kpi-label">Glossary Terms</div>
            <div class="kpi-value accent">{gloss_terms}</div>
            <div class="kpi-sub">DE→FR mappings defined</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Total Glossary Hits</div>
            <div class="kpi-value success">{gloss_hits:,}</div>
            <div class="kpi-sub">Consistent terms enforced</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Top Term</div>
            <div class="kpi-value" style="font-size:18px;">
                {top_terms[0][0] if top_terms else "—"}
            </div>
            <div class="kpi-sub">
                {f"{top_terms[0][1]} uses" if top_terms else "No data yet"}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if top_terms:
        top_html = "".join(
            f'<span class="chip chip-accent">{de} <span class="chip-arrow">→ {glossary["terms"].get(de,"?")}</span> · {n}×</span>'
            for de, n in top_terms
        )
        st.markdown(f"""
        <div class="card" style="margin-top:0;">
            <div class="card-title">Top glossary terms used</div>
            <div>{top_html}</div>
        </div>
        """, unsafe_allow_html=True)

    if total_cost is None:
        st.markdown("""
        <div class="alert alert-info" style="margin-top:16px;">
            <span class="alert-icon">ℹ</span>
            <span>
                <strong>API cost unavailable</strong> for jobs completed before token tracking was added.
                Future translations will include cost estimates.
            </span>
        </div>
        """, unsafe_allow_html=True)


# =============================================================================
# PAGE: GLOSSARY MANAGEMENT
# =============================================================================

def glossary_page():
    render_page_header(
        "Glossary Management",
        "DE→FR terminology enforced consistently across all translations",
    )

    glossary    = load_glossary()
    terms       = glossary.get("terms", {})
    gloss_stats = glossary.get("stats", {})
    term_counts = gloss_stats.get("term_counts", {})

    # ── Stats ──
    total_hits  = gloss_stats.get("total_hits", 0)
    total_terms = len(terms)
    used_terms  = len([t for t in terms if t in term_counts])

    st.markdown(f"""
    <div class="kpi-row-3">
        <div class="kpi">
            <div class="kpi-label">Total Terms</div>
            <div class="kpi-value accent">{total_terms}</div>
            <div class="kpi-sub">Defined mappings</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Terms Used</div>
            <div class="kpi-value success">{used_terms}</div>
            <div class="kpi-sub">Matched in source texts</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Total Hits</div>
            <div class="kpi-value">{total_hits:,}</div>
            <div class="kpi-sub">Across all translations</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Glossary table ──
    st.markdown('<div class="section-label">Term List</div>', unsafe_allow_html=True)

    rows = []
    for de, fr in sorted(terms.items()):
        rows.append({
            "German":      de,
            "French":      fr,
            "Times Used":  term_counts.get(de, 0),
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)

    # ── Add new term ──
    st.markdown('<div class="section-label">Add / Update Term</div>', unsafe_allow_html=True)

    with st.form("add_term_form"):
        col_de, col_fr = st.columns(2)
        with col_de:
            new_de = st.text_input("German term", placeholder="e.g. Kopfteil")
        with col_fr:
            new_fr = st.text_input("French translation", placeholder="e.g. Tête de lit")
        add_submitted = st.form_submit_button("Add term →", use_container_width=True)

    if add_submitted:
        new_de = new_de.strip()
        new_fr = new_fr.strip()
        if new_de and new_fr:
            glossary["terms"][new_de] = new_fr
            save_glossary(glossary)
            st.success(f"Added: **{new_de}** → **{new_fr}**")
            st.rerun()
        else:
            st.error("Both fields are required.")

    # ── Reset to defaults ──
    st.markdown('<div class="section-label">Reset</div>', unsafe_allow_html=True)
    if st.button("Reset glossary to defaults"):
        glossary["terms"] = DEFAULT_GLOSSARY_TERMS.copy()
        save_glossary(glossary)
        st.success("Glossary reset to defaults.")
        st.rerun()


# =============================================================================
# MAIN
# =============================================================================

def main():
    is_auth = st.session_state.get("authenticated", False)

    st.set_page_config(
        page_title="DE-FR Translator",
        page_icon="🌐",
        layout="wide",
        initial_sidebar_state="expanded" if is_auth else "collapsed",
    )

    inject_custom_css()

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        login_page()
        return

    page = render_sidebar()

    if page == "Translator":
        translator_page()
    elif page == "Translation History":
        history_page()
    elif page == "Analytics":
        analytics_page()
    elif page == "Glossary":
        glossary_page()

    render_footer()


if __name__ == "__main__":
    main()
