"""
Dutch QA engine.
Wraps nl_engine QA + adds additional checks.
Never imports French code.
"""

from nl_engine import nl_qa_check


class DutchQA:
    """QA checks for Dutch translation output."""

    def check(self, text: str, canonical: str = "") -> list[dict]:
        """
        Run QA checks on a Dutch translation.
        Returns list of issues: [{severity, category, message}].
        """
        return nl_qa_check(text, canonical)
