"""
French style application — wraps intelligence.py FR style functions.
"""

from intelligence import (
    apply_french_semantic_normalization,
    apply_french_typography_rules,
)


def apply_fr_style(text: str) -> str:
    """
    Apply FR semantic normalization + typography rules.
    Wrapper over the intelligence.py functions.
    """
    text = apply_french_semantic_normalization(text)
    text = apply_french_typography_rules(text)
    return text
