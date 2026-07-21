"""
Intelligent product name compression for the FR "name" column.

Replaces blind character-truncation with priority-based compression:
product type and model name are never touched; connector words, then
accessory clauses, then secondary feature words are compressed or
dropped — in that order — until the name fits the character limit.
The "opt." marker (product naming convention) is always preserved.
"""

import re
from dataclasses import dataclass


DEFAULT_LIMIT = 40

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
    "Suspension", "Plafonnier", "Lampe",
    "Meuble vasque", "Meuble TV", "Meuble",
    "Badset", "Meuble de salle de bain",
]
_PRODUCT_TYPES_SORTED = sorted(PRODUCT_TYPES, key=len, reverse=True)

# Model names are almost never in a fixed list — detected by capitalization.
# This set only forces the classification for names we already know about.
KNOWN_MODELS = {
    "Sam", "Forrest", "Paku", "Malia", "Levin", "Nordic", "Vedene", "Arin",
    "Bocca", "Level36", "Asely", "Entry", "Cosy", "Firenze",
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
    "panoramique",
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
# Fixed idioms are self-contained and safe to rewrite unconditionally.
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

# "avec <noun>" -> "<noun>" is only safe to strip when the noun ends the
# clause (end of string, or followed by another connector listing more
# items). If more description follows ("avec tiroirs de rangement"), this
# must NOT fire — the noun still needs its "de rangement" qualifier, which
# the chunk-level accessory pass (Pass 3) handles instead.
_BOUNDED_NOUNS = r"rangements?|tiroirs?|étagères?|commodes?|bureau|coussins?|miroir|éclairage"
_BOUNDED_NOUN_COMPRESSION = re.compile(
    r"\bavec (" + _BOUNDED_NOUNS + r")\b(?=\s*(?:et\b|&|$))", re.IGNORECASE,
)

# "opt." is a Home24 naming-convention marker (optional-accessory flag), not
# descriptive text — it must survive compression intact. Extracted before
# compression and always reattached to the final result.
_OPT_TOKEN_RE = re.compile(r"\bopt\.\s*", re.IGNORECASE)
_OPT_SUFFIX = " opt."

# Strategies that discard real information (as opposed to rewording it) —
# these are the ones a human should double-check before publishing.
_REVIEW_STRATEGIES = {"accessory_removal", "feature_trim", "hard_truncate", "gpt_semantic_rewrite"}


@dataclass
class CompressionResult:
    text: str
    original: str
    original_length: int
    final_length: int
    compressed: bool
    strategy: str
    product_type: str | None = None
    model_name: str | None = None
    removed_segment: str | None = None
    review_recommended: bool = False


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


def _try_candidate(candidate: str, limit: int) -> str | None:
    cleaned = _strip_trailing_junk(_collapse_ws(candidate))
    if cleaned and len(cleaned) <= limit:
        return cleaned
    return None


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


def _assemble(product_type: str | None, zone_tokens: list[str], chunks: list[tuple[str, str]]) -> str:
    pieces = []
    if product_type:
        pieces.append(product_type)
    if zone_tokens:
        pieces.append(" ".join(zone_tokens))
    text = " ".join(p for p in pieces if p)
    for connector, chunk in chunks:
        if chunk:
            text = f"{text} {connector} {chunk}"
    return text


class ProductNameCompressionEngine:
    """Compress a translated product name to fit `limit` chars without
    reducing it to an unfinished-looking fragment, and without ever
    silently losing the "opt." naming-convention marker."""

    def compress(
        self,
        name: str,
        limit: int = DEFAULT_LIMIT,
        gpt_fallback=None,
    ) -> CompressionResult:
        original = name or ""
        text = _basic_clean(original)

        if not text:
            return CompressionResult(text, original, len(original), 0, False, "none")

        if len(text) <= limit:
            return CompressionResult(text, original, len(original), len(text), False, "none")

        has_opt = bool(_OPT_TOKEN_RE.search(text))
        if not has_opt:
            return self._compress_body(text, original, limit, gpt_fallback)

        # Reserve room for " opt." up front, compress the rest, then always
        # reattach it — "opt." is never subject to any compression pass.
        body_source = _collapse_ws(_OPT_TOKEN_RE.sub(" ", text))
        effective_limit = max(limit - len(_OPT_SUFFIX), 1)
        result = self._compress_body(body_source, original, effective_limit, gpt_fallback)

        final_text = _strip_trailing_junk(result.text) + _OPT_SUFFIX
        if len(final_text) > limit:
            budget = max(limit - len(_OPT_SUFFIX), 0)
            trimmed = result.text[:budget].rstrip()
            last_space = trimmed.rfind(" ")
            if last_space > 0:
                trimmed = trimmed[:last_space]
            final_text = (_strip_trailing_junk(trimmed) + _OPT_SUFFIX) if trimmed else _OPT_SUFFIX.strip()

        result.text          = final_text
        result.final_length  = len(final_text)
        result.compressed    = True
        return result

    def _compress_body(
        self, text: str, original: str, limit: int, gpt_fallback,
    ) -> CompressionResult:
        if len(text) <= limit:
            return CompressionResult(text, original, len(_basic_clean(original)), len(text), False, "none")

        product_type, rest = _match_product_type(text)

        # Pass 1 — semantic compression (synonym dictionary), re-parsed
        # afterwards since it can remove connectors entirely.
        compressed_text = _apply_semantic_compressions(text)
        if compressed_text != text:
            candidate = _try_candidate(compressed_text, limit)
            if candidate:
                return self._result(candidate, original, "semantic_compression", product_type)
            text = compressed_text
            product_type, rest = _match_product_type(text)

        zone, chunks = _split_chunks(rest)
        zone_tokens = zone.split(" ") if zone else []
        model_idx = _find_model_index(zone_tokens)
        model_name = zone_tokens[model_idx] if model_idx is not None else None

        # Pass 2 — swap the first connector for a terser "+"
        if chunks:
            swapped = list(chunks)
            first_conn, first_chunk = swapped[0]
            if _strip_accents(first_conn) in {"avec", "et"}:
                swapped[0] = ("+", first_chunk)
                candidate = _try_candidate(_assemble(product_type, zone_tokens, swapped), limit)
                if candidate:
                    return self._result(candidate, original, "connector_compression", product_type, model_name)

        # Pass 3 — categorize accessory chunks (e.g. "tiroirs de rangement" or
        # "commodes & étagère" -> "rangement"). Applied cumulatively across all
        # matching chunks, then checked once, per the multi-pass design.
        working_chunks = list(chunks)
        any_categorized = False
        for i, (connector, chunk_text) in enumerate(working_chunks):
            chunk_words = {
                _strip_accents(w.strip(".,;:")) for w in chunk_text.replace("&", " ").split()
            }
            if chunk_words & STORAGE_WORDS and chunk_text.lower() != "rangement":
                working_chunks[i] = (connector, "rangement")
                any_categorized = True
        # Merge adjacent chunks that both collapsed to the same accessory label.
        merged_chunks: list[tuple[str, str]] = []
        for connector, chunk_text in working_chunks:
            if merged_chunks and merged_chunks[-1][1].lower() == chunk_text.lower():
                continue
            merged_chunks.append((connector, chunk_text))
        working_chunks = merged_chunks
        if any_categorized:
            candidate = _try_candidate(_assemble(product_type, zone_tokens, working_chunks), limit)
            if candidate:
                return self._result(candidate, original, "accessory_compression", product_type, model_name)

        # Pass 4 — drop accessory chunks entirely, lowest priority (last) first.
        # This discards real information, so the dropped text is reported.
        for i in range(len(working_chunks) - 1, -1, -1):
            trimmed_chunks = working_chunks[:i]
            candidate = _try_candidate(_assemble(product_type, zone_tokens, trimmed_chunks), limit)
            if candidate:
                dropped = working_chunks[i:]
                removed = " ".join(f"{c} {t}".strip() for c, t in dropped if t).strip()
                return self._result(
                    candidate, original, "accessory_removal", product_type, model_name,
                    removed_segment=removed or None,
                )
        working_chunks = []

        # Pass 5 — trim secondary feature words from the zone, right to left,
        # never touching the protected model token. Also discards real
        # information, so the dropped words are reported in order.
        trimmed_tokens = list(zone_tokens)
        removed_words: list[str] = []
        i = len(trimmed_tokens) - 1
        while i >= 0:
            if model_idx is None or i != model_idx:
                removed_words.insert(0, trimmed_tokens[i])
                trimmed_tokens.pop(i)
                if model_idx is not None and i < model_idx:
                    model_idx -= 1
                candidate = _try_candidate(_assemble(product_type, trimmed_tokens, []), limit)
                if candidate:
                    return self._result(
                        candidate, original, "feature_trim", product_type, model_name,
                        removed_segment=" ".join(removed_words) or None,
                    )
            i -= 1

        # Pass 6 — GPT semantic rewrite, only reached when product type +
        # model name alone still exceed the limit.
        head_only = _try_candidate(_assemble(product_type, trimmed_tokens, []), 10**6) or text
        if gpt_fallback is not None:
            rewritten = gpt_fallback(original, limit)
            if rewritten:
                candidate = _try_candidate(rewritten, limit)
                if candidate:
                    return self._result(
                        candidate, original, "gpt_semantic_rewrite", product_type, model_name,
                        removed_segment="(rewritten by AI — compare against the original source)",
                    )

        # Pass 7 — absolute last resort: truncate at a word boundary.
        truncated = head_only[:limit]
        last_space = truncated.rfind(" ")
        if last_space > limit * 0.5:
            truncated = truncated[:last_space]
        truncated = _strip_trailing_junk(truncated) or head_only[:limit]
        removed = head_only[len(truncated):].strip(" -:&+,")
        return self._result(
            truncated, original, "hard_truncate", product_type, model_name,
            removed_segment=removed or None,
        )

    @staticmethod
    def _result(
        text: str, original: str, strategy: str,
        product_type: str | None = None, model_name: str | None = None,
        removed_segment: str | None = None,
    ) -> CompressionResult:
        return CompressionResult(
            text=text,
            original=original,
            original_length=len(_basic_clean(original)),
            final_length=len(text),
            compressed=True,
            strategy=strategy,
            product_type=product_type,
            model_name=model_name,
            removed_segment=removed_segment,
            review_recommended=strategy in _REVIEW_STRATEGIES,
        )


def compress_product_name(
    name: str, limit: int = DEFAULT_LIMIT, gpt_fallback=None,
) -> CompressionResult:
    return ProductNameCompressionEngine().compress(name, limit=limit, gpt_fallback=gpt_fallback)
