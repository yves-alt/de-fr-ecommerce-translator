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
"""

import re
import threading
from collections import Counter, defaultdict
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
    # Dimension abbreviations
    r'BHT|BxHxT'
    r')\b',
    re.UNICODE,
)

_L1_ACCEPTABLE = frozenset({
    "beige", "taupe", "polyester", "set", "velours",
    "glas", "creme", "klein", "bouclé", "boucle",
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
