"""
Home24 Dutch (NL) Localization Engine — Trados TM-powered.

Pipeline priority:
  1. Exact TM match        → EXACT_TM_MATCH
  2. Fuzzy TM match        → FUZZY_TM_MATCH
  3. Terminology injection → AI_GUIDED (constrains GPT output)
  4. Dekor normalization   → applied pre/post-AI
  5. Forbidden patterns    → applied post-AI
  6. Format normalization  → applied post-AI
  7. QA validation         → applied post-AI
"""

import re
from collections import Counter
from difflib import SequenceMatcher


# =============================================================================
# CANONICAL TERMINOLOGY  — derived from Trados TM corpus analysis
# =============================================================================

# Dekor / finish patterns — longest first so multi-word phrases replace before substrings
NL_DEKOR_MAP: list[tuple[str, str]] = [
    ("Eiche Artisan Dekor",    "Artisan eikenlook"),
    ("Eiche Viking Dekor",     "Viking eikenhouten look"),
    ("Eiche hell Dekor",       "lichte eikenhouten look"),
    ("Eiche dunkel Dekor",     "donkere eikenhouten look"),
    ("Eiche natur Dekor",      "natuurlijke eikenhouten look"),
    ("Zinneiche Dekor",        "tin-eikenhouten look"),
    ("Kernbuche Dekor",        "kernbeukenhouten look"),
    ("Marmor Weiß Dekor",      "witte marmerlook"),
    ("Marmor Schwarz Dekor",   "zwarte marmerlook"),
    ("Marmor Grau Dekor",      "grijze marmerlook"),
    ("Beton Dekor",            "betonlook"),
    ("Artisan Dekor",          "Artisan look"),
    ("Eiche Dekor",            "eikenhouten look"),
    ("Dekor",                  "look"),           # generic fallback — last
]

# Color map — full German → Dutch canonical
# "Color-of-X" descriptors get -kleurig in NL; basic colors do not
NL_COLOR_MAP: list[tuple[str, str]] = [
    # Compound shades first
    ("dunkelgrau",     "donkergrijs"),
    ("hellgrau",       "lichtgrijs"),
    ("dunkelbraun",    "donkerbruin"),
    ("hellbraun",      "lichtbruin"),
    ("dunkelblau",     "donkerblauw"),
    ("hellblau",       "lichtblauw"),
    ("dunkelgrün",     "donkergroen"),
    ("hellgrün",       "lichtgroen"),
    ("Sandanthrazit",  "zandantraciet"),
    ("Sandschwarz",    "zandzwart"),
    ("Sandbeige",      "zandbeige"),
    # Descriptor-style colors (always -kleurig in NL)
    ("Anthrazit",      "antracietkleurig"),
    ("Graphit",        "grafietkleurig"),
    ("Silber",         "zilverkleurig"),
    ("Gold",           "goudkleurig"),
    ("Creme",          "crèmekleurig"),
    ("Kupfer",         "koper"),
    # Basic colors
    ("Schwarz",        "zwart"),
    ("Weiß",           "wit"),
    ("Grau",           "grijs"),
    ("Braun",          "bruin"),
    ("Blau",           "blauw"),
    ("Grün",           "groen"),
    ("Rot",            "rood"),
    ("Gelb",           "geel"),
    ("Rosa",           "roze"),
    ("Orange",         "oranje"),
    ("Beige",          "beige"),
    ("Türkis",         "turquoise"),
    ("Lila",           "lila"),
    ("Violett",        "paars"),
    ("Pink",           "pink"),
    ("Natur",          "natuurlijk"),
    ("Matt",           "mat"),
]

# Canonical furniture name map — TM-verified (longest first)
NL_FURNITURE_CANONICAL: list[tuple[str, str]] = [
    # TV furniture
    ("TV-Lowboard",              "Tv-meubel"),
    ("TV Lowboard",              "Tv-meubel"),
    ("Fernsehsessel",            "tv-fauteuil"),
    # Lighting — compound LED forms first
    ("LED-Pendelleuchte",        "LED-hanglamp"),
    ("LED-Deckenleuchte",        "LED-plafondlamp"),
    ("LED-Wandleuchte",          "LED-wandlamp"),
    ("LED-Tischleuchte",         "LED-tafellamp"),
    ("LED-Stehleuchte",          "LED-staande lamp"),
    ("LED-Deckenleuchten",       "LED-plafondlamp"),
    ("Pendelleuchte",            "hanglamp"),
    ("Tischleuchte",             "tafellamp"),
    ("Deckenleuchten",           "plafondlamp"),
    ("Deckenleuchte",            "plafondlamp"),
    ("Wandleuchte",              "wandlamp"),
    ("Stehleuchte",              "staande lamp"),
    # Seating
    ("Polstergarnitur",          "bankstellen"),
    ("Loungesessel",             "loungestoel"),
    ("Bigsofa",                  "XXL-bank"),
    ("Big-Sofa",                 "XXL-bank"),
    ("XXL Sessel",               "XXL-fauteuil"),
    ("Schlafsessel",             "slaapfauteuil"),
    ("Drehsessel",               "draaifauteuil"),
    ("Freischwinger",            "sledestoel"),
    ("Armlehnenstuhl",           "stoel met armleuningen"),
    ("Cocktailsessel",           "fauteuil"),
    # Bathroom sets
    ("Badezimmerset",            "Badkamerset"),
    ("Badset",                   "Badkamerset"),
    ("Waschbeckenunterschrank",  "wastafelonderkast"),
    ("Spiegelschrank",           "spiegelkast"),
    ("Spiegelpaneel",            "spiegelpaneel"),
    # Textiles / decor
    ("Dekokissen",               "sierkussen"),
    ("Raffgardinenrollo",        "vouwgordijn"),
    ("Wanddekoration",           "wanddecoratie"),
    ("Wanduhr",                  "wandklok"),
    # Tableware
    ("Tellerset",                "bordenset"),
    ("Trinkhalm-Set",            "set rietjes"),
    ("Dekanter",                 "karaf"),
    # Storage
    ("Steckregal",               "opbergrek"),
    ("Kommode",                  "kast"),        # in product name context
    # Outdoor
    ("Gartensitzgruppe",         "tuinset"),
    ("Gartenessgruppe",          "tuinset"),
    # Column labels (appear as "Label:" prefixes in structured data)
    ("Absetzung",                "afwerking"),
    ("Füllung",                  "vulling"),
    ("Abdeckplatte",             "afdekplaat"),
    ("Oberplatte",               "bovenblad"),
    ("Kleiderstange",            "kledingroede"),
    ("Innenstoff",               "binnenstof"),
    ("Belastbarkeit",            "draagkracht"),
    ("Lieferumfang",             "leveringsomvang"),
    ("Inklusive",                "inclusief"),
]

# Forbidden outputs → canonical replacements (detected post-AI, applied as correction)
NL_FORBIDDEN_REPLACEMENTS: list[tuple[str, str]] = [
    # TV furniture wrong forms
    ("TV lowboard",          "Tv-meubel"),
    ("TV-lowboard",          "Tv-meubel"),
    ("televisie meubel",     "Tv-meubel"),
    ("televisie-meubel",     "Tv-meubel"),
    ("televisiemeubel",      "Tv-meubel"),
    ("Televisiemeubel",      "Tv-meubel"),
    # Dekor anti-patterns
    ("eiken decor",          "eikenlook"),
    ("Eiken decor",          "eikenlook"),
    ("decor eik",            "eikenlook"),
    ("Decor eik",            "eikenlook"),
    ("eikenhouten decor",    "eikenhouten look"),
    # vaatwasserfront wrong forms
    ("vaatwasserpaneel",     "vaatwasserfront"),
    ("vaatwasser paneel",    "vaatwasserfront"),
    ("vaatwasser front",     "vaatwasserfront"),
    # Greeploos wrong forms
    ("zonder greep",         "greeploos"),
    ("zonder grepen",        "greeploos"),
    # Rattan/weaving wrong forms
    ("synthetisch rotan",    "kunststof vlechtwerk"),
    ("kunststof rotan",      "kunststof vlechtwerk"),
    # Gepoedercoat wrong form
    ("poedergecoat",         "gepoedercoat"),
    # Incorrect set composition wording
    ("bestaand uit",         "bestaande uit"),
]


# =============================================================================
# FORMAT NORMALIZATION RULES  — derived from TM analysis
# =============================================================================

_NL_PCT_SPACE    = re.compile(r'(\d)\s+%')
_NL_SLASH_SPACES = re.compile(
    r'(?<=[a-zA-Zéàèùâêîôûëïüçœæ\d])\s+/\s+(?=[a-zA-Zéàèùâêîôûëïüçœæ\d])',
    re.UNICODE,
)
_NL_DEKOR_RESIDUE = re.compile(r'\bDekor\b', re.UNICODE)
_NL_BHT    = re.compile(r'\bBHT\b|\bBxHxT\b|B\s*x\s*H\s*x\s*T\b', re.IGNORECASE)
_NL_TEILIG = re.compile(r'(\d+(?:[.,]\d+)?)-?teilig\b', re.IGNORECASE)
_NL_TYP    = re.compile(r'\bTyp\b\s+([A-Z]\b)', re.UNICODE)
_NL_SITZER = re.compile(r'(\d+(?:[.,]5)?)-?[Ss]itzer\b')
_NL_SITZER_SOFA = re.compile(r'(\d+(?:[.,]5)?)-?[Ss]itzer\s+[Ss]ofa\b')
_NL_FLAMMIG    = re.compile(r'(\d+)-flammig\b', re.IGNORECASE)
_NL_PCT_UPPER  = re.compile(r'(\d+%)\s+([A-ZÄÖÜ][a-zäöüß]+)')
_NL_INCL       = re.compile(r'\binklusive\b', re.IGNORECASE)
_NL_INKL       = re.compile(r'\binkl\.\b',    re.IGNORECASE)
_NL_OHNE_DEKO  = re.compile(r'\bohne\s+Dekoration\b', re.IGNORECASE)
_NL_BESTEHEND  = re.compile(r'\bbestehend\s+aus\b', re.IGNORECASE)
_NL_SET_BEST   = re.compile(r'\bSet\s+bestehend\s+aus\b', re.IGNORECASE)


def apply_nl_format_normalization(text: str) -> str:
    """Apply Home24 NL formatting conventions derived from TM corpus."""
    if not text:
        return text
    # Percentage: remove space before %
    text = _NL_PCT_SPACE.sub(r'\1%', text)
    # Lowercase material name after percentage
    text = _NL_PCT_UPPER.sub(lambda m: f"{m.group(1)} {m.group(2).lower()}", text)
    # Slash: no spaces around (color/material combos)
    text = _NL_SLASH_SPACES.sub('/', text)
    # BHT / BxHxT → B x H x D
    text = _NL_BHT.sub('B x H x D', text)
    # Residual "Dekor" → "look"
    text = _NL_DEKOR_RESIDUE.sub('look', text)
    # "3-teilig" → "3-delig"
    text = _NL_TEILIG.sub(lambda m: m.group(1).replace(',', '.') + '-delig', text)
    # "Typ A" → "type A"
    text = _NL_TYP.sub(lambda m: f"type {m.group(1)}", text)
    # "3-Sitzer Sofa" → "3-zitsbank" (combined)
    text = _NL_SITZER_SOFA.sub(lambda m: f"{m.group(1).replace(',', '.')}-zitsbank", text)
    # "3-Sitzer" → "3-zits"
    text = _NL_SITZER.sub(lambda m: f"{m.group(1).replace(',', '.')}-zits", text)
    # "1-flammig" → "1-lichts"
    text = _NL_FLAMMIG.sub(lambda m: f"{m.group(1)}-lichts", text)
    # German connector words that slip through
    text = _NL_SET_BEST.sub('set bestaande uit', text)
    text = _NL_BESTEHEND.sub('bestaande uit', text)
    text = _NL_INCL.sub('inclusief', text)
    text = _NL_INKL.sub('incl.', text)
    text = _NL_OHNE_DEKO.sub('zonder decoratie', text)
    # Collapse extra spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def apply_nl_dekor_patterns(text: str) -> str:
    """Replace German Dekor compounds with canonical NL equivalents."""
    for de_form, nl_form in NL_DEKOR_MAP:
        if de_form.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(de_form) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pat.sub(nl_form, text)
    return text


def apply_nl_color_normalization(text: str) -> str:
    """
    Replace residual German color words in Dutch text with canonical NL forms.
    Applied after AI translation to catch leftover German color terms.
    Safe on Dutch text because the source words are unambiguously German.
    """
    for de_color, nl_color in NL_COLOR_MAP:
        if de_color.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<![a-zäöüß])' + re.escape(de_color) + r'(?![a-zäöüß])', re.IGNORECASE | re.UNICODE)
        text = pat.sub(nl_color, text)
    return text


def apply_nl_furniture_canonical(text: str) -> str:
    """Apply canonical NL furniture name mappings derived from TM."""
    for de_term, nl_term in NL_FURNITURE_CANONICAL:
        if de_term.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(de_term) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pat.sub(nl_term, text)
    return text


def apply_nl_forbidden_patterns(text: str) -> tuple[str, int]:
    """Replace forbidden NL patterns with canonical equivalents."""
    corrections = 0
    for wrong, right in NL_FORBIDDEN_REPLACEMENTS:
        if wrong.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(wrong) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        new = pat.sub(right, text)
        if new != text:
            corrections += 1
            text = new
    return text, corrections


def nl_post_process(text: str) -> str:
    """
    Full Dutch post-processing pipeline (zero API calls).
    Applied after AI translation:
      dekor → colors → furniture → forbidden → format.
    """
    text = apply_nl_dekor_patterns(text)
    text = apply_nl_color_normalization(text)
    text = apply_nl_furniture_canonical(text)
    text = apply_nl_forbidden_patterns(text)[0]
    text = apply_nl_format_normalization(text)
    return text


# =============================================================================
# GERMAN RESIDUE DETECTION (NL-specific)
# =============================================================================

_NL_GERMAN_RESIDUE_RE = re.compile(
    r'\b(?:'
    r'Dekor|Schrank|Tisch|Sofa|Sessel|Leuchte|Lampe|Schublade|Kommode|Bett|Stuhl|'
    r'Regal|Sideboard|Highboard|Spanplatte|Arbeitsplatte|Geschirrspüler|Grifflos|'
    r'Hängeschrank|Oberschrank|Unterschrank|Waschtisch|Waschbecken|Badezimmer|'
    r'Badset|Spiegel|Füße|Füsse|Korpus|Breite|Höhe|Tiefe|Länge|Maße|'
    r'Baumwolle|Polyester|Wolle|Leinen|Viskose|'
    r'Schwarz|Weiß|Grau|Braun|Blau|Grün|Rot|Anthrazit|Graphit|Silber|'
    r'teilig|Sitzer|flammig|Fernsehsessel|Typ\b'
    r')\b',
    re.UNICODE,
)


def detect_nl_german_residue(text: str) -> list[str]:
    """Return list of German words found in NL output."""
    return _NL_GERMAN_RESIDUE_RE.findall(text)


# =============================================================================
# NL QA ENGINE
# =============================================================================

def nl_qa_check(translation: str) -> list[dict]:
    """
    Run QA checks on a Dutch translation.
    Returns list of issues [{severity, category, message}].
    """
    issues = []
    residues = detect_nl_german_residue(translation)
    if residues:
        issues.append({
            "severity": "High",
            "category": "German residue",
            "message":  f"German words in NL output: {', '.join(sorted(set(residues)))}",
        })
    if re.search(r'\bDekor\b', translation, re.UNICODE):
        issues.append({
            "severity": "High",
            "category": "Untranslated term",
            "message":  '"Dekor" not localized → should be "look"',
        })
    if re.search(r'\d\s+%', translation):
        issues.append({
            "severity": "Low",
            "category": "Formatting",
            "message":  'Space before % — should be "100%" not "100 %"',
        })
    if re.search(r'\bBHT\b', translation, re.IGNORECASE):
        issues.append({
            "severity": "Medium",
            "category": "Formatting",
            "message":  "BHT not converted to B x H x D",
        })
    for wrong, _ in NL_FORBIDDEN_REPLACEMENTS:
        if wrong.lower() in translation.lower():
            issues.append({
                "severity": "High",
                "category": "Forbidden pattern",
                "message":  f'Forbidden pattern detected: "{wrong}"',
            })
            break  # one report per cell is enough
    return issues


# =============================================================================
# HOME24 DUTCH CORPUS ENGINE
# =============================================================================

def _normalize(text: str) -> str:
    """Normalize for TM lookup: strip, lowercase, collapse whitespace."""
    return re.sub(r'\s+', ' ', str(text).strip().lower())


class Home24DutchCorpusEngine:
    """
    TM-powered Dutch localization engine.
    Loads ~38k Trados TM entries and provides exact + fuzzy matching plus
    terminology extraction for AI prompt guidance.
    """

    def __init__(self, entries: list[dict]) -> None:
        """
        entries: list of {"source": str, "target": str, "usage_count": int}
        """
        self._exact: dict[str, str] = {}
        # Ordered list of (norm_source, target) for fuzzy scan — sorted by length
        # so shorter, more specific entries (single terms) rank earlier in partial matching
        raw: list[tuple[str, str, int]] = []

        for e in entries:
            src = str(e.get("source", "")).strip()
            tgt = str(e.get("target", "")).strip()
            if not src or not tgt or src == tgt:
                continue
            key = _normalize(src)
            self._exact[key] = tgt
            raw.append((key, tgt, e.get("usage_count", 0)))

        # Sort: higher usage_count first within same length bucket (for fuzzy scan quality)
        raw.sort(key=lambda x: (-len(x[0]), -x[2]))
        self._entries: list[tuple[str, str]] = [(k, t) for k, t, _ in raw]

        # Term index: short TM segments (≤5 tokens) → NL term
        # Used for terminology extraction / prompt injection
        self._term_index: dict[str, str] = {}
        term_candidates: dict[str, list[str]] = {}
        for src_norm, tgt, usage in raw:
            token_count = src_norm.count(' ') + 1
            if 1 <= token_count <= 5:
                term_candidates.setdefault(src_norm, []).append(tgt)
        for src_key, targets in term_candidates.items():
            self._term_index[src_key] = Counter(targets).most_common(1)[0][0]

    # ── Exact match ──────────────────────────────────────────────────────────

    def exact_match(self, source: str) -> str | None:
        """Return exact TM match or None."""
        return self._exact.get(_normalize(source))

    # ── Fuzzy match ──────────────────────────────────────────────────────────

    def fuzzy_match(
        self,
        source: str,
        threshold: float = 0.82,
        max_candidates: int = 600,
    ) -> tuple[str, float] | None:
        """
        Best fuzzy TM match via sequence similarity.
        Returns (translation, score) or None.
        Capped at max_candidates to stay fast on 38k entries.
        """
        src_norm = _normalize(source)
        slen = len(src_norm)
        if slen < 6 or slen > 220:
            return None

        best_score = 0.0
        best_tgt: str | None = None
        checked = 0

        for tm_src, tm_tgt in self._entries:
            # Quick length gate — skip if >45% length difference
            if abs(len(tm_src) - slen) > slen * 0.45 + 5:
                continue
            ratio = SequenceMatcher(None, src_norm, tm_src, autojunk=False).ratio()
            if ratio > best_score:
                best_score = ratio
                best_tgt = tm_tgt
            checked += 1
            if checked >= max_candidates:
                break

        if best_score >= threshold and best_tgt:
            return best_tgt, round(best_score, 3)
        return None

    # ── Terminology extraction ────────────────────────────────────────────────

    def extract_terminology(self, source: str, max_terms: int = 8) -> list[tuple[str, str]]:
        """
        Find TM short-segment matches that appear in source.
        Returns list of (de_term, nl_term) pairs for AI prompt injection.
        """
        results: list[tuple[str, str]] = []
        src_lower = source.lower()
        seen_nl: set[str] = set()

        for tm_src, nl_tgt in self._term_index.items():
            if tm_src in src_lower and nl_tgt not in seen_nl:
                results.append((tm_src, nl_tgt))
                seen_nl.add(nl_tgt)
                if len(results) >= max_terms:
                    break

        return results

    # ── AI prompt guidance ────────────────────────────────────────────────────

    def get_prompt_guidance(self, source: str) -> str:
        """
        Return TM-derived guidance block for injection into the AI system prompt.
        Empty string if no useful TM context found.
        """
        lines: list[str] = []

        # Exact match: tell the AI to use it directly
        exact = self.exact_match(source)
        if exact:
            return (
                f"\nTM EXACT MATCH — reproduce this wording exactly:\n"
                f"  DE: {source}\n"
                f"  NL: {exact}"
            )

        # Fuzzy match ≥ 85%: strong guidance
        fuzzy = self.fuzzy_match(source, threshold=0.85)
        if fuzzy:
            tgt, score = fuzzy
            lines.append(
                f"\nTM FUZZY MATCH ({score:.0%}) — strongly reuse this NL wording:\n"
                f"  NL reference: {tgt}"
            )

        # Terminology extraction
        terms = self.extract_terminology(source, max_terms=6)
        if terms:
            lines.append("\nTM terminology — use these exact NL equivalents:")
            for de, nl in terms:
                lines.append(f'  • "{de}" → "{nl}"')

        return "\n".join(lines)

    # ── Confidence classification ─────────────────────────────────────────────

    def confidence_level(self, source: str) -> str:
        if self.exact_match(source):
            return "EXACT_TM_MATCH"
        if self.fuzzy_match(source, threshold=0.85):
            return "FUZZY_TM_MATCH"
        if self.extract_terminology(source):
            return "AI_GUIDED"
        return "LOW_CONFIDENCE"

    def __len__(self) -> int:
        return len(self._entries)


# =============================================================================
# EXCEL IMPORT HELPER
# =============================================================================

def parse_trados_xlsx(path: str) -> list[dict]:
    """
    Parse Trados TM Export Excel file.
    Returns list of {"source": str, "target": str, "usage_count": int}.
    Skips identical source/target pairs (metadata fields, untranslated rows).
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb["Translation Units"]
    except Exception as exc:
        raise ValueError(f"Cannot read TM file: {exc}") from exc

    entries: list[dict] = []
    header_skipped = False

    for row in ws.iter_rows(values_only=True):
        if not header_skipped:
            header_skipped = True
            continue  # skip header row

        src  = row[1] if len(row) > 1 else None
        tgt  = row[2] if len(row) > 2 else None
        usage = row[7] if len(row) > 7 else 0

        src = str(src).strip() if src is not None else ""
        tgt = str(tgt).strip() if tgt is not None else ""
        if not src or not tgt or src == tgt:
            continue

        entries.append({
            "source":      src,
            "target":      tgt,
            "usage_count": int(usage) if usage and str(usage).isdigit() else 0,
        })

    return entries
