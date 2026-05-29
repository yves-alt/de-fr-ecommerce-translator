"""
Dutch (NL) engine wrapper.
Imports ONLY from nl_engine.py and engines/dutch/dutch_glossary.py.
Never imports French code.
"""

from nl_engine import (
    Home24DutchCorpusEngine,
    nl_post_process,
    nl_qa_check,
    apply_nl_dekor_patterns,
    apply_nl_color_normalization,
    apply_nl_furniture_canonical,
    apply_nl_forbidden_patterns,
    apply_nl_format_normalization,
)
from engines.dutch.dutch_glossary import lookup_nl_term, fuzzy_lookup_nl_term


class DutchEngine:
    """
    NL engine wrapper around Home24DutchCorpusEngine.
    Provides glossary-first lookup before delegating to corpus engine.
    """

    def __init__(self, corpus_engine: Home24DutchCorpusEngine | None = None) -> None:
        self._corpus = corpus_engine

    # ── Glossary-first translation ────────────────────────────────────────

    def translate_with_glossary(self, source: str, glossary: list[dict] | None = None) -> str | None:
        """
        Priority:
          1. Exact match in dutch_glossary_terms DB
          2. Fuzzy match in dutch_glossary_terms DB (≥0.85)
          3. Corpus engine exact match
          4. None (caller falls back to AI)
        """
        # 1. DB exact match
        exact = lookup_nl_term(source)
        if exact:
            return nl_post_process(exact)

        # 2. DB fuzzy match
        fuzzy = fuzzy_lookup_nl_term(source, threshold=0.85)
        if fuzzy:
            return nl_post_process(fuzzy)

        # 3. Corpus exact match
        if self._corpus:
            corpus_exact = self._corpus.exact_match(source)
            if corpus_exact:
                return nl_post_process(corpus_exact)

        return None

    # ── Post-processing ───────────────────────────────────────────────────

    def apply_post_process(self, text: str, canonical: str = "") -> str:
        """Full NL post-processing pipeline."""
        return nl_post_process(text, canonical)

    # ── QA ────────────────────────────────────────────────────────────────

    def apply_qa(self, text: str, canonical: str = "") -> list[dict]:
        """Run NL QA checks. Returns list of issue dicts."""
        return nl_qa_check(text, canonical)

    # ── Corpus passthrough ────────────────────────────────────────────────

    def get_prompt_guidance(self, source: str) -> str:
        """Return TM prompt guidance for the NL AI prompt."""
        if self._corpus:
            return self._corpus.get_prompt_guidance(source)
        return ""

    def corpus_exact_match(self, source: str) -> str | None:
        if self._corpus:
            return self._corpus.exact_match(source)
        return None

    def corpus_segment_match(self, source: str) -> str | None:
        if self._corpus:
            return self._corpus.segment_tm_match(source)
        return None

    def corpus_fuzzy_match(
        self, source: str, threshold: float = 0.82
    ) -> tuple[str, float] | None:
        if self._corpus:
            return self._corpus.fuzzy_match(source, threshold=threshold)
        return None
