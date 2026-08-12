"""
HumanCorrectionPropagationEngine — analyzes one human correction made in the
Trados-style review grid and decides which *other* rows in the current file
can safely receive the same fix, at what confidence, without ever touching
model names, dimensions, quantities, colors, Jira keys or article numbers
that legitimately differ between rows.

One correction should teach the current file, not just the one cell.

Confidence tiers (spec Part H):
  SAFE   — identical normalized German source + same column profile.
           Applied automatically.
  HIGH   — same sentence pattern; only recognized protected variables
           (model/quantity/dimension/Jira key/article number) differ, and
           each one can be unambiguously located and swapped in the
           corrected target. Applied automatically, caller should notify.
  MEDIUM — the same wrong target phrase/term appears inside a different,
           non-identical sentence. Never auto-applied — always returned for
           an explicit "apply / review / ignore" decision.
  LOW    — everything else (ambiguous variable placement, multi-word
           differences that aren't a recognized protected category).
           Suggestion only, never auto-applied.

A color mismatch between two sources is an absolute veto (Part R): colors
translate differently per language, so they can never be treated as a
copy-through variable the way a model name or quantity suffix can. A vetoed
pair is excluded outright — it is never even offered as a LOW suggestion.

Every proposed target text is run through FrenchCapitalizationEngine before
being returned, so propagated corrections never regress capitalization
quality relative to a freshly translated cell (spec acceptance criterion 9).
"""

import re
import difflib
from dataclasses import dataclass, field

from engines.french.capitalization_engine import (
    FrenchCapitalizationEngine,
    PROTECTED_MODEL_NAMES,
    PROTECTED_ACRONYMS,
)


CONF_SAFE   = "SAFE"
CONF_HIGH   = "HIGH"
CONF_MEDIUM = "MEDIUM"
CONF_LOW    = "LOW"

_VETO = object()  # sentinel: this pair must never propagate, not even as a suggestion


# =============================================================================
# PROTECTED-VARIABLE CLASSIFICATION
# =============================================================================

# Quantity suffixes seen verbatim on both sides of DE->FR in this catalog
# ("2er-Set" stays "2er-Set"), plus generic "<n> x" / "<n> pièces" shapes.
_QUANTITY_RE = re.compile(
    r'^\d+\s?(?:er-Set|er-set|-Set|-set|x|St(?:ü|u)ck|pi[eè]ces?|pcs)\.?$', re.IGNORECASE,
)

# Dimensions / weights — "120 cm", "45x60cm", "2.5kg" style tokens.
_DIMENSION_RE = re.compile(r'^\d+(?:[.,]\d+)?\s?(?:cm|mm|m|kg|g|l|ml)\.?$', re.IGNORECASE)

# Home24-style article numbers — long bare digit runs.
_ARTICLE_NUMBER_RE = re.compile(r'^\d{6,}$')

# Jira-style issue keys, e.g. "PC-24287".
_JIRA_KEY_RE = re.compile(r'^[A-Z][A-Z0-9]{1,9}-\d+$')

# Color words that must veto propagation when they differ — translated per
# language, never copied through like a model name or quantity suffix.
_COLOR_WORDS = frozenset({
    # German
    "schwarz", "weiß", "weiss", "grau", "braun", "beige", "blau", "rot",
    "grün", "gruen", "gelb", "orange", "rosa", "lila", "violett", "taupe",
    "creme", "anthrazit", "natur", "gold", "silber", "bronze", "petrol",
    # French
    "noir", "noire", "blanc", "blanche", "gris", "grise", "marron", "bleu",
    "bleue", "rouge", "jaune", "rose", "violet", "violette", "vert", "verte",
    "creme", "crème", "anthracite", "naturel", "naturelle", "or", "argent",
    "bronze", "petrole", "pétrole",
})

# Small stoplist of very common connector/article words that must never be
# mistaken for a "variable" slot even though they can appear TitleCase at a
# German sentence start.
_COMMON_WORD_STOPLIST = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer",
    "und", "oder", "mit", "ohne", "für", "fuer", "von", "bei", "auf",
    "le", "la", "les", "un", "une", "des", "et", "ou", "avec", "sans",
    "pour", "de", "du", "sur",
})


def _classify_token(token: str) -> str | None:
    """Category of a single word/token, or None if it's not a recognized
    protected-variable shape. COLOR is reported distinctly so callers can
    veto on it rather than treat it as copy-through."""
    bare = token.strip(".,;:()")
    if not bare:
        return None
    if bare.lower() in _COLOR_WORDS:
        return "COLOR"
    if bare in PROTECTED_MODEL_NAMES or bare.upper() in PROTECTED_ACRONYMS:
        return "MODEL"
    if _QUANTITY_RE.match(bare):
        return "QTY"
    if _DIMENSION_RE.match(bare):
        return "DIM"
    if _JIRA_KEY_RE.match(bare):
        return "JIRA"
    if _ARTICLE_NUMBER_RE.match(bare):
        return "ARTICLE"
    letters = [c for c in bare if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return "MODEL"  # unregistered ALL-CAPS token, e.g. "EVIRA", "NOVA"
    if (
        bare[0].isupper() and bare[1:].islower() and len(bare) >= 3
        and bare.lower() not in _COMMON_WORD_STOPLIST
    ):
        return "MODEL"  # unregistered TitleCase proper-noun-shaped token
    return None


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def _words(text: str) -> list[str]:
    return _normalize(text).split(" ") if _normalize(text) else []


# =============================================================================
# PART E — EXACT SOURCE MATCH
# =============================================================================

def is_exact_source_match(source_a: str, source_b: str) -> bool:
    return bool(_normalize(source_a)) and _normalize(source_a) == _normalize(source_b)


# =============================================================================
# PART G/H — PATTERN (PROTECTED-VARIABLE TEMPLATE) MATCH
# =============================================================================

def build_variable_template(source_a: str, source_b: str):
    """Compare two German sources word-by-word. Returns:
      - a list of (category, value_a, value_b) pairs if every differing span
        is a single-word, same-category protected variable (safe template);
      - `_VETO` if a differing span is a COLOR (or the two colors differ) —
        this pair must never propagate, at any confidence;
      - None if the sentences aren't a recognized template match at all
        (different structure, multi-word differences, unrecognized words).
    """
    words_a, words_b = _words(source_a), _words(source_b)
    if not words_a or not words_b:
        return None

    sm = difflib.SequenceMatcher(a=words_a, b=words_b, autojunk=False)
    pairs: list[tuple[str, str, str]] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag != "replace" or (i2 - i1) != 1 or (j2 - j1) != 1:
            # insertion/deletion (word count changed) or a multi-word swap —
            # not a clean protected-variable slot, no safe template here.
            return None
        val_a, val_b = words_a[i1], words_b[j1]
        cat_a, cat_b = _classify_token(val_a), _classify_token(val_b)
        if cat_a == "COLOR" or cat_b == "COLOR":
            return _VETO if val_a.strip(".,;:()").lower() != val_b.strip(".,;:()").lower() else None
        if cat_a is None or cat_a != cat_b:
            return None
        pairs.append((cat_a, val_a, val_b))

    return pairs or None  # empty pairs means the sources were identical — caller handles that as exact match


def apply_variable_template(target_new: str, template: list[tuple[str, str, str]]) -> str | None:
    """Substitute each corrected row's variable value with the candidate
    row's own value inside the human-corrected target text. Returns None
    (never guess) if a value can't be located unambiguously — those cases
    fall back to a LOW suggestion rather than a silent wrong edit."""
    result = target_new
    for _cat, val_a, val_b in template:
        bare_a = val_a.strip(".,;:()")
        occurrences = [m for m in re.finditer(re.escape(bare_a), result)]
        if len(occurrences) != 1:
            return None
        m = occurrences[0]
        result = result[:m.start()] + val_b.strip(".,;:()") + result[m.end():]
    return result


# =============================================================================
# PART F/Q — TERM-LEVEL (TARGET-PHRASE) MATCH
# =============================================================================

def extract_term_change(target_old: str, target_new: str, max_words: int = 4, max_len: int = 40):
    """Isolate the minimal contiguous phrase that changed between the old
    and new target text. Returns (old_phrase, new_phrase) only when there is
    exactly one contiguous changed span and it's short — a clean
    terminology/capitalization swap, not a full-sentence rewrite. None
    otherwise (nothing safe to propagate at the term level)."""
    old_words, new_words = _words(target_old), _words(target_new)
    if not old_words or not new_words:
        return None

    sm = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    changed_ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    if len(changed_ops) != 1:
        return None  # more than one changed span — not a clean single-term swap

    tag, i1, i2, j1, j2 = changed_ops[0]

    if tag == "replace":
        old_phrase = " ".join(old_words[i1:i2])
        new_phrase = " ".join(new_words[j1:j2])
    elif tag == "insert":
        # Word(s) added with nothing removed — e.g. "velours" -> "velours
        # côtelé". Anchor on the adjacent unchanged word so the result is
        # still a locatable phrase rather than a bare "nothing -> X" swap.
        if i1 > 0:
            old_phrase = old_words[i1 - 1]
            new_phrase = " ".join(new_words[j1 - 1:j2])
        elif i2 < len(old_words):
            old_phrase = old_words[i2]
            new_phrase = " ".join(new_words[j1:j2 + 1])
        else:
            return None  # insertion with no adjacent word to anchor on
    elif tag == "delete":
        # Word(s) removed with nothing added — mirror image of insert.
        if i1 > 0 and j1 > 0:
            old_phrase = " ".join(old_words[i1 - 1:i2])
            new_phrase = new_words[j1 - 1]
        elif i2 < len(old_words) and j2 < len(new_words):
            old_phrase = " ".join(old_words[i1:i2 + 1])
            new_phrase = new_words[j2]
        else:
            return None  # deletion with no adjacent word to anchor on
    else:
        return None

    if not old_phrase or old_phrase == new_phrase:
        return None
    if len(old_phrase.split()) > max_words or len(old_phrase) > max_len or len(new_phrase) > max_len:
        return None
    return old_phrase, new_phrase


def _find_phrase(text: str, phrase: str):
    """Case-tolerant, word-boundary search for `phrase` inside `text`.
    Returns the re.Match or None. Matches "Revêtement"/"revêtement"
    regardless of which case the corrected phrase itself used."""
    pattern = re.compile(r'\b' + re.escape(phrase) + r'\b', re.IGNORECASE)
    return pattern.search(text)


def replace_phrase_case_aware(text: str, match: re.Match, new_phrase: str) -> str:
    """Replace the matched span with `new_phrase`, preserving whether the
    matched occurrence started with an uppercase letter (segment/label
    start) or lowercase (mid-sentence) — final casing is still normalized
    afterwards by the capitalization engine, this just avoids handing it an
    obviously wrong starting case."""
    found = match.group(0)
    replacement = new_phrase
    if found[:1].isupper() and replacement[:1].isalpha():
        replacement = replacement[0].upper() + replacement[1:]
    elif found[:1].islower() and replacement[:1].isalpha():
        replacement = replacement[0].lower() + replacement[1:]
    return text[:match.start()] + replacement + text[match.end():]


# =============================================================================
# PART R — SAFEGUARD: NEVER PROPAGATE PRODUCT-SPECIFIC DATA
# =============================================================================

def has_conflicting_protected_data(source_a: str, source_b: str) -> bool:
    """True if the two sources differ only/also in a protected-data span
    (model, dimension, quantity, article number, Jira key) that
    build_variable_template couldn't cleanly resolve into a template —
    used as an extra guard before any exact-style propagation, so a caller
    that only checked string difference (not full normalization) still
    refuses to blindly propagate across genuinely different products."""
    template = build_variable_template(source_a, source_b)
    return template is _VETO or (
        template is None and _normalize(source_a) != _normalize(source_b)
        and any(_classify_token(w) for w in set(_words(source_a)) ^ set(_words(source_b)))
    )


# =============================================================================
# PART K — GLOSSARY LEARNING SUGGESTION
# =============================================================================

def _looks_like_term(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if any(p in t for p in (".", "!", "?", ";", "<br>", ":")):
        return False
    return len(t.split()) <= 3


def suggest_glossary_update(source: str, target_old: str, target_new: str) -> dict | None:
    """A full-cell correction where both the German source and the new
    French text are short, clean terms (not sentences) looks like a
    terminology fix worth teaching the glossary. Never proposed from an
    arbitrary full-sentence correction — spec Part K's explicit gate."""
    if not _looks_like_term(source) or not _looks_like_term(target_new):
        return None
    if _normalize(target_old) == _normalize(target_new):
        return None
    return {
        "source_term": _normalize(source),
        "old_target_term": _normalize(target_old),
        "new_target_term": _normalize(target_new),
        "reason": f'Human-reviewed correction: "{source}" -> "{target_new}" (was "{target_old}").',
    }


# =============================================================================
# ORCHESTRATION
# =============================================================================

@dataclass
class PropagationMatch:
    row_id: str
    proposed_target: str
    confidence: str
    reason: str


@dataclass
class PropagationAnalysis:
    safe:   list = field(default_factory=list)
    high:   list = field(default_factory=list)
    medium: list = field(default_factory=list)
    low:    list = field(default_factory=list)
    glossary_suggestion: dict | None = None

    @property
    def auto_apply(self) -> list:
        """SAFE + HIGH — applied automatically per spec Part H."""
        return self.safe + self.high

    @property
    def needs_decision(self) -> list:
        """MEDIUM — shown to the user as 'apply / review / ignore'."""
        return self.medium

    @property
    def total_affected(self) -> int:
        return len(self.safe) + len(self.high) + len(self.medium) + len(self.low)


class HumanCorrectionPropagationEngine:
    """Analyzes one confirmed human correction against every other row
    currently in the review file and classifies safe/possible propagation
    targets. Never mutates its inputs — callers apply the returned matches
    explicitly (spec Part D: 'one correction should teach the current
    file')."""

    def __init__(self, capitalization_engine: FrenchCapitalizationEngine | None = None):
        self._cap_engine = capitalization_engine or FrenchCapitalizationEngine()

    def _finalize(self, text: str, column: str, source: str) -> str:
        return self._cap_engine.capitalize(text, canonical=column, source=source).text

    def analyze(
        self,
        corrected_row: dict,
        other_rows: list[dict],
    ) -> PropagationAnalysis:
        """`corrected_row`: {"id", "column", "source", "target_old", "target_new"}.
        `other_rows`: same shape plus "target_old" (current cell text) and
        optional "confirmed" (bool) — confirmed rows are never overwritten,
        a reviewer's own deliberate choice always wins."""
        source_a    = corrected_row["source"]
        target_old  = corrected_row["target_old"]
        target_new  = corrected_row["target_new"]
        column      = corrected_row["column"]
        self_id     = corrected_row["id"]

        analysis = PropagationAnalysis()
        handled_ids: set = set()

        for row in other_rows:
            if row["id"] == self_id or row.get("column") != column or row.get("confirmed"):
                continue
            source_b = row.get("source", "")

            if is_exact_source_match(source_a, source_b):
                proposed = self._finalize(target_new, column, source_b)
                analysis.safe.append(PropagationMatch(
                    row["id"], proposed, CONF_SAFE,
                    "Identical German source and column profile.",
                ))
                handled_ids.add(row["id"])
                continue

            template = build_variable_template(source_a, source_b)
            if template is _VETO or template is None:
                continue  # colors differ (veto), or no clean template — leave for term-level pass
            proposed_raw = apply_variable_template(target_new, template)
            if proposed_raw is None:
                continue
            proposed = self._finalize(proposed_raw, column, source_b)
            var_desc = ", ".join(f'{a}→{b}' for _cat, a, b in template)
            analysis.high.append(PropagationMatch(
                row["id"], proposed, CONF_HIGH,
                f"Same pattern — only {var_desc} differ.",
            ))
            handled_ids.add(row["id"])

        term_change = extract_term_change(target_old, target_new)
        if term_change:
            old_phrase, new_phrase = term_change
            for row in other_rows:
                if row["id"] == self_id or row["id"] in handled_ids:
                    continue
                if row.get("column") != column or row.get("confirmed"):
                    continue
                row_target = row.get("target_old", "")
                match = _find_phrase(row_target, old_phrase)
                if not match:
                    continue
                proposed_raw = replace_phrase_case_aware(row_target, match, new_phrase)
                proposed = self._finalize(proposed_raw, column, row.get("source", ""))
                analysis.medium.append(PropagationMatch(
                    row["id"], proposed, CONF_MEDIUM,
                    f'"{old_phrase}" -> "{new_phrase}" also found here.',
                ))
                handled_ids.add(row["id"])

        analysis.glossary_suggestion = suggest_glossary_update(source_a, target_old, target_new)
        return analysis
