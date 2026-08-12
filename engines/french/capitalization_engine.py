"""
FrenchCapitalizationEngine — single authoritative, column-aware, context-aware
French capitalization normalizer for Home24 DE→FR content.

Replaces the old app.py capitalization pass (_KNOWN_BRANDS, _cap_first,
_apply_slash_caps, _apply_percent_lowercase, _restore_brand_caps,
apply_french_capitalization_rules) whose `canonical`/`glossary` parameters
were accepted but never used — every column got identical treatment and
casing after ':' was never touched at all.

French does not capitalize ordinary nouns the way German does. This engine
never blindly upper/lowercases a whole string; it protects proper
names/acronyms/model designations first, classifies each <br>-delimited
segment by shape (new label, new independent sentence, or a mere
continuation), and only then decides the case of a handful of well-defined
positions: segment starts, values right after ':', and both sides of a bare
'/' separator. Everything else is left exactly as translation produced it.

Shares its protected-token registry with engines/french/french_name_engine.py
(KNOWN_MODELS there imports PROTECTED_MODEL_NAMES from here) instead of
keeping two separate brand lists that can drift apart.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# PROTECTED-TOKEN REGISTRY
# =============================================================================

# Merges the old app.py _KNOWN_BRANDS with french_name_engine.py's KNOWN_MODELS
# into one deduplicated set — the single source of truth for both modules.
PROTECTED_MODEL_NAMES: frozenset[str] = frozenset({
    # formerly app.py _KNOWN_BRANDS
    "Arin", "Bocca", "Level36", "Sonoma", "Loft", "Scandi",
    "Asely", "Vedene", "Lano", "Bori", "Nalo", "Veda",
    # formerly french_name_engine.py KNOWN_MODELS
    "Sam", "Forrest", "Paku", "Malia", "Levin", "Nordic", "Entry", "Cosy",
    "Firenze", "Boston", "Ossy", "Hudson", "Scout",
})

# Acronyms/brand spellings that must survive verbatim regardless of position.
PROTECTED_ACRONYMS: frozenset[str] = frozenset({
    "MDF", "LED", "USB-C", "USB", "FSC", "PEFC", "OEKO-TEX", "Home24",
    "LDPE", "HDPE", "PVC", "PU", "PP", "ABS", "MDP", "HPL",
})

# Case-insensitive lookup: lowercased form -> canonical display form, so a
# mis-cased occurrence ("mdf", "Led", "arin") is restored to the correct one.
_PROTECTED_CANONICAL: dict[str, str] = {
    **{name.lower(): name for name in PROTECTED_MODEL_NAMES},
    **{acr.lower(): acr for acr in PROTECTED_ACRONYMS},
}

# Roman numerals — only protect standalone tokens of 2+ letters (avoids
# treating a lone "I"/"X" in ordinary prose as a numeral).
_ROMAN_NUMERAL_RE = re.compile(r'\b[IVXLCDM]{2,}\b')

# "type X" / "type. X" designations (target-side spelling is always lowercase
# "type" per the product-name engine's own convention — this only protects
# the span from being touched, it never forces a case change itself).
_TYPE_DESIGNATION_RE = re.compile(r'\b(?:[Tt]ype|[Tt]yp)\.?\s*[A-Za-z0-9]{1,3}\b')

_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

# Whole-word matches of every protected model/acronym name, longest first so
# "Level36" isn't pre-empted by a shorter overlapping alternative.
_PROTECTED_TERMS_RE = re.compile(
    r'\b(' + '|'.join(sorted((re.escape(k) for k in _PROTECTED_CANONICAL), key=len, reverse=True)) + r')\b',
    re.IGNORECASE | re.UNICODE,
)


def is_protected_token(word: str) -> bool:
    """True if the bare (punctuation-stripped) word must never be re-cased."""
    bare = word.strip(".,;:!?").lower()
    return bare in _PROTECTED_CANONICAL


def _looks_like_acronym(word: str) -> bool:
    """Conservative guard: an unregistered but ALL-CAPS token (len >= 2) is
    left alone rather than force-lowercased — better to under-correct than
    to break a brand/acronym we don't have listed."""
    bare = word.strip(".,;:!?")
    letters = [c for c in bare if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Replace every protected span with an opaque \\x00Pn\\x00 placeholder.

    Protected model names / acronyms are replaced with their *canonical*
    casing (not the literal matched text), so restoring them doubles as the
    "restore protected tokens exactly" step even when upstream text had the
    wrong case (e.g. "mdf" -> placeholder that restores to "MDF").
    <br>, URLs, roman numerals and "type X" designations are restored
    byte-for-byte, unchanged.
    """
    tokens: dict[str, str] = {}
    counter = [0]

    def _protect(pattern: re.Pattern, t: str, replacement=None) -> str:
        def _sub(m: re.Match) -> str:
            key = f'\x00P{counter[0]}\x00'
            counter[0] += 1
            tokens[key] = replacement(m) if replacement else m.group(0)
            return key
        return pattern.sub(_sub, t)

    if not text:
        return text, tokens

    protected = text
    protected = _protect(_BR_RE, protected)
    protected = _protect(_URL_RE, protected)
    protected = _protect(_TYPE_DESIGNATION_RE, protected)
    protected = _protect(_ROMAN_NUMERAL_RE, protected)
    protected = _protect(
        _PROTECTED_TERMS_RE, protected,
        replacement=lambda m: _PROTECTED_CANONICAL[m.group(0).lower()],
    )
    return protected, tokens


def restore_tokens(text: str, tokens: dict[str, str]) -> str:
    """Inverse of protect_tokens — placeholders are restored last, verbatim,
    so nothing inside them was ever visible to the casing rules below."""
    for key, original in tokens.items():
        text = text.replace(key, original)
    return text


# =============================================================================
# SEGMENT CLASSIFICATION
# =============================================================================

class SegmentRole(Enum):
    LABEL_START     = "label_start"     # e.g. "Revêtement :" starting a <br> segment
    SENTENCE_START  = "sentence_start"  # a new independent sentence after <br>
    CONTINUATION    = "continuation"    # wraps/continues the previous clause — no forced cap


# Lowercase connector words that, when they open a segment, mark it as a
# continuation of the previous clause rather than a new label/sentence.
_CONTINUATION_CONNECTORS = frozenset({
    "et", "ou", "avec", "sans", "de", "du", "des", "pour", "sur", "dans",
    "en", "à", "au", "aux", "par", "sous", "entre", "chez", "vers",
})

_LABEL_WORD_RE = re.compile(r'^[^\x00:.!?]{1,30}$')


class SegmentClassifier:
    """Classifies each <br>-delimited segment of a cell value by shape, so
    the engine capitalizes new labels/sentences without blindly capitalizing
    every continuation fragment (spec: label-vs-value, standalone sentence,
    vs. mere continuation after <br>)."""

    def classify_segment(
        self, segment: str, is_first_segment: bool, bare_first_bias: "SegmentRole" = None,
    ) -> SegmentRole:
        """`bare_first_bias` resolves the one genuinely ambiguous case: the
        very first segment of a cell, with no label/colon, no continuation
        connector, and starting lowercase. A raw attribute value like
        "noir/gris" (colorDetail/materialDetail) must stay lowercase; an
        under-capitalized full sentence in a narrative column
        (qualityDetail/deliveryScope/...) should still read as a sentence
        start. There is nothing *before* the first segment to "continue", so
        it is never itself CONTINUATION — the column decides between
        SENTENCE_START and leaving it alone."""
        bias = bare_first_bias or SegmentRole.SENTENCE_START
        stripped = segment.lstrip()
        if not stripped:
            return SegmentRole.CONTINUATION

        trimmed = stripped.rstrip()
        colon_pos = stripped.find(':')
        if colon_pos > 0 and _LABEL_WORD_RE.match(stripped[:colon_pos]):
            return SegmentRole.LABEL_START

        if trimmed and trimmed[-1] in ".!?":
            return SegmentRole.SENTENCE_START

        first_word_match = re.match(r"[a-zàâäéèêëïîôöùûüçœæ]+", stripped)
        if first_word_match and first_word_match.group(0) in _CONTINUATION_CONNECTORS:
            return bias if is_first_segment else SegmentRole.CONTINUATION

        if stripped[0].islower():
            return bias if is_first_segment else SegmentRole.CONTINUATION

        # Uppercase-start, no colon/label, no terminal punctuation: reads as
        # its own independent sentence/segment.
        return SegmentRole.SENTENCE_START


# =============================================================================
# COLUMN PROFILES
# =============================================================================

@dataclass
class ColumnCapitalizationRules:
    """Per-column knobs — data, not branching code, so adding a profile for
    a new canonical column is a one-line registry edit."""
    capitalize_label_start: bool = True
    capitalize_sentence_start: bool = True
    lowercase_value_after_colon: bool = True   # unless proper name/acronym/full sentence
    lowercase_after_slash: bool = True         # never force title-case after '/'
    lowercase_after_percent: bool = True       # "100 % polyester", not "100 % Polyester"
    # What a bare, label-less, connector-less, lowercase-starting FIRST
    # segment defaults to: SENTENCE_START (narrative columns — an
    # under-capitalized sentence should still get a capital) or
    # CONTINUATION (spec-sheet/value columns — a raw attribute value like
    # "noir/gris" stays exactly as authored).
    bare_first_segment_bias: SegmentRole = SegmentRole.SENTENCE_START


_GENERIC_PROFILE = ColumnCapitalizationRules()
_VALUE_BIAS = SegmentRole.CONTINUATION

_COLUMN_PROFILES: dict[str, ColumnCapitalizationRules] = {
    "name":                       ColumnCapitalizationRules(lowercase_value_after_colon=False),
    "colorDetail":                ColumnCapitalizationRules(bare_first_segment_bias=_VALUE_BIAS),
    "materialDetail":             ColumnCapitalizationRules(bare_first_segment_bias=_VALUE_BIAS),
    "deliveryScope":              ColumnCapitalizationRules(),
    "otherMeasurements":          ColumnCapitalizationRules(bare_first_segment_bias=_VALUE_BIAS),
    "qualityDetail":              ColumnCapitalizationRules(),
    "textileCompositionCover1":   ColumnCapitalizationRules(bare_first_segment_bias=_VALUE_BIAS),
    "variantName":                ColumnCapitalizationRules(
        lowercase_value_after_colon=False, bare_first_segment_bias=_VALUE_BIAS,
    ),
    "warningsAndSafetyInformation": ColumnCapitalizationRules(),
}


def get_column_profile(canonical: str | None) -> ColumnCapitalizationRules:
    return _COLUMN_PROFILES.get(canonical or "", _GENERIC_PROFILE)


# =============================================================================
# LOW-LEVEL CASE HELPERS
# =============================================================================

def _cap_first(s: str) -> str:
    """Uppercase the first alphabetic character of s (no-op on placeholders,
    digits, punctuation-only or empty strings)."""
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i + 1:]
        if ch not in " \t":
            return s  # first meaningful char isn't a letter (placeholder, digit, punct) — leave alone
    return s


def _lower_first(s: str) -> str:
    """Lowercase the first alphabetic character of s, unless that first word
    is a protected placeholder or looks like an unregistered acronym."""
    stripped = s.lstrip()
    if not stripped or not stripped[0].isalpha():
        return s
    first_word = re.match(r"[^\s/]+", stripped).group(0)
    if _looks_like_acronym(first_word):
        return s
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.lower() + s[i + 1:]
        if ch not in " \t":
            return s
    return s


_PERCENT_FOLLOWER_RE = re.compile(r'(\d+\s*%)\s+([^\s/\x00][\w\x00]*)', re.UNICODE)

_SLASH_PAIR_RE = re.compile(
    r'([^\s/\x00][^\s/]{1,60})'
    r'/'
    r'([^\s/\x00][^\s/]{1,60})',
    re.UNICODE,
)


def _apply_percent_lowercase(segment: str) -> str:
    def repl(m: re.Match) -> str:
        word = m.group(2)
        if _looks_like_acronym(word) or not word[0].isalpha():
            return m.group(0)
        return m.group(1) + " " + word[0].lower() + word[1:]
    return _PERCENT_FOLLOWER_RE.sub(repl, segment)


def _apply_slash_neutral(segment: str, skip_offset: int | None) -> str:
    """Lowercase both sides of a bare 'word/word' separator unless a side is
    protected, acronym-shaped, or is the segment's own first word (whose
    case was already decided by the segment-start rule)."""
    def repl(m: re.Match) -> str:
        left, right = m.group(1), m.group(2)
        if not (skip_offset is not None and m.start(1) == skip_offset):
            if left[0].isalpha() and not _looks_like_acronym(left):
                left = left[0].lower() + left[1:]
        if right[0].isalpha() and not _looks_like_acronym(right):
            right = right[0].lower() + right[1:]
        return left + "/" + right
    return _SLASH_PAIR_RE.sub(repl, segment)


# =============================================================================
# ENGINE
# =============================================================================

@dataclass
class CapitalizationResult:
    text: str
    original: str
    changed: bool
    changes: list = field(default_factory=list)  # [{"rule": str, "before": str, "after": str}]


class FrenchCapitalizationEngine:
    """Single authoritative capitalization pass. Runs last, after glossary/TM/
    GPT/residue-fix text has already been written, and after product-name
    compression has already produced its result — this is the "capitalize"
    step in the protect -> translate -> compress -> capitalize -> restore ->
    validate order."""

    def __init__(self):
        self._classifier = SegmentClassifier()

    def capitalize(
        self,
        text: str,
        canonical: str | None = None,
        source: str | None = None,
        glossary: dict | None = None,
    ) -> CapitalizationResult:
        if not text or not str(text).strip():
            return CapitalizationResult(text=text, original=text, changed=False)

        original = text
        rules = get_column_profile(canonical)
        protected, tokens = protect_tokens(text)

        # Split on the <br> placeholders (they're now opaque tokens produced
        # by protect_tokens, not the literal "<br>" string).
        br_keys = {k for k, v in tokens.items() if _BR_RE.fullmatch(v or "")}
        segments: list[str] = []
        buf = ""
        i = 0
        while i < len(protected):
            matched_key = None
            for key in br_keys:
                if protected.startswith(key, i):
                    matched_key = key
                    break
            if matched_key:
                segments.append(buf)
                segments.append(matched_key)
                buf = ""
                i += len(matched_key)
            else:
                buf += protected[i]
                i += 1
        segments.append(buf)

        changes: list = []
        out: list[str] = []
        seg_index = 0
        for part in segments:
            if part in br_keys:
                out.append(part)
                continue
            is_first = (seg_index == 0)
            seg_index += 1
            role = self._classifier.classify_segment(part, is_first, rules.bare_first_segment_bias)

            new_part = part
            if rules.lowercase_after_percent:
                new_part = _apply_percent_lowercase(new_part)

            skip_slash_offset = None
            if role in (SegmentRole.LABEL_START, SegmentRole.SENTENCE_START):
                if (role == SegmentRole.LABEL_START and rules.capitalize_label_start) or (
                    role == SegmentRole.SENTENCE_START and rules.capitalize_sentence_start
                ):
                    before = new_part
                    new_part = _cap_first(new_part)
                    if new_part != before:
                        changes.append({"rule": f"{role.value}_cap", "before": before, "after": new_part})
                    m = re.match(r'\s*', new_part)
                    skip_slash_offset = m.end() if new_part[m.end():m.end() + 1].isalpha() else None

            if rules.lowercase_value_after_colon:
                colon_pos = new_part.find(':')
                if colon_pos != -1:
                    value = new_part[colon_pos + 1:]
                    trimmed = value.strip()
                    is_full_sentence = bool(trimmed) and trimmed[-1] in ".!?"
                    if trimmed and not is_full_sentence:
                        lowered = _lower_first(value)
                        if lowered != value:
                            changes.append({
                                "rule": "colon_value_lowercase",
                                "before": new_part[:colon_pos + 1] + value,
                                "after": new_part[:colon_pos + 1] + lowered,
                            })
                        new_part = new_part[:colon_pos + 1] + lowered

            if rules.lowercase_after_slash:
                before = new_part
                new_part = _apply_slash_neutral(new_part, skip_slash_offset)
                if new_part != before:
                    changes.append({"rule": "slash_neutral", "before": before, "after": new_part})

            out.append(new_part)

        joined = "".join(out)
        final = restore_tokens(joined, tokens)
        restored_changes = [
            {**c, "before": restore_tokens(c["before"], tokens), "after": restore_tokens(c["after"], tokens)}
            for c in changes
        ]

        return CapitalizationResult(
            text=final, original=original, changed=(final != original), changes=restored_changes,
        )


# =============================================================================
# SAFE DETERMINISTIC AUTO-FIX
# =============================================================================

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9\-]+", re.UNICODE)


def auto_fix_protected_casing(text: str) -> str:
    """The one deterministic, always-safe auto-fix class: a mis-cased
    protected model name or acronym (e.g. "Mdf" -> "MDF") is corrected.
    Nothing else about the text is touched — no sentence/segment/colon
    logic runs here, so this is safe to apply silently as a starting-point
    normalization (spec Part 20)."""
    if not text:
        return text

    def repl(m: re.Match) -> str:
        word = m.group(0)
        canonical = _PROTECTED_CANONICAL.get(word.lower())
        return canonical if canonical and canonical != word else word

    return _WORD_RE.sub(repl, text)


# =============================================================================
# VALIDATION / QA
# =============================================================================

CAP_SEVERITY_INFO     = "Info"
CAP_SEVERITY_WARNING  = "Warning"
CAP_SEVERITY_CRITICAL = "Critical"

_RULE_TO_ISSUE = {
    "label_start_cap":       ("cap_lowercase_label_start", CAP_SEVERITY_WARNING),
    "sentence_start_cap":    ("cap_lowercase_sentence_start", CAP_SEVERITY_WARNING),
    "colon_value_lowercase": ("cap_value_after_colon_upper", CAP_SEVERITY_WARNING),
    "slash_neutral":         ("cap_slash_forced_title", CAP_SEVERITY_INFO),
}


def validate_french_capitalization(
    text: str,
    canonical: str | None = None,
    source: str | None = None,
    glossary: dict | None = None,
) -> list[dict]:
    """Non-mutating QA pass. Runs the engine over `text` and classifies every
    change it *would* make into a severity tier — it does not rewrite
    `text` itself. A protected-token casing defect (detected independently
    of the engine's own change list, since protect_tokens/restore_tokens
    always self-heals those) is reported as Critical; ordinary
    label/sentence/colon casing gaps are Warning; cosmetic slash-casing
    drift is Info."""
    if not text or not str(text).strip():
        return []

    issues: list[dict] = []

    # Critical: a protected model/acronym token whose casing in `text`
    # doesn't match its registered canonical form.
    for m in _PROTECTED_TERMS_RE.finditer(text):
        found = m.group(0)
        canonical_form = _PROTECTED_CANONICAL[found.lower()]
        if found != canonical_form:
            issues.append({
                "type": "cap_protected_token_altered",
                "severity": CAP_SEVERITY_CRITICAL,
                "reason": f'"{found}" should be written "{canonical_form}".',
            })

    engine = FrenchCapitalizationEngine()
    result = engine.capitalize(text, canonical=canonical, source=source, glossary=glossary)
    for change in result.changes:
        issue_type, severity = _RULE_TO_ISSUE.get(change["rule"], ("cap_cosmetic_spacing", CAP_SEVERITY_INFO))
        issues.append({
            "type": issue_type,
            "severity": severity,
            "reason": f'"{change["before"].strip()}" -> "{change["after"].strip()}"',
        })

    return issues
