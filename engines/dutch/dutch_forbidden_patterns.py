"""
Dutch forbidden patterns — extended list (Parts 6 + 7).
"""

import re
from nl_engine import NL_FORBIDDEN_REPLACEMENTS

# Extended NL forbidden rules (superset of NL_FORBIDDEN_REPLACEMENTS + additional entries)
NL_FORBIDDEN_RULES: list[tuple[str, str]] = [
    # Include everything from nl_engine
    *NL_FORBIDDEN_REPLACEMENTS,
    # Additional rules from Part 6/7 not already in nl_engine
    ("zaagsnede",               "grof gezaagde eikenlook"),
    ("Decor",                   "look"),
    ("Badmat",                  "badkuipmat"),    # for Badewannenmatte context
    ("Douchematten",            "douchemat"),
]

# Deduplicate while preserving order (first occurrence wins)
_seen: set[str] = set()
_deduped: list[tuple[str, str]] = []
for _wrong, _right in NL_FORBIDDEN_RULES:
    if _wrong.lower() not in _seen:
        _seen.add(_wrong.lower())
        _deduped.append((_wrong, _right))
NL_FORBIDDEN_RULES = _deduped
del _seen, _deduped, _wrong, _right


def apply_nl_forbidden(text: str) -> str:
    """Apply all NL forbidden pattern replacements."""
    for wrong, right in NL_FORBIDDEN_RULES:
        if wrong.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(wrong) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pat.sub(right, text)
    return text
