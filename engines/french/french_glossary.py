"""
French glossary accessor — wraps database.py FR-specific glossary functions.
Never imports NL code.
"""

from database import db_load_glossary, db_save_glossary


def load_fr_glossary() -> dict | None:
    """Load the French glossary from the database."""
    return db_load_glossary("French")


def save_fr_glossary(glossary: dict) -> None:
    """Persist the French glossary to the database."""
    db_save_glossary(glossary, "French")


def lookup_fr_term(source_term: str) -> str | None:
    """
    Look up a single German term in the FR glossary.
    Returns the French target or None if not found.
    """
    glossary = load_fr_glossary()
    if not glossary:
        return None
    terms = glossary.get("terms", {})
    # Exact match first
    if source_term in terms:
        return terms[source_term]
    # Case-insensitive fallback
    low = source_term.strip().lower()
    for de, fr in terms.items():
        if de.strip().lower() == low:
            return fr
    return None
