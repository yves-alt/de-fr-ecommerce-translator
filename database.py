"""
SQLite database backend for the DE→FR Translator.
Replaces translation_history.json, translation_memory.json, and glossary.json.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "localization_platform.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    email      TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translation_jobs (
    id                        TEXT PRIMARY KEY,
    datetime                  TEXT NOT NULL,
    original_filename         TEXT,
    output_filename           TEXT,
    sheet_name                TEXT,
    source_language           TEXT DEFAULT 'German',
    target_language           TEXT DEFAULT 'French',
    cells_translated          INTEGER DEFAULT 0,
    cells_skipped             INTEGER DEFAULT 0,
    residue_corrections       INTEGER DEFAULT 0,
    unresolved_warnings       INTEGER DEFAULT 0,
    processing_time_seconds   REAL DEFAULT 0,
    processing_time_formatted TEXT,
    estimated_cost_usd        REAL,
    prompt_tokens             INTEGER,
    completion_tokens         INTEGER,
    tm_hits                   INTEGER DEFAULT 0,
    tm_misses                 INTEGER DEFAULT 0,
    batch_count               INTEGER DEFAULT 0,
    avg_batch_size            REAL DEFAULT 0,
    api_calls_reduced         INTEGER DEFAULT 0,
    glossary_hits             INTEGER DEFAULT 0,
    review_count              INTEGER DEFAULT 0,
    retry_count               INTEGER DEFAULT 0,
    critical_warnings         INTEGER DEFAULT 0,
    high_warnings             INTEGER DEFAULT 0,
    medium_warnings           INTEGER DEFAULT 0,
    low_warnings              INTEGER DEFAULT 0,
    total_warnings            INTEGER DEFAULT 0,
    quality_score             INTEGER DEFAULT 100,
    warning_categories        TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS review_warnings (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES translation_jobs(id),
    severity        TEXT NOT NULL,
    category        TEXT,
    row             INTEGER,
    col_name        TEXT,
    source_text     TEXT,
    translated_text TEXT,
    reason          TEXT,
    suggested_fix   TEXT,
    timestamp       TEXT
);

CREATE TABLE IF NOT EXISTS translation_memory (
    tm_key      TEXT PRIMARY KEY,
    translation TEXT NOT NULL,
    col_type    TEXT,
    created_at  TEXT,
    hit_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS glossary_terms (
    de_term    TEXT PRIMARY KEY,
    fr_term    TEXT NOT NULL,
    hit_count  INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS app_metrics (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def _db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(default_glossary: dict | None = None) -> None:
    with _db() as conn:
        conn.executescript(_SCHEMA)
    _migrate_json_if_needed()
    if default_glossary:
        _seed_glossary_if_empty(default_glossary)


# =============================================================================
# HISTORY
# =============================================================================

def db_load_history() -> list:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM translation_jobs ORDER BY datetime DESC"
            ).fetchall()
        result = []
        for row in rows:
            rec = dict(row)
            if rec.get("warning_categories"):
                try:
                    rec["warning_categories"] = json.loads(rec["warning_categories"])
                except (json.JSONDecodeError, TypeError):
                    rec["warning_categories"] = {}
            result.append(rec)
        return result
    except Exception:
        return []


def db_save_history_record(record: dict) -> None:
    wc = record.get("warning_categories", {})
    wc_json = json.dumps(wc if isinstance(wc, dict) else {}, ensure_ascii=False)

    params = (
        record.get("id") or str(uuid.uuid4()),
        record.get("datetime", ""),
        record.get("original_filename"),
        record.get("output_filename"),
        record.get("sheet_name"),
        record.get("source_language", "German"),
        record.get("target_language", "French"),
        record.get("cells_translated", 0),
        record.get("cells_skipped", 0),
        record.get("residue_corrections", 0),
        record.get("unresolved_warnings", 0),
        record.get("processing_time_seconds", 0),
        record.get("processing_time_formatted"),
        record.get("estimated_cost_usd"),
        record.get("prompt_tokens"),
        record.get("completion_tokens"),
        record.get("tm_hits", 0),
        record.get("tm_misses", 0),
        record.get("batch_count", 0),
        record.get("avg_batch_size", 0.0),
        record.get("api_calls_reduced", 0),
        record.get("glossary_hits", 0),
        record.get("review_count", 0),
        record.get("retry_count", 0),
        record.get("critical_warnings", 0),
        record.get("high_warnings", 0),
        record.get("medium_warnings", 0),
        record.get("low_warnings", 0),
        record.get("total_warnings", 0),
        record.get("quality_score", 100),
        wc_json,
    )

    try:
        with _db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO translation_jobs (
                    id, datetime, original_filename, output_filename,
                    sheet_name, source_language, target_language,
                    cells_translated, cells_skipped, residue_corrections,
                    unresolved_warnings, processing_time_seconds,
                    processing_time_formatted, estimated_cost_usd,
                    prompt_tokens, completion_tokens,
                    tm_hits, tm_misses, batch_count, avg_batch_size,
                    api_calls_reduced, glossary_hits, review_count, retry_count,
                    critical_warnings, high_warnings, medium_warnings, low_warnings,
                    total_warnings, quality_score, warning_categories
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                params,
            )
    except Exception:
        pass


def db_save_warnings(job_id: str, warnings: list) -> None:
    if not warnings:
        return
    rows = []
    for w in warnings:
        rows.append((
            str(uuid.uuid4()),
            job_id,
            w.get("severity", "Low"),
            w.get("category"),
            w.get("row"),
            w.get("column"),
            w.get("source_text"),
            w.get("translated_text"),
            w.get("reason"),
            w.get("suggested_fix"),
            w.get("timestamp"),
        ))
    try:
        with _db() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO review_warnings
                    (id, job_id, severity, category, row, col_name,
                     source_text, translated_text, reason, suggested_fix, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    except Exception:
        pass


# =============================================================================
# TRANSLATION MEMORY
# =============================================================================

def db_load_translation_memory() -> dict:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT tm_key, translation, col_type, created_at, hit_count "
                "FROM translation_memory"
            ).fetchall()
            metrics = conn.execute(
                "SELECT key, value FROM app_metrics WHERE key IN "
                "('tm_total_hits','tm_total_misses','tm_api_calls_saved')"
            ).fetchall()

        entries = {}
        for row in rows:
            entries[row["tm_key"]] = {
                "translation": row["translation"],
                "col_type":    row["col_type"],
                "created_at":  row["created_at"],
                "hit_count":   row["hit_count"],
            }

        m = {r["key"]: int(r["value"]) for r in metrics}
        return {
            "entries": entries,
            "global_stats": {
                "total_hits":            m.get("tm_total_hits", 0),
                "total_misses":          m.get("tm_total_misses", 0),
                "total_api_calls_saved": m.get("tm_api_calls_saved", 0),
            },
        }
    except Exception:
        return {
            "entries": {},
            "global_stats": {
                "total_hits":            0,
                "total_misses":          0,
                "total_api_calls_saved": 0,
            },
        }


def db_save_translation_memory(tm: dict) -> None:
    entries = tm.get("entries", {})
    gs = tm.get("global_stats", {})

    rows = []
    now = datetime.now().isoformat(timespec="seconds")
    for key, val in entries.items():
        rows.append((
            key,
            val.get("translation", ""),
            val.get("col_type", "other"),
            val.get("created_at", now),
            val.get("hit_count", 0),
        ))

    try:
        with _db() as conn:
            conn.executemany(
                """
                INSERT INTO translation_memory (tm_key, translation, col_type, created_at, hit_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tm_key) DO UPDATE SET
                    translation = excluded.translation,
                    hit_count   = excluded.hit_count
                """,
                rows,
            )
            for k, v in [
                ("tm_total_hits",            gs.get("total_hits", 0)),
                ("tm_total_misses",          gs.get("total_misses", 0)),
                ("tm_api_calls_saved",       gs.get("total_api_calls_saved", 0)),
            ]:
                conn.execute(
                    "INSERT INTO app_metrics(key, value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )
    except Exception:
        pass


# =============================================================================
# GLOSSARY
# =============================================================================

def db_load_glossary() -> dict:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT de_term, fr_term, hit_count FROM glossary_terms ORDER BY rowid"
            ).fetchall()

        if not rows:
            return None

        terms = {row["de_term"]: row["fr_term"] for row in rows}
        total_hits = sum(row["hit_count"] for row in rows)
        term_counts = {
            row["de_term"]: row["hit_count"]
            for row in rows
            if row["hit_count"] > 0
        }
        return {
            "terms": terms,
            "stats": {"total_hits": total_hits, "term_counts": term_counts},
        }
    except Exception:
        return None


def db_save_glossary(glossary: dict) -> None:
    terms = glossary.get("terms", {})
    stats = glossary.get("stats", {})
    term_counts = stats.get("term_counts", {})
    now = datetime.now().isoformat(timespec="seconds")

    rows = []
    for de, fr in terms.items():
        rows.append((
            de,
            fr,
            term_counts.get(de, 0),
            now,
        ))

    try:
        with _db() as conn:
            conn.executemany(
                """
                INSERT INTO glossary_terms (de_term, fr_term, hit_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(de_term) DO UPDATE SET
                    fr_term    = excluded.fr_term,
                    hit_count  = excluded.hit_count,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
    except Exception:
        pass


# =============================================================================
# STATUS
# =============================================================================

def db_get_status() -> dict:
    try:
        with _db() as conn:
            jobs    = conn.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0]
            tm      = conn.execute("SELECT COUNT(*) FROM translation_memory").fetchone()[0]
            glossary = conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0]
        return {
            "connected":     True,
            "jobs":          jobs,
            "tm_entries":    tm,
            "glossary_terms": glossary,
        }
    except Exception:
        return {"connected": False, "jobs": 0, "tm_entries": 0, "glossary_terms": 0}


# =============================================================================
# MIGRATION
# =============================================================================

def _migrate_json_if_needed() -> None:
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT value FROM app_metrics WHERE key='migration_done'"
            ).fetchone()
            if row:
                return

        _run_json_migration()

        with _db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_metrics(key,value) VALUES('migration_done','1')"
            )
    except Exception:
        pass


def _run_json_migration() -> None:
    base = DB_PATH.parent

    # History
    history_file = base / "translation_history.json"
    if history_file.exists():
        try:
            with open(history_file, encoding="utf-8") as f:
                records = json.load(f)
            for rec in records:
                if "id" not in rec:
                    rec["id"] = str(uuid.uuid4())
                db_save_history_record(rec)
        except Exception:
            pass

    # Translation memory
    tm_file = base / "translation_memory.json"
    if tm_file.exists():
        try:
            with open(tm_file, encoding="utf-8") as f:
                tm = json.load(f)
            if "entries" in tm:
                db_save_translation_memory(tm)
        except Exception:
            pass

    # Glossary
    glossary_file = base / "glossary.json"
    if glossary_file.exists():
        try:
            with open(glossary_file, encoding="utf-8") as f:
                glossary = json.load(f)
            if "terms" in glossary:
                db_save_glossary(glossary)
        except Exception:
            pass


def _seed_glossary_if_empty(terms: dict) -> None:
    try:
        with _db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0]
            if count > 0:
                return

        now = datetime.now().isoformat(timespec="seconds")
        rows = [(de, fr, 0, now) for de, fr in terms.items()]
        with _db() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO glossary_terms (de_term, fr_term, hit_count, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
    except Exception:
        pass
