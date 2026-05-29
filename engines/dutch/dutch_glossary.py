"""
Dutch dedicated glossary module.
Uses the separate dutch_glossary_terms DB table — never mixes with French glossary.
"""

import re
from difflib import SequenceMatcher
from database import (
    db_dutch_glossary_load_all,
    db_dutch_glossary_lookup,
    db_dutch_glossary_fuzzy_lookup,
    db_dutch_glossary_import_excel,
)


def load_nl_glossary() -> list[dict]:
    """Load all active Dutch glossary terms from dutch_glossary_terms table."""
    return db_dutch_glossary_load_all(active_only=True)


def lookup_nl_term(source_term: str) -> str | None:
    """
    Exact-match lookup (case-insensitive) in the Dutch glossary.
    Returns the Dutch target or None.
    """
    return db_dutch_glossary_lookup(source_term)


def fuzzy_lookup_nl_term(source_term: str, threshold: float = 0.85) -> str | None:
    """
    Fuzzy lookup in the Dutch glossary using SequenceMatcher.
    Returns the best Dutch target above the threshold or None.
    """
    return db_dutch_glossary_fuzzy_lookup(source_term, threshold)


def import_nl_glossary_excel(path: str) -> tuple[int, int]:
    """
    Parse the DE→NL glossary Excel file and import into dutch_glossary_terms.
    Returns (imported, skipped).
    """
    return db_dutch_glossary_import_excel(path)


# =============================================================================
# GLOSSARY EXTRACTOR — derives term pairs from TM entries
# =============================================================================

_PROPRIETARY_NAMES = frozenset({
    "groove", "hudson", "manchester", "morteens", "natura", "lofta",
})

_UNITS_RE = re.compile(r'\d+\s*(?:cm|mm|m|kg|g|l|ml|st|pcs)\b', re.IGNORECASE)
_DIGITS_ONLY_RE = re.compile(r'^\d+$')
_PUNCT_ONLY_RE = re.compile(r'^[^\w]+$', re.UNICODE)
_PAREN_RE = re.compile(r'\(([^)]+)\)')

_DELIMITERS = re.compile(
    r'<br>|&lt;br&gt;|(?<!\w)/(?!\w)|,\s+|\s+-\s+',
    re.IGNORECASE,
)


def _split_chunks(text: str) -> list[str]:
    """Split text on BR/slash/comma-space/space-hyphen-space delimiters."""
    chunks = _DELIMITERS.split(text)
    result = []
    for chunk in chunks:
        chunk = chunk.strip()
        if chunk:
            result.append(chunk)
    return result


def _is_valid_chunk(chunk: str) -> bool:
    """Return True if the chunk is usable as a glossary term."""
    if len(chunk) < 2:
        return False
    if _DIGITS_ONLY_RE.match(chunk):
        return False
    if _PUNCT_ONLY_RE.match(chunk):
        return False
    if _UNITS_RE.search(chunk):
        return False
    if chunk.lower() in _PROPRIETARY_NAMES:
        return False
    if any(name in chunk.lower() for name in _PROPRIETARY_NAMES):
        return False
    return True


def _extract_parens(text: str) -> list[str]:
    """Extract content of parentheses as standalone segments."""
    return [m.group(1).strip() for m in _PAREN_RE.finditer(text) if m.group(1).strip()]


class NLGlossaryExtractor:
    """Extracts DE→NL term pairs from TM entries."""

    def extract_from_tm_entries(self, entries: list[dict]) -> list[dict]:
        """
        entries: list of {"source": str, "target": str}
        Returns: list of {"source_term_de": str, "target_term_nl": str, "frequency": int}
        """
        freq: dict[tuple[str, str], int] = {}
        multi_nl: dict[str, list[str]] = {}

        for entry in entries:
            src = str(entry.get("source", "")).strip()
            tgt = str(entry.get("target", "")).strip()
            if not src or not tgt:
                continue

            # Extract parenthesized segments as candidates too
            src_parens = _extract_parens(src)
            tgt_parens = _extract_parens(tgt)

            # Split both on delimiters
            de_chunks = _split_chunks(src)
            nl_chunks = _split_chunks(tgt)

            # Only map if counts are equal
            if len(de_chunks) == len(nl_chunks) and len(de_chunks) > 0:
                for de, nl in zip(de_chunks, nl_chunks):
                    de = de.strip()
                    nl = nl.strip()
                    if not _is_valid_chunk(de) or not _is_valid_chunk(nl):
                        continue
                    # German: max 3 words; Dutch: max 4 words
                    if len(de.split()) > 3 or len(nl.split()) > 4:
                        continue
                    # German nouns: capitalize first letter
                    de_norm = de[0].upper() + de[1:] if de else de
                    # Dutch: lowercase unless appears to be proper noun
                    nl_norm = nl[0].lower() + nl[1:] if nl and nl[0].isupper() else nl
                    pair = (de_norm, nl_norm)
                    freq[pair] = freq.get(pair, 0) + 1
                    multi_nl.setdefault(de_norm, []).append(nl_norm)

            # Parenthesized extras
            if len(src_parens) == len(tgt_parens):
                for de, nl in zip(src_parens, tgt_parens):
                    if not _is_valid_chunk(de) or not _is_valid_chunk(nl):
                        continue
                    if len(de.split()) > 3 or len(nl.split()) > 4:
                        continue
                    de_norm = de[0].upper() + de[1:] if de else de
                    nl_norm = nl[0].lower() + nl[1:] if nl and nl[0].isupper() else nl
                    pair = (de_norm, nl_norm)
                    freq[pair] = freq.get(pair, 0) + 1

        # For German terms with multiple Dutch translations, pick highest frequency
        best: dict[str, tuple[str, int]] = {}
        for (de, nl), count in freq.items():
            if de not in best or count > best[de][1]:
                best[de] = (nl, count)

        result = []
        for de, (nl, count) in sorted(best.items(), key=lambda x: -x[1][1]):
            result.append({
                "source_term_de": de,
                "target_term_nl": nl,
                "frequency":      count,
            })
        return result
