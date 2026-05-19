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
    "kitchen": [
        "küchenzeile", "küche", "einbauküche", "küchenblock", "küchenfront",
        "gsp", "geschirrspüler", "spüle", "spülenschrank", "arbeitsplatte",
        "hängeschrank", "oberschrank", "apothekerschrank",
    ],
    "bathroom": [
        "waschbecken", "waschtisch", "badezimmer", "spiegelschrank",
        "badmöbel", "wastafel", "unterflurauszug", "badmöbel",
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
        "gartenessgruppe", "gartengruppe", "gartenset", "gartensofa",
        "loungeset", "loungesofa", "loungesessel", "sofaelement", "sofamodul",
        "terrassenset", "gartenliege", "gartenbank",
        "polyrattan", "geflecht", "kunststoffgeflecht",
        "pulverbeschichtet",
    ],
    "lighting": [
        "lampe", "leuchte", "pendelleuchte", "tischlampe",
        "wandlampe", "stehlampe",
    ],
    "mattress": [
        "matratze", "taschenfederkern", "taschenfederkernmatratze",
        "kaltschaummatratze", "latexmatratze", "bonellfeder",
        "7-zonen", "9-zonen", "zonen-taschenfederkern",
        "kokosmatte", "kokosschicht", "doppeltuch", "reißverschluss",
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
    "kitchen":  "Product: CUISINE — prefer: plan de travail, meuble bas, meuble haut, colonne, façade, sans poignée, lave-vaisselle.",
    "bathroom": "Product: BATHROOM — prefer: meuble vasque, miroir, colonne de rangement.",
    "office":   "Product: OFFICE — prefer: bureau, caisson, réglable en hauteur.",
    "textile":  "Product: TEXTILE — prefer: housse, garnissage, lavable.",
    "outdoor":  "Product: OUTDOOR FURNITURE — prefer: salon de jardin, mobilier de jardin, résine tressée, thermolaqué, résistant aux UV, ensemble composé de, module de canapé.",
    "lighting": "Product: LIGHTING — prefer: ampoule incluse, culot E27, intensité réglable.",
    "mattress": (
        "Product: MATTRESS — prefer: matelas à ressorts ensachés, coutil, couche de coco, "
        "fermeture éclair sur 4 côtés, revêtement amovible. "
        "NEVER use 'paillasson' for Kokosmatte — always 'couche de coco'. "
        "Preserve model names exactly (Asely, Arin, etc.)."
    ),
}

_CATEGORY_NL_HINTS: dict[str, str] = {
    "sofa":     "Product: BANK/ZITMEUBEL — prefer: zitting, rugleuning, armleuning, onderstel, schuimvulling, bekleding.",
    "bed":      "Product: BED — prefer: hoofdbord, lattenbodem, bedframe, poten.",
    "table":    "Product: TAFEL — prefer: tafelblad, onderstel, uitschuifbaar, verlengstuk.",
    "wardrobe": "Product: OPBERGEN — prefer: kledingkast, lade, legplank, draaideuren.",
    "kitchen": (
        "Product: KEUKEN — gebruik: keukenblok, inbouwkeuken, werkblad, spoelbak, spoelkast, "
        "onderkast, hangkast, bovenkast, hoge kast, apothekerskast, frontpaneel, plint. "
        "GSP / GSP-Blende / Geschirrspüler-Blende → vaatwasserfront (ALTIJD). "
        "BHT / BxHxT / B x H x T → B x H x D. Grifflos → greeploos. "
        "Unterflurauszug → onderliggende ladegeleider."
    ),
    "bathroom": (
        "Product: BADKAMER — gebruik: wastafelmeubel, wastafel, wastafelonderkast, spiegel, opbergkast. "
        "Einzelwaschtisch → enkele wastafel. Doppelwaschtisch → dubbele wastafel. "
        "Unterflurauszug → onderliggende ladegeleider. Armatur → kraan. "
        "Soft-Close / Softclose → soft-close. Dämpfung → demping."
    ),
    "office":   "Product: KANTOOR — prefer: bureau, ladeblok, in hoogte verstelbaar.",
    "textile":  "Product: TEXTIEL — prefer: hoes, vulling, wasbaar.",
    "outdoor":  "Product: BUITEN — prefer: UV-bestendig, weerbestendig, stapelbaar.",
    "lighting": "Product: VERLICHTING — prefer: lamp inbegrepen, fitting E27, dimbaar.",
    "mattress": (
        "Product: MATRAS — prefer: pocketveringmatras, tijk, kokoslaag, ritssluiting, afneembare hoes. "
        "Preserve model names exactly (Asely, Arin, etc.)."
    ),
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


# =============================================================================
# FURNITURE LOCALIZATION ENGINE
# =============================================================================

# Curated DE→FR furniture term map — applied as fast local pass before/after AI
# Longest entries first within each section so multi-word phrases replace before substrings.
FURNITURE_TERM_MAP_FR: dict[str, str] = {
    # Dimension abbreviations (German → French standard)
    "Breite x Höhe x Tiefe":          "largeur x hauteur x profondeur",
    "B x H x T":                      "L x H x P",
    "BxHxT":                          "L x H x P",
    "BHT":                            "L x H x P",
    # Décor / wood finish — compound forms first
    "Artisan Eiche Dekor":            "décor chêne artisan",
    "Artisan-Eiche-Dekor":            "décor chêne artisan",
    "Eiche Artisan Dekor":            "décor chêne artisan",
    "Artisan Dekor Eiche":            "décor chêne artisan",
    "Eiche Dekor":                    "décor chêne",
    "Dekor Eiche":                    "décor chêne",
    # Seating accessories
    "Fußhocker":                      "repose-pieds",
    "Fusshocker":                     "repose-pieds",
    "Chaiselongue":                   "chaise longue",
    "chaiselongue":                   "chaise longue",
    # Handles / kitchen
    "Grifflos":                       "sans poignées",
    "grifflos":                       "sans poignées",
    "autark":                         "équipée",
    # Drawer runner (French)
    "Unterflurauszug":                "tiroir sous-plancher",
    "Unterflurführung":               "tiroir sous-plancher",
    "Unterflur-Auszug":               "tiroir sous-plancher",
    # Colors
    "Schlamm":                        "argile",
    # Outdoor / garden sets
    "Gartenessgruppe":                "ensemble de jardin",
    "Gartengruppe":                   "salon de jardin",
    "Gartenset":                      "salon de jardin",
    "Loungeset":                      "salon de jardin",
    "Loungesofa":                     "canapé de jardin",
    "Loungesessel":                   "fauteuil de jardin",
    "Terrassenset":                   "ensemble de terrasse",
    "Sofaelement":                    "module de canapé",
    "Sofamodul":                      "module de canapé",
    "Gartenstuhl":                    "chaise de jardin",
    "Gartentisch":                    "table de jardin",
    "Gartenbank":                     "banc de jardin",
    "Gartenliege":                    "chaise longue de jardin",
    "Gartensofa":                     "canapé de jardin",
    "Gartenmöbel":                    "mobilier de jardin",
    "Terrassenmöbel":                 "mobilier de terrasse",
    # Materials / finishes
    "pulverbeschichtet":              "thermolaqué",
    "Pulverbeschichtung":             "revêtement thermolaqué",
    "thermobeschichtet":              "thermolaqué",
    "Geflecht":                       "résine tressée",
    "Kunststoffgeflecht":             "résine tressée",
    "Flechtwerk":                     "résine tressée",
    "Polyrattan":                     "résine tressée",
    "Rattan":                         "rotin",
    # Frame / structure
    "Tischgestell":                   "piètement de table",
    "Untergestell":                   "structure inférieure",
    "Zargen":                         "traverses",
    "Zarge":                          "traverse",
    # Phrases (longest first so multi-word replaces before single words)
    "Set bestehend aus":              "ensemble composé de",
    "bestehend aus":                  "composé de",
    "ohne Dekoration":                "sans décoration",
    "inkl. Dekoration":               "décoration incluse",
    # Adjectives / descriptors
    "Ausziehbar":                     "extensible",
    "Absetzung":                      "bordure contrastante",
    "Abhebung":                       "bordure contrastante",
    "Dekoration":                     "décoration",
    # Mattress / bedding
    "7-Zonen-Taschenfederkernmatratze": "matelas ressorts ensachés 7 zones",
    "9-Zonen-Taschenfederkernmatratze": "matelas ressorts ensachés 9 zones",
    "Taschenfederkernmatratze":       "matelas à ressorts ensachés",
    "Taschenfederkern":               "ressorts ensachés",
    "4-seitiger Reißverschluss":      "fermeture éclair sur 4 côtés",
    "Einseitige Kokosmatte":          "couche de coco sur une face",
    "Abnehmbarer Bezug":              "revêtement amovible",
    "Kokosmatte":                     "couche de coco",
    "Kokosschicht":                   "couche de coco",
    "Doppeltuch":                     "coutil double",
    "Reißverschluss":                 "fermeture éclair",
    "Matratze":                       "matelas",
}

FURNITURE_TERM_MAP_NL: dict[str, str] = {
    # Garden / outdoor
    "Gartenessgruppe":    "tuinset",
    "Gartengruppe":       "tuinset",
    "Gartenset":          "tuinset",
    "Loungeset":          "loungeset",
    "Sofaelement":        "canapémodule",
    "Sofamodul":          "canapémodule",
    "Gartenstuhl":        "tuinstoel",
    "Gartentisch":        "tuintafel",
    "Gartenbank":         "tuinbank",
    "Gartenliege":        "tuinligstoel",
    "Gartenmöbel":        "tuinmeubelen",
    "Terrassenmöbel":     "terrasmeubilair",
    "Terrassenset":       "tuinset",
    "pulverbeschichtet":  "gepoedercoat",
    "Pulverbeschichtung": "poedercoating",
    "Geflecht":           "vlechtwerk",
    "Kunststoffgeflecht": "kunststof vlechtwerk",
    "Polyrattan":         "kunststof vlechtwerk",
    "Rattan":             "rotan",
    "Tischgestell":       "tafelpoten",
    "Untergestell":       "onderframe",
    "Zargen":             "verbindingsstukken",
    "Set bestehend aus":  "set bestaande uit",
    "bestehend aus":      "bestaande uit",
    "ohne Dekoration":    "zonder decoratie",
    "Ausziehbar":         "uitschuifbaar",
    "Absetzung":          "contrasterende rand",
    "Dekoration":         "decoratie",
    # Mattress / bedding
    "7-Zonen-Taschenfederkernmatratze": "7-zones pocketveringmatras",
    "9-Zonen-Taschenfederkernmatratze": "9-zones pocketveringmatras",
    "Taschenfederkernmatratze":         "pocketveringmatras",
    "Taschenfederkern":                 "pocketveringkern",
    "4-seitiger Reißverschluss":        "ritssluiting aan 4 zijden",
    "Einseitige Kokosmatte":            "kokoslaag aan één zijde",
    "Abnehmbarer Bezug":                "afneembare hoes",
    "Kokosmatte":                       "kokoslaag",
    "Kokosschicht":                     "kokoslaag",
    "Doppeltuch":                       "dubbeldoek",
    "Reißverschluss":                   "ritssluiting",
    "Matratze":                         "matras",
    # Dishwasher / GSP — longest compound forms first
    "Geschirrspülerblende":             "vaatwasserfront",
    "Geschirrspüler-Blende":            "vaatwasserfront",
    "Geschirrspüler Blende":            "vaatwasserfront",
    "GSP-Blende":                       "vaatwasserfront",
    "GSP Blende":                       "vaatwasserfront",
    "Geschirrspüler":                   "vaatwasser",
    # Drawer runners — longest first
    "Waschbeckenunterschrank":          "wastafelonderkast",
    "Unterflurführung":                 "onderliggende ladegeleider",
    "Unterflur-Auszug":                 "onderliggende ladegeleider",
    "Unterflurauszug":                  "onderliggende ladegeleider",
    # Dimensions
    "Breite x Höhe x Tiefe":            "breedte x hoogte x diepte",
    "B x H x T":                        "B x H x D",
    "BxHxT":                            "B x H x D",
    "BHT":                              "B x H x D",
    # Handles
    "Grifflos":                         "greeploos",
    # Kitchen furniture — compound forms before simple ones
    "Doppelwaschtisch":                 "dubbele wastafel",
    "Einzelwaschtisch":                 "enkele wastafel",
    "Spülenschrank":                    "spoelkast",
    "Apothekerschrank":                 "apothekerskast",
    "Einbauküche":                      "inbouwkeuken",
    "Küchenzeile":                      "keukenblok",
    "Oberschrank":                      "bovenkast",
    "Hängeschrank":                     "hangkast",
    "Unterschrank":                     "onderkast",
    "Hochschrank":                      "hoge kast",
    "Arbeitsplatte":                    "werkblad",
    "Waschtisch":                       "wastafelmeubel",
    "Waschbecken":                      "wastafel",
    "Schubkasten":                      "lade",
    "Schubladen":                       "lades",
    "Schublade":                        "lade",
    "Auszug":                           "lade",
    "Spüle":                            "spoelbak",
    "Blende":                           "frontpaneel",
    "Korpus":                           "romp",
    "Sockel":                           "plint",
    "Griffe":                           "grepen",
    "Griff":                            "greep",
    # Bathroom fittings
    "Armatur":                          "kraan",
    "Siphon":                           "sifon",
    "Überlauf":                         "overloop",
    "Soft-Close":                       "soft-close",
    "Softclose":                        "soft-close",
    "Dämpfung":                         "demping",
    "Ablage":                           "legplank",
}

# Sorted once by length descending so multi-word phrases replace before substrings
_FURNITURE_TERMS_FR_SORTED = sorted(FURNITURE_TERM_MAP_FR.keys(), key=len, reverse=True)
_FURNITURE_TERMS_NL_SORTED = sorted(FURNITURE_TERM_MAP_NL.keys(), key=len, reverse=True)


def apply_furniture_terms(text: str, target_language: str = "French") -> str:
    """Replace known German furniture terms with target-language equivalents (fast, no API)."""
    if not text:
        return text
    if target_language == "Dutch":
        term_map = FURNITURE_TERM_MAP_NL
        sorted_keys = _FURNITURE_TERMS_NL_SORTED
    else:
        term_map = FURNITURE_TERM_MAP_FR
        sorted_keys = _FURNITURE_TERMS_FR_SORTED

    for de_term in sorted_keys:
        if de_term.lower() not in text.lower():
            continue
        pattern = re.compile(r'(?<!\w)' + re.escape(de_term) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pattern.sub(term_map[de_term], text)
    return text


def auto_learn_glossary_from_source(
    source_texts: list[str],
    glossary: dict,
    target_language: str = "French",
    min_occurrences: int = 2,
) -> list[dict]:
    """
    Scan source texts for known furniture terms not yet in the glossary.
    Returns list of {source_term, target_term, occurrences} dicts for auto-adding.
    """
    term_map = FURNITURE_TERM_MAP_FR if target_language == "French" else FURNITURE_TERM_MAP_NL
    existing_lower = {k.lower() for k in glossary.get("terms", {}).keys()}

    freq: Counter = Counter()
    for text in source_texts:
        if not text:
            continue
        for de_term in term_map:
            if de_term.lower() in existing_lower:
                continue
            if re.search(r'(?<!\w)' + re.escape(de_term) + r'(?!\w)', text, re.IGNORECASE | re.UNICODE):
                freq[de_term] += 1

    learnable = []
    for term, count in freq.most_common():
        if count < min_occurrences:
            continue
        learnable.append({
            "source_term": term,
            "target_term": term_map[term],
            "occurrences": count,
        })
    return learnable


# ── Translation Consistency Engine ────────────────────────────────────────────

# Wrong AI-generated French variants → preferred canonical
CONSISTENCY_VARIANTS_FR: dict[str, str] = {
    # Powder coating wrong variants (longest first)
    "revêtement de poudre":           "thermolaqué",
    "revêtu de poudre":               "thermolaqué",
    "revêtu par poudre":              "thermolaqué",
    "laqué par poudre":               "thermolaqué",
    "traitement en poudre":           "thermolaqué",
    "rotin synthétique":              "résine tressée",
    "rattan synthétique":             "résine tressée",
    "osier synthétique":              "résine tressée",
    "rotin en plastique":             "résine tressée",
    # Composition / set wording
    "ensemble consistant de":         "ensemble composé de",
    "set consistant de":              "ensemble composé de",
    "se compose de":                  "composé de",
    "qui comprend":                   "composé de",
    "contenant":                      "composé de",
    # Tableware
    "assiettes à manger":             "assiettes",
    "assiette à manger":              "assiette",
    # Furniture / product terminology
    "chaiselongue":                   "chaise longue",
    "cuisine autonome":               "cuisine équipée",
    # Color corrections
    "boue":                           "argile",
    # Décor position (wrong word order)
    "chêne artisan décor":            "décor chêne artisan",
    "artisan chêne décor":            "décor chêne artisan",
    "chêne décor artisan":            "décor chêne artisan",
    # Awkward literal phrases
    "table sans revêtement":          "table",
    "décoration non comprise":        "accessoires non inclus",
}

# Wrong AI-generated Dutch variants → preferred canonical
CONSISTENCY_VARIANTS_NL: dict[str, str] = {
    "synthetisch rotan":          "kunststof vlechtwerk",
    "kunststof rotan":            "kunststof vlechtwerk",
    "poedercoating":              "gepoedercoat",
    "bevat":                      "bestaande uit",
    "omvat":                      "bestaande uit",
    # Kitchen/bathroom wrong variants
    "vaatwasser front":           "vaatwasserfront",
    "vaatwasserpaneel":           "vaatwasserfront",
    "lade geleider":              "onderliggende ladegeleider",
    "onderliggende lader":        "onderliggende ladegeleider",
    "breedte x hoogte x diepte":  "B x H x D",
    "zonder greep":               "greeploos",
    "zonder grepen":              "greeploos",
    "gootsteen":                  "spoelbak",
}

_CONSISTENCY_KEYS_FR = sorted(CONSISTENCY_VARIANTS_FR.keys(), key=len, reverse=True)
_CONSISTENCY_KEYS_NL = sorted(CONSISTENCY_VARIANTS_NL.keys(), key=len, reverse=True)


def run_local_consistency_pass(
    results: dict,
    source_lookup: dict,
    glossary: dict,
    target_language: str = "French",
) -> dict:
    """
    Two-stage consistency pass (no API calls):
      Stage 1 — same source → same translation: cells with identical German source
        that received different translations are unified (glossary wins; otherwise
        most-frequent translation wins).
      Stage 2 — hard variant replacement: known wrong AI-generated variants are
        replaced with the preferred term.
    Returns {"corrections": int, "detected": int, "harmonized": int}.
    """
    from collections import defaultdict

    variant_map  = CONSISTENCY_VARIANTS_FR if target_language == "French" else CONSISTENCY_VARIANTS_NL
    sorted_keys  = _CONSISTENCY_KEYS_FR    if target_language == "French" else _CONSISTENCY_KEYS_NL
    glos_terms   = {k.lower(): v for k, v in glossary.get("terms", {}).items()}

    # Stage 1 — group by normalized source text
    src_to_keys: defaultdict = defaultdict(list)
    src_to_translations: defaultdict = defaultdict(list)

    for key, tr in results.items():
        src_text, _ = source_lookup.get(key, ("", "other"))
        if not src_text or not tr:
            continue
        norm = src_text.strip().lower()
        src_to_keys[norm].append(key)
        src_to_translations[norm].append(tr)

    corrections = 0
    detected    = 0
    harmonized  = 0

    for norm_src, translations in src_to_translations.items():
        unique_tr = set(translations)
        if len(unique_tr) <= 1:
            continue
        detected += 1

        canonical = glos_terms.get(norm_src)
        if canonical is None:
            canonical = Counter(translations).most_common(1)[0][0]

        for key in src_to_keys[norm_src]:
            if results[key] != canonical:
                results[key] = canonical
                corrections += 1
        harmonized += 1

    # Stage 2 — hard variant replacement
    for key in list(results.keys()):
        text = results[key]
        if not text:
            continue
        changed = False
        for wrong in sorted_keys:
            if wrong.lower() not in text.lower():
                continue
            pattern = re.compile(
                r'(?<!\w)' + re.escape(wrong) + r'(?!\w)',
                re.IGNORECASE | re.UNICODE,
            )
            new_text = pattern.sub(variant_map[wrong], text)
            if new_text != text:
                text    = new_text
                changed = True
        if changed:
            results[key] = text
            corrections += 1

    return {"corrections": corrections, "detected": detected, "harmonized": harmonized}


# =============================================================================
# FRENCH HOME24 STYLE — SEMANTIC NORMALIZATION
# =============================================================================

# Complex regex patterns for French output that requires rewriting, not just
# word replacement. Applied per-cell after translation and consistency passes.
_FR_SEMANTIC_FIXES: list[tuple[re.Pattern, str]] = [
    # BHT dimension labels still in output after partial translation
    (re.compile(r'\bBHT\b',                    re.IGNORECASE | re.UNICODE), 'L x H x P'),
    (re.compile(r'\bBxHxT\b',                  re.IGNORECASE | re.UNICODE), 'L x H x P'),
    (re.compile(r'\bB\s+x\s+H\s+x\s+T\b',     re.IGNORECASE | re.UNICODE), 'L x H x P'),
    # German dimension words that slipped through
    (re.compile(r'\bBreite\b',                  re.IGNORECASE | re.UNICODE), 'largeur'),
    (re.compile(r'\bH[öo]he\b',                re.IGNORECASE | re.UNICODE), 'hauteur'),
    (re.compile(r'\bTiefe\b',                   re.IGNORECASE | re.UNICODE), 'profondeur'),
    # Chaise longue — must be two words
    (re.compile(r'\bchaiselongue\b',            re.IGNORECASE | re.UNICODE), 'chaise longue'),
    # Tableware: assiette(s) à manger → assiette(s)
    (re.compile(r'\bassiettes?\s+à\s+manger\b', re.IGNORECASE | re.UNICODE), 'assiettes'),
    # German-pattern literal translations → natural French
    (re.compile(r'\bcuisine\s+autonome\b',                       re.IGNORECASE | re.UNICODE), 'cuisine équipée'),
    (re.compile(r'\bset\s+consist(?:ant|e)\s+de\b',              re.IGNORECASE | re.UNICODE), 'ensemble composé de'),
    (re.compile(r'\bensemble\s+consist(?:ant|e)\s+de\b',         re.IGNORECASE | re.UNICODE), 'ensemble composé de'),
    # Powder coating various wrong forms
    (re.compile(r'\brevêtement\s+(?:à\s+la\s+|de\s+|par\s+)?poudre\b', re.IGNORECASE | re.UNICODE), 'thermolaqué'),
    (re.compile(r'\brevêtu\s+(?:à\s+la\s+|de\s+|par\s+)poudre\b',      re.IGNORECASE | re.UNICODE), 'thermolaqué'),
    (re.compile(r'\blaqué\s+(?:à\s+la\s+|de\s+|par\s+)poudre\b',       re.IGNORECASE | re.UNICODE), 'thermolaqué'),
    # Décor position — wrong word order → correct home24.fr order
    (re.compile(r'\bchêne\s+artisan\s+d[eé]cor\b',  re.IGNORECASE | re.UNICODE), 'décor chêne artisan'),
    (re.compile(r'\bartisan\s+chêne\s+d[eé]cor\b',  re.IGNORECASE | re.UNICODE), 'décor chêne artisan'),
    (re.compile(r'\bchêne\s+d[eé]cor\s+artisan\b',  re.IGNORECASE | re.UNICODE), 'décor chêne artisan'),
    (re.compile(r'\bd[eé]cor\s+artisan\s+chêne\b',  re.IGNORECASE | re.UNICODE), 'décor chêne artisan'),
    # Untranslated "Dekor" remaining in French text
    (re.compile(r'\bDekor\b',                        re.UNICODE),                 'décor'),
    # Awkward literal phrase
    (re.compile(r'\btable\s+sans\s+rev[eê]tement\b', re.IGNORECASE | re.UNICODE), 'table'),
    # Color: boue → argile
    (re.compile(r'\bboue\b',                         re.IGNORECASE | re.UNICODE), 'argile'),
]


def apply_french_semantic_normalization(text: str) -> str:
    """
    Convert literal German-pattern translations to natural French e-commerce wording.
    Runs after translation and consistency passes, before typography and capitalisation.
    """
    if not text:
        return text
    for pat, repl in _FR_SEMANTIC_FIXES:
        text = pat.sub(repl, text)
    return re.sub(r'  +', ' ', text)


# =============================================================================
# FRENCH TYPOGRAPHY RULES
# =============================================================================

_TYPO_BR_RE  = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TYPO_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
# Slash between alphabetic words (both sides must start with a letter)
_TYPO_SLASH_RE = re.compile(
    r'(?<=[a-zA-Zéàèùâêîôûëïüçœæ])\s*/\s*(?=[a-zA-Zéàèùâêîôûëïüçœæ])',
    re.UNICODE,
)


def apply_french_typography_rules(text: str) -> str:
    """
    Apply French typography: non-breaking space before ':', spaces around '/'
    in product color/material combinations.
    Preserves URLs, <br> tags, and percentage composition slashes.
    """
    if not text:
        return text

    tokens: dict[str, str] = {}
    counter = [0]

    def _protect(pat: re.Pattern, t: str) -> str:
        def _sub(m: re.Match) -> str:
            k = f'\x00P{counter[0]}\x00'
            counter[0] += 1
            tokens[k] = m.group(0)
            return k
        return pat.sub(_sub, t)

    text = _protect(_TYPO_BR_RE, text)
    text = _protect(_TYPO_URL_RE, text)

    # Colon spacing (French typography: space before and after ':')
    text = re.sub(r'(?<!\s):', ' :', text)    # space before ':'
    text = re.sub(r':(?!\s)',  ': ', text)    # space after ':'

    # Slash spacing: alphabetic / alphabetic → alphabetic / alphabetic
    # Skip when '%' precedes the slash in the same segment (composition context)
    _snapshot = text  # snapshot for context lookup (before slash substitution)

    def _slash_repl(m: re.Match) -> str:
        before_slash = _snapshot[:m.start()]
        last_ph = before_slash.rfind('\x00')
        segment_before = before_slash[last_ph + 1:] if last_ph >= 0 else before_slash
        if '%' in segment_before:
            return m.group(0)
        return ' / '

    text = _TYPO_SLASH_RE.sub(_slash_repl, text)

    # Collapse double spaces created by above rules
    text = re.sub(r'  +', ' ', text).strip()

    for k, v in tokens.items():
        text = text.replace(k, v)

    return text
