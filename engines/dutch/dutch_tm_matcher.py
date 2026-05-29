"""
Dutch TM matcher — wraps Home24DutchCorpusEngine.
Loads from session state or database.
"""

from nl_engine import Home24DutchCorpusEngine


def get_engine(session_state: dict | None = None) -> Home24DutchCorpusEngine | None:
    """
    Return the NL corpus engine from session state (if available),
    or None if not loaded yet.
    The engine is loaded once by app.py and stored in st.session_state.
    """
    if session_state is None:
        return None
    return session_state.get("nl_corpus_engine")


class NLTMMatcher:
    """
    Wrapper around Home24DutchCorpusEngine providing a clean matching API.
    """

    def __init__(self, engine: Home24DutchCorpusEngine | None = None) -> None:
        self._engine = engine

    @classmethod
    def from_session(cls, session_state: dict) -> "NLTMMatcher":
        """Construct from Streamlit session state."""
        engine = get_engine(session_state)
        return cls(engine)

    def exact_match(self, source: str) -> str | None:
        if self._engine:
            return self._engine.exact_match(source)
        return None

    def segment_match(self, source: str) -> str | None:
        if self._engine:
            return self._engine.segment_tm_match(source)
        return None

    def fuzzy_match(
        self, source: str, threshold: float = 0.82
    ) -> tuple[str, float] | None:
        if self._engine:
            return self._engine.fuzzy_match(source, threshold=threshold)
        return None

    def get_prompt_guidance(self, source: str) -> str:
        if self._engine:
            return self._engine.get_prompt_guidance(source)
        return ""

    def extract_terminology(self, source: str, max_terms: int = 10) -> list[tuple[str, str]]:
        if self._engine:
            return self._engine.extract_terminology(source, max_terms=max_terms)
        return []

    def __bool__(self) -> bool:
        return self._engine is not None
