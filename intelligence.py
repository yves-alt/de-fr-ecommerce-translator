"""
Translation Intelligence Engine
Hybrid pipeline: Normalization → Exact TM → Semantic TM → Glossary-Only → Pattern → GPT
DE→FR only.
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
# GLOSSARY INDEX — O(1) lookups regardless of glossary size
# =============================================================================
# The official Home24 glossary can hold thousands of entries. Scanning
# terms.items() per cell (the original approach) is O(cells × terms) and
# becomes a real bottleneck past a few hundred terms. glossary_index()
# builds a lowercase lookup map once per glossary and caches it on the
# glossary dict itself; glossary_ngram_hits() then finds every matching
# term inside a text in O(text length) instead of O(#terms).

def glossary_index(glossary: dict) -> dict:
    """Return (and cache) {'map': {lower_de: (de, fr)}, 'max_words': int}."""
    terms = glossary.get("terms", {}) or {}
    cache = glossary.get("_index_cache")
    if cache is not None and cache.get("size") == len(terms):
        return cache
    lower_map: dict[str, tuple[str, str]] = {}
    max_words = 1
    for de, fr in terms.items():
        key = normalize_text(de).lower()
        if not key:
            continue
        lower_map[key] = (de, fr)
        wc = key.count(" ") + 1
        if wc > max_words:
            max_words = wc
    cache = {"size": len(terms), "map": lower_map, "max_words": max_words}
    glossary["_index_cache"] = cache
    return cache


_GLOSSARY_TOKEN_RE = re.compile(r"[\wÀ-ÿ'-]+", re.UNICODE)


def glossary_ngram_hits(text: str, glossary: dict) -> dict[str, int]:
    """
    Find every glossary term occurring in `text`, matching multi-word terms
    too (up to the glossary's longest term, in words). O(text length),
    independent of glossary size — safe to call per-cell even with a
    glossary of many thousands of terms.

    Returns {original_de_term: occurrence_count}.
    """
    cache = glossary_index(glossary)
    lower_map = cache["map"]
    if not lower_map:
        return {}
    max_words = cache["max_words"]
    words = _GLOSSARY_TOKEN_RE.findall(text)
    lower_words = [w.lower() for w in words]
    n = len(lower_words)
    hits: dict[str, int] = {}
    for i in range(n):
        for span in range(1, max_words + 1):
            if i + span > n:
                break
            candidate = " ".join(lower_words[i:i + span])
            match = lower_map.get(candidate)
            if match:
                de_original = match[0]
                hits[de_original] = hits.get(de_original, 0) + 1
    return hits


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

    lower_map = glossary_index(glossary)["map"]
    if not lower_map:
        return None

    low = normalize_text(stripped).lower()

    # Exact single-term match
    exact = lower_map.get(low)
    if exact:
        return exact[1]

    # Separator-split compound — every part must resolve
    parts, sep = _split_on_separators(stripped)
    if len(parts) <= 1:
        return None

    translated: list[str] = []
    for part in parts:
        if not part:
            continue
        match = lower_map.get(normalize_text(part).lower())
        if match is None:
            return None
        translated.append(match[1])

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


# Built-in fiber name maps — used as fallback when the glossary has no entry.
# EU standard format: "X % material" (space before %).
_FIBER_NAMES_FR: dict[str, str] = {
    "polyester":    "polyester",
    "baumwolle":    "coton",
    "wolle":        "laine",
    "seide":        "soie",
    "leinen":       "lin",
    "viskose":      "viscose",
    "polyamid":     "polyamide",
    "polypropylen": "polypropylène",
    "acryl":        "acrylique",
    "modacryl":     "modacrylique",
    "elasthan":     "élasthanne",
    "lycra":        "lycra",
    "modal":        "modal",
    "tencel":       "tencel",
    "lyocell":      "lyocell",
    "kokos":        "coco",
    "kokosfaser":   "fibre de coco",
    "gummi":        "caoutchouc",
    "latex":        "latex",
    "jute":         "jute",
    "sisal":        "sisal",
    "hanf":         "chanvre",
    "bambus":       "bambou",
    "nylon":        "nylon",
    "mikrofaser":   "microfibre",
    "chenille":     "chenille",
    "leder":        "cuir",
    "kunstleder":   "similicuir",
    "polyacryl":    "polyacrylique",
    "polyurethan":  "polyuréthane",
}

def _translate_pct_composition(
    text: str,
    glossary: dict,
    target_language: str,
) -> str | None:
    """
    Translate '60 % Baumwolle / 40 % Polyester' using built-in fiber map + glossary.
    Output format: 'X % material' (EU standard — space before %).
    """
    fiber_map = _FIBER_NAMES_FR
    glos_terms = {k.lower(): v.lower() for k, v in glossary.get("terms", {}).items()}

    # Split on comma or slash separators
    parts = re.split(r"\s*[,/]\s*", text)
    out: list[str] = []
    sep = " / " if "/" in text else ", "

    for part in parts:
        m = re.match(r"^(\d+)\s*%\s*(.+)$", part.strip(), re.IGNORECASE)
        if not m:
            return None
        pct, fiber = m.group(1), m.group(2).strip()
        fiber_lo = fiber.lower()

        # Glossary first (user-maintained, highest authority)
        matched = glos_terms.get(fiber_lo)
        # Built-in map as fallback
        if matched is None:
            matched = fiber_map.get(fiber_lo)
        if matched is None:
            return None
        out.append(f"{pct} % {matched}")

    return sep.join(out)


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
    lang_prefix = "fr:"
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

def get_product_type_hint(category: str, target_language: str = "French") -> str:
    """Return a short prompt hint for the detected product category."""
    if category == "generic":
        return ""
    hint = _CATEGORY_FR_HINTS.get(category, "")
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
    # Sofa / seating category — the Home24-preferred translation, not the
    # more literal "canapé d'angle" GPT would otherwise default to
    "Wohnlandschaft":                 "canapé panoramique",
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
    # Carpet / rug product types — compound forms first
    "Hochflorteppich":                "tapis à poils longs",
    "Kurzflorteppich":                "tapis à poils courts",
    "Teppichläufer":                  "tapis de couloir",
    "Kuhfellteppich":                 "tapis en cuir de vache",
    "Sisalteppich":                   "tapis en sisal",
    "Juteteppich":                    "tapis en jute",
    "Naturteppich":                   "tapis naturel",
    "Schaffell":                      "peau de mouton",
    "Kunstfell":                      "fourrure synthétique",
    "Fußmatte":                       "tapis d'entrée",
    "Läufer":                         "chemin de couloir",
    "Teppich":                        "tapis",
    # Textile composition materials
    "Polypropylen":                   "polypropylène",
    "Polyamid":                       "polyamide",
    "Modacryl":                       "modacrylique",
    "Kokosfaser":                     "fibre de coco",
    "Viskose":                        "viscose",
    "Gummi":                          "caoutchouc",
    "Mikrofaser":                     "microfibre",
    # Colors
    "Elfenbein":                      "ivoire",
    "Puderrosa":                      "rose poudré",
    "Blaugrün":                       "bleu-vert",
    "Hellbraun":                      "brun clair",
    "Hellgrün":                       "vert clair",
    "Dunkelgrau":                     "gris foncé",
    "Dunkelblau":                     "bleu foncé",
    "Hellgrau":                       "gris clair",
    "Dunkelgrün":                     "vert foncé",
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

# Sorted once by length descending so multi-word phrases replace before substrings
_FURNITURE_TERMS_FR_SORTED = sorted(FURNITURE_TERM_MAP_FR.keys(), key=len, reverse=True)


def apply_furniture_terms(text: str, target_language: str = "French") -> str:
    """Replace known German furniture terms with French equivalents (fast, no API)."""
    if not text:
        return text
    for de_term in _FURNITURE_TERMS_FR_SORTED:
        if de_term.lower() not in text.lower():
            continue
        pattern = re.compile(r'(?<!\w)' + re.escape(de_term) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pattern.sub(FURNITURE_TERM_MAP_FR[de_term], text)
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
    term_map = FURNITURE_TERM_MAP_FR
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
    # Carpet runners — "couverture" is a common AI mistranslation of "Läufer" (runner rug)
    "couverture de couloir":          "chemin de couloir",
    "tapis couverture":               "chemin de couloir",
    # Textile composition wrong forms
    "couche de coco / caoutchouc":    "coco / caoutchouc",
    "couche de coco":                 "coco",
    # Rug/carpet wrong product type names
    "tapis à haute pile":             "tapis à poils longs",
    "tapis ras":                      "tapis à poils courts",
}

_CONSISTENCY_KEYS_FR = sorted(CONSISTENCY_VARIANTS_FR.keys(), key=len, reverse=True)


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

    variant_map  = CONSISTENCY_VARIANTS_FR
    sorted_keys  = _CONSISTENCY_KEYS_FR
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
    # Carpet runner: "Couverture [CapitalWord NNN]" is a wrong AI translation of "Läufer"
    # Pattern: "Couverture" followed by a proper noun and a 3+ digit product code
    (re.compile(r'\bCouverture\b(?=\s+[A-Z][a-z]+\s+\d{3,})', re.UNICODE),       'Chemin'),
    # Textile composition: normalize spacing to EU standard "X % material"
    (re.compile(r'(\d+)%\s*([a-zéàèùâêîôûëïüçœæ])', re.UNICODE),                r'\1 % \2'),
    # Wrong carpet type names from overly literal AI translation
    (re.compile(r'\btapis\s+à\s+haute?\s+pile\b',    re.IGNORECASE | re.UNICODE), 'tapis à poils longs'),
    (re.compile(r'\btapis\s+ras\b',                  re.IGNORECASE | re.UNICODE), 'tapis à poils courts'),
    (re.compile(r'\btapis\s+de\s+sol\b(?!\s+de\b)',  re.IGNORECASE | re.UNICODE), "tapis d'entrée"),
    # Läufer residue (German not translated)
    (re.compile(r'\bLäufer\b',                        re.IGNORECASE | re.UNICODE), 'Chemin de couloir'),
    # Fußmatte residue
    (re.compile(r'\bFußmatte\b',                      re.IGNORECASE | re.UNICODE), "Tapis d'entrée"),
    (re.compile(r'\bFussmatte\b',                     re.IGNORECASE | re.UNICODE), "Tapis d'entrée"),
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


# =============================================================================
# CONTEXT RECONSTRUCTION ENGINE
# =============================================================================

_CTX_SEATING_KW = frozenset([
    "fauteuil", "canapé", "sofa", "lounge", "sessel", "sitz", "polster",
    "ottomane", "relaxsessel", "schlafsofa", "ecksofa", "couch", "liege",
    "stuhl", "hocker", "sitzelement",
])
_CTX_OUTDOOR_KW = frozenset([
    "garten", "outdoor", "terrasse", "loungeset", "gartenset", "rattan",
    "polyrattan", "geflecht", "kunststoffgeflecht",
])
_CTX_KITCHEN_KW = frozenset([
    "küche", "küchenzeile", "einbauküche", "arbeitsplatte", "unterschrank",
    "hängeschrank", "oberschrank", "hochschrank", "geschirrspüler", "gsp",
    "spüle", "apothekerschrank",
])
_CTX_BATHROOM_KW = frozenset([
    "bad", "waschtisch", "waschbecken", "spiegel", "badmöbel", "badezimmer",
    "spiegelschrank",
])
_CTX_MATTRESS_KW = frozenset([
    "matratze", "taschenfederkern", "kaltschaum", "kokos", "latexmatratze",
    "kaltschaummatratze", "bonellfeder",
])
_CTX_TABLEWARE_KW = frozenset([
    "geschirr", "teller", "schüssel", "besteck", "service", "porzellan",
    "keramik", "geschirrset", "tafelgeschirr",
])
_CTX_TABLE_KW = frozenset([
    "esstisch", "couchtisch", "beistelltisch",
])


def build_row_context(row_data: dict[str, str]) -> dict:
    """
    Build a lightweight context dict from all visible column values in a product row.
    Used for context-aware terminology selection and AI prompt enrichment.
    """
    combined = " ".join(str(v) for v in row_data.values() if v).lower()

    is_seating  = any(kw in combined for kw in _CTX_SEATING_KW)
    is_outdoor  = any(kw in combined for kw in _CTX_OUTDOOR_KW)
    is_kitchen  = any(kw in combined for kw in _CTX_KITCHEN_KW)
    is_bathroom = any(kw in combined for kw in _CTX_BATHROOM_KW)
    is_mattress = any(kw in combined for kw in _CTX_MATTRESS_KW)
    is_tableware= any(kw in combined for kw in _CTX_TABLEWARE_KW)
    is_table    = any(kw in combined for kw in _CTX_TABLE_KW)

    m = re.search(r'\b(\d+)[- ]?(?:teilig|stück|pièces?|pieces?|teile)\b', combined, re.IGNORECASE)
    quantity = int(m.group(1)) if m else None
    is_set = quantity is not None or bool(re.search(
        r'\b(?:set|lot|gruppe|garnitur|komplett)\b', combined, re.IGNORECASE
    ))

    if is_outdoor:
        ptype = "outdoor"
    elif is_kitchen:
        ptype = "kitchen"
    elif is_bathroom:
        ptype = "bathroom"
    elif is_mattress:
        ptype = "mattress"
    elif is_tableware:
        ptype = "tableware"
    elif is_seating:
        ptype = "seating"
    elif is_table:
        ptype = "table"
    else:
        ptype = "generic"

    return {
        "product_type":  ptype,
        "is_seating":    is_seating,
        "is_outdoor":    is_outdoor,
        "is_kitchen":    is_kitchen,
        "is_bathroom":   is_bathroom,
        "is_mattress":   is_mattress,
        "is_tableware":  is_tableware,
        "is_table":      is_table,
        "is_set":        is_set,
        "quantity":      quantity,
    }


# Context-aware disambiguation: DE term → FR choice depending on product_type
_CONTEXT_TERMINOLOGY_FR: dict[str, dict[str, str]] = {
    "fußhocker": {"seating": "repose-pieds", "outdoor": "repose-pieds", "default": "pouf"},
    "fusshocker": {"seating": "repose-pieds", "outdoor": "repose-pieds", "default": "pouf"},
    "bezug": {"mattress": "coutil", "default": "revêtement"},
    "gestell": {"table": "piètement", "default": "structure"},
    "autark": {"kitchen": "équipée", "default": "autonome"},
}


def apply_context_terminology_fr(text: str, context: dict) -> str:
    """Apply context-aware German→French terminology choices to residual German terms."""
    ptype = context.get("product_type", "generic")
    for de_term, variants in _CONTEXT_TERMINOLOGY_FR.items():
        if de_term.lower() not in text.lower():
            continue
        fr_term = variants.get(ptype) or variants.get("default", "")
        if not fr_term:
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(de_term) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pat.sub(fr_term, text)
    return text


def get_context_prompt_hint(context: dict, target_language: str = "French") -> str:
    """Return a short context hint for the AI prompt based on detected row context."""
    if target_language != "French":
        return ""
    ptype = context.get("product_type", "generic")
    hints = {
        "outdoor":   "CONTEXT: Outdoor/garden furniture. Prefer: résine tressée, thermolaqué, repose-pieds, ensemble composé de.",
        "kitchen":   "CONTEXT: Kitchen furniture. Prefer: cuisine équipée, meuble haut, meuble bas, plan de travail, sans poignées.",
        "bathroom":  "CONTEXT: Bathroom. Prefer: meuble vasque, miroir, colonne de rangement, meuble sous-vasque.",
        "mattress":  "CONTEXT: Mattress. Prefer: matelas à ressorts ensachés, coutil, couche de coco, revêtement amovible.",
        "tableware": "CONTEXT: Tableware. Prefer: service de vaisselle, service de table, assiettes. NEVER 'assiettes à manger'.",
        "seating":   "CONTEXT: Seating. Fußhocker → repose-pieds. Prefer: assise, dossier, accoudoir, revêtement.",
        "table":     "CONTEXT: Table. Prefer: table, table extensible, piètement. Use 'table à manger' only if explicitly dining.",
    }
    hint = hints.get(ptype, "")
    return f"\n{hint}" if hint else ""


# =============================================================================
# HOME24 FR CORPUS — Curated style examples by product type
# =============================================================================

HOME24_FR_STYLE_EXAMPLES: dict[str, list[str]] = {
    "tableware": [
        "Service de vaisselle Nature Collection",
        "Assiettes de service — lot de 6",
        "Service de table 18 pièces",
        "Assiettes creuses Nature Collection",
    ],
    "outdoor": [
        "Salon de jardin composé de : 1 canapé, 2 fauteuils et 1 table basse",
        "Ensemble de jardin en résine tressée thermolaquée",
        "Chaise longue de jardin",
        "Repose-pieds assorti au fauteuil lounge",
    ],
    "kitchen": [
        "Cuisine équipée",
        "Meuble haut de cuisine",
        "Cuisine décor chêne artisan",
        "Meuble TV bas lumineux",
    ],
    "mattress": [
        "Matelas à ressorts ensachés 7 zones",
        "Couche de coco sur une face",
        "Revêtement amovible — fermeture éclair sur 4 côtés",
    ],
    "seating": [
        "Canapé 3 places",
        "Fauteuil lounge avec repose-pieds",
        "Revêtement tissu structuré",
    ],
    "materials": [
        "Décor chêne artisan",
        "Imitation chêne artisan",
        "Structure métal thermolaqué",
        "Résine tressée",
    ],
    "bathroom": [
        "Meuble sous-vasque",
        "Colonne de rangement",
        "Miroir de salle de bain",
    ],
}


def get_corpus_style_hint(product_type: str, target_language: str = "French") -> str:
    """
    Return a brief home24.fr style reference for the AI prompt.
    Injected as style guidance to improve output naturalness.
    """
    if target_language != "French":
        return ""
    examples = HOME24_FR_STYLE_EXAMPLES.get(product_type, [])
    if not examples:
        examples = HOME24_FR_STYLE_EXAMPLES.get("materials", [])[:2]
    if not examples:
        return ""
    lines = "\n".join(f"  • {e}" for e in examples[:4])
    return f"\nHome24.fr style reference:\n{lines}"


# =============================================================================
# FORBIDDEN PATTERN APPLICATION
# =============================================================================

def apply_forbidden_patterns(
    text: str,
    patterns: list[dict],
    target_language: str = "French",
) -> tuple[str, int]:
    """
    Apply a list of forbidden pattern dicts (from DB) to the text.
    Returns (corrected_text, number_of_replacements).
    patterns: list of {forbidden_text, replacement_text, severity, auto_replace}
    """
    if not text or not patterns:
        return text, 0

    corrections = 0
    for p in patterns:
        forbidden = p.get("forbidden_text", "")
        replacement = p.get("replacement_text", "")
        if not forbidden or not replacement:
            continue
        if forbidden.lower() not in text.lower():
            continue
        pat = re.compile(
            r'(?<!\w)' + re.escape(forbidden) + r'(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
        new_text = pat.sub(replacement, text)
        if new_text != text:
            text = new_text
            corrections += 1

    return text, corrections
