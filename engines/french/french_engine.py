"""
French (FR) engine — thin wrapper over intelligence.py.
Exposes FR-only API. Never imports anything NL-specific.
"""

from intelligence import (
    FURNITURE_TERM_MAP_FR,
    CONSISTENCY_VARIANTS_FR,
    apply_french_semantic_normalization,
    apply_french_typography_rules,
    apply_forbidden_patterns,
    try_glossary_only,
    try_pattern_translation,
    semantic_tm_match,
    run_local_consistency_pass,
)
from engines.french.french_name_compression import (
    ProductNameCompressionEngine,
    CompressionResult,
)


class FrenchEngine:
    """FR-only translation engine wrapping intelligence.py functions."""

    TARGET_LANGUAGE = "French"

    _name_compression_engine = ProductNameCompressionEngine()

    # ── Product name compression ────────────────────────────────────────────

    def compress_name(self, name: str, limit: int = 40, gpt_fallback=None) -> CompressionResult:
        """Compress a translated product name to fit `limit` chars while
        preserving product type, model name and commercial meaning."""
        return self._name_compression_engine.compress(name, limit=limit, gpt_fallback=gpt_fallback)

    # ── Glossary-based translation ────────────────────────────────────────

    def translate_with_glossary(self, text: str, glossary: dict) -> str | None:
        """Attempt a pure glossary translation. Returns None if not fully covered."""
        return try_glossary_only(text, glossary, self.TARGET_LANGUAGE)

    def translate_with_pattern(self, text: str, glossary: dict) -> str | None:
        """Attempt a pattern/rule-based translation."""
        return try_pattern_translation(text, glossary, self.TARGET_LANGUAGE)

    # ── Consistency ───────────────────────────────────────────────────────

    def apply_consistency(self, text: str, memory: dict | None = None) -> str:
        """Apply FR local consistency pass."""
        return run_local_consistency_pass(text, memory or {}, self.TARGET_LANGUAGE)

    # ── QA / style ────────────────────────────────────────────────────────

    def apply_qa(self, text: str, db_patterns: list | None = None) -> str:
        """Apply forbidden-pattern replacement for FR."""
        if db_patterns:
            return apply_forbidden_patterns(text, db_patterns, self.TARGET_LANGUAGE)
        return text

    def apply_style(self, text: str) -> str:
        """Apply FR semantic normalization + typography rules."""
        text = apply_french_semantic_normalization(text)
        text = apply_french_typography_rules(text)
        return text

    # ── Semantic TM ───────────────────────────────────────────────────────

    def semantic_tm_lookup(self, text: str, tm: dict) -> str | None:
        """Look up FR semantic TM match."""
        return semantic_tm_match(text, tm, self.TARGET_LANGUAGE)

    # ── Term maps ─────────────────────────────────────────────────────────

    @property
    def term_map(self) -> dict:
        return FURNITURE_TERM_MAP_FR

    @property
    def consistency_variants(self) -> dict:
        return CONSISTENCY_VARIANTS_FR
