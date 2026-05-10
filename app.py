"""
German to French E-commerce Translator
AI-powered product localization tool for e-commerce platforms.

Author: Yves Koulle Banga
"""

import streamlit as st
import os
import re
import csv
import json
import uuid
import copy
import hmac
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO, StringIO
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openai import OpenAI

from database import (
    init_db,
    db_load_history,
    db_save_history_record,
    db_save_warnings,
    db_load_translation_memory,
    db_save_translation_memory,
    db_load_glossary,
    db_save_glossary,
    db_get_status,
)

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

DEFAULT_BATCH_SIZE      = 15
DEFAULT_MAX_CONCURRENT  = 3
MAX_BATCH_RETRIES       = 2
API_TIMEOUT_SECONDS = 45
MAX_API_RETRIES     = 3
RETRY_BASE_DELAY    = 1.0   # seconds; doubles on each retry

REVIEW_FILL = PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid")

# Warning severity levels
SEVERITY_CRITICAL = "Critical"
SEVERITY_HIGH     = "High"
SEVERITY_MEDIUM   = "Medium"
SEVERITY_LOW      = "Low"

SEVERITY_DEDUCTION = {
    SEVERITY_CRITICAL: 10,
    SEVERITY_HIGH:      5,
    SEVERITY_MEDIUM:    2,
    SEVERITY_LOW:       1,
}

SEVERITY_ORDER = [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW]

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

# Protected column detection — two tiers to avoid false positives on short words
PROTECTED_SUBSTRINGS = [
    "articlenumber", "article_number", "articlenr", "artnummer", "artnr",
    "artikelnummer", "artikelnr", "sku", "productid", "product_id",
    "produktid", "gtin", "barcode", "ean13", "ean8",
]
PROTECTED_EXACT = {
    "id", "ean", "article", "artikel", "ref", "reference", "reference id",
}
# Keep old name for backward compat with any callers
PROTECTED_KEYWORDS = PROTECTED_SUBSTRINGS

IMPORTANT_KEYWORDS = [
    "name", "color", "colour", "delivery", "measurement",
    "quality", "textile", "composition", "material", "variant",
    "farbe", "liefer", "masse", "qualitat", "beschreibung",
]

# Keywords used to score candidate header rows
HEADER_SCORE_KEYWORDS = {
    "article", "artikelnummer", "sku", "product", "name", "color", "colour",
    "farbe", "material", "composition", "textile", "textil", "delivery",
    "lieferumfang", "scope", "quality", "detail", "measurement", "masse",
    "dimensions", "variant", "beschreibung", "nummer", "id", "ean", "gtin",
}

# T1: exact match against _normalize_col_header() output (spaces-collapsed form also tried)
TRANSLATE_ALIASES_T1 = {
    "name": [
        "name", "productname", "product name", "produktname", "produkt name",
        "artikelname", "artikel name", "artikelbezeichnung", "artikel bezeichnung",
        "produktbezeichnung", "produkt bezeichnung", "bezeichnung", "titelname",
        "title", "product title", "producttitle",
    ],
    "colorDetail": [
        "colordetail", "color detail", "colourdetail", "colour detail",
        "farbe", "farbdetail", "farb detail", "farbbezeichnung",
        "colorname", "color name", "colourname", "colour name",
        "variantcolor", "variant color", "couleur", "detailcouleur",
        "detail couleur", "couleurdetail", "couleur detail",
        "colorangabe", "color angabe", "couleurduproduit",
    ],
    "deliveryScope": [
        "deliveryscope", "delivery scope", "delivery_scope", "lieferumfang",
        "delivery contents", "deliverycontents", "lieferinhalt",
        "lieferung", "inhaltsangabe", "contenulivraison", "contenu livraison",
        "perimetre livraison", "perimetre de livraison", "scope de livraison",
        "leveringsomvang", "leveromfang",
    ],
    "materialDetail": [
        "materialdetail", "material detail", "materialdetails", "material details",
        "materialinfo", "material info", "materialbeschreibung", "material beschreibung",
        "materialangaben", "material angaben", "werkstoffe", "werkstoff",
        "materiaux", "detail matiere", "detailmatiere", "compositionmatiere",
        "composition matiere", "matiere",
    ],
    "otherMeasurements": [
        "othermeasurements", "other measurements", "other measurement",
        "masse", "abmessungen", "abmessung", "measurements", "measurement",
        "dimensions", "dimension", "maßangaben", "maß angaben",
        "gesamtmasse", "gesamt masse", "produktmasse", "produkt masse",
        "dimensionen", "ausmasse", "aus masse", "autresmesures", "autres mesures",
        "mesures", "groesse", "breite hohe tiefe",
    ],
    "qualityDetail": [
        "qualitydetail", "quality detail", "qualitydetails", "quality details",
        "qualitatsdetail", "qualitats detail", "qualite", "detail qualite",
        "detailqualite", "qualitaet", "pflegehinweise", "pflege hinweise",
        "eigenschaften", "produkteigenschaften",
    ],
    "textileCompositionCover1": [
        "textilecompositioncover1", "textile composition cover 1",
        "textilecompositioncover",  "textile composition cover",
        "textilecomposition",       "textile composition",
        "textecomposition",         "texte composition",
        "compositioncover",         "composition cover",
        "compositioncover1",        "composition cover 1",
        "textecompositioncover1",   "texte composition cover 1",
        "compositiontextile",       "composition textile",
        "textilzusammensetzung",    "textil zusammensetzung",
        "zusammensetzung",
        "materialzusammensetzung",  "material zusammensetzung",
        "textilescomposition",      "textiles composition",
        "bezugzusammensetzung",     "bezug zusammensetzung",
    ],
    "variantName": [
        "variantname", "variant name", "variantenname", "varianten name",
        "variantbezeichnung", "variant bezeichnung",
        "ausfuhrung", "ausfuehrung", "ausführung", "variante",
        "variantennamen", "varianten namen",
    ],
}

# T2: substring match against normalized header (word-boundary safe substrings)
TRANSLATE_ALIASES_T2 = {
    "textileCompositionCover1": [
        "textile", "textil", "composition", "zusammensetzung", "compositiontextile",
    ],
    "materialDetail":    ["material", "matiere", "werkstoff", "materiaux"],
    "colorDetail":       ["color", "colour", "farbe", "couleur"],
    "deliveryScope":     ["delivery", "lieferumfang", "livraison", "lieferinhalt"],
    "otherMeasurements": ["measurement", "dimension", "abmessung", "mesure"],
    "qualityDetail":     ["quality", "qualite", "qualitat", "qualitaet", "pflege"],
    "variantName":       ["variante", "ausfuhrung"],
    "name":              ["designation", "bezeichnung"],
}

# T3: word-set matching for compound/scrambled headers (≥2 matching words required)
CANONICAL_WORD_SETS: dict[str, set[str]] = {
    "name": {
        "name", "product", "produkt", "artikel", "bezeichnung", "title",
    },
    "colorDetail": {
        "color", "colour", "farbe", "couleur", "detail", "variant",
    },
    "deliveryScope": {
        "delivery", "scope", "lieferumfang", "lieferung", "inhalt", "contenu", "livraison",
    },
    "materialDetail": {
        "material", "detail", "matiere", "werkstoff", "werkstoffe", "materiaux",
    },
    "otherMeasurements": {
        "measurement", "dimension", "masse", "abmessung", "mesure", "groesse",
        "breite", "hohe", "tiefe", "laenge",
    },
    "qualityDetail": {
        "quality", "qualite", "qualitat", "detail", "pflege", "eigenschaften",
    },
    "textileCompositionCover1": {
        "textile", "composition", "cover", "zusammensetzung", "textil", "bezug",
    },
    "variantName": {
        "variant", "ausfuhrung", "ausfuehrung", "variante", "ausführung",
    },
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
    return db_load_history()


def save_history_record(record: dict) -> None:
    db_save_history_record(record)


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
    return db_load_translation_memory()


def save_translation_memory(tm: dict) -> None:
    db_save_translation_memory(tm)


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
    data = db_load_glossary()
    if data is not None:
        return data
    return {
        "terms": DEFAULT_GLOSSARY_TERMS.copy(),
        "stats": {"total_hits": 0, "term_counts": {}},
    }


def save_glossary(glossary: dict) -> None:
    db_save_glossary(glossary)


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


def _issue_meta(issue_type: str, source: str, translation: str) -> dict:
    """Return severity, category, suggested_fix for a given issue type."""
    if issue_type == "german_residue":
        return {
            "severity":      SEVERITY_CRITICAL,
            "category":      "German residue",
            "suggested_fix": "Retranslate manually or apply glossary corrections",
        }
    if issue_type == "identical_output":
        return {
            "severity":      SEVERITY_CRITICAL,
            "category":      "Missing translation",
            "suggested_fix": "Output is identical to source — retranslate this cell manually",
        }
    if issue_type == "api_failure":
        return {
            "severity":      SEVERITY_CRITICAL,
            "category":      "API failure",
            "suggested_fix": "API failed for this cell — retranslate manually",
        }
    if issue_type == "batch_mismatch":
        return {
            "severity":      SEVERITY_CRITICAL,
            "category":      "Batch output mismatch",
            "suggested_fix": "Batch returned wrong count — retranslate this cell manually",
        }
    if issue_type == "lost_br_tags":
        missing = source.count("<br>") - translation.count("<br>")
        return {
            "severity":      SEVERITY_HIGH,
            "category":      "Formatting issue",
            "suggested_fix": f"Reinsert {missing} missing <br> tag(s) at the correct position(s)",
        }
    if issue_type == "name_too_long":
        return {
            "severity":      SEVERITY_HIGH,
            "category":      "Product name rule violation",
            "suggested_fix": f"Shorten to ≤40 chars (currently {len(translation)}); remove adjectives if needed",
        }
    if issue_type == "name_has_comma":
        return {
            "severity":      SEVERITY_HIGH,
            "category":      "Product name rule violation",
            "suggested_fix": "Remove the comma from the product name",
        }
    if issue_type == "glossary_inconsistency":
        return {
            "severity":      SEVERITY_HIGH,
            "category":      "Glossary inconsistency",
            "suggested_fix": "Apply the standard glossary term listed in the reason field",
        }
    if issue_type == "too_short":
        return {
            "severity":      SEVERITY_MEDIUM,
            "category":      "Suspicious translation length",
            "suggested_fix": "Verify the translation is complete; re-run if truncated",
        }
    if issue_type == "too_long":
        return {
            "severity":      SEVERITY_MEDIUM,
            "category":      "Suspicious translation length",
            "suggested_fix": "Check for duplicated or hallucinated content; translation should not exceed ~2.5× source length",
        }
    if issue_type == "possible_hallucination":
        return {
            "severity":      SEVERITY_MEDIUM,
            "category":      "Possible hallucination",
            "suggested_fix": "Review carefully — unexpected content may have been generated",
        }
    return {
        "severity":      SEVERITY_LOW,
        "category":      "Manual review recommended",
        "suggested_fix": "Review this cell manually",
    }


def _check_glossary_inconsistency(source: str, translation: str, glossary: dict) -> list[str]:
    """Check first 25 glossary terms (those in the model prompt) for missed applications."""
    terms = glossary.get("terms", {})
    prompt_terms = dict(list(terms.items())[:25])
    src_lower = source.lower()
    tr_lower  = translation.lower()
    violations = []
    for de, fr in prompt_terms.items():
        if len(de) <= 5:
            continue
        if re.search(r'\b' + re.escape(de.lower()) + r'\b', src_lower):
            if fr.lower() not in tr_lower:
                violations.append(f"{de} → {fr}")
    return violations[:2]


def compute_quality_score(warnings: list) -> int:
    """Score 0–100: start at 100, deduct per warning severity, floor at 0."""
    score = 100
    for w in warnings:
        score -= SEVERITY_DEDUCTION.get(w.get("severity", SEVERITY_LOW), 1)
    return max(0, score)


def quality_verdict(score: int) -> tuple[str, str]:
    """Return (verdict_text, color_token) for the score."""
    if score >= 95:
        return "Excellent — ready to use", "#10b981"
    if score >= 85:
        return "Good — minor review recommended", "#7c5cfc"
    if score >= 70:
        return "Needs review before use", "#f59e0b"
    return "Do not publish without manual review", "#ef4444"


def _normalize_header(header: str) -> set[str]:
    """Split camelCase / PascalCase / snake_case header into lowercase word tokens."""
    no_under = header.replace("_", " ")
    spaced   = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', no_under)
    spaced   = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', spaced)
    return {w.lower() for w in spaced.split() if w} | {header.strip().lower()}


def _normalize_col_header(raw) -> str:
    """
    Full normalization of a raw Excel header for alias matching.
    Handles: camelCase, snake_case, line-breaks, invisible chars, accents.
    Returns a lowercase space-separated string.
    """
    text = str(raw)
    # Replace line breaks, tabs, non-breaking spaces, zero-width chars
    text = re.sub(r'[\n\r\t\xa0​‌‍﻿]', ' ', text)
    # Remove remaining control/format characters (keep spaces)
    text = ''.join(
        c for c in text
        if unicodedata.category(c) not in ('Cc', 'Cf') or c == ' '
    )
    # Expand camelCase / PascalCase: insert space before uppercase run
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)
    # Insert space between letter and digit (e.g. Cover1 → Cover 1)
    text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', text)
    # Replace underscores, hyphens, dots with spaces
    text = re.sub(r'[_\-\.]', ' ', text)
    # Normalize unicode — NFKD decomposes characters; then drop combining marks
    # so ä→a, ö→o, ü→u, é→e, etc. (good for cross-language matching)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    # Collapse whitespace, lowercase
    return ' '.join(text.split()).lower()


# =============================================================================
# DESIGN SYSTEM — CSS
# =============================================================================

def inject_custom_css(theme: str = "Dark"):
    dark = theme == "Dark"

    # ── Background tokens ──────────────────────────────────────────────────────
    bg_app    = "#0a0a0f"                 if dark else "#f4f4fa"
    bg_sb     = "#06060d"                 if dark else "#eceaf6"
    bg_card   = "#111118"                 if dark else "#ffffff"
    bg_input  = "#18181f"                 if dark else "#f0f0f8"
    bg_hover  = "rgba(255,255,255,0.02)"  if dark else "rgba(0,0,0,0.025)"
    bg_subtle = "rgba(255,255,255,0.025)" if dark else "rgba(0,0,0,0.03)"
    # ── Border / divider tokens ────────────────────────────────────────────────
    divider   = "rgba(255,255,255,0.05)"  if dark else "rgba(0,0,0,0.07)"
    divider_s = "rgba(255,255,255,0.04)"  if dark else "rgba(0,0,0,0.05)"
    border    = "rgba(255,255,255,0.06)"  if dark else "rgba(0,0,0,0.09)"
    border_sm = "rgba(255,255,255,0.07)"  if dark else "rgba(0,0,0,0.09)"
    border_md = "rgba(255,255,255,0.08)"  if dark else "rgba(0,0,0,0.10)"
    border_dsh= "rgba(255,255,255,0.09)"  if dark else "rgba(0,0,0,0.12)"
    border_hv = "rgba(255,255,255,0.12)"  if dark else "rgba(0,0,0,0.16)"
    hover_rb  = "rgba(255,255,255,0.05)"  if dark else "rgba(0,0,0,0.06)"
    # ── Text tokens ───────────────────────────────────────────────────────────
    text      = "#f1f0f7" if dark else "#1a1a2e"
    text2     = "#686880" if dark else "#5a5a7a"
    text2b    = "#4a4a60" if dark else "#6a6a8a"
    text3     = "#3a3a52" if dark else "#7070a0"
    text4     = "#2e2e44" if dark else "#9090b8"
    text5     = "#22223a" if dark else "#aaaacc"
    text6     = "#1e1e2e" if dark else "#b0b0cc"
    # ── Component-specific tokens ──────────────────────────────────────────────
    sb_btn    = "#3a3a52" if dark else "#8888aa"
    code_bg   = "rgba(255,255,255,0.07)" if dark else "rgba(0,0,0,0.06)"
    code_clr  = "#9b9bbb" if dark else "#6060a0"
    prog_trk  = "rgba(255,255,255,0.05)" if dark else "rgba(0,0,0,0.08)"
    chip_bg   = "rgba(255,255,255,0.04)" if dark else "rgba(0,0,0,0.04)"
    chip_bdr  = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.09)"

    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ── Reset & Base ─────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    .stApp {{
        background-color: {bg_app} !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: {text};
        -webkit-font-smoothing: antialiased;
    }}

    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .main {{
        background-color: {bg_app} !important;
    }}

    .main .block-container {{
        padding: 2.5rem 2.5rem 4rem !important;
        max-width: 1080px !important;
    }}

    #MainMenu, footer, header,
    div[data-testid="stDecoration"],
    [data-testid="stToolbar"] {{ display: none !important; visibility: hidden !important; }}

    /* ── Animations ───────────────────────────────────────────── */
    @keyframes fadeUp {{
        from {{ opacity: 0; transform: translateY(14px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes glow-pulse {{
        0%, 100% {{ box-shadow: 0 0 0 0 rgba(124,92,252,0.5); }}
        50%       {{ box-shadow: 0 0 0 7px rgba(124,92,252,0); }}
    }}
    @keyframes dot-pulse {{
        0%, 100% {{ opacity: 1; transform: scale(1); }}
        50%       {{ opacity: 0.4; transform: scale(0.75); }}
    }}
    @keyframes slide-in {{
        from {{ opacity: 0; transform: translateX(-6px); }}
        to   {{ opacity: 1; transform: translateX(0); }}
    }}

    /* ── Sidebar ──────────────────────────────────────────────── */
    [data-testid="stSidebar"] {{
        background-color: {bg_sb} !important;
        border-right: 1px solid {divider} !important;
        min-width: 216px !important;
    }}
    [data-testid="stSidebarContent"] {{ padding: 20px 14px !important; }}

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div,
    [data-testid="stSidebar"] label {{ color: {text2} !important; }}

    [data-testid="stSidebar"] hr {{
        border: none !important;
        border-top: 1px solid {divider} !important;
        margin: 10px 0 !important;
    }}

    [data-testid="stSidebar"] [data-testid="stRadio"] label {{
        font-size: 13px !important;
        font-weight: 500 !important;
        padding: 8px 10px !important;
        border-radius: 7px !important;
        cursor: pointer !important;
        transition: color 0.15s, background 0.15s !important;
        display: block !important;
    }}
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{
        color: {text} !important;
        background: {hover_rb} !important;
    }}

    [data-testid="stSidebar"] .stButton > button {{
        background: transparent !important;
        color: {sb_btn} !important;
        border: 1px solid {border} !important;
        border-radius: 8px !important;
        font-size: 12px !important;
        font-weight: 500 !important;
        padding: 7px 14px !important;
        box-shadow: none !important;
        letter-spacing: 0.01em !important;
        transition: color 0.15s, border-color 0.15s, background 0.15s !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        color: #f87171 !important;
        border-color: rgba(248,113,113,0.25) !important;
        background: rgba(248,113,113,0.06) !important;
        transform: none !important;
        box-shadow: none !important;
    }}

    .sb-brand {{ padding: 6px 0 18px; }}
    .sb-wordmark {{
        display: flex; align-items: center; gap: 9px;
        font-size: 14px; font-weight: 700; letter-spacing: -0.02em;
        color: {text} !important;
    }}
    .sb-dot {{
        width: 7px; height: 7px; border-radius: 50%;
        background: #7c5cfc; flex-shrink: 0;
    }}
    .sb-org {{
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.09em; color: {text5} !important;
        margin-top: 3px; padding-left: 16px;
    }}
    .sb-nav-label {{
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: {text5} !important;
        padding: 0 10px; margin-bottom: 4px; display: block;
    }}
    .sb-theme-label {{
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: {text5} !important;
        padding: 0 10px; margin-bottom: 4px; display: block;
    }}
    .sb-user {{
        background: {bg_subtle};
        border: 1px solid {divider};
        border-radius: 8px; padding: 10px 12px; margin: 6px 0;
    }}
    .sb-user-label {{
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.08em; color: {text5} !important; display: block;
    }}
    .sb-user-email {{
        font-size: 11px; color: {text2b} !important;
        margin-top: 4px; display: block; word-break: break-all;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
    }}

    /* ── Login page ───────────────────────────────────────────── */
    .login-hero {{
        text-align: center; padding: 56px 0 36px;
        animation: fadeUp 0.5s ease;
    }}
    .login-lockup {{
        display: inline-flex; align-items: center; gap: 9px;
        font-size: 13px; font-weight: 600; color: {text3};
        letter-spacing: 0.07em; text-transform: uppercase;
        margin-bottom: 36px;
    }}
    .login-lockup-dot {{ width: 7px; height: 7px; border-radius: 50%; background: #7c5cfc; }}
    .login-title {{
        font-size: 34px; font-weight: 800; color: {text};
        letter-spacing: -0.04em; margin: 0 0 10px; line-height: 1.1;
    }}
    .login-subtitle {{ font-size: 14px; color: {text3}; font-weight: 400; }}
    .login-footer {{
        text-align: center; font-size: 11px; color: {text6};
        margin-top: 18px; font-weight: 500;
    }}
    .login-form-title {{
        font-size: 19px; font-weight: 700; color: {text};
        letter-spacing: -0.03em;
    }}
    .login-form-sub {{
        font-size: 12px; color: {text4}; margin-top: 5px;
    }}

    [data-testid="stForm"] {{
        background: {bg_card} !important;
        border: 1px solid {border_sm} !important;
        border-radius: 14px !important;
        padding: 32px 36px !important;
        animation: fadeUp 0.45s ease 0.08s both;
    }}

    /* ── Page header ──────────────────────────────────────────── */
    .page-hd {{
        padding: 2px 0 26px;
        border-bottom: 1px solid {divider};
        margin-bottom: 28px;
        animation: fadeUp 0.3s ease;
    }}
    .page-hd-title {{
        font-size: 22px; font-weight: 700; color: {text};
        letter-spacing: -0.03em; line-height: 1.2;
    }}
    .page-hd-sub {{ font-size: 13px; color: {text3}; margin-top: 4px; font-weight: 400; }}

    /* ── Section label ────────────────────────────────────────── */
    .section-label {{
        font-size: 11px; font-weight: 700; color: {text4};
        text-transform: uppercase; letter-spacing: 0.1em;
        margin: 28px 0 12px;
    }}

    /* ── Cards ────────────────────────────────────────────────── */
    .card {{
        background: {bg_card};
        border: 1px solid {border};
        border-radius: 12px; padding: 24px; margin: 10px 0;
        animation: fadeUp 0.3s ease;
        transition: border-color 0.2s;
    }}
    .card:hover {{ border-color: {border_hv}; }}
    .card-title {{
        font-size: 12px; font-weight: 700; color: {text3};
        text-transform: uppercase; letter-spacing: 0.09em;
        margin-bottom: 18px; padding-bottom: 14px;
        border-bottom: 1px solid {divider};
    }}

    /* ── Alert / message blocks ───────────────────────────────── */
    .alert {{
        display: flex; gap: 11px; align-items: flex-start;
        padding: 13px 16px; border-radius: 9px; margin: 10px 0;
        font-size: 13px; line-height: 1.55;
        animation: fadeUp 0.3s ease;
    }}
    .alert-icon {{ font-size: 14px; flex-shrink: 0; margin-top: 1px; }}
    .alert-info  {{ background: rgba(90,140,248,0.07); border: 1px solid rgba(90,140,248,0.14); color: #7a9ff5; }}
    .alert-success {{ background: rgba(16,185,129,0.07); border: 1px solid rgba(16,185,129,0.14); color: #4fcba4; }}
    .alert-warn  {{ background: rgba(245,158,11,0.07); border: 1px solid rgba(245,158,11,0.14); color: #c89a44; }}
    .alert strong {{ color: {text}; font-weight: 600; }}
    .alert code {{
        font-family: Menlo, Monaco, monospace; font-size: 11px;
        background: {code_bg}; padding: 1px 5px; border-radius: 4px;
        color: {code_clr};
    }}

    /* ── Stat result cards ────────────────────────────────────── */
    .result-grid {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin: 18px 0; }}
    .result-card {{
        background: {bg_card}; border: 1px solid {border};
        border-radius: 11px; padding: 18px 16px;
        transition: border-color 0.2s, transform 0.2s;
        animation: fadeUp 0.35s ease;
    }}
    .result-card:hover {{ border-color: {border_hv}; transform: translateY(-2px); }}
    .result-card-label {{
        font-size: 10px; font-weight: 700; color: {text4};
        text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px;
    }}
    .result-card-value {{
        font-size: 28px; font-weight: 800; letter-spacing: -0.04em;
        font-variant-numeric: tabular-nums; color: {text};
    }}
    .result-card-value.accent  {{ color: #7c5cfc; }}
    .result-card-value.success {{ color: #10b981; }}
    .result-card-value.warn    {{ color: #f59e0b; }}

    /* ── Column chips ─────────────────────────────────────────── */
    .chip {{
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 5px;
        font-size: 11px; font-weight: 600;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
        margin: 3px 3px 3px 0;
    }}
    .chip-accent {{
        background: rgba(124,92,252,0.1);
        border: 1px solid rgba(124,92,252,0.18);
        color: #9b7fff;
    }}
    .chip-muted {{
        background: {chip_bg};
        border: 1px solid {chip_bdr};
        color: {text3};
    }}
    .chip-arrow {{ color: {text3}; font-family: sans-serif; font-weight: 400; }}

    /* ── File chip ────────────────────────────────────────────── */
    .file-chip {{
        display: inline-flex; align-items: center; gap: 8px;
        background: rgba(124,92,252,0.08);
        border: 1px solid rgba(124,92,252,0.18);
        color: #9b7fff; padding: 6px 14px; border-radius: 20px;
        font-size: 12px; font-weight: 600; margin: 8px 0;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
        animation: slide-in 0.25s ease;
    }}

    /* ── Progress shell ───────────────────────────────────────── */
    .prog-shell {{
        background: {bg_card};
        border: 1px solid {border};
        border-radius: 12px; padding: 26px 28px; margin: 14px 0;
        animation: fadeUp 0.3s ease;
    }}
    .prog-head {{
        display: flex; align-items: center;
        justify-content: space-between; margin-bottom: 18px;
    }}
    .prog-phase {{
        font-size: 12px; font-weight: 700; color: {text};
        text-transform: uppercase; letter-spacing: 0.07em;
    }}
    .prog-sheet {{ font-size: 11px; color: {text4}; margin-top: 3px; }}
    .prog-badge {{
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 20px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
        background: rgba(124,92,252,0.12);
        border: 1px solid rgba(124,92,252,0.22);
        color: #9b7fff;
    }}
    .prog-badge-dot {{
        width: 5px; height: 5px; border-radius: 50%; background: #7c5cfc;
        animation: dot-pulse 1.4s ease infinite;
    }}
    .prog-track {{
        width: 100%; height: 3px;
        background: {prog_trk};
        border-radius: 2px; overflow: hidden; margin: 14px 0;
        position: relative;
    }}
    .prog-bar {{
        height: 3px; border-radius: 2px;
        background: linear-gradient(90deg, #7c5cfc 0%, #5a8cf8 100%);
        transition: width 0.4s ease; position: relative;
    }}
    .prog-bar::after {{
        content: ''; position: absolute; right: -1px; top: -2px;
        width: 7px; height: 7px; background: #9b7fff;
        border-radius: 50%; animation: glow-pulse 1.6s ease infinite;
    }}
    .prog-item {{
        display: flex; align-items: center; gap: 8px;
        font-size: 12px; color: {text3}; margin: 10px 0;
        font-family: Menlo, Monaco, 'Cascadia Code', monospace;
    }}
    .prog-item-dot {{
        width: 5px; height: 5px; border-radius: 50%; background: #7c5cfc; flex-shrink: 0;
        animation: dot-pulse 1.4s ease infinite;
    }}
    .prog-item-col {{ color: #9b7fff; }}
    .prog-item-row {{ color: {text4}; margin-left: 6px; }}
    .prog-stats {{
        display: flex; gap: 28px; margin-top: 18px; padding-top: 14px;
        border-top: 1px solid {divider_s};
        flex-wrap: wrap;
    }}
    .prog-stat-val {{
        font-size: 15px; font-weight: 700; color: {text};
        font-variant-numeric: tabular-nums; display: block;
    }}
    .prog-stat-lbl {{
        font-size: 9px; font-weight: 700; color: {text4};
        text-transform: uppercase; letter-spacing: 0.09em;
        margin-top: 2px; display: block;
    }}

    /* ── Quality gate ─────────────────────────────────────────── */
    .qg {{
        background: {bg_card}; border: 1px solid {border};
        border-radius: 11px; overflow: hidden; margin: 14px 0;
        animation: fadeUp 0.35s ease;
    }}
    .qg-row {{
        display: flex; align-items: center; gap: 16px;
        padding: 13px 20px;
        border-bottom: 1px solid {divider_s};
        font-size: 13px;
        transition: background 0.15s;
    }}
    .qg-row:last-child {{ border-bottom: none; }}
    .qg-row:hover {{ background: {bg_hover}; }}
    .qg-icon {{ flex-shrink: 0; font-size: 13px; }}
    .qg-label {{ font-weight: 600; color: {text2}; min-width: 160px; font-size: 12px; }}
    .qg-value {{ color: {text3}; font-size: 12px; font-family: Menlo, Monaco, monospace; }}

    /* ── Warning detail ───────────────────────────────────────── */
    .warn-detail {{
        display: flex; gap: 12px; align-items: flex-start;
        padding: 13px 16px; margin: 7px 0;
        background: rgba(245,158,11,0.04);
        border: 1px solid rgba(245,158,11,0.1);
        border-radius: 9px; font-size: 12px; color: {text2};
        animation: fadeUp 0.3s ease;
    }}
    .warn-detail-dot {{
        width: 5px; height: 5px; border-radius: 50%;
        background: #f59e0b; margin-top: 4px; flex-shrink: 0;
    }}
    .warn-detail strong {{ color: #c8952a; }}

    /* ── Success / completion banner ──────────────────────────── */
    .success-banner {{
        display: flex; align-items: center; gap: 16px;
        padding: 20px 24px;
        background: rgba(16,185,129,0.06);
        border: 1px solid rgba(16,185,129,0.14);
        border-radius: 11px; margin: 16px 0;
        animation: fadeUp 0.3s ease;
    }}
    .success-banner-icon {{
        width: 36px; height: 36px; border-radius: 50%;
        background: rgba(16,185,129,0.15);
        border: 1px solid rgba(16,185,129,0.25);
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; flex-shrink: 0;
    }}
    .success-banner-title {{ font-size: 14px; font-weight: 700; color: #10b981; }}
    .success-banner-sub   {{ font-size: 11px; color: #2e4a40; margin-top: 3px; }}

    .warn-banner {{
        padding: 18px 22px;
        background: rgba(245,158,11,0.05);
        border: 1px solid rgba(245,158,11,0.12);
        border-radius: 11px; margin: 16px 0;
        animation: fadeUp 0.3s ease;
    }}
    .warn-banner-title {{ font-size: 14px; font-weight: 700; color: #c89a44; }}
    .warn-banner-sub   {{ font-size: 11px; color: #3a2e1a; margin-top: 3px; }}

    /* ── Metric cards ─────────────────────────────────────────── */
    .kpi-row   {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin: 18px 0; }}
    .kpi-row-3 {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 10px; margin: 18px 0; }}
    .kpi {{
        background: {bg_card};
        border: 1px solid {border};
        border-radius: 11px; padding: 20px 18px;
        transition: border-color 0.2s, transform 0.2s;
        animation: fadeUp 0.35s ease;
    }}
    .kpi:hover {{ border-color: {border_hv}; transform: translateY(-2px); }}
    .kpi-label {{
        font-size: 10px; font-weight: 700; color: {text4};
        text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px;
    }}
    .kpi-value {{
        font-size: 28px; font-weight: 800; letter-spacing: -0.04em;
        color: {text}; font-variant-numeric: tabular-nums;
    }}
    .kpi-value.accent  {{ color: #7c5cfc; }}
    .kpi-value.success {{ color: #10b981; }}
    .kpi-value.warn    {{ color: #f59e0b; }}
    .kpi-sub {{ font-size: 11px; color: {text4}; margin-top: 5px; }}

    /* ── Hero metric ──────────────────────────────────────────── */
    .hero-kpi {{
        text-align: center; padding: 52px 32px; border-radius: 14px;
        background: linear-gradient(135deg, rgba(124,92,252,0.07) 0%, rgba(90,140,248,0.07) 100%);
        border: 1px solid rgba(124,92,252,0.16); margin: 20px 0;
        animation: fadeUp 0.4s ease;
    }}
    .hero-kpi-value {{
        font-size: 80px; font-weight: 800; letter-spacing: -0.05em; line-height: 1;
        background: linear-gradient(135deg, #7c5cfc 0%, #5a8cf8 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        margin: 0;
    }}
    .hero-kpi-label {{ font-size: 15px; color: {text3}; margin: 14px 0 0; font-weight: 500; }}
    .hero-kpi-sub   {{ font-size: 12px; color: {text5}; margin: 6px 0 0; }}

    /* ── History ──────────────────────────────────────────────── */
    .history-empty {{
        text-align: center; padding: 70px 20px;
        color: {text4}; font-size: 14px; font-weight: 500;
    }}
    .history-empty-sub {{ font-size: 12px; color: {text5}; }}
    .history-empty-sub strong {{ color: {text4}; }}
    .cloud-note {{
        padding: 11px 15px; border-radius: 8px; margin: 14px 0;
        font-size: 11px; line-height: 1.5;
        background: rgba(90,140,248,0.06);
        border: 1px solid rgba(90,140,248,0.12);
        color: #4a6899;
    }}

    /* ── Footer ───────────────────────────────────────────────── */
    .footer-author {{ color: {text3} !important; }}
    .footer-version {{ color: {text6} !important; }}

    /* ── Streamlit native overrides ───────────────────────────── */
    [data-testid="stTextInput"] input {{
        background: {bg_input} !important;
        border: 1px solid {border_md} !important;
        border-radius: 8px !important;
        color: {text} !important;
        font-size: 13px !important;
        caret-color: #7c5cfc !important;
    }}
    [data-testid="stTextInput"] input:focus {{
        border-color: rgba(124,92,252,0.45) !important;
        box-shadow: 0 0 0 3px rgba(124,92,252,0.1) !important;
        outline: none !important;
    }}
    [data-testid="stTextInput"] label p {{ color: {text2b} !important; font-size: 12px !important; font-weight: 500 !important; }}

    [data-testid="stNumberInput"] input {{
        background: {bg_input} !important;
        border: 1px solid {border_md} !important;
        border-radius: 8px !important;
        color: {text} !important;
        font-size: 13px !important;
    }}
    [data-testid="stNumberInput"] label p {{ color: {text2b} !important; font-size: 12px !important; }}

    [data-testid="stSelectbox"] > div > div {{
        background: {bg_input} !important;
        border: 1px solid {border_md} !important;
        border-radius: 8px !important;
        color: {text} !important;
        font-size: 13px !important;
    }}
    [data-testid="stSelectbox"] label p {{ color: {text2b} !important; font-size: 12px !important; }}

    .stProgress {{ padding: 6px 0 !important; }}
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, #7c5cfc 0%, #5a8cf8 100%) !important;
        border-radius: 2px !important;
    }}

    .stButton > button {{
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
    }}
    .stButton > button:hover {{
        background: #8f71ff !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 5px 18px rgba(124,92,252,0.45) !important;
    }}
    .stButton > button:active {{ transform: translateY(0) !important; }}

    .stDownloadButton > button {{
        background: rgba(16,185,129,0.1) !important;
        color: #10b981 !important;
        border: 1px solid rgba(16,185,129,0.22) !important;
        border-radius: 9px !important;
        padding: 12px 26px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        box-shadow: none !important;
        transition: background 0.15s, border-color 0.15s, transform 0.15s !important;
    }}
    .stDownloadButton > button:hover {{
        background: rgba(16,185,129,0.16) !important;
        border-color: rgba(16,185,129,0.38) !important;
        transform: translateY(-1px) !important;
    }}

    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploader"] > div {{
        background: {bg_hover} !important;
        border: 1.5px dashed {border_dsh} !important;
        border-radius: 11px !important;
        transition: border-color 0.2s, background 0.2s !important;
    }}
    [data-testid="stFileUploader"] section:hover,
    [data-testid="stFileUploader"] > div:hover {{
        border-color: rgba(124,92,252,0.38) !important;
        background: rgba(124,92,252,0.03) !important;
    }}
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] p {{ color: {text3} !important; font-size: 13px !important; }}
    [data-testid="stFileUploader"] small {{ color: {text5} !important; }}
    [data-testid="stFileUploader"] button {{
        background: rgba(124,92,252,0.1) !important;
        color: #9b7fff !important;
        border: 1px solid rgba(124,92,252,0.2) !important;
        border-radius: 7px !important;
        font-size: 12px !important;
        font-weight: 600 !important;
    }}

    [data-testid="stExpander"] {{
        background: {bg_card} !important;
        border: 1px solid {border} !important;
        border-radius: 9px !important;
    }}
    [data-testid="stExpander"] summary {{
        color: {text3} !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        padding: 10px 14px !important;
    }}

    [data-testid="stDataFrame"] {{
        border-radius: 11px !important;
        overflow: hidden !important;
        border: 1px solid {border} !important;
    }}

    .site-footer {{
        margin-top: 80px; padding: 22px 0;
        border-top: 1px solid {divider_s};
        display: flex; align-items: center; justify-content: space-between;
        font-size: 11px; color: {text6};
        animation: fadeUp 0.4s ease;
    }}

    /* ── Severity badges ─────────────────────────────────── */
    .sev-badge {{
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: 4px;
        font-size: 11px; font-weight: 700;
        letter-spacing: 0.04em; text-transform: uppercase;
    }}
    .sev-critical {{
        background: rgba(239,68,68,0.12);
        border: 1px solid rgba(239,68,68,0.22);
        color: #ef4444;
    }}
    .sev-high {{
        background: rgba(245,158,11,0.12);
        border: 1px solid rgba(245,158,11,0.22);
        color: #f59e0b;
    }}
    .sev-medium {{
        background: rgba(250,204,21,0.10);
        border: 1px solid rgba(250,204,21,0.20);
        color: #ca8a04;
    }}
    .sev-low {{
        background: rgba(129,140,248,0.10);
        border: 1px solid rgba(129,140,248,0.20);
        color: #818cf8;
    }}
    .alert-success {{
        background: rgba(16,185,129,0.07);
        border: 1px solid rgba(16,185,129,0.14);
        color: #4fcba4;
    }}

    @media (max-width: 780px) {{
        .kpi-row, .result-grid {{ grid-template-columns: repeat(2,1fr) !important; }}
        .hero-kpi-value {{ font-size: 52px !important; }}
        .main .block-container {{ padding: 1.5rem 1.2rem 3rem !important; }}
    }}
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
    concurrency  = stats.get("max_concurrent_used", 1)
    avg_dur      = stats.get("avg_batch_duration", 0.0)
    failed_b     = stats.get("failed_batches", 0)

    conc_sub = f"{concurrency}× parallel" if concurrency > 1 else "sequential mode"
    dur_sub  = f"{avg_dur}s avg/batch" if avg_dur > 0 else "–"

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
    <div class="kpi-row" style="margin-top:8px;">
        <div class="kpi">
            <div class="kpi-label">Concurrency</div>
            <div class="kpi-value accent">{concurrency}</div>
            <div class="kpi-sub">{conc_sub}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Avg Batch Time</div>
            <div class="kpi-value">{avg_dur}s</div>
            <div class="kpi-sub">{dur_sub}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Failed Batches</div>
            <div class="kpi-value {'warn' if failed_b else 'success'}">{failed_b}</div>
            <div class="kpi-sub">{'Fell back to single-cell' if failed_b else 'All batches succeeded'}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Retries</div>
            <div class="kpi-value">{stats.get("retry_count", 0)}</div>
            <div class="kpi-sub">API retry events</div>
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
    normalized_map  = classification.get("normalized_map", {})
    header_row      = classification.get("header_row", 1)

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
            <span>No translatable columns detected automatically — see debug info below.</span>
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

    row_note = f' <span style="font-size:11px;color:#686880;">(headers detected in row {header_row})</span>' if header_row != 1 else ""

    st.markdown(f"""
    <div class="card">
        <div class="card-title">Column detection{row_note}</div>
        {will_translate_html}
        {prot_html}
        {missed_html}
    </div>
    """, unsafe_allow_html=True)

    if ignored:
        with st.expander(f"Ignored columns ({len(ignored)})"):
            st.markdown(", ".join(f"`{h}`" for h in ignored))

    # Debug panel — shown only when automatic detection found nothing
    if not to_translate:
        with st.expander("🔍 Detection debug report", expanded=True):
            st.caption(f"Header row detected: **row {header_row}**")

            all_raw = list(normalized_map.keys())
            if all_raw:
                rows = [
                    {
                        "Raw header":        h,
                        "Normalized":        normalized_map.get(h, ""),
                        "Status":            (
                            "Protected" if h in protected
                            else "Ignored"
                        ),
                    }
                    for h in all_raw
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.warning("No headers found in the detected header row. The sheet may be empty or the header row was not detected correctly.")


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

        st.markdown("---")
        st.markdown('<span class="sb-theme-label">Appearance</span>', unsafe_allow_html=True)
        st.radio(
            "Theme",
            ["Dark", "Light"],
            key="theme",
            label_visibility="collapsed",
        )

        st.markdown("---")
        db_status = db_get_status()
        dot   = "🟢" if db_status["connected"] else "🔴"
        label = "SQLite · connected" if db_status["connected"] else "SQLite · error"
        st.markdown(
            f'<div style="font-size:0.72rem;color:#9ca3af;margin-top:2px;">'
            f'{dot} <strong style="color:#e5e7eb;">{label}</strong><br>'
            f'Jobs: {db_status["jobs"]} &nbsp;·&nbsp; '
            f'TM: {db_status["tm_entries"]} &nbsp;·&nbsp; '
            f'Glossary: {db_status["glossary_terms"]}'
            f"</div>",
            unsafe_allow_html=True,
        )

    return page


def render_footer():
    st.markdown("""
    <div class="site-footer">
        <span>Built by <strong class="footer-author">Yves Koulle Banga</strong></span>
        <span class="footer-version">DE→FR Translator · v5.0</span>
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


def analyze_translation_quality(
    source: str, translation: str, canonical: str, glossary: dict | None = None
) -> list[dict]:
    """Return enriched quality issues. Each dict has: type, reason, severity, category, suggested_fix.

    Excel highlighting signals:
      - Critical/High issues → REVIEW_FILL only when checkbox enabled
      - original_excel_highlights → always preserved
      - glossary_hits → analytics only, never affect cell color
    """
    issues   = []
    _glossary = glossary or {}

    # Identical output (Critical) — check before residue so we don't double-flag
    if translation.strip() == source.strip():
        src_lower      = source.strip().lower()
        glossary_terms = _glossary.get("terms", {})
        is_expected    = (
            src_lower in {w.lower() for w in FRENCH_ACCEPTABLE_WORDS}
            or any(
                src_lower == de.lower() and translation.strip().lower() == fr.lower()
                for de, fr in glossary_terms.items()
            )
        )
        if not is_expected:
            meta = _issue_meta("identical_output", source, translation)
            issues.append({
                "type":   "identical_output",
                "reason": "Translation matches source text — likely untranslated",
                **meta,
            })

    # German residue (recorded here; final verdict via warning_details after all fix passes)
    residue = detect_german_residue(translation)
    if residue:
        meta = _issue_meta("german_residue", source, translation)
        issues.append({
            "type":   "german_residue",
            "reason": f"German words detected: {', '.join(residue[:3])}",
            **meta,
        })

    # Too short (Medium)
    if len(source) > 6 and len(translation) < max(3, len(source) * 0.4):
        meta = _issue_meta("too_short", source, translation)
        issues.append({
            "type":   "too_short",
            "reason": f"Very short ({len(translation)} chars vs {len(source)} source)",
            **meta,
        })

    # Too long (Medium)
    if len(source) > 20 and len(translation) > len(source) * 2.5:
        meta = _issue_meta("too_long", source, translation)
        issues.append({
            "type":   "too_long",
            "reason": f"Unusually long ({len(translation)} chars vs {len(source)} source)",
            **meta,
        })

    # Lost <br> tags (High)
    src_br = source.count("<br>")
    if src_br > 0 and translation.count("<br>") < src_br:
        meta = _issue_meta("lost_br_tags", source, translation)
        issues.append({
            "type":   "lost_br_tags",
            "reason": f"Lost {src_br - translation.count('<br>')} <br> tag(s)",
            **meta,
        })

    # Product name rules (High)
    if canonical == "name":
        if len(translation) > 40:
            meta = _issue_meta("name_too_long", source, translation)
            issues.append({
                "type":   "name_too_long",
                "reason": f"Exceeds 40 chars ({len(translation)})",
                **meta,
            })
        if "," in translation:
            meta = _issue_meta("name_has_comma", source, translation)
            issues.append({
                "type":   "name_has_comma",
                "reason": "Contains a comma",
                **meta,
            })

    # Glossary inconsistency (High) — only prompt-block terms, long ones only
    violations = _check_glossary_inconsistency(source, translation, _glossary)
    if violations:
        meta = _issue_meta("glossary_inconsistency", source, translation)
        issues.append({
            "type":   "glossary_inconsistency",
            "reason": f"Glossary term(s) not applied: {' | '.join(violations)}",
            **meta,
        })

    return issues


def _api_call_with_retry(fn, *, max_retries: int = MAX_API_RETRIES, notify_fn=None):
    """Call fn() with exponential backoff on failure. Re-raises if all attempts fail."""
    delay    = RETRY_BASE_DELAY
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            msg  = str(exc).lower()
            wait = delay * 4 if ("rate limit" in msg or "429" in msg) else delay
            if notify_fn:
                notify_fn(f"API error (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait:.0f}s…")
            time.sleep(wait)
            delay *= 2
    raise last_exc


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
    notify_fn=None,
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
            response = _api_call_with_retry(
                lambda: client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_msg},
                    ],
                    temperature=0.3,
                    max_tokens=min(4000, n * 200),
                    timeout=API_TIMEOUT_SECONDS,
                ),
                notify_fn=notify_fn,
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
    return _fallback_single_translations(client, texts, canonical, token_counter, glossary, notify_fn=notify_fn)


def _fallback_single_translations(
    client,
    texts: list[str],
    canonical: str,
    token_counter: dict,
    glossary: dict,
    notify_fn=None,
) -> list[str]:
    glossary_block = _glossary_prompt_block(glossary)
    system_prompt  = _build_system_prompt(canonical, glossary_block)
    results        = []
    for text in texts:
        try:
            response = _api_call_with_retry(
                lambda t=text: client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": f"Translate to French:\n\n{t}"},
                    ],
                    temperature=0.3,
                    max_tokens=500,
                    timeout=API_TIMEOUT_SECONDS,
                ),
                notify_fn=notify_fn,
            )
            if token_counter is not None and response.usage:
                token_counter["prompt_tokens"]     += response.usage.prompt_tokens
                token_counter["completion_tokens"] += response.usage.completion_tokens
            results.append(response.choices[0].message.content.strip())
        except Exception:
            results.append(text)
    return results


def _run_batch_task(
    client,
    batch_id: int,
    batch_items: list,
    canonical: str,
    glossary: dict,
    retry_counter: list,
    retry_lock: threading.Lock,
) -> dict:
    """Worker: runs one translation batch in a thread. No shared-state mutations."""
    local_tokens  = {"prompt_tokens": 0, "completion_tokens": 0}
    local_glossary = {"total_hits": 0, "term_counts": {}}
    texts  = [item[4] for item in batch_items]
    failed = False
    start  = time.time()

    def _notify(_msg: str) -> None:
        with retry_lock:
            retry_counter[0] += 1

    try:
        translations = translate_batch(
            client, texts, canonical,
            local_tokens, glossary, local_glossary,
            notify_fn=_notify,
        )
    except Exception:
        failed       = True
        translations = list(texts)

    return {
        "batch_id":          batch_id,
        "batch_items":       batch_items,
        "translations":      translations,
        "prompt_tokens":     local_tokens["prompt_tokens"],
        "completion_tokens": local_tokens["completion_tokens"],
        "glossary_hits":     local_glossary.get("total_hits", 0),
        "glossary_terms":    local_glossary.get("term_counts", {}),
        "failed":            failed,
        "duration":          time.time() - start,
    }


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
        response = _api_call_with_retry(
            lambda: client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You remove German words from French texts for Home24 France e-commerce."},
                    {"role": "user",   "content": fix_prompt},
                ],
                temperature=0.2,
                max_tokens=500,
                timeout=API_TIMEOUT_SECONDS,
            ),
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


def detect_header_row(worksheet, max_rows: int = 10) -> tuple[int, dict]:
    """
    Scan the first max_rows rows to find the most likely header row.
    Returns (row_number, {raw_header_text: col_index}).
    Falls back to row 1 if nothing scores well.
    """
    best_row     = 1
    best_score   = -1
    best_headers: dict[str, int] = {}

    scan_limit = min(max_rows, worksheet.max_row or 1)

    for row_num in range(1, scan_limit + 1):
        score   = 0
        headers: dict[str, int] = {}

        for cell in worksheet[row_num]:
            if cell.value is None:
                continue
            raw  = str(cell.value)
            text = raw.strip()
            if not text:
                continue

            # Penalty: looks like a pure number (data row, not header row)
            try:
                float(raw)
                score -= 3
                continue
            except (ValueError, TypeError):
                pass

            headers[text] = cell.column
            score += 1  # each non-empty string cell

            # Bonus: contains known header keywords
            norm = _normalize_col_header(text)
            if any(kw in norm for kw in HEADER_SCORE_KEYWORDS):
                score += 3

        if score > best_score:
            best_score   = score
            best_row     = row_num
            best_headers = headers

    return best_row, best_headers


def detect_columns(worksheet) -> dict:
    """Backward-compatible wrapper — returns {raw_header: col_idx} from detected header row."""
    _, headers = detect_header_row(worksheet)
    return headers


def _is_protected(norm: str, raw: str) -> bool:
    """Return True if this column should never be translated."""
    # Exact match on fully-normalized, space-collapsed form
    norm_c = norm.replace(' ', '')
    if norm_c in PROTECTED_EXACT or norm in PROTECTED_EXACT:
        return True
    # Substring match for longer protected patterns
    if any(pk in norm_c for pk in PROTECTED_SUBSTRINGS):
        return True
    return False


def _classify_header(header: str) -> tuple[str | None, str, str]:
    """
    Classify a raw header into a canonical translation target.
    Returns (canonical_or_None, normalized_form, match_tier).
    """
    norm   = _normalize_col_header(header)
    norm_c = norm.replace(' ', '')          # collapsed form

    # T1 — exact match (try both spaced and collapsed)
    for can, aliases in TRANSLATE_ALIASES_T1.items():
        if norm in aliases or norm_c in aliases:
            return can, norm, "T1-exact"

    # T2 — substring of normalized header
    for can, substrings in TRANSLATE_ALIASES_T2.items():
        if any(sub in norm for sub in substrings):
            return can, norm, "T2-substring"

    # T3 — word-set overlap (≥2 words must match)
    header_words = set(norm.split())
    best_can, best_score = None, 0
    for can, word_set in CANONICAL_WORD_SETS.items():
        score = len(header_words & word_set)
        if score >= 2 and score > best_score:
            best_can, best_score = can, score
    if best_can:
        return best_can, norm, f"T3-wordset({best_score})"

    return None, norm, "no-match"


def classify_columns(all_columns: dict) -> dict:
    """
    Classify raw {header: col_idx} into translatable / protected / ignored.
    Returns a dict with debug metadata for the column report.
    """
    to_translate:    dict[str, tuple] = {}
    protected:       dict[str, int]   = {}
    ignored:         dict[str, int]   = {}
    possible_missed: list[str]        = []
    normalized_map:  dict[str, str]   = {}
    ignored_reasons: dict[str, str]   = {}

    for header, col_idx in all_columns.items():
        norm = _normalize_col_header(header)
        normalized_map[header] = norm

        if _is_protected(norm, header):
            protected[header] = col_idx
            continue

        canonical, _, tier = _classify_header(header)

        if canonical is not None:
            to_translate[header] = (col_idx, canonical)
        else:
            ignored[header] = col_idx
            ignored_reasons[header] = "No alias / keyword match"
            if any(ik in norm for ik in IMPORTANT_KEYWORDS):
                possible_missed.append(header)

    return {
        "to_translate":    to_translate,
        "protected":       protected,
        "ignored":         ignored,
        "possible_missed": possible_missed,
        "normalized_map":  normalized_map,
        "ignored_reasons": ignored_reasons,
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


def _parallel_progress_html(
    sheet: str,
    total_batches: int,
    completed: int,
    running: int,
    failed: int,
    cells_done: int,
    total_cells: int,
    tm_hits: int,
    elapsed: float,
    eta: float,
    pct: int,
) -> str:
    fail_str = f" · <span style='color:#ef4444;'>{failed} failed</span>" if failed else ""
    return f"""
    <div class="prog-shell">
        <div class="prog-head">
            <div>
                <div class="prog-phase">Parallel Batch Translation</div>
                <div class="prog-sheet">Sheet: {sheet} · {running} batch(es) running concurrently{fail_str}</div>
            </div>
            <span class="prog-badge"><span class="prog-badge-dot"></span>ACTIVE</span>
        </div>
        <div class="prog-track">
            <div class="prog-bar" style="width:{pct}%"></div>
        </div>
        <div class="prog-item">
            <div class="prog-item-dot"></div>
            <span class="prog-item-col">Processing {running} batch(es) in parallel</span>
            <span class="prog-item-row">{cells_done} / {total_cells} cells</span>
        </div>
        <div class="prog-stats">
            <div><span class="prog-stat-val">{completed}/{total_batches}</span><span class="prog-stat-lbl">Batches done</span></div>
            <div><span class="prog-stat-val">{running}</span><span class="prog-stat-lbl">Running</span></div>
            <div><span class="prog-stat-val">{tm_hits}</span><span class="prog-stat-lbl">TM Hits</span></div>
            <div><span class="prog-stat-val">{failed}</span><span class="prog-stat-lbl">Failed</span></div>
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
    highlight_review_warnings: bool = False,
    max_concurrent_batches: int = DEFAULT_MAX_CONCURRENT,
    header_row: int = 1,
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
        "review_items":        [],
        "all_warnings":        [],
        "review_count":        0,
        "retry_count":         0,
        "failed_cells":        0,
        "failed_batches":      0,
        "avg_batch_duration":  0.0,
        "max_concurrent_used": max_concurrent_batches,
        "critical_warnings":   0,
        "high_warnings":       0,
        "medium_warnings":     0,
        "low_warnings":        0,
        "quality_score":       100,
        "warning_categories":  {},
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

        data_start_row = header_row + 1     # first row with actual data
        total_rows     = max(0, worksheet.max_row - header_row)
        start_time     = time.time()

        # ── Phase 0: Pre-scan ─────────────────────────────────────────────────
        progress_bar.progress(0.02)
        progress_container.markdown(
            _batch_progress_html(
                "Scanning", sheet_name, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 2
            ),
            unsafe_allow_html=True,
        )

        cells_queue: list[tuple] = []
        for row_num in range(data_start_row, worksheet.max_row + 1):
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

        # ── Phase 2: Parallel batch translation ──────────────────────────────
        by_col_type: dict[str, list] = {}
        for item in api_queue:
            ct = _tm_col_type(item[3])
            by_col_type.setdefault(ct, []).append(item)

        total_api_cells = len(api_queue)

        # Build a flat, ordered batch list across all col_types
        batch_list: list[tuple] = []
        for col_type, items in by_col_type.items():
            for batch_start in range(0, len(items), batch_size):
                batch_items    = items[batch_start : batch_start + batch_size]
                canonical_used = batch_items[0][3]
                batch_list.append((batch_items, canonical_used))

        total_batches  = len(batch_list)
        retry_counter  = [0]
        retry_lock     = threading.Lock()
        batch_results  = []
        completed_batches = 0
        failed_batches    = 0
        api_cells_done    = 0
        batch_durations   = []

        with ThreadPoolExecutor(max_workers=max(1, max_concurrent_batches)) as executor:
            future_map = {
                executor.submit(
                    _run_batch_task,
                    client, bid, batch_items, canonical, glossary, retry_counter, retry_lock,
                ): bid
                for bid, (batch_items, canonical) in enumerate(batch_list)
            }

            for future in as_completed(future_map):
                result = future.result()
                batch_results.append(result)
                completed_batches += 1
                api_cells_done    += len(result["batch_items"])
                if result["failed"]:
                    failed_batches += 1
                batch_durations.append(result["duration"])

                # Accumulate counters on main thread (thread-safe)
                token_counter["prompt_tokens"]     += result["prompt_tokens"]
                token_counter["completion_tokens"] += result["completion_tokens"]
                glossary_run_stats["total_hits"]   += result["glossary_hits"]
                for term, cnt in result["glossary_terms"].items():
                    glossary_run_stats["term_counts"][term] = (
                        glossary_run_stats["term_counts"].get(term, 0) + cnt
                    )

                # Progress update (main thread only)
                pct_api = int((api_cells_done / max(total_api_cells, 1)) * 100)
                elapsed = time.time() - start_time
                rate    = api_cells_done / max(elapsed, 0.1)
                eta     = (total_api_cells - api_cells_done) / max(rate, 0.1)
                in_flight = max(0, min(max_concurrent_batches, total_batches - completed_batches))
                progress_bar.progress(0.05 + (api_cells_done / max(total_api_cells, 1)) * 0.60)
                progress_container.markdown(
                    _parallel_progress_html(
                        sheet_name, total_batches, completed_batches, in_flight,
                        failed_batches, api_cells_done, total_api_cells,
                        stats["tm_hits"], elapsed, eta, pct_api,
                    ),
                    unsafe_allow_html=True,
                )

        # Apply results sequentially (main thread — no concurrent Excel writes)
        for result in sorted(batch_results, key=lambda r: r["batch_id"]):
            for i, (row_num, col_header, col_idx, canonical, text) in enumerate(result["batch_items"]):
                tr = str(result["translations"][i]).strip() if i < len(result["translations"]) else text
                if canonical == "name":
                    tr = validate_product_name(tr)
                results[(row_num, col_idx)] = tr
                tm_put(tm, text, tr, _tm_col_type(canonical))
                stats["cells_translated"] += 1

        # Count TM hits as translated
        stats["cells_translated"] += stats["tm_hits"]
        stats["batch_count"]       = total_batches
        stats["failed_batches"]    = failed_batches
        stats["avg_batch_duration"] = round(
            sum(batch_durations) / max(len(batch_durations), 1), 2
        )
        stats["max_concurrent_used"] = max_concurrent_batches
        stats["avg_batch_size"] = (
            round(total_api_cells / max(total_batches, 1), 1)
            if total_batches > 0 else 0.0
        )

        # 1 API call per cell without batching + TM; now 1 per batch + 0 for TM hits
        stats["api_calls_made"]    = total_batches
        stats["api_calls_reduced"] = max(total_to_process - total_batches - stats["tm_hits"], 0)

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

        # Build source lookup for quality analysis
        source_lookup: dict[tuple, tuple] = {
            (row_num, col_idx): (text, canonical)
            for row_num, col_header, col_idx, canonical, text in cells_queue
        }

        # ── Signal separation ─────────────────────────────────────────────────
        # Three independent signals — only the first two may affect Excel color:
        #   original_excel_highlights : source cell fills → always preserved
        #   review_warnings           : quality issues  → REVIEW_FILL only when
        #                               highlight_review_warnings=True (opt-in checkbox)
        #   glossary_hits             : analytics only  → NEVER affect cell color

        # Capture original fills from the source workbook before writing anything.
        original_excel_highlights: dict[tuple, object] = {}
        for (rn, ci) in results:
            src_cell = worksheet.cell(row=rn, column=ci)
            if src_cell.fill and getattr(src_cell.fill, "fill_type", None) not in (None, "none"):
                try:
                    original_excel_highlights[(rn, ci)] = copy.copy(src_cell.fill)
                except Exception:
                    pass

        all_warnings: list[dict] = []
        review_items: list[dict] = []
        cells_original_highlight = 0
        cells_review_highlighted  = 0

        col_header_map = {ci: h for h, (ci, _) in to_translate.items()}

        for (row_num, col_idx), translation in results.items():
            cell       = worksheet.cell(row=row_num, column=col_idx)
            cell.value = translation
            src_text, src_canonical = source_lookup.get((row_num, col_idx), (translation, "other"))
            has_original = (row_num, col_idx) in original_excel_highlights
            col_header   = col_header_map.get(col_idx, str(col_idx))

            # Quality analysis — glossary_hits tracked separately, never affect cell color.
            issues = analyze_translation_quality(src_text, translation, src_canonical, glossary)

            ts = datetime.now().isoformat(timespec="seconds")
            has_critical_or_high = False

            for issue in issues:
                if issue["type"] == "german_residue":
                    continue  # deferred to post-fix warning_details for accuracy
                sev = issue.get("severity", SEVERITY_LOW)
                if sev in (SEVERITY_CRITICAL, SEVERITY_HIGH):
                    has_critical_or_high = True
                src_snippet = src_text[:120] + "…" if len(src_text) > 120 else src_text
                tr_snippet  = translation[:120] + "…" if len(translation) > 120 else translation
                all_warnings.append({
                    "severity":        sev,
                    "category":        issue.get("category", "Manual review recommended"),
                    "row":             row_num,
                    "column":          col_header,
                    "original_text":   src_snippet,
                    "translated_text": tr_snippet,
                    "reason":          issue.get("reason", ""),
                    "suggested_fix":   issue.get("suggested_fix", ""),
                    "timestamp":       ts,
                })

            if issues:
                review_items.append({
                    "row":         row_num,
                    "col_idx":     col_idx,
                    "translation": translation[:60] + "…" if len(translation) > 60 else translation,
                    "issues":      issues,
                })
                # Highlight only Critical/High when checkbox is enabled
                if highlight_review_warnings and has_critical_or_high:
                    cell.fill = REVIEW_FILL
                    cells_review_highlighted += 1
                elif has_original:
                    cell.fill = original_excel_highlights[(row_num, col_idx)]
                    cells_original_highlight += 1
            elif has_original:
                cell.fill = original_excel_highlights[(row_num, col_idx)]
                cells_original_highlight += 1

        total_cells_for_passes = total_rows * len(to_translate)

        # ── Phase 3: Residue check ────────────────────────────────────────────
        checked = 0
        for row_num in range(data_start_row, worksheet.max_row + 1):
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

        for row_num in range(data_start_row, worksheet.max_row + 1):
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

        # ── Merge confirmed unresolved residue into all_warnings ─────────────────
        ts_fin = datetime.now().isoformat(timespec="seconds")
        for wd in stats["warning_details"]:
            all_warnings.append({
                "severity":        SEVERITY_CRITICAL,
                "category":        "German residue",
                "row":             wd["row"],
                "column":          wd["column"],
                "original_text":   "",
                "translated_text": wd["text"],
                "reason":          f"Unresolved German words after 3 fix attempts: {', '.join(wd.get('residue', []))}",
                "suggested_fix":   "Retranslate manually — automated residue fixing failed",
                "timestamp":       ts_fin,
            })

        _crit = sum(1 for w in all_warnings if w["severity"] == SEVERITY_CRITICAL)
        _high = sum(1 for w in all_warnings if w["severity"] == SEVERITY_HIGH)
        _med  = sum(1 for w in all_warnings if w["severity"] == SEVERITY_MEDIUM)
        _low  = sum(1 for w in all_warnings if w["severity"] == SEVERITY_LOW)
        from collections import Counter
        _cat_counts = Counter(w["category"] for w in all_warnings)

        stats["all_warnings"]       = all_warnings
        stats["critical_warnings"]  = _crit
        stats["high_warnings"]      = _high
        stats["medium_warnings"]    = _med
        stats["low_warnings"]       = _low
        stats["quality_score"]      = compute_quality_score(all_warnings)
        stats["warning_categories"] = dict(_cat_counts)
        stats["review_count"]       = len(all_warnings)

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

        stats["review_items"] = review_items  # per-cell legacy list
        stats["retry_count"]  = retry_counter[0]

        # Audit counters for the export highlighting report
        stats["original_highlights_preserved"] = cells_original_highlight
        stats["review_highlights_applied"]      = cells_review_highlighted
        stats["highlight_review_warnings"]      = highlight_review_warnings

        return output, stats

    finally:
        os.unlink(tmp_path)


# =============================================================================
# REVIEW DASHBOARD
# =============================================================================

def render_review_dashboard(all_warnings: list, stats: dict, highlight_in_excel: bool):
    score               = stats.get("quality_score", 100)
    verdict_text, score_color = quality_verdict(score)
    critical = stats.get("critical_warnings", 0)
    high     = stats.get("high_warnings", 0)
    medium   = stats.get("medium_warnings", 0)
    low_     = stats.get("low_warnings", 0)

    st.markdown(f"""
    <div class="card" style="text-align:center;padding:28px 24px;">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.1em;color:#686880;margin-bottom:10px;">
            Translation Quality Score
        </div>
        <div style="font-size:62px;font-weight:800;letter-spacing:-0.04em;
                    color:{score_color};line-height:1;">
            {score}<span style="font-size:24px;color:#686880;">/100</span>
        </div>
        <div style="font-size:13px;color:#686880;margin-top:10px;">{verdict_text}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label" style="color:#ef4444;">Critical</div>
            <div class="kpi-value" style="color:#ef4444;">{critical}</div>
            <div class="kpi-sub">−10 pts each</div>
        </div>
        <div class="kpi">
            <div class="kpi-label" style="color:#f59e0b;">High</div>
            <div class="kpi-value" style="color:#f59e0b;">{high}</div>
            <div class="kpi-sub">−5 pts each</div>
        </div>
        <div class="kpi">
            <div class="kpi-label" style="color:#ca8a04;">Medium</div>
            <div class="kpi-value" style="color:#ca8a04;">{medium}</div>
            <div class="kpi-sub">−2 pts each</div>
        </div>
        <div class="kpi">
            <div class="kpi-label" style="color:#818cf8;">Low</div>
            <div class="kpi-value" style="color:#818cf8;">{low_}</div>
            <div class="kpi-sub">−1 pt each</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not all_warnings:
        st.markdown("""
        <div class="alert alert-success">
            <span class="alert-icon">✓</span>
            <span><strong>No warnings detected.</strong> Translation passed all quality checks.</span>
        </div>
        """, unsafe_allow_html=True)
        return

    excel_note = (
        "Critical and High warnings are highlighted yellow in the downloaded Excel."
        if highlight_in_excel
        else "Warnings shown here only — Excel highlighting is off (checkbox unchecked)."
    )
    st.markdown(f"""
    <div class="alert alert-info">
        <span class="alert-icon">ℹ</span>
        <span>{excel_note} Glossary hits never create highlights.</span>
    </div>
    """, unsafe_allow_html=True)

    with st.expander(f"Warning details — {len(all_warnings)} warning(s)", expanded=True):
        c1, c2, c3, c4 = st.columns([1.4, 1.4, 2, 2])
        with c1:
            sev_filter = st.selectbox(
                "Severity", ["All"] + SEVERITY_ORDER, key="wd_sev"
            )
        with c2:
            col_opts   = ["All"] + sorted(set(w["column"] for w in all_warnings))
            col_filter = st.selectbox("Column", col_opts, key="wd_col")
        with c3:
            cat_opts   = ["All"] + sorted(set(w["category"] for w in all_warnings))
            cat_filter = st.selectbox("Category", cat_opts, key="wd_cat")
        with c4:
            search = st.text_input("Search in reason / text", placeholder="e.g. Bezug", key="wd_search")

        filtered = all_warnings
        if sev_filter != "All":
            filtered = [w for w in filtered if w["severity"] == sev_filter]
        if col_filter != "All":
            filtered = [w for w in filtered if w["column"] == col_filter]
        if cat_filter != "All":
            filtered = [w for w in filtered if w["category"] == cat_filter]
        if search:
            sl = search.lower()
            filtered = [
                w for w in filtered
                if sl in w.get("reason", "").lower()
                or sl in w.get("original_text", "").lower()
                or sl in w.get("translated_text", "").lower()
            ]

        st.caption(f"{len(filtered)} of {len(all_warnings)} warning(s) shown")

        if filtered:
            rows = [
                {
                    "Severity":    w["severity"],
                    "Category":    w["category"],
                    "Row":         w["row"],
                    "Column":      w["column"],
                    "Reason":      w["reason"],
                    "Original":    w.get("original_text", "")[:70],
                    "Translation": w.get("translated_text", "")[:70],
                    "Suggested Fix": w.get("suggested_fix", ""),
                }
                for w in filtered
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)

            csv_buf = StringIO()
            writer  = csv.DictWriter(csv_buf, fieldnames=[
                "severity", "category", "row", "column",
                "original_text", "translated_text", "reason", "suggested_fix",
            ])
            writer.writeheader()
            for w in filtered:
                writer.writerow({k: w.get(k, "") for k in writer.fieldnames})
            st.download_button(
                label="↓ Download warnings as CSV",
                data=csv_buf.getvalue().encode("utf-8"),
                file_name="translation_warnings.csv",
                mime="text/csv",
                use_container_width=True,
            )


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
                <div class="login-form-title">Sign in</div>
                <div class="login-form-sub">Internal access · Home24 e-commerce tools</div>
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

        header_row, peek_headers = detect_header_row(wb_peek[selected_sheet])
        wb_peek.close()
        classification = classify_columns(peek_headers)
        classification["header_row"] = header_row

        render_column_report(classification)

        # Manual fallback when automatic detection found nothing
        if not classification["to_translate"] and peek_headers:
            st.markdown("""
            <div class="alert alert-warn" style="margin-top:0;">
                <span class="alert-icon">⚠</span>
                <div>
                    <strong>Automatic detection failed.</strong>
                    Please select the columns you want to translate below.
                    Protected columns (articleNumber, SKU, ID) will never be translated.
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Offer all non-protected headers as candidates
            protected_keys = set(classification["protected"].keys())
            candidates = [h for h in peek_headers if h not in protected_keys]

            manual_cols = st.multiselect(
                "Select columns to translate:",
                options=candidates,
                key="manual_col_select",
                help="Choose each column header that contains German text to translate.",
            )

            if manual_cols:
                manual_to_translate = {}
                for h in manual_cols:
                    col_idx = peek_headers[h]
                    # Best-effort canonical type; fallback to "other"
                    canonical, _, _ = _classify_header(h)
                    manual_to_translate[h] = (col_idx, canonical or "other")
                classification["to_translate"] = manual_to_translate

        # Advanced settings
        with st.expander("Advanced settings"):
            col_bs, col_cc = st.columns(2)
            with col_bs:
                batch_size = st.slider(
                    "Batch size (cells per request)",
                    min_value=5, max_value=30,
                    value=DEFAULT_BATCH_SIZE,
                    help="Cells grouped into one API request. Larger = fewer calls, bigger payloads.",
                )
            with col_cc:
                max_concurrent_batches = st.slider(
                    "Max concurrent batches",
                    min_value=1, max_value=5,
                    value=DEFAULT_MAX_CONCURRENT,
                    help=(
                        "How many batches are sent to OpenAI in parallel. "
                        "3 is a safe default; set to 1 for sequential (same as before)."
                    ),
                )
            st.markdown("---")
            highlight_warnings_in_excel = st.checkbox(
                "Highlight review warnings in exported Excel",
                value=False,
                key="highlight_warnings_excel",
                help=(
                    "When checked, cells flagged by Human Review Mode are highlighted "
                    "yellow in the exported file. Off by default — warnings appear in the "
                    "dashboard report only, and original source highlights are always preserved."
                ),
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
                    highlight_review_warnings=highlight_warnings_in_excel,
                    max_concurrent_batches=int(max_concurrent_batches),
                    header_row=header_row,
                )
                progress_container.empty()
                progress_bar.empty()

                job_id = str(uuid.uuid4())
                save_history_record({
                    "id":                        job_id,
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
                    "review_count":              stats.get("review_count", 0),
                    "retry_count":               stats.get("retry_count", 0),
                    "critical_warnings":         stats.get("critical_warnings", 0),
                    "high_warnings":             stats.get("high_warnings", 0),
                    "medium_warnings":           stats.get("medium_warnings", 0),
                    "low_warnings":              stats.get("low_warnings", 0),
                    "total_warnings":            len(stats.get("all_warnings", [])),
                    "quality_score":             stats.get("quality_score", 100),
                    "warning_categories":        stats.get("warning_categories", {}),
                })
                db_save_warnings(job_id, stats.get("all_warnings", []))

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

                # ── Review Dashboard ──
                st.markdown('<div class="section-label">Review Dashboard</div>', unsafe_allow_html=True)
                render_review_dashboard(
                    stats.get("all_warnings", []),
                    stats,
                    highlight_warnings_in_excel,
                )

                # ── Export Audit ──
                n_orig  = stats.get("original_highlights_preserved", 0)
                n_rev   = stats.get("review_highlights_applied", 0)
                n_gloss = stats.get("glossary_hits", 0)
                n_total_warn = len(stats.get("all_warnings", []))
                rev_label = (
                    f"{n_rev} cell(s) highlighted (Critical + High only)"
                    if highlight_warnings_in_excel
                    else f"0 — checkbox off, {n_total_warn} warning(s) in dashboard only"
                )
                orig_label = f"{n_orig} cell(s) — source formatting preserved" if n_orig else "None in this file"
                audit_rows = [
                    ("📋", "Original source highlights",    orig_label),
                    ("🟡" if n_rev else "✅", "Review warnings in Excel", rev_label),
                    ("✅", "Glossary hits in Excel",
                     f"{n_gloss} hit(s) tracked in analytics — no cell color applied"),
                ]
                audit_html = "".join(
                    f"""<div class="qg-row">
                        <span class="qg-icon">{icon}</span>
                        <span class="qg-label">{label}</span>
                        <span class="qg-value">{value}</span>
                    </div>"""
                    for icon, label, value in audit_rows
                )
                st.markdown('<div class="section-label">Export Audit</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="qg">{audit_html}</div>', unsafe_allow_html=True)

                # ── Completion banner ──
                cost_str = (
                    f"${stats['estimated_cost_usd']:.4f}"
                    if stats.get("estimated_cost_usd") is not None
                    else "cost N/A"
                )
                processed_sheet = stats.get("sheet_name", "")
                qs = stats.get("quality_score", 100)
                vt, _ = quality_verdict(qs)

                if not stats.get("all_warnings"):
                    st.markdown(f"""
                    <div class="success-banner">
                        <div class="success-banner-icon">✓</div>
                        <div>
                            <div class="success-banner-title">Translation complete — Score {qs}/100</div>
                            <div class="success-banner-sub">
                                {vt} · Sheet: {processed_sheet} · {stats["cells_translated"]} cells ·
                                {stats["total_time"]} · {cost_str}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="warn-banner">
                        <div class="warn-banner-title">
                            Translation complete — Score {qs}/100 · {n_total_warn} warning(s)
                        </div>
                        <div class="warn-banner-sub">
                            {vt} · Sheet: {processed_sheet} · {stats["total_time"]} · {cost_str}
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
            <span class="history-empty-sub">
                Go to <strong>Translator</strong> to get started.
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
        qs  = r.get("quality_score")
        rows.append({
            "Date / Time":     dt,
            "File":            r.get("original_filename", ""),
            "Sheet":           r.get("sheet_name", ""),
            "Translated":      r.get("cells_translated", 0),
            "Score":           f"{qs}/100" if qs is not None else "—",
            "Critical":        r.get("critical_warnings", "—"),
            "High":            r.get("high_warnings", "—"),
            "Warnings (total)": r.get("total_warnings", r.get("unresolved_warnings", 0)),
            "Residue Fixes":   r.get("residue_corrections", 0),
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
            <span class="history-empty-sub">
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

    # ── Cost Dashboard ──
    total_prompt     = sum(r.get("prompt_tokens", 0) or 0 for r in history)
    total_completion = sum(r.get("completion_tokens", 0) or 0 for r in history)
    total_tokens_all = total_prompt + total_completion
    avg_cost_file    = round(total_cost / total_files, 4)     if total_cost and total_files > 0     else None
    avg_cost_cell    = round(total_cost / total_translated, 6) if total_cost and total_translated > 0 else None

    st.markdown('<div class="section-label">Cost Dashboard</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-label">Total Tokens Used</div>
            <div class="kpi-value accent">{total_tokens_all:,}</div>
            <div class="kpi-sub">All jobs combined</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Prompt Tokens</div>
            <div class="kpi-value">{total_prompt:,}</div>
            <div class="kpi-sub">${total_prompt * _INPUT_COST_PER_TOKEN:.4f} input cost</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Completion Tokens</div>
            <div class="kpi-value">{total_completion:,}</div>
            <div class="kpi-sub">${total_completion * _OUTPUT_COST_PER_TOKEN:.4f} output cost</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Avg Cost / File</div>
            <div class="kpi-value warn">{f"${avg_cost_file:.4f}" if avg_cost_file is not None else "—"}</div>
            <div class="kpi-sub">Per translation job</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if avg_cost_cell is not None:
        st.markdown(f"""
        <div class="kpi-row-3">
            <div class="kpi">
                <div class="kpi-label">Avg Cost / Cell</div>
                <div class="kpi-value warn">${avg_cost_cell:.6f}</div>
                <div class="kpi-sub">Per translated cell</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Input Rate</div>
                <div class="kpi-value" style="font-size:18px;">$0.15 / 1M</div>
                <div class="kpi-sub">GPT-4o-mini prompt tokens</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Output Rate</div>
                <div class="kpi-value" style="font-size:18px;">$0.60 / 1M</div>
                <div class="kpi-sub">GPT-4o-mini completion tokens</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    cost_by_job = {
        f"#{i + 1}": r.get("estimated_cost_usd") or 0
        for i, r in enumerate(reversed(history))
        if r.get("estimated_cost_usd") is not None
    }
    if len(cost_by_job) > 1:
        st.markdown('<div class="section-label">Cost per Job</div>', unsafe_allow_html=True)
        st.bar_chart(cost_by_job)

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

    # ── Quality Score Analytics ──
    scored_records = [r for r in history if r.get("quality_score") is not None]
    if scored_records:
        avg_score      = round(sum(r["quality_score"] for r in scored_records) / len(scored_records), 1)
        total_critical = sum(r.get("critical_warnings", 0) for r in history)
        total_high     = sum(r.get("high_warnings", 0) for r in history)
        total_medium   = sum(r.get("medium_warnings", 0) for r in history)
        total_low      = sum(r.get("low_warnings", 0) for r in history)
        files_critical = sum(1 for r in history if r.get("critical_warnings", 0) > 0)

        score_color = "#10b981" if avg_score >= 85 else ("#f59e0b" if avg_score >= 70 else "#ef4444")
        st.markdown('<div class="section-label">Quality Score</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="kpi-row">
            <div class="kpi">
                <div class="kpi-label">Avg Quality Score</div>
                <div class="kpi-value" style="color:{score_color};">{avg_score}/100</div>
                <div class="kpi-sub">Across {len(scored_records)} job(s)</div>
            </div>
            <div class="kpi">
                <div class="kpi-label" style="color:#ef4444;">Critical Warnings</div>
                <div class="kpi-value" style="color:#ef4444;">{total_critical}</div>
                <div class="kpi-sub">{files_critical} file(s) affected</div>
            </div>
            <div class="kpi">
                <div class="kpi-label" style="color:#f59e0b;">High Warnings</div>
                <div class="kpi-value" style="color:#f59e0b;">{total_high}</div>
                <div class="kpi-sub">−5 pts each</div>
            </div>
            <div class="kpi">
                <div class="kpi-label" style="color:#ca8a04;">Medium / Low</div>
                <div class="kpi-value" style="color:#ca8a04;">{total_medium + total_low}</div>
                <div class="kpi-sub">Medium {total_medium} · Low {total_low}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Most common warning categories across all jobs
        from collections import Counter
        all_cats: Counter = Counter()
        for r in history:
            for cat, cnt in r.get("warning_categories", {}).items():
                all_cats[cat] += cnt
        if all_cats:
            top_cats = all_cats.most_common(5)
            chips = "".join(
                f'<span class="chip chip-muted">{cat} <span class="chip-arrow">· {n}×</span></span>'
                for cat, n in top_cats
            )
            st.markdown(f"""
            <div class="card" style="margin-top:0;">
                <div class="card-title">Most common warning categories</div>
                <div>{chips}</div>
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

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "theme" not in st.session_state:
        st.session_state["theme"] = "Dark"
    if "db_initialized" not in st.session_state:
        init_db(default_glossary=DEFAULT_GLOSSARY_TERMS)
        st.session_state["db_initialized"] = True

    inject_custom_css(st.session_state["theme"])

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
