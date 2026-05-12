"""
Translation Intelligence Engine
Hybrid pipeline: Normalization → Exact TM → Semantic TM → Glossary-Only → Pattern → GPT
Applies to both German→French and German→Dutch modes.
"""

import re
from collections import Counter
from difflib import SequenceMatcher


# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_text(text: str) -> str:
    """Trim, collapse whitespace, normalize line breaks and non-breaking spaces."""
    text = str(text).strip()
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("\xa0", " ").replace("\t", " ")
    return re.sub(r" {2,}", " ", text)


def normalize_lower(text: str) -> str:
    return normalize_text(text).lower()


# =============================================================================
# SMART DUPLICATE DETECTION  (Part 2)
# =============================================================================

def dedup_api_queue(api_queue: list) -> tuple[list, dict, int, int]:
    """
    Collapse duplicate source texts before batching.

    api_queue items: (row_num, col_header, col_idx, canonical, text)

    Returns:
        unique_queue     — one representative item per unique (text, canonical) pair
        dup_restore_map  — {(row_num, col_idx): (rep_row, rep_col_idx)} for duplicates
        dup_groups       — number of groups that contained ≥1 duplicate
        cells_saved      — total duplicate cells that skip their own API call
    """
    seen: dict[tuple, tuple] = {}
    unique_queue: list = []
    dup_restore_map: dict[tuple, tuple] = {}
    all_keys: list[tuple] = []

    for item in api_queue:
        row_num, col_header, col_idx, canonical, text = item
        key = (normalize_lower(text), canonical)
        all_keys.append(key)
        if key in seen:
            dup_restore_map[(row_num, col_idx)] = seen[key]
        else:
            seen[key] = (row_num, col_idx)
            unique_queue.append(item)

    counts = Counter(all_keys)
    dup_groups = sum(1 for c in counts.values() if c > 1)
    cells_saved = sum(c - 1 for c in counts.values() if c > 1)
    return unique_queue, dup_restore_map, dup_groups, cells_saved


# =============================================================================
# GLOSSARY-ONLY TRANSLATION  (Part 1 — Step 3)
# =============================================================================

def _split_on_separators(text: str) -> tuple[list[str], str]:
    """Split on <br>, comma, or slash. Returns (parts, sep_token)."""
    if re.search(r"<br\s*/?>", text, re.IGNORECASE):
        parts = re.split(r"<br\s*/?>", text, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()], "<br>"
    if "/" in text and "," not in text:
        return [p.strip() for p in text.split("/") if p.strip()], "/"
    if "," in text:
        return [p.strip() for p in text.split(",") if p.strip()], ", "
    return [text.strip()], ""


def try_glossary_only(
    text: str,
    glossary: dict,
    target_language: str = "French",
) -> str | None:
    """
    Translate text using glossary alone — no API call.
    Returns translation if the entire text resolves via glossary; else None.
    Only handles texts ≤120 chars to stay safe.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return None

    terms = glossary.get("terms", {})
    if not terms:
        return None

    low = stripped.lower()

    # Exact single-term match
    for de, tr in terms.items():
        if de.lower() == low:
            return tr

    # Separator-split compound — every part must resolve
    parts, sep = _split_on_separators(stripped)
    if len(parts) <= 1:
        return None

    translated: list[str] = []
    for part in parts:
        if not part:
            continue
        pl = part.lower()
        matched = None
        for de, tr in terms.items():
            if de.lower() == pl:
                matched = tr
                break
        if matched is None:
            return None
        translated.append(matched)

    return sep.join(translated)


# =============================================================================
# PATTERN / RULE-BASED TRANSLATION  (Part 1 — Step 4)
# =============================================================================

# Dimension string: "B 120 x H 80 x T 40 cm", "120 × 80 cm", "Ø 45 cm"
# Allows optional label letters between dimensions (B, H, T, Ø...)
_DIM_RE = re.compile(
    r"^[A-ZÄÖÜa-zäöüß\sØø]*"          # optional prefix label
    r"\d+[\.,]?\d*"                      # first number
    r"(?:\s*(?:x|×|X)\s*"               # × separator
    r"[A-ZÄÖÜa-zäöüß]?\s*"             # optional label between dimensions
    r"\d+[\.,]?\d*)+"                    # next number (one or more pairs)
    r"\s*(?:cm|mm|m\b|in\b)?\s*$",
    re.IGNORECASE,
)

# Pure numeric / measurement tokens only
_NUMERIC_RE = re.compile(r"^[\d\s.,×xXcmminkgcl%/\-+²³()Øø]+$")

# Percentage composition: "100% Polyester" or "60% Baumwolle, 40% Polyester"
_PCT_RE = re.compile(
    r"^\d+\s*%\s*[A-ZÄÖÜa-zäöüß][\w\-äöüÄÖÜß]*"
    r"(?:\s*[,/]\s*\d+\s*%\s*[A-ZÄÖÜa-zäöüß][\w\-äöüÄÖÜß]*)*$"
)


def try_pattern_translation(
    text: str,
    glossary: dict,
    target_language: str = "French",
) -> str | None:
    """
    Return a local translation for texts that match a known mechanical pattern.
    Returns None to signal: send to API.
    """
    s = text.strip()
    if not s:
        return None

    # Pure numeric / unit string — language-neutral, keep as-is
    if _NUMERIC_RE.match(s) and len(s) <= 40:
        return s

    # Dimension expressions — numbers and units are universal
    if _DIM_RE.match(s) and len(s) <= 80:
        return s

    # Percentage compositions — translate fiber names via glossary
    if _PCT_RE.match(s):
        result = _translate_pct_composition(s, glossary, target_language)
        if result is not None:
            return result

    return None


def _translate_pct_composition(
    text: str,
    glossary: dict,
    target_language: str,
) -> str | None:
    """Translate '60% Baumwolle, 40% Polyester' using glossary fiber mappings."""
    terms = glossary.get("terms", {})
    parts = re.split(r"\s*[,/]\s*", text)
    out: list[str] = []
    for part in parts:
        m = re.match(r"^(\d+)\s*%\s*(.+)$", part.strip(), re.IGNORECASE)
        if not m:
            return None
        pct, fiber = m.group(1), m.group(2).strip()
        fiber_lo = fiber.lower()
        matched = None
        for de, tr in terms.items():
            if de.lower() == fiber_lo:
                matched = tr.lower()
                break
        if matched is None:
            return None
        out.append(f"{pct}% {matched}")
    return ", ".join(out)


# =============================================================================
# SEMANTIC TRANSLATION MEMORY  (Part 3)
# =============================================================================

def semantic_tm_match(
    tm: dict,
    text: str,
    col_type: str,
    target_language: str = "French",
    threshold: float = 0.88,
) -> tuple[str, float] | None:
    """
    Find a semantically similar TM entry using sequence similarity.
    Only considers entries for the same language prefix and col_type.
    Capped at 300 candidates per col_type for performance.
    Returns (translation, score) or None.
    """
    lang_prefix = "nl:" if target_language == "Dutch" else "fr:"
    text_norm = normalize_lower(text)

    if len(text_norm) < 8 or len(text_norm) > 150:
        return None

    best_score = 0.0
    best_tr = None
    checked = 0

    for key, val in tm.get("entries", {}).items():
        if not key.startswith(lang_prefix):
            continue
        rest = key[len(lang_prefix):]          # "col_type:text"
        colon = rest.find(":")
        if colon < 0:
            continue
        tm_col = rest[:colon]
        if tm_col != col_type:
            continue
        tm_text = rest[colon + 1:]

        # Quick length gate — skip if lengths differ by >40%
        if abs(len(tm_text) - len(text_norm)) > len(text_norm) * 0.4 + 4:
            continue

        ratio = SequenceMatcher(None, text_norm, tm_text.lower(), autojunk=False).ratio()
        if ratio > best_score:
            best_score = ratio
            best_tr = val["translation"]

        checked += 1
        if checked >= 300:
            break

    if best_score >= threshold and best_tr:
        return best_tr, round(best_score, 3)
    return None


# =============================================================================
# PRODUCT TYPE DETECTION  (Part 5)
# =============================================================================

_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "sofa": [
        "sofa", "couch", "sessel", "ecksofa", "schlafsofa", "longchair",
        "recamiere", "ottomane", "polsterecke", "wohnlandschaft",
        "canapé", "fauteuil", "hoekbank", "slaapbank",
    ],
    "bed": [
        "bett", "boxspringbett", "polsterbett", "futonbett", "kinderbett",
        "einzelbett", "doppelbett", "hochbett",
    ],
    "table": [
        "esstisch", "couchtisch", "beistelltisch", "bartisch",
        "esstischgruppe",
    ],
    "wardrobe": [
        "kleiderschrank", "kommode", "sideboard", "highboard",
        "vitrine", "aktenschrank",
    ],
    "bathroom": [
        "waschbecken", "waschtisch", "badezimmer", "spiegelschrank",
        "badmöbel", "wastafel",
    ],
    "office": [
        "schreibtisch", "bürostuhl", "rollcontainer", "computertisch",
    ],
    "textile": [
        "kissen", "teppich", "vorhang", "bettwäsche",
        "kissenbezug", "deckenbezug",
    ],
    "outdoor": [
        "gartenstuhl", "gartentisch", "terrassenmöbel", "gartenmöbel",
    ],
    "lighting": [
        "lampe", "leuchte", "pendelleuchte", "tischlampe",
        "wandlampe", "stehlampe",
    ],
}


def detect_product_type(
    name_texts: list[str] | None = None,
    context_texts: list[str] | None = None,
) -> str:
    """
    Detect furniture category from product names and context.
    Returns a category key or 'generic'.
    """
    combined = ""
    for t in (name_texts or []):
        if t:
            combined += " " + t.lower()
    for t in (context_texts or [])[:3]:
        if t:
            combined += " " + t.lower()[:200]

    best_cat, best_score = "generic", 0
    for cat, keywords in _PRODUCT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score, best_cat = score, cat

    return best_cat if best_score > 0 else "generic"


_CATEGORY_FR_HINTS: dict[str, str] = {
    "sofa":     "Product: SOFA/SEATING — prefer: assise, dossier, accoudoir, piètement, mousse HR, revêtement.",
    "bed":      "Product: BED — prefer: tête de lit, sommier, cadre de lit, lattes, pieds de lit.",
    "table":    "Product: TABLE — prefer: plateau, piétement, rallonge, extensible.",
    "wardrobe": "Product: STORAGE — prefer: penderie, tiroir, tablette, porte battante/coulissante.",
    "bathroom": "Product: BATHROOM — prefer: meuble vasque, miroir, colonne de rangement.",
    "office":   "Product: OFFICE — prefer: bureau, caisson, réglable en hauteur.",
    "textile":  "Product: TEXTILE — prefer: housse, garnissage, lavable.",
    "outdoor":  "Product: OUTDOOR — prefer: résistant aux UV, aluminium laqué, empilable.",
    "lighting": "Product: LIGHTING — prefer: ampoule incluse, culot E27, intensité réglable.",
}

_CATEGORY_NL_HINTS: dict[str, str] = {
    "sofa":     "Product: BANK/ZITMEUBEL — prefer: zitting, rugleuning, armleuning, onderstel, schuimvulling, bekleding.",
    "bed":      "Product: BED — prefer: hoofdbord, lattenbodem, bedframe, poten.",
    "table":    "Product: TAFEL — prefer: tafelblad, onderstel, uitschuifbaar, verlengstuk.",
    "wardrobe": "Product: OPBERGEN — prefer: kledingkast, lade, legplank, draaideuren.",
    "bathroom": "Product: BADKAMER — prefer: wastafelkast, spiegel, opbergkast.",
    "office":   "Product: KANTOOR — prefer: bureau, ladeblok, in hoogte verstelbaar.",
    "textile":  "Product: TEXTIEL — prefer: hoes, vulling, wasbaar.",
    "outdoor":  "Product: BUITEN — prefer: UV-bestendig, weerbestendig, stapelbaar.",
    "lighting": "Product: VERLICHTING — prefer: lamp inbegrepen, fitting E27, dimbaar.",
}


def get_product_type_hint(category: str, target_language: str = "French") -> str:
    """Return a short prompt hint for the detected product category."""
    if category == "generic":
        return ""
    hints = _CATEGORY_NL_HINTS if target_language == "Dutch" else _CATEGORY_FR_HINTS
    hint = hints.get(category, "")
    return f"\n{hint}" if hint else ""


# =============================================================================
# GLOSSARY SUGGESTION EXTRACTION  (Part 4)
# =============================================================================

_GERMAN_TOKEN_RE = re.compile(
    r"\b([A-ZÄÖÜ][a-zäöüß]{3,}|[a-zäöüß]{4,})\b", re.UNICODE
)

_SUGGESTION_STOPWORDS = frozenset({
    "und", "mit", "oder", "für", "aus", "bei", "zur", "zum", "von", "vom",
    "sowie", "inkl", "inklusive", "ohne", "über", "unter", "auch", "sehr",
    "sind", "wird", "kann", "durch", "nach", "beim", "eine", "einen", "einer",
    "nicht", "mehr", "alle", "diesem", "dieser", "seine", "ihrer", "ihrem",
    "werden", "haben", "wurde", "worden",
})


def extract_glossary_suggestions(
    source_texts: list[str],
    glossary: dict,
    target_language: str = "French",
    min_occurrences: int = 2,
    max_results: int = 20,
) -> list[dict]:
    """
    Find recurring German terms in source texts not already in the glossary.
    Returns a ranked list of suggestion dicts for admin review.
    """
    existing_lower = {k.lower() for k in glossary.get("terms", {}).keys()}
    term_counts: Counter = Counter()
    term_contexts: dict[str, str] = {}

    for text in source_texts:
        if not text:
            continue
        tokens_in_doc = set(_GERMAN_TOKEN_RE.findall(text))
        for token in tokens_in_doc:
            tl = token.lower()
            if tl in _SUGGESTION_STOPWORDS or tl in existing_lower or len(token) < 4:
                continue
            term_counts[token] += 1
            if token not in term_contexts:
                term_contexts[token] = normalize_text(text)[:100]

    results = []
    for term, count in term_counts.most_common(max_results * 3):
        if count < min_occurrences:
            break
        results.append({
            "term":            term,
            "occurrences":     count,
            "example_context": term_contexts.get(term, ""),
            "target_language": target_language,
        })
        if len(results) >= max_results:
            break

    return results
