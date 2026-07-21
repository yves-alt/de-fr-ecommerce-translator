"""
Enterprise Translation Pipeline — Scalability Engine

Handles large Excel files (200+ rows), multi-sheet workbooks,
variant-heavy catalogs, and repeated product structures.

Components:
  LargeFileModeConfig       — auto-detects large files and adjusts settings
  SemanticRowClusterer      — groups rows by product family before batching
  WorkbookConsistencyMemory — workbook-global terminology consistency
  build_clustered_batches   — hierarchical batching (cluster → batch → cells)
  qa_cell_needs_ai_fix      — fast multi-layer QA (no API)
  SheetDebugMetrics         — per-sheet stats for admin debug mode
  ColumnHeaderNormalizer    — canonical header normalization
  ColumnClassifier          — classifies headers the known-column registry missed
  TranslationPlanBuilder    — builds the full per-column translation plan
  TranslationCoverageValidator — verifies plan vs. actual results post-translation
"""

import re
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# LARGE FILE MODE — thresholds and config
# =============================================================================

LARGE_FILE_ROW_THRESHOLD   = 200   # rows per translatable sheet
LARGE_FILE_SHEET_THRESHOLD = 2     # number of translatable sheets
LARGE_FILE_BATCH_SIZE      = 8     # smaller batches reduce context pollution
LARGE_FILE_CLUSTER_SIZE    = 25    # max rows per semantic cluster
LARGE_FILE_MAX_CONCURRENT  = 2     # lower concurrency for stability
NORMAL_BATCH_SIZE          = 15
NORMAL_CLUSTER_SIZE        = 50
NORMAL_MAX_CONCURRENT      = 3


class LargeFileModeConfig:
    """Configuration bundle for large file mode. Constructed from row/sheet counts."""

    __slots__ = ("active", "batch_size", "cluster_size", "max_concurrent")

    def __init__(self, row_count: int, sheet_count: int = 1):
        self.active = (
            row_count > LARGE_FILE_ROW_THRESHOLD
            or sheet_count > LARGE_FILE_SHEET_THRESHOLD
        )
        if self.active:
            self.batch_size     = LARGE_FILE_BATCH_SIZE
            self.cluster_size   = LARGE_FILE_CLUSTER_SIZE
            self.max_concurrent = LARGE_FILE_MAX_CONCURRENT
        else:
            self.batch_size     = NORMAL_BATCH_SIZE
            self.cluster_size   = NORMAL_CLUSTER_SIZE
            self.max_concurrent = NORMAL_MAX_CONCURRENT


def detect_large_file_mode(row_count: int, sheet_count: int = 1) -> "LargeFileModeConfig":
    """Return a LargeFileModeConfig for the given workbook dimensions."""
    return LargeFileModeConfig(row_count, sheet_count)


# =============================================================================
# SEMANTIC ROW CLUSTERER
# Groups product rows by semantic similarity for coherent AI batching.
# Prevents kitchen rows mixing with textiles, outdoor with mattresses, etc.
# =============================================================================

_CATEGORY_KW: frozenset = frozenset({
    # Seating
    "sofa", "couch", "sessel", "ecksofa", "schlafsofa", "longchair",
    "recamiere", "ottomane", "polsterecke",
    # Beds
    "bett", "boxspringbett", "polsterbett", "futonbett",
    "einzelbett", "doppelbett", "hochbett",
    # Tables
    "esstisch", "couchtisch", "beistelltisch", "bartisch",
    # Storage
    "kleiderschrank", "kommode", "sideboard", "highboard", "vitrine",
    # Kitchen
    "küche", "küchenzeile", "einbauküche", "küchenblock",
    "geschirrspüler", "geschirrspuler",
    # Bathroom
    "waschbecken", "waschtisch", "badmöbel", "spiegelschrank", "badezimmer",
    # Textiles
    "kissen", "teppich", "vorhang", "bettwäsche", "bettwaesche",
    # Outdoor / garden
    "gartenstuhl", "gartentisch", "gartenmöbel", "loungeset",
    "gartenessgruppe", "gartenset", "terrassenset", "gartensofa",
    # Lighting
    "lampe", "leuchte", "pendelleuchte",
    # Mattress
    "matratze", "taschenfederkern", "kaltschaum",
    # Tableware
    "geschirr", "teller", "porzellan", "geschirrset",
    # Carpet / rugs / floor textiles
    "fußmatte", "fussmatte", "läufer", "laufer",
    "hochflorteppich", "kurzflorteppich", "teppichläufer",
    "sisalteppich", "juteteppich", "kuhfellteppich",
    "schaffell", "kunstfell",
})

_WORD_SPLIT_RE = re.compile(r'[^\wäöüÄÖÜß]+')


def _extract_cluster_key(texts: list) -> str:
    """
    Return a semantic cluster key from a list of cell values from one row.
    Priority: category keyword > first two significant product-name words > generic.
    """
    sorted_texts = sorted(
        (t for t in texts if t and len(t.strip()) > 3),
        key=len, reverse=True,
    )
    if not sorted_texts:
        return "__generic__"

    name_text = sorted_texts[0].lower()
    words = _WORD_SPLIT_RE.split(name_text)

    for word in words:
        clean = re.sub(r'[^a-zäöüß]', '', word)
        if len(clean) >= 4 and clean in _CATEGORY_KW:
            return clean

    sig_words = [w for w in words[:6] if len(w) > 2][:2]
    return " ".join(sig_words) if sig_words else "__generic__"


class SemanticRowClusterer:
    """
    Groups cells_queue rows into semantic clusters before AI batching.

    Each cluster contains rows with similar product names / categories.
    Within a cluster rows share context, so the AI prompt stays coherent.
    Large clusters are split into sub-chunks bounded by max_cluster_size.
    """

    def __init__(self, max_cluster_size: int = LARGE_FILE_CLUSTER_SIZE):
        self.max_cluster_size = max_cluster_size

    def cluster(self, cells_queue: list) -> list:
        """
        cells_queue: list of (row_num, col_header, col_idx, canonical, text)
        Returns: list of clusters, each a list of cells_queue items.
        """
        row_texts: dict  = defaultdict(list)
        row_items: dict  = defaultdict(list)

        for item in cells_queue:
            row_num = item[0]
            text    = item[4]
            row_texts[row_num].append(text)
            row_items[row_num].append(item)

        row_cluster_key: dict = {
            row_num: _extract_cluster_key(texts)
            for row_num, texts in row_texts.items()
        }

        cluster_rows: dict = defaultdict(list)
        for row_num, key in row_cluster_key.items():
            cluster_rows[key].append(row_num)

        result = []
        for key in cluster_rows:
            cluster_items = []
            for row_num in sorted(cluster_rows[key]):
                cluster_items.extend(row_items[row_num])
            for i in range(0, len(cluster_items), self.max_cluster_size):
                result.append(cluster_items[i : i + self.max_cluster_size])

        return result


def build_clustered_batches(
    final_api_queue: list,
    batch_size: int,
    cluster_first: bool = True,
    max_cluster_size: int = LARGE_FILE_CLUSTER_SIZE,
) -> tuple:
    """
    Build the batch list from the API queue.

    cluster_first=True (large file mode):
      Rows → semantic clusters → within each cluster: group by canonical type → batches.
      Keeps related products in the same AI call for better context quality.

    cluster_first=False (legacy):
      Group by canonical type only, then split into batches.

    Returns:
      (batch_list, cluster_count)
      batch_list: list of (batch_items, canonical_used)
    """
    if not cluster_first:
        by_col_type: dict = defaultdict(list)
        for item in final_api_queue:
            by_col_type[item[3]].append(item)
        batch_list = []
        for canonical, items in by_col_type.items():
            for i in range(0, len(items), batch_size):
                chunk = items[i : i + batch_size]
                batch_list.append((chunk, chunk[0][3]))
        return batch_list, 0

    clusterer = SemanticRowClusterer(max_cluster_size=max_cluster_size)
    clusters  = clusterer.cluster(final_api_queue)

    batch_list = []
    for cluster in clusters:
        by_col_type_in_cluster: dict = defaultdict(list)
        for item in cluster:
            by_col_type_in_cluster[item[3]].append(item)
        for canonical, items in by_col_type_in_cluster.items():
            for i in range(0, len(items), batch_size):
                chunk = items[i : i + batch_size]
                batch_list.append((chunk, canonical))

    return batch_list, len(clusters)


# =============================================================================
# WORKBOOK CONSISTENCY MEMORY
# Tracks translations produced during a single workbook session.
# Enforces: same (source, canonical) → same translation workbook-wide.
# Prevents "Bettwäsche Banda" becoming "linge de lit Banda" in row 12 and
# "housse de lit Banda" in row 87.
# =============================================================================

class WorkbookConsistencyMemory:
    """
    Workbook-level translation consistency tracker.

    Stored as a Streamlit session_state singleton so it persists across
    multiple sheet translations within the same upload session.

    Thread-safe (batch translation runs in ThreadPoolExecutor).
    """

    def __init__(self):
        self._memory: dict  = {}    # (norm_source, canonical) → translation
        self._conflicts     = 0
        self._enforcements  = 0
        self._lock          = threading.Lock()

    def record(self, source: str, canonical: str, translation: str) -> None:
        """Record a translation (first-seen wins, no overwrite)."""
        if not source.strip() or not translation.strip():
            return
        key = (source.strip().lower(), canonical)
        with self._lock:
            self._memory.setdefault(key, translation.strip())

    def enforce(self, source: str, canonical: str, translation: str) -> str:
        """
        Return the canonical translation for this source+canonical pair.
        If a previous translation was already recorded, return that one.
        Otherwise record this translation and return it unchanged.
        """
        if not source.strip():
            return translation
        key = (source.strip().lower(), canonical)
        with self._lock:
            if key in self._memory:
                existing = self._memory[key]
                if existing != translation.strip():
                    self._conflicts += 1
                self._enforcements += 1
                return existing
            self._memory[key] = translation.strip()
            return translation

    def lookup(self, source: str, canonical: str) -> Optional[str]:
        """Return the recorded translation or None (no side effects)."""
        key = (source.strip().lower(), canonical)
        with self._lock:
            return self._memory.get(key)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "terms_tracked":  len(self._memory),
                "conflicts":      self._conflicts,
                "enforcements":   self._enforcements,
            }

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            self._conflicts    = 0
            self._enforcements = 0


# =============================================================================
# MULTI-LAYER QA (no API)
# Layer 1: Fast regex residue check
# Layer 2: Forbidden pattern check
# Layer 3 is the existing AI residue-fix — called only when L1 or L2 fires.
# =============================================================================

_L1_RESIDUE_RE = re.compile(
    r'\b(?:'
    # Dimensions / measurements
    r'Maße|Breite|Höhe|Tiefe|Länge|'
    # Furniture parts
    r'Bezug|Gestell|Füße|Schublade|Schubladen|Türen|Tür|'
    r'Polster|Lehne|Armlehne|Armlehnen|Rücken|Beine|Sitz|'
    # Materials
    r'Holz|Metall|Kunststoff|Stoff|Leder|Glas|Spanplatte|'
    r'Webstoff|Strukturstoff|Samtstoff|Massivholz|Furnier|'
    r'lackiert|geölt|gebeizt|'
    # Wood species
    r'Eiche|Buche|Kiefer|Nussbaum|Ahorn|Birke|'
    # Colors that are unambiguously German
    r'dunkelgrau|hellgrau|dunkelbraun|hellbraun|dunkelblau|hellblau|'
    r'Anthrazit|weiß|weiss|schwarz|grün|blau|grau|braun|'
    # Textiles
    r'Bettwäsche|Baumwolle|Leinen|Wolle|Polyester|Viskose|'
    # Product names
    r'Sofa|Sessel|Schrank|Kommode|Regal|Lampe|Bett|Stuhl|'
    # Descriptors
    r'teilig|Sitzer|höhenverstellbar|ausziehbar|klappbar|'
    r'Lieferumfang|Hinweis|Achtung|'
    # Outdoor
    r'Loungeset|Sofaelement|Gartenessgruppe|Gartenset|'
    r'Gartenstuhl|Gartentisch|Gartenmöbel|'
    # Materials / finishes
    r'pulverbeschichtet|Geflecht|Polyrattan|Flechtwerk|'
    # Mattress
    r'Taschenfederkern|Kokosmatte|Reißverschluss|Doppeltuch|'
    # Kitchen / bathroom
    r'Küchenzeile|Einbauküche|Arbeitsplatte|Grifflos|grifflos|'
    r'Waschtisch|Waschbecken|Unterflurauszug|'
    # Carpet / rug / floor textile types
    r'Fußmatte|Fussmatte|Hochflorteppich|Kurzflorteppich|Teppichläufer|'
    r'Sisalteppich|Juteteppich|Kuhfellteppich|Schaffell|Kunstfell|'
    r'Läufer|Teppich|'
    # Textile composition materials (German terms that must not appear in French output)
    r'Polypropylen|Polyamid|Modacryl|Kokosfaser|Kokos|Gummi|Mikrofaser|'
    r'Elfenbein|Puderrosa|'
    # Dimension abbreviations
    r'BHT|BxHxT'
    r')\b',
    re.UNICODE,
)

_L1_ACCEPTABLE = frozenset({
    # Colors same in German and French
    "beige", "taupe",
    # Product/style terms used unchanged
    "set", "bouclé", "boucle", "velours",
    # Textile materials valid in both languages
    "polyester", "polyamide", "viscose", "modacrylique", "polypropylène",
    "coco", "caoutchouc", "latex", "nylon", "sisal", "jute", "chenille",
    "microfibre",
    # Glass/other materials
    "glas", "creme",
    # Common adjectives
    "klein",
    # Color/term abbreviations
    "multi",
})


def qa_layer1_residue(text: str) -> bool:
    """Layer 1: True if German residue found (fast regex, no API)."""
    if not text:
        return False
    text_lower = text.lower()
    # Skip if the only match is an acceptable bilingual word
    for word in _L1_ACCEPTABLE:
        if word in text_lower and not _L1_RESIDUE_RE.search(
            re.sub(r'\b' + re.escape(word) + r'\b', '', text, flags=re.IGNORECASE)
        ):
            return False
    return bool(_L1_RESIDUE_RE.search(text))


def qa_layer2_forbidden(text: str, forbidden_patterns: list) -> bool:
    """Layer 2: True if a forbidden pattern found (dict lookup, no API)."""
    if not text or not forbidden_patterns:
        return False
    text_lower = text.lower()
    return any(
        p.get("forbidden_text", "").lower() in text_lower
        for p in forbidden_patterns
    )


def qa_cell_needs_ai_fix(
    text: str,
    forbidden_patterns: list,
) -> tuple:
    """
    Run L1 + L2 QA.
    Returns (needs_ai_fix: bool, issues: list[str]).
    Caller runs AI fix only when needs_ai_fix is True.
    """
    issues = []
    if qa_layer1_residue(text):
        issues.append("german_residue")
    if qa_layer2_forbidden(text, forbidden_patterns):
        issues.append("forbidden_pattern")
    return bool(issues), issues


# =============================================================================
# PER-SHEET DEBUG METRICS  (visible in admin debug mode only)
# =============================================================================

class SheetDebugMetrics:
    """
    Collects per-sheet processing metrics.
    Displayed in the admin debug panel after translation.
    """

    def __init__(self, sheet_name: str):
        self.sheet_name        = sheet_name
        self.rows              = 0
        self.cells_total       = 0
        self.tm_hits           = 0
        self.trados_exact      = 0
        self.trados_fuzzy      = 0
        self.glossary_only     = 0
        self.pattern           = 0
        self.semantic_tm       = 0
        self.ai_cells          = 0
        self.retry_count       = 0
        self.residue_count     = 0
        self.failed_batches    = 0
        self.consistency_fixes = 0
        self.processing_time   = 0.0
        self.cluster_count     = 0
        self.large_file_mode   = False

    @property
    def tm_hit_pct(self) -> float:
        total = self.cells_total or 1
        served_from_tm = (
            self.tm_hits + self.trados_exact + self.trados_fuzzy
            + self.glossary_only + self.pattern + self.semantic_tm
        )
        return round(100 * served_from_tm / total, 1)

    @property
    def ai_pct(self) -> float:
        return round(100 * self.ai_cells / max(self.cells_total, 1), 1)

    def to_dict(self) -> dict:
        return {
            "Sheet":             self.sheet_name,
            "Rows":              self.rows,
            "Cells":             self.cells_total,
            "TM hit %":          f"{self.tm_hit_pct}%",
            "AI generated %":    f"{self.ai_pct}%",
            "Clusters":          self.cluster_count,
            "Trados exact":      self.trados_exact,
            "Trados fuzzy":      self.trados_fuzzy,
            "Glossary-only":     self.glossary_only,
            "Pattern":           self.pattern,
            "Semantic TM":       self.semantic_tm,
            "Retries":           self.retry_count,
            "Residue cells":     self.residue_count,
            "Failed batches":    self.failed_batches,
            "Consistency fixes": self.consistency_fixes,
            "Time (s)":          round(self.processing_time, 1),
            "Large file mode":   "Yes" if self.large_file_mode else "No",
        }


# =============================================================================
# DYNAMIC COLUMN CLASSIFICATION
#
# The known-column registry (app.py: HOME24_TRANSLATABLE_CANONICAL, T1/T2/T3
# aliases, PROTECTED_SUBSTRINGS/EXACT) stays authoritative for headers it
# recognizes — none of that changes. This section only handles what's left
# over: headers that registry doesn't match at all. Historically those were
# silently dropped ("ignored"). Instead of ignoring them, ColumnClassifier
# inspects the header *and* a sample of its actual cell values to decide
# whether it's translatable content, a technical/protected field, empty, or
# genuinely ambiguous — so new Home24 columns are handled automatically
# instead of requiring a code change every time.
# =============================================================================

class ColumnType(Enum):
    PRODUCT_NAME        = "product_name"        # the "name" column specifically
    KNOWN_CONTENT        = "known_content"        # matched the existing registry
    UNKNOWN_CONTENT      = "unknown_content"       # new descriptive column, detected dynamically
    PROTECTED_METADATA   = "protected_metadata"    # business identifier — never touched
    TECHNICAL_DATA        = "technical_data"        # URL/date/hash/code-shaped values — never touched
    EMPTY                = "empty"                # no non-empty sample values found
    AMBIGUOUS             = "ambiguous"             # mixed signals — needs human confirmation


class TranslationProfile(Enum):
    PRODUCT_NAME               = "product_name"                 # 40-char limit + compression engine
    KNOWN_SPECIALIZED          = "known_specialized"             # existing per-column prompt (materialDetail, etc.)
    GENERIC_HOME24_DESCRIPTION = "generic_home24_description"    # safe default for unknown content columns
    NONE                       = "none"                          # not translated


@dataclass
class ColumnClassification:
    """Result of classifying a single header (+ its sample values)."""
    header: str
    normalized_header: str
    column_type: ColumnType
    confidence: str          # "high" | "medium" | "low"
    reason: str
    translatable: bool
    profile: TranslationProfile = TranslationProfile.NONE
    non_empty_samples: int = 0
    sample_size: int = 0


class ColumnHeaderNormalizer:
    """
    Canonical header normalization: lowercase, trim, collapse whitespace,
    split camelCase/PascalCase/snake_case into words, strip accents and
    invisible/control characters. Same algorithm app.py's column-matching
    registry relies on — kept here as the single source of truth so the
    dynamic classifier and the known-column matcher never disagree on what
    a given header normalizes to.
    """

    _INVISIBLE_RE = re.compile(r'[\n\r\t\xa0​‌‍﻿]')
    _LOWER_UPPER_RE = re.compile(r'([a-z])([A-Z])')
    _ACRONYM_RE = re.compile(r'([A-Z]+)([A-Z][a-z])')
    _LETTER_DIGIT_RE = re.compile(r'([a-zA-Z])(\d)')
    _DIGIT_LETTER_RE = re.compile(r'(\d)([a-zA-Z])')
    _SEPARATOR_RE = re.compile(r'[_\-.]')

    def normalize(self, raw) -> str:
        text = str(raw)
        text = self._INVISIBLE_RE.sub(' ', text)
        text = ''.join(
            c for c in text
            if unicodedata.category(c) not in ('Cc', 'Cf') or c == ' '
        )
        text = self._LOWER_UPPER_RE.sub(r'\1 \2', text)
        text = self._ACRONYM_RE.sub(r'\1 \2', text)
        text = self._LETTER_DIGIT_RE.sub(r'\1 \2', text)
        text = self._DIGIT_LETTER_RE.sub(r'\1 \2', text)
        text = self._SEPARATOR_RE.sub(' ', text)
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        return ' '.join(text.split()).lower()


# Header tokens (after normalization, which space-separates camelCase/
# snake_case — so only single-word tokens are ever reachable here) that
# suggest a business identifier — never translated even if not already
# caught by the existing PROTECTED_SUBSTRINGS/PROTECTED_EXACT lists.
_PROTECTED_HEADER_TOKENS = frozenset({
    "id", "key", "code", "sku", "gtin", "ean", "number", "nr", "ref",
    "reference", "guid", "uuid",
})

# Header tokens suggesting technical/system data rather than a business
# identifier — same "never translate" outcome, different reporting label.
_TECHNICAL_HEADER_TOKENS = frozenset({
    "url", "uri", "link", "date", "datetime", "timestamp", "locale",
    "lang", "language", "token", "hash", "path", "email", "status",
    "flag", "boolean", "currency", "price", "vat", "tax",
})

_URL_RE      = re.compile(r'^(https?://|www\.)', re.IGNORECASE)
_EMAIL_RE    = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_DATE_RE     = re.compile(
    r'^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?Z?)?$'
    r'|^\d{1,2}[./]\d{1,2}[./]\d{2,4}$'
)
_HASH_RE       = re.compile(r'^[0-9a-fA-F]{16,}$')
_BOOLEAN_RE    = re.compile(r'^(true|false|ja|nein|yes|no)$', re.IGNORECASE)
_PURE_VALUE_RE = re.compile(r'^[\d\s.,%€$£/\-+()]+$')
_CODE_RE       = re.compile(r'^[A-Z0-9][A-Z0-9\-_./]{2,}$')  # no lowercase, no spaces

_GERMAN_STOPWORDS = frozenset({
    "und", "oder", "mit", "fur", "aus", "bei", "zur", "zum", "von", "vom",
    "der", "die", "das", "ist", "sind", "wird", "werden", "auch", "sehr",
    "nicht", "mehr", "alle", "diese", "dieser", "eine", "einen", "einer",
    "kann", "durch", "nach", "beim", "sowie", "inkl", "ohne", "uber",
    "im", "am", "als", "wie", "bis", "um",
})

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def _looks_technical(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if _URL_RE.search(v) or _EMAIL_RE.match(v) or _DATE_RE.match(v):
        return True
    if _HASH_RE.match(v) or _BOOLEAN_RE.match(v):
        return True
    if _PURE_VALUE_RE.match(v):
        return True
    # Short token, no spaces, no lowercase — reads as a code, not a word
    if len(v) <= 30 and ' ' not in v and not any(c.islower() for c in v) and any(c.isalnum() for c in v):
        return True
    if ' ' not in v and _CODE_RE.match(v):
        return True
    return False


def _looks_like_prose(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if _looks_technical(v):
        return False  # a URL/email/code is never prose, even if it contains letter runs
    words = _WORD_RE.findall(v)
    if len(words) < 2:
        return False
    avg_len = sum(len(w) for w in words) / len(words)
    if not (2.5 <= avg_len <= 15):
        return False
    lower_words = {w.lower() for w in words}
    return bool(lower_words & _GERMAN_STOPWORDS) or len(words) >= 3


class ColumnClassifier:
    """
    Classifies a header that the known-column registry did NOT match, using
    the header text plus a sample of its actual (non-empty) cell values.
    Never asked to reclassify a header the registry already resolved —
    that specialized behavior is untouched.
    """

    def __init__(self, normalizer: Optional[ColumnHeaderNormalizer] = None):
        self.normalizer = normalizer or ColumnHeaderNormalizer()

    def classify(self, header: str, samples: list) -> ColumnClassification:
        normalized = self.normalizer.normalize(header)
        header_tokens = set(normalized.split())

        non_empty = [str(s).strip() for s in samples if s is not None and str(s).strip()]
        sample_size = len(samples)

        if not non_empty:
            return ColumnClassification(
                header, normalized, ColumnType.EMPTY, "high",
                "No non-empty sample values found in this column",
                translatable=False, profile=TranslationProfile.NONE,
                non_empty_samples=0, sample_size=sample_size,
            )

        header_protected_like  = bool(header_tokens & _PROTECTED_HEADER_TOKENS)
        header_technical_like  = bool(header_tokens & _TECHNICAL_HEADER_TOKENS)

        n = len(non_empty)
        technical_hits = sum(1 for v in non_empty if _looks_technical(v))
        prose_hits     = sum(1 for v in non_empty if _looks_like_prose(v))
        technical_ratio = technical_hits / n
        prose_ratio     = prose_hits / n

        def result(column_type, confidence, reason, translatable, profile):
            return ColumnClassification(
                header, normalized, column_type, confidence, reason, translatable,
                profile=profile, non_empty_samples=n, sample_size=sample_size,
            )

        # Too little data to trust a ratio — fall back to the header alone,
        # or admit we don't know, before any value-based branch below runs
        # (a single sample can otherwise produce a spurious 100% ratio).
        if n < 2:
            if header_protected_like or header_technical_like:
                label = ColumnType.PROTECTED_METADATA if header_protected_like else ColumnType.TECHNICAL_DATA
                return result(
                    label, "medium",
                    "Header name matches a known identifier/technical pattern "
                    "(too few sampled values to confirm from data alone)",
                    translatable=False, profile=TranslationProfile.NONE,
                )
            return result(
                ColumnType.AMBIGUOUS, "low",
                f"Only {n} non-empty sample value(s) available — not enough to classify confidently",
                translatable=False, profile=TranslationProfile.NONE,
            )

        # Mixed value-level signal beats any single-sided claim, including
        # the header — a column that's half codes and half prose genuinely
        # needs a human to look at it, regardless of what its header says.
        if technical_ratio >= 0.3 and prose_ratio >= 0.3:
            return result(
                ColumnType.AMBIGUOUS, "low",
                f"Mixed signals: {technical_hits}/{n} sampled values look technical, "
                f"{prose_hits}/{n} look like descriptive text",
                translatable=False, profile=TranslationProfile.NONE,
            )

        # Strong, one-sided value-level signal.
        if technical_ratio >= 0.7:
            label = ColumnType.PROTECTED_METADATA if header_protected_like else ColumnType.TECHNICAL_DATA
            return result(
                label, "high",
                f"{technical_hits}/{n} sampled values look like technical data "
                f"(IDs, URLs, dates, codes, booleans, or pure numbers)",
                translatable=False, profile=TranslationProfile.NONE,
            )

        if prose_ratio >= 0.6:
            return result(
                ColumnType.UNKNOWN_CONTENT, "high",
                f"{prose_hits}/{n} sampled values look like descriptive German text",
                translatable=True, profile=TranslationProfile.GENERIC_HOME24_DESCRIPTION,
            )

        # Weaker/no value signal — fall back to the header as a prior.
        if header_protected_like or header_technical_like:
            label = ColumnType.PROTECTED_METADATA if header_protected_like else ColumnType.TECHNICAL_DATA
            return result(
                label, "medium",
                "Header name matches a known identifier/technical pattern "
                "(sampled values were not conclusive on their own)",
                translatable=False, profile=TranslationProfile.NONE,
            )

        if prose_ratio > technical_ratio and prose_ratio >= 0.4:
            return result(
                ColumnType.UNKNOWN_CONTENT, "medium",
                f"{prose_hits}/{n} sampled values look descriptive; no conflicting technical signal",
                translatable=True, profile=TranslationProfile.GENERIC_HOME24_DESCRIPTION,
            )

        return result(
            ColumnType.AMBIGUOUS, "low",
            f"Inconclusive: {technical_hits}/{n} technical-looking, {prose_hits}/{n} descriptive-looking",
            translatable=False, profile=TranslationProfile.NONE,
        )


@dataclass
class TranslationPlanEntry:
    """One row of the Translation Plan (spec item 8)."""
    header: str
    normalized_header: str
    column_type: ColumnType
    action: str              # "Translate" | "Preserve" | "Awaiting review"
    profile: TranslationProfile
    reason: str
    non_empty_cells: int
    expected_translations: int
    confidence: str = "high"


class TranslationPlanBuilder:
    """
    Builds the full Translation Plan for a workbook: the existing known-
    column classification is taken as-is (protected + recognized content
    columns keep their exact current behavior); every header that fell
    through to "ignored" is re-examined by ColumnClassifier using sampled
    cell values, and the plan records an explicit action + reason for it —
    nothing is silently skipped.
    """

    def __init__(self, classifier: Optional[ColumnClassifier] = None):
        self.classifier = classifier or ColumnClassifier()

    def build(
        self,
        classification: dict,
        column_samples: dict,
        column_nonempty_counts: dict,
    ) -> dict:
        """
        classification: output of app.py's classify_columns() —
            {"to_translate": {header: (col_idx, canonical)}, "protected": {...},
             "ignored": {header: col_idx}, ...}
        column_samples: {header: [sample values]} for headers in "ignored"
        column_nonempty_counts: {header: total non-empty cell count} for ALL headers

        Returns a dict with:
          "to_translate"       — extended copy, newly-detected content columns added (canonical="other")
          "protected"          — extended copy, newly-detected technical/protected columns added
          "plan"                — list[TranslationPlanEntry], one per non-empty column
          "needs_confirmation" — {header: ColumnClassification} for AMBIGUOUS columns
          "summary"             — counts for the analysis panel (spec item 10)
        """
        to_translate = dict(classification.get("to_translate", {}))
        protected    = dict(classification.get("protected", {}))
        ignored      = classification.get("ignored", {})

        plan: list[TranslationPlanEntry] = []
        needs_confirmation: dict[str, ColumnClassification] = {}
        newly_detected_content: list[str] = []
        additional_protected: list[str] = []
        additional_technical: list[str] = []

        for header, (col_idx, canonical) in to_translate.items():
            non_empty = column_nonempty_counts.get(header, 0)
            profile = (
                TranslationProfile.PRODUCT_NAME if canonical == "name"
                else TranslationProfile.KNOWN_SPECIALIZED
            )
            col_type = ColumnType.PRODUCT_NAME if canonical == "name" else ColumnType.KNOWN_CONTENT
            plan.append(TranslationPlanEntry(
                header=header, normalized_header=classification.get("normalized_map", {}).get(header, ""),
                column_type=col_type, action="Translate", profile=profile,
                reason=f"Matched the known Home24 '{canonical}' column pattern",
                non_empty_cells=non_empty, expected_translations=non_empty,
            ))

        for header in protected:
            non_empty = column_nonempty_counts.get(header, 0)
            plan.append(TranslationPlanEntry(
                header=header, normalized_header=classification.get("normalized_map", {}).get(header, ""),
                column_type=ColumnType.PROTECTED_METADATA, action="Preserve",
                profile=TranslationProfile.NONE,
                reason="Recognized protected identifier",
                non_empty_cells=non_empty, expected_translations=0,
            ))

        for header, col_idx in ignored.items():
            samples = column_samples.get(header, [])
            result = self.classifier.classify(header, samples)
            non_empty = column_nonempty_counts.get(header, result.non_empty_samples)

            if result.column_type == ColumnType.EMPTY:
                plan.append(TranslationPlanEntry(
                    header=header, normalized_header=result.normalized_header,
                    column_type=ColumnType.EMPTY, action="Preserve",
                    profile=TranslationProfile.NONE, reason=result.reason,
                    non_empty_cells=0, expected_translations=0,
                ))
                continue

            if result.column_type == ColumnType.AMBIGUOUS:
                needs_confirmation[header] = result
                plan.append(TranslationPlanEntry(
                    header=header, normalized_header=result.normalized_header,
                    column_type=ColumnType.AMBIGUOUS, action="Awaiting review",
                    profile=TranslationProfile.NONE, reason=result.reason,
                    non_empty_cells=non_empty, expected_translations=0,
                    confidence=result.confidence,
                ))
                continue

            if result.translatable:
                to_translate[header] = (col_idx, "other")
                newly_detected_content.append(header)
                plan.append(TranslationPlanEntry(
                    header=header, normalized_header=result.normalized_header,
                    column_type=ColumnType.UNKNOWN_CONTENT, action="Translate",
                    profile=result.profile, reason=result.reason,
                    non_empty_cells=non_empty, expected_translations=non_empty,
                    confidence=result.confidence,
                ))
            else:
                protected[header] = col_idx
                if result.column_type == ColumnType.PROTECTED_METADATA:
                    additional_protected.append(header)
                else:
                    additional_technical.append(header)
                plan.append(TranslationPlanEntry(
                    header=header, normalized_header=result.normalized_header,
                    column_type=result.column_type, action="Preserve",
                    profile=TranslationProfile.NONE, reason=result.reason,
                    non_empty_cells=non_empty, expected_translations=0,
                    confidence=result.confidence,
                ))

        summary = {
            "known_translatable_columns": sum(
                1 for e in plan if e.column_type in (ColumnType.KNOWN_CONTENT, ColumnType.PRODUCT_NAME)
            ),
            "additional_content_columns": len(newly_detected_content),
            "protected_metadata_columns": sum(
                1 for e in plan if e.column_type == ColumnType.PROTECTED_METADATA
            ),
            "technical_columns_preserved": sum(
                1 for e in plan if e.column_type == ColumnType.TECHNICAL_DATA
            ),
            "columns_requiring_review": len(needs_confirmation),
            "newly_detected_content_columns": newly_detected_content,
            "additional_protected_columns": additional_protected,
            "additional_technical_columns": additional_technical,
        }

        return {
            "to_translate":       to_translate,
            "protected":          protected,
            "plan":               plan,
            "needs_confirmation": needs_confirmation,
            "summary":            summary,
        }


class TranslationCoverageValidator:
    """
    Post-translation check (spec item 11): for every column the plan marked
    "Translate", verify every non-empty source cell produced a result.
    Anything missing is reported with column, row, source value and reason —
    never silently dropped.
    """

    def validate(
        self,
        plan: list,
        cells_queue: list,
        results: dict,
    ) -> list:
        """
        cells_queue: list of (row_num, col_header, col_idx, canonical, text)
        results: {(row_num, col_idx): translation}

        Returns a list of failure dicts: {column, row, source_value, reason}.
        Empty list means coverage is clean.
        """
        translatable_headers = {e.header for e in plan if e.action == "Translate"}
        failures = []
        for row_num, col_header, col_idx, canonical, text in cells_queue:
            if col_header not in translatable_headers:
                continue
            if not text or not text.strip():
                continue
            result = results.get((row_num, col_idx))
            if result is None:
                failures.append({
                    "column": col_header, "row": row_num, "source_value": text,
                    "reason": "Cell was queued for translation but produced no result",
                })
            elif not str(result).strip():
                failures.append({
                    "column": col_header, "row": row_num, "source_value": text,
                    "reason": "Cell was translated to an empty value",
                })
        return failures
