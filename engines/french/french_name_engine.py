"""
FrenchProductNameEngine — single source of truth for the DE→FR Home24 "name"
column: terminology protection, 40-character optimization, "opt." handling,
type/variant-designation preservation, final validation and human-review
warning generation.

Replaces engines/french/french_name_compression.py. The pipeline it feeds is
otherwise unchanged: this module only decides what the final French product
name string should be.
"""

import re
from dataclasses import dataclass
from enum import Enum


DEFAULT_LIMIT = 40


# =============================================================================
# COMPONENT VOCABULARY
# =============================================================================

class ProductNameComponent(Enum):
    PRODUCT_TYPE         = "product_type"
    MODEL                = "model"
    TYPE_DESIGNATION     = "type_designation"
    CAPACITY             = "capacity"
    PRIMARY_FUNCTION     = "primary_function"
    ESSENTIAL_CONFIG     = "essential_config"
    PRIMARY_ACCESSORY    = "primary_accessory"
    SECONDARY_ACCESSORY  = "secondary_accessory"
    MATERIAL             = "material"
    OPTIONAL_FEATURE     = "optional_feature"
    CONNECTOR            = "connector"
    FILLER               = "filler"


# =============================================================================
# STATIC VOCABULARY (product types, models, connectors) — unchanged from the
# previous compression engine, extended with the lighting/bollard types seen
# in the Boston/Ossy naming-convention examples.
# =============================================================================

# Longest phrase first so greedy prefix matching picks "Lit mezzanine"
# before falling back to plain "Lit".
PRODUCT_TYPES = [
    "Lit mezzanine", "Lit superposé", "Lit maison", "Lit gigogne", "Lit banquette", "Lit coffre", "Lit",
    "Armoire penderie", "Armoire",
    "Canapé panoramique", "Canapé d'angle", "Canapé convertible", "Canapé de jardin", "Canapé",
    "Bloc cuisine", "Kitchenette", "Cuisine",
    "Table basse", "Table à manger", "Table extensible", "Table de jardin", "Table",
    "Chaise longue", "Chaise de jardin", "Chaise",
    "Fauteuil de jardin", "Fauteuil",
    "Salon de jardin", "Ensemble de jardin", "Mobilier de jardin",
    "Commode", "Étagère", "Bureau", "Matelas", "Tapis", "Banc de jardin", "Banc", "Buffet", "Vitrine",
    "Applique murale", "Applique", "Borne lumineuse", "Borne", "Suspension", "Plafonnier", "Lampadaire", "Lampe",
    "Meuble vasque", "Meuble TV", "Meuble",
    "Badset", "Meuble de salle de bain",
]
_PRODUCT_TYPES_SORTED = sorted(PRODUCT_TYPES, key=len, reverse=True)

# Model names are almost never in a fixed list — detected by capitalization.
# This set only forces the classification for names we already know about.
KNOWN_MODELS = {
    "Sam", "Forrest", "Paku", "Malia", "Levin", "Nordic", "Vedene", "Arin",
    "Bocca", "Level36", "Asely", "Entry", "Cosy", "Firenze",
    "Boston", "Ossy", "Hudson", "Scout",
}

# Capitalized-looking words that are NOT model names — descriptive adjectives,
# materials and colors that GPT sometimes capitalizes.
COMMON_DESCRIPTORS = {
    "massif", "massive", "coulissante", "coulissantes", "extensible", "extensibles",
    "convertible", "convertibles", "rembourre", "rembourree", "rembourres", "rembourrees",
    "matelasse", "matelassee", "capitonne", "capitonnee", "scandinave", "industriel",
    "industrielle", "moderne", "contemporain", "contemporaine", "naturel", "naturelle",
    "chene", "hetre", "bois", "metal", "metallique", "velours", "cuir", "tissu", "rotin",
    "rangement", "rangements", "tiroir", "tiroirs", "commode", "commodes",
    "etagere", "etageres", "miroir", "panier", "paniers", "penderie", "noir", "noire",
    "blanc", "blanche", "gris", "grise", "beige", "taupe", "argile", "terracotta",
    "reversible", "pliant", "pliante", "empilable", "modulable", "angle", "places",
    "panoramique", "type", "capteur", "recamiere", "murale", "lumineuse",
}

STORAGE_WORDS = {
    "commode", "commodes", "etagere", "etageres", "tiroir", "tiroirs",
    "panier", "paniers", "rangement", "rangements", "penderie",
}

# Longest phrase first: word-boundary alternation used to split the name
# into a protected zone and a chain of (connector, accessory) chunks.
# "de/du/des" are deliberately excluded here — they're genitive glue inside
# a clause ("tiroirs de rangement"), not clause separators, so splitting on
# them would tear one accessory in two.
CONNECTORS = [
    "avec des", "y compris", "ainsi que", "avec", "et", "&", "pour", "+",
]
_CONNECTOR_PATTERN = re.compile(
    r"\s+(" + "|".join(re.escape(c) for c in CONNECTORS) + r")\s+", re.IGNORECASE,
)

_FORBIDDEN_TRAILING = {
    "avec", "et", "&", "+", "de", "du", "des", "pour", "mit", "und", "and",
    "sans", "y", "ainsi", "que", "compris", "en", "à", "au", "aux",
    "dans", "sur", "sous", "par", "chez", "le", "la", "les", "un", "une",
}

# Semantic rewrites applied before any word gets dropped — these preserve
# meaning while shortening it, per the "compress, don't cut" principle.
SEMANTIC_COMPRESSIONS = [
    (r"\ben bois massif\b", "massif"),
    (r"\bavec fonction lit\b", "convertible"),
    (r"\bavec rallonge\b", "extensible"),
    (r"\bavec portes coulissantes\b", "coulissante"),
    (r"\bavec porte coulissante\b", "coulissante"),
]
_SEMANTIC_COMPRESSIONS_COMPILED = [
    (re.compile(p, re.IGNORECASE), r) for p, r in SEMANTIC_COMPRESSIONS
]

_BOUNDED_NOUNS = r"rangements?|tiroirs?|étagères?|commodes?|bureau|coussins?|miroir|éclairage"
_BOUNDED_NOUN_COMPRESSION = re.compile(
    r"\bavec (" + _BOUNDED_NOUNS + r")\b(?=\s*(?:et\b|&|$))", re.IGNORECASE,
)


# =============================================================================
# "opt." — Home24 naming-convention marker (Part 3)
# =============================================================================

_OPT_TOKEN_RE       = re.compile(r"\bopt\.\s*", re.IGNORECASE)
_OPT_DUP_OPTION_RE  = re.compile(r"\boption\s+opt\.", re.IGNORECASE)
_OPT_DUP_MARK_RE    = re.compile(r"\bopt\.\s*opt\.", re.IGNORECASE)
_OPT_DUP_DOT_RE     = re.compile(r"\bopt\.\.+", re.IGNORECASE)
_OPT_EXPANDED_RE    = re.compile(r"\ben option\b|\boption\b(?!\s*\.)", re.IGNORECASE)
# Everything from "opt." up to the next top-level connector (or end of
# string) is the optional-feature clause that must travel with the marker.
_OPT_CLAUSE_RE = re.compile(
    r"\bopt\.\s*(?:avec\s+|mit\s+)?(?P<obj>[^,]*?)(?=\s+(?:"
    + "|".join(re.escape(c) for c in CONNECTORS) + r")\b|$)",
    re.IGNORECASE,
)


def normalize_opt_duplicates(text: str) -> str:
    """Part 3.2 — collapse accidental duplication ('option opt.', 'opt. opt.',
    'opt..') down to exactly one clean 'opt.' marker."""
    prev = None
    while prev != text:
        prev = text
        text = _OPT_DUP_OPTION_RE.sub("opt.", text)
        text = _OPT_DUP_MARK_RE.sub("opt.", text)
        text = _OPT_DUP_DOT_RE.sub("opt.", text)
    return _collapse_ws(text)


def normalize_opt_expansion(source: str, text: str) -> str:
    """Part 3.1/3.4 — undo unauthorized expansions ('option', 'en option')
    when the source only ever said the bare 'opt.', and guarantee the
    source-to-target invariant unconditionally: if the source has 'opt.' the
    result always has it too, even if GPT replaced it with something that
    isn't a clean substitution (e.g. a bare 'avec') rather than dropping it
    outright — same safety net the app's existing opt.-preservation already
    relies on for every other column."""
    if not _OPT_TOKEN_RE.search(source or ""):
        return text
    if _OPT_TOKEN_RE.search(text):
        return text
    if _OPT_EXPANDED_RE.search(text):
        text = _collapse_ws(_OPT_EXPANDED_RE.sub("opt.", text, count=1))
        if _OPT_TOKEN_RE.search(text):
            return text
    return text.rstrip() + " opt."


def _extract_opt_clause(text: str) -> tuple[str, str | None]:
    """Return (text_without_opt_clause, opt_clause) where opt_clause is the
    full 'opt. <object>' span including the marker, or None if absent."""
    m = _OPT_CLAUSE_RE.search(text)
    if not m:
        return text, None
    clause = _collapse_ws(text[m.start():m.end()])
    remainder = _collapse_ws(text[:m.start()] + " " + text[m.end():])
    return remainder, clause


def _opt_clause_variants(clause: str) -> list[str]:
    """Compressible forms of an opt. clause, longest/most-informative first.
    'opt. avec capteur' -> ['opt. avec capteur', 'opt. capteur', 'opt.']."""
    if not clause:
        return []
    variants = [clause]
    no_connector = re.sub(r"^\bopt\.\s*(?:avec|et)\s+", "opt. ", clause, flags=re.IGNORECASE)
    no_connector = _collapse_ws(no_connector)
    if no_connector != clause:
        variants.append(no_connector)
    bare = "opt."
    if variants[-1] != bare:
        variants.append(bare)
    return variants


# =============================================================================
# "Typ"/"Type" variant designation (Part 2)
# =============================================================================

_TYPE_DESIGNATION_SRC_RE = re.compile(r"\b(?:Typ|Type)\.?\s*([A-Za-z0-9]{1,3})\b")
_TYPE_DESIGNATION_TGT_RE = re.compile(r"\btype\.?\s*([A-Za-z0-9]{1,3})\b", re.IGNORECASE)
_TRAILING_TYPE_WORD_RE   = re.compile(r"\btype\s+([A-Za-z0-9]{1,3})\b\.?\s*$", re.IGNORECASE)
_BUSINESS_VARIANT_KEYWORDS = ("Variante", "Kombi")


def _detect_type_designation(source: str) -> str | None:
    """Variant letter/number named by the source's 'Typ X' / 'Type X', if any."""
    m = _TYPE_DESIGNATION_SRC_RE.search(source or "")
    return m.group(1) if m else None


def _detect_business_variant_marker(source: str, glossary: dict | None) -> tuple[str, str] | None:
    """'Variante A' / 'Kombi A' style markers — only treated as a protected
    designation when the exact two-word phrase is itself a glossary entry,
    per the spec's 'glossary/business rule requires preserving it' gate."""
    if not glossary:
        return None
    lower_map = glossary_index(glossary).get("map", {})
    for kw in _BUSINESS_VARIANT_KEYWORDS:
        m = re.search(rf"\b{kw}\.?\s*([A-Za-z0-9]{{1,3}})\b", source or "")
        if m and f"{kw.lower()} {m.group(1).lower()}" in lower_map:
            return kw, m.group(1)
    return None


def _variant_letter_present(text: str, letter: str) -> bool:
    """True if the bare variant letter/number still appears as its own token
    (with or without the word 'type' in front of it) — Part 6/9's "variant
    B preserved" criterion, independent of whether the word "type" itself
    survived compression."""
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(letter)}(?![A-Za-z0-9])", text))


def ensure_type_designation_preserved(source: str, translation: str, glossary: dict | None = None) -> str:
    """Part 2 — mirror of the existing opt.-preservation mechanism. GPT
    sometimes drops 'Typ X' entirely during translation (e.g. "Wandleuchte
    Boston Typ A" -> "Applique murale Boston A" loses the word "type", or
    worse, the whole designation vanishes); this restores "type X" so the
    variant that differentiates the SKU is never silently lost. 'type' stays
    lowercase — it is only ever re-inserted at the end of the name, never as
    the first word."""
    if not translation or not source:
        return translation

    letter = _detect_type_designation(source)
    if letter and not _TYPE_DESIGNATION_TGT_RE.search(translation):
        stripped = translation.rstrip()
        trailing_letter = re.search(rf"(?<![A-Za-z0-9]){re.escape(letter)}\s*$", stripped)
        if trailing_letter:
            # bare letter already trails the name ("... Boston A") — the word
            # "type" was dropped in translation; re-insert it right before
            # the letter instead of duplicating the letter at the end.
            translation = stripped[: trailing_letter.start()] + "type " + stripped[trailing_letter.start():]
        else:
            translation = stripped + f" type {letter}"

    variant = _detect_business_variant_marker(source, glossary)
    if variant:
        kw, vletter = variant
        if not re.search(rf"\b{kw}\.?\s*{re.escape(vletter)}\b", translation, re.IGNORECASE):
            translation = translation.rstrip() + f" {kw} {vletter}"

    return translation


# =============================================================================
# GLOSSARY INDEX (local copy of intelligence.py's helper — kept import-free
# so this module has no dependency on the app's intelligence layer; app.py
# already has its own copy wired into the main pipeline).
# =============================================================================

_GLOSSARY_TOKEN_RE = re.compile(r"[\wÀ-ÿ'-]+", re.UNICODE)


def glossary_index(glossary: dict) -> dict:
    terms = (glossary or {}).get("terms", {}) or {}
    cache = (glossary or {}).get("_index_cache")
    if cache is not None and cache.get("size") == len(terms):
        return cache
    lower_map: dict[str, tuple[str, str]] = {}
    max_words = 1
    for de, fr in terms.items():
        key = " ".join(str(de).strip().split()).lower()
        if not key:
            continue
        lower_map[key] = (de, fr)
        wc = key.count(" ") + 1
        if wc > max_words:
            max_words = wc
    cache = {"size": len(terms), "map": lower_map, "max_words": max_words}
    if glossary is not None:
        glossary["_index_cache"] = cache
    return cache


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _strip_accents(word: str) -> str:
    table = str.maketrans("éèêëàâäîïôöùûüç", "eeeeaaaiioouuuc")
    return word.lower().translate(table)


def _collapse_ws(text: str) -> str:
    return " ".join(text.split())


def _basic_clean(name: str) -> str:
    name = _collapse_ws(name)
    name = name.replace(",", "")
    name = re.sub(r"\([^)]*\)", "", name)
    name = name.replace("(", "").replace(")", "")
    name = re.sub(r"\[[^\]]*\]", "", name)
    name = name.replace("[", "").replace("]", "")
    return _collapse_ws(name)


def _strip_trailing_junk(text: str) -> str:
    text = text.strip()
    changed = True
    while changed and text:
        changed = False
        stripped = text.rstrip(" -:&+,")
        if stripped != text:
            text = stripped
            changed = True
            continue
        tokens = text.split(" ")
        if tokens and _strip_accents(tokens[-1].rstrip(".,;:")) in _FORBIDDEN_TRAILING:
            tokens.pop()
            text = " ".join(tokens)
            changed = True
    return text.strip()


def _match_product_type(text: str) -> tuple[str | None, str]:
    for pt in _PRODUCT_TYPES_SORTED:
        if text == pt:
            return text, ""
        if text.lower().startswith(pt.lower() + " "):
            return text[: len(pt)], text[len(pt):].lstrip()
    return None, text


def _find_model_index(tokens: list[str]) -> int | None:
    for i, tok in enumerate(tokens):
        bare = tok.rstrip(".,;:")
        if not bare or bare.isdigit():
            continue
        if bare in KNOWN_MODELS:
            return i
        if bare[0].isupper() and _strip_accents(bare) not in COMMON_DESCRIPTORS and len(bare) > 1:
            return i
    return None


def _split_chunks(text: str) -> tuple[str, list[tuple[str, str]]]:
    if not text:
        return "", []
    parts = _CONNECTOR_PATTERN.split(text)
    zone = parts[0].strip()
    chunks = list(zip(parts[1::2], parts[2::2]))
    return zone, [(c, t.strip()) for c, t in chunks]


def _apply_semantic_compressions(text: str) -> str:
    for pattern, replacement in _SEMANTIC_COMPRESSIONS_COMPILED:
        text = pattern.sub(replacement, text)
    text = _BOUNDED_NOUN_COMPRESSION.sub(r"\1", text)
    return _collapse_ws(text)


def _assemble(product_type: str | None, zone_tokens: list[str], chunks: list[tuple[str, str]],
              opt_clause: str | None = None, opt_position: str = "after_zone") -> str:
    pieces = []
    if product_type:
        pieces.append(product_type)
    if zone_tokens:
        pieces.append(" ".join(zone_tokens))
    text = " ".join(p for p in pieces if p)
    if opt_clause and opt_position == "after_zone":
        text = f"{text} {opt_clause}".strip()
    for connector, chunk in chunks:
        if chunk:
            text = f"{text} {connector} {chunk}"
    if opt_clause and opt_position == "end":
        text = f"{text} {opt_clause}".strip()
    return _collapse_ws(text)


# =============================================================================
# ENDING VALIDATION (Part 8)
# =============================================================================

def validate_french_name_ending(text: str) -> tuple[bool, str | None]:
    """Reject a French product name that ends on an incomplete/dangling
    element. Context matters: 'type A' is complete, bare 'type' is not;
    'opt. capteur' is complete, bare 'opt.' is not."""
    if not text or not text.strip():
        return False, "empty name"

    stripped = text.strip()

    if _OPT_DUP_MARK_RE.search(stripped) or _OPT_DUP_OPTION_RE.search(stripped):
        return False, "duplicated opt. marker"
    if _OPT_DUP_DOT_RE.search(stripped):
        return False, "doubled punctuation after opt."
    if stripped.count("(") != stripped.count(")") or stripped.count("[") != stripped.count("]"):
        return False, "unmatched brackets"
    if re.search(r"\.{2,}\s*$", stripped) or stripped.endswith("…"):
        return False, "trailing ellipsis"
    if re.search(r"[\-:&+/,]\s*$", stripped):
        return False, "trailing separator"

    tokens = stripped.split(" ")
    last = tokens[-1].rstrip(".,;:")

    if re.fullmatch(r"opt\.?", last, re.IGNORECASE):
        return False, 'name ends on a dangling "opt." with no referenced feature'
    if _strip_accents(last) == "type":
        return False, 'name ends on "type" with no variant letter'
    if _strip_accents(last) in _FORBIDDEN_TRAILING:
        return False, f'name ends on an incomplete connector ("{tokens[-1]}")'

    return True, None


# =============================================================================
# CANDIDATE GENERATION + SCORING (Parts 4–9)
# =============================================================================

@dataclass
class NameCandidate:
    text: str
    strategy: str
    removed_segment: str | None = None
    removed_concept: str | None = None


@dataclass
class NameResult:
    text: str
    original: str
    original_length: int
    final_length: int
    compressed: bool
    strategy: str
    product_type: str | None = None
    model_name: str | None = None
    type_designation: str | None = None
    removed_segment: str | None = None
    removed_concept: str | None = None
    review_recommended: bool = False
    severity: str = "Medium"
    reason: str | None = None


# Strategies that discard real information (as opposed to rewording it) —
# these are the ones a human should double-check before publishing.
_REVIEW_STRATEGIES = {
    "accessory_removal", "feature_trim", "hard_truncate",
    "gpt_semantic_rewrite", "opt_object_removal",
}
_CRITICAL_STRATEGIES = {"hard_truncate", "opt_object_removal"}


class FrenchProductNameEngine:
    """Single source of truth for DE→FR product-name terminology, 40-char
    optimization and final validation (spec Parts 1–11)."""

    def process(
        self,
        source: str,
        translation: str,
        limit: int = DEFAULT_LIMIT,
        glossary: dict | None = None,
        gpt_fallback=None,
    ) -> NameResult:
        original = translation or ""
        text = original

        # Step 1 — recover information the translation step may have dropped
        # or corrupted, before any compression is considered.
        text = normalize_opt_expansion(source or "", text)
        text = normalize_opt_duplicates(text)
        text = ensure_type_designation_preserved(source or "", text, glossary)
        text = normalize_opt_duplicates(text)  # re-insertion can't itself duplicate, but stay safe
        text = _basic_clean(text)

        letter = _detect_type_designation(source or "")

        if not text:
            return NameResult(text, original, len(original), 0, False, "none")

        valid_ending, ending_reason = validate_french_name_ending(text)
        if len(text) <= limit and valid_ending:
            return NameResult(
                text, original, len(_basic_clean(original)), len(text), text != original,
                "none" if text == original else "recovery_normalization",
                type_designation=letter,
            )

        return self._compress(text, original, limit, glossary, gpt_fallback, letter)

    # -- internals ------------------------------------------------------

    def _compress(
        self, text: str, original: str, limit: int, glossary: dict | None,
        gpt_fallback, letter: str | None,
    ) -> NameResult:
        has_opt = bool(_OPT_TOKEN_RE.search(text))
        body, opt_clause = _extract_opt_clause(text) if has_opt else (text, None)

        candidates = self._generate_candidates(body, limit, opt_clause, gpt_fallback)

        valid = []
        for cand in candidates:
            ok, _reason = validate_french_name_ending(cand.text)
            if not ok or len(cand.text) > limit:
                continue
            if has_opt and not _OPT_TOKEN_RE.search(cand.text):
                continue  # opt. invariant: never silently dropped
            if letter and not _variant_letter_present(cand.text, letter) and cand.strategy != "hard_truncate":
                continue  # source variant must survive unless truly unavoidable
            valid.append(cand)

        if valid:
            best = max(valid, key=lambda c: self._score(c, text, limit, glossary, letter, has_opt))
        else:
            best = self._hard_truncate(text, limit, opt_clause)

        product_type, _ = _match_product_type(body)
        zone, _ = _split_chunks(_match_product_type(body)[1])
        model_idx = _find_model_index(zone.split(" ")) if zone else None
        model_name = zone.split(" ")[model_idx] if (zone and model_idx is not None) else None

        review = best.strategy in _REVIEW_STRATEGIES
        severity = "Critical" if best.strategy in _CRITICAL_STRATEGIES else "Medium"
        if letter and not _variant_letter_present(best.text, letter):
            severity = "Critical"
            review = True

        return NameResult(
            text=best.text,
            original=original,
            original_length=len(_basic_clean(original)),
            final_length=len(best.text),
            compressed=True,
            strategy=best.strategy,
            product_type=product_type,
            model_name=model_name,
            type_designation=letter,
            removed_segment=best.removed_segment,
            removed_concept=best.removed_concept,
            review_recommended=review,
            severity=severity,
            reason=self._reason_for(best),
        )

    def _generate_candidates(
        self, body: str, limit: int, opt_clause: str | None, gpt_fallback,
    ) -> list[NameCandidate]:
        effective_limit = limit
        if opt_clause:
            # reserve room for the shortest opt. form so downstream strategies
            # know roughly what budget they're working with
            effective_limit = max(limit - len(" opt."), 1)

        candidates: list[NameCandidate] = []

        def add(body_text: str, strategy: str, removed_segment=None, removed_concept=None,
                opt_variant: str | None = None):
            oc = opt_variant if opt_variant is not None else opt_clause
            full = _assemble(*self._split_for_assembly(body_text), opt_clause=oc)
            full = _strip_trailing_junk(_collapse_ws(full))
            if full:
                candidates.append(NameCandidate(full, strategy, removed_segment, removed_concept))

        # 0. as-is (post semantic compression), every opt. clause variant
        opt_variants = _opt_clause_variants(opt_clause) if opt_clause else [None]

        semantic_body = _apply_semantic_compressions(body)
        for ov in opt_variants:
            removed = None if ov == opt_clause else (
                "opt. object wording" if ov not in (None, "opt.") else "optional-feature object"
            )
            add(semantic_body, "semantic_compression" if semantic_body != body else "none",
                removed_concept=(None if ov == opt_clause else "opt. object"), opt_variant=ov)

        product_type, rest = _match_product_type(semantic_body)
        zone, chunks = _split_chunks(rest)
        zone_tokens = zone.split(" ") if zone else []
        model_idx = _find_model_index(zone_tokens)

        # 1. drop the word "type" but keep the bare variant letter — Part 6:
        # wording is compressible, the differentiating letter is not.
        for ov in opt_variants:
            m = _TRAILING_TYPE_WORD_RE.search(zone)
            if m:
                shrunk_zone = _TRAILING_TYPE_WORD_RE.sub(m.group(1), zone)
                add(_assemble_body(product_type, shrunk_zone, chunks), "type_word_compression",
                    removed_segment="type", opt_variant=ov)

        # 2. shorten the first connector — either swap it for "+" or drop it
        # entirely (chunk text lands directly after the zone). Both keep the
        # accessory itself intact; only the joining word is compressed.
        if chunks:
            first_conn, first_chunk = chunks[0]
            if _strip_accents(first_conn) in {"avec", "et"}:
                for ov in opt_variants:
                    swapped = [("+", first_chunk)] + list(chunks[1:])
                    add(_assemble_body(product_type, zone, swapped), "connector_compression", opt_variant=ov)
                for ov in opt_variants:
                    dropped_conn = [("", first_chunk)] + list(chunks[1:])
                    add(_assemble_body(product_type, zone, dropped_conn), "connector_removal", opt_variant=ov)

        # 3. categorize accessory chunks -> "rangement"
        working_chunks = list(chunks)
        any_categorized = False
        for i, (connector, chunk_text) in enumerate(working_chunks):
            chunk_words = {
                _strip_accents(w.strip(".,;:")) for w in chunk_text.replace("&", " ").split()
            }
            if chunk_words & STORAGE_WORDS and chunk_text.lower() != "rangement":
                working_chunks[i] = (connector, "rangement")
                any_categorized = True
        merged_chunks: list[tuple[str, str]] = []
        for connector, chunk_text in working_chunks:
            if merged_chunks and merged_chunks[-1][1].lower() == chunk_text.lower():
                continue
            merged_chunks.append((connector, chunk_text))
        working_chunks = merged_chunks
        if any_categorized:
            for ov in opt_variants:
                add(_assemble_body(product_type, zone, working_chunks), "accessory_compression", opt_variant=ov)

        # 4. drop accessory chunks one at a time from the end — every drop
        # point is offered as its own candidate so scoring (not "first fit")
        # picks which accessory survives.
        for i in range(len(working_chunks) - 1, -1, -1):
            trimmed_chunks = working_chunks[:i]
            dropped = working_chunks[i:]
            removed = " ".join(f"{c} {t}".strip() for c, t in dropped if t).strip()
            for ov in opt_variants:
                add(_assemble_body(product_type, zone, trimmed_chunks), "accessory_removal",
                    removed_segment=removed or None, opt_variant=ov)

        # 5. trim secondary feature words from the zone, right to left, never
        # the protected model token — every trim depth offered as a candidate.
        trimmed_tokens = list(zone_tokens)
        removed_words: list[str] = []
        idx = len(trimmed_tokens) - 1
        cur_model_idx = model_idx
        while idx >= 0:
            if cur_model_idx is None or idx != cur_model_idx:
                removed_words.insert(0, trimmed_tokens[idx])
                trimmed_tokens.pop(idx)
                if cur_model_idx is not None and idx < cur_model_idx:
                    cur_model_idx -= 1
                for ov in opt_variants:
                    add(_assemble_body(product_type, " ".join(trimmed_tokens), working_chunks), "feature_trim",
                        removed_segment=" ".join(removed_words) or None, opt_variant=ov)
            idx -= 1

        # 5b. combine: trim the zone AND drop the accessory chunk(s) — the
        # true last-resort before hard truncation, offered explicitly rather
        # than assumed, so scoring can still prefer it over hard_truncate
        # when the accessory genuinely can't be kept within the limit.
        if working_chunks:
            for ov in opt_variants:
                add(_assemble_body(product_type, " ".join(trimmed_tokens), []), "feature_trim",
                    removed_segment=(" ".join(removed_words) + " " +
                                      " ".join(f"{c} {t}".strip() for c, t in working_chunks if t)).strip() or None,
                    opt_variant=ov)

        # 6. GPT semantic rewrite — only offered when local strategies alone
        # cannot fit product type + model within the limit.
        if gpt_fallback is not None:
            head_only = _assemble_body(product_type, " ".join(trimmed_tokens), [])
            rewritten = gpt_fallback(body, effective_limit)
            if rewritten:
                for ov in opt_variants:
                    add(rewritten, "gpt_semantic_rewrite",
                        removed_segment="(rewritten by AI — compare against the original source)",
                        opt_variant=ov)

        return candidates

    @staticmethod
    def _split_for_assembly(body_text: str) -> tuple[str | None, list[str], list[tuple[str, str]]]:
        product_type, rest = _match_product_type(body_text)
        zone, chunks = _split_chunks(rest)
        zone_tokens = zone.split(" ") if zone else []
        return product_type, zone_tokens, chunks

    def _score(self, cand: NameCandidate, pre_compression_body: str, limit: int,
               glossary: dict | None, letter: str | None, has_opt: bool) -> float:
        score = 0.0
        text = cand.text

        # mild length-headroom preference — a tiebreaker, not the driver
        score += (limit - len(text)) * 0.1

        product_type, _ = _match_product_type(pre_compression_body)
        if product_type and text.lower().startswith(product_type.lower()):
            score += 30
        elif not product_type:
            score += 15  # nothing to preserve, don't penalize

        if letter and _variant_letter_present(text, letter):
            score += 25
            if _TRAILING_TYPE_WORD_RE.search(text):
                score += 3  # slight bonus for keeping the word "type" too

        if has_opt:
            if _OPT_TOKEN_RE.search(text):
                score += 15
                # opt. clause still has an object beyond the bare marker
                if not re.search(r"\bopt\.\s*$", text, re.IGNORECASE):
                    score += 10

        if glossary:
            lower_map = glossary_index(glossary).get("map", {})
            hits = sum(1 for _de, (_de2, fr) in lower_map.items() if fr and fr.lower() in text.lower())
            score += min(hits, 3) * 3

        if cand.removed_segment:
            score -= 3 * len(cand.removed_segment.split())

        strategy_penalty = {
            "none": 0, "semantic_compression": 0, "type_word_compression": 1,
            "connector_compression": 2, "connector_removal": 2, "accessory_compression": 3,
            "accessory_removal": 12, "feature_trim": 15,
            "gpt_semantic_rewrite": 10, "hard_truncate": 30, "opt_object_removal": 25,
        }
        score -= strategy_penalty.get(cand.strategy, 5)

        if re.search(r"\s{2,}", text) or text != text.strip():
            score -= 5  # naturalness

        return score

    def _hard_truncate(self, body: str, limit: int, opt_clause: str | None) -> NameCandidate:
        """Absolute last resort — always produces *something* structurally
        valid (Part 8: a name must never end on a dangling "opt."), always
        flagged Critical for human review. Tries head + "opt." + at least
        one object word first; only drops the optional-feature marker
        entirely when there is truly no room left for it plus any content —
        a bare trailing "opt." is never an acceptable output, per Part 3.3."""
        head_only = body

        if opt_clause:
            rest = opt_clause[len("opt."):].strip()
            first_word = rest.split(" ")[0] if rest else ""
            if first_word:
                trailer = f"opt. {first_word}"
                budget = max(limit - len(" " + trailer), 0)
                truncated = _truncate_at_word(head_only, budget)
                if truncated:
                    candidate_text = _collapse_ws(f"{truncated} {trailer}")
                    if len(candidate_text) <= limit:
                        ok, _ = validate_french_name_ending(candidate_text)
                        if ok:
                            removed = head_only[len(truncated):].strip(" -:&+,")
                            return NameCandidate(
                                candidate_text, "hard_truncate", removed_segment=removed or None,
                            )

        # opt. (and its object) cannot be fit at all — drop it entirely
        # rather than leave a dangling marker.
        truncated = _truncate_at_word(head_only, limit)
        if len(truncated) > limit:
            truncated = truncated[:limit].rstrip()
        strategy = "opt_object_removal" if opt_clause else "hard_truncate"
        removed = head_only[len(truncated):].strip(" -:&+,")
        return NameCandidate(
            truncated, strategy,
            removed_segment=removed or (opt_clause or None),
            removed_concept="entire optional-feature marker (opt.)" if opt_clause else None,
        )

    @staticmethod
    def _reason_for(cand: NameCandidate) -> str:
        labels = {
            "none": "No compression required.",
            "recovery_normalization": "Translation was corrected to restore dropped terminology (opt./type designation).",
            "semantic_compression": "Rewritten using an approved shorter synonym.",
            "type_word_compression": 'The word "type" was dropped; the variant letter was kept.',
            "connector_compression": "Connector word shortened.",
            "connector_removal": "Connector word dropped; the accessory it introduced was kept.",
            "accessory_compression": "Accessory wording generalized to an approved category term.",
            "accessory_removal": "An accessory clause was removed to fit the 40-character limit.",
            "feature_trim": "Secondary descriptive wording was removed to fit the 40-character limit.",
            "gpt_semantic_rewrite": "Rewritten by AI to fit the 40-character limit.",
            "hard_truncate": "Emergency fallback: name was truncated because no valid shorter candidate could be built.",
            "opt_object_removal": "Emergency fallback: the optional-feature object had to be dropped; only \"opt.\" survives.",
        }
        return labels.get(cand.strategy, "Name was compressed.")


def _truncate_at_word(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    t = text[:budget]
    last_space = t.rfind(" ")
    if last_space > budget * 0.5:
        t = t[:last_space]
    return _strip_trailing_junk(t)


def _assemble_body(product_type: str | None, zone: str, chunks: list[tuple[str, str]]) -> str:
    zone_tokens = zone.split(" ") if zone else []
    return _assemble(product_type, zone_tokens, chunks)


# =============================================================================
# BACKWARD-COMPATIBLE ENTRY POINT
# =============================================================================

def process_product_name(
    source: str, translation: str, limit: int = DEFAULT_LIMIT,
    glossary: dict | None = None, gpt_fallback=None,
) -> NameResult:
    return FrenchProductNameEngine().process(
        source, translation, limit=limit, glossary=glossary, gpt_fallback=gpt_fallback,
    )


# Public aliases for consumers outside this module (e.g. the live-edit
# validator in app.py) that only need the detection primitives, not the
# full engine.
detect_type_designation = _detect_type_designation
variant_letter_present  = _variant_letter_present
