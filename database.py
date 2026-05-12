"""
SQLite database backend for the Home24 Localization Platform.
Supports DE→FR and DE→NL translation memory, multilingual glossary,
user roles, and login activity tracking.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "localization_platform.db"

# Base schema — uses CREATE TABLE IF NOT EXISTS so it is safe on existing DBs.
# Migration functions below handle upgrades from older schema versions.
_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS translation_jobs (
    id                        TEXT PRIMARY KEY,
    datetime                  TEXT NOT NULL,
    original_filename         TEXT,
    output_filename           TEXT,
    sheet_name                TEXT,
    source_language           TEXT DEFAULT 'German',
    target_language           TEXT DEFAULT 'French',
    output_prefix             TEXT DEFAULT 'FR',
    user_email                TEXT DEFAULT '',
    user_role                 TEXT DEFAULT '',
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
    warning_categories        TEXT DEFAULT '{}',
    excel_exported            INTEGER DEFAULT 1,
    csv_exported              INTEGER DEFAULT 0,
    csv_removed_column        TEXT DEFAULT '',
    csv_delimiter             TEXT DEFAULT ';',
    csv_encoding              TEXT DEFAULT 'utf-8-sig'
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
    source_term     TEXT NOT NULL,
    target_language TEXT NOT NULL DEFAULT 'French',
    target_term     TEXT NOT NULL,
    hit_count       INTEGER DEFAULT 0,
    updated_at      TEXT,
    PRIMARY KEY (source_term, target_language)
);

CREATE TABLE IF NOT EXISTS user_logins (
    id            TEXT PRIMARY KEY,
    user_email    TEXT NOT NULL,
    role          TEXT NOT NULL,
    login_time    TEXT NOT NULL,
    last_seen     TEXT,
    session_id    TEXT,
    login_success INTEGER DEFAULT 1,
    created_at    TEXT NOT NULL
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


# =============================================================================
# INIT & MIGRATION
# =============================================================================

def init_db(
    default_glossary: dict | None = None,
    default_nl_glossary: dict | None = None,
) -> None:
    with _db() as conn:
        conn.executescript(_SCHEMA)
    _ensure_v2_migration()
    _migrate_json_if_needed()
    if default_glossary:
        _seed_glossary_if_empty(default_glossary, "French")
    if default_nl_glossary:
        _seed_glossary_if_empty(default_nl_glossary, "Dutch")


def _get_schema_version() -> int:
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT value FROM app_metrics WHERE key='schema_version'"
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_schema_version(v: int) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_metrics(key,value) VALUES('schema_version',?)",
            (str(v),),
        )


def _table_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_v2_migration() -> None:
    """Upgrade schema from v1 (FR-only) to v2 (multilingual)."""
    if _get_schema_version() >= 2:
        return
    try:
        _migrate_glossary_to_multilingual()
        _ensure_jobs_columns()
        _ensure_user_logins_table()
        _migrate_tm_keys_to_language_prefix()
        _set_schema_version(2)
    except Exception:
        pass


def _migrate_glossary_to_multilingual() -> None:
    """Convert old glossary_terms(de_term PK, fr_term) → new composite PK schema."""
    try:
        with _db() as conn:
            cols = _table_columns(conn, "glossary_terms")
            if "de_term" not in cols:
                return  # Already new schema or table doesn't exist
            conn.execute(
                "ALTER TABLE glossary_terms RENAME TO _glossary_terms_v1"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS glossary_terms (
                    source_term     TEXT NOT NULL,
                    target_language TEXT NOT NULL DEFAULT 'French',
                    target_term     TEXT NOT NULL,
                    hit_count       INTEGER DEFAULT 0,
                    updated_at      TEXT,
                    PRIMARY KEY (source_term, target_language)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO glossary_terms
                    (source_term, target_language, target_term, hit_count, updated_at)
                SELECT de_term, 'French', fr_term, hit_count, updated_at
                FROM _glossary_terms_v1
            """)
            conn.execute("DROP TABLE _glossary_terms_v1")
    except Exception:
        pass


def _ensure_jobs_columns() -> None:
    """Add v2 columns to translation_jobs if they are missing."""
    new_cols = [
        ("output_prefix", "TEXT DEFAULT 'FR'"),
        ("user_email",    "TEXT DEFAULT ''"),
        ("user_role",     "TEXT DEFAULT ''"),
        ("excel_exported",     "INTEGER DEFAULT 1"),
        ("csv_exported",       "INTEGER DEFAULT 0"),
        ("csv_removed_column", "TEXT DEFAULT ''"),
        ("csv_delimiter",      "TEXT DEFAULT ';'"),
        ("csv_encoding",       "TEXT DEFAULT 'utf-8-sig'"),
    ]
    try:
        with _db() as conn:
            existing = _table_columns(conn, "translation_jobs")
            for col_name, col_def in new_cols:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE translation_jobs ADD COLUMN {col_name} {col_def}"
                    )
    except Exception:
        pass


def _ensure_user_logins_table() -> None:
    try:
        with _db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_logins (
                    id            TEXT PRIMARY KEY,
                    user_email    TEXT NOT NULL,
                    role          TEXT NOT NULL,
                    login_time    TEXT NOT NULL,
                    last_seen     TEXT,
                    session_id    TEXT,
                    login_success INTEGER DEFAULT 1,
                    created_at    TEXT NOT NULL
                )
            """)
    except Exception:
        pass


def _migrate_tm_keys_to_language_prefix() -> None:
    """Prefix all existing TM keys with 'fr:' (treat legacy entries as French)."""
    try:
        with _db() as conn:
            conn.execute("""
                UPDATE translation_memory
                SET tm_key = 'fr:' || tm_key
                WHERE tm_key NOT LIKE 'fr:%'
                  AND tm_key NOT LIKE 'nl:%'
            """)
    except Exception:
        pass


# =============================================================================
# HISTORY
# =============================================================================

def db_load_history() -> list:
    """Return all jobs — for admin use."""
    return _load_jobs_where()


def db_load_history_for_user(user_email: str, role: str) -> list:
    """Return jobs scoped to the user (admin sees all)."""
    if role == "admin":
        return _load_jobs_where()
    return _load_jobs_where("user_email = ?", (user_email.strip().lower(),))


def _load_jobs_where(condition: str = "", params: tuple = ()) -> list:
    try:
        sql = "SELECT * FROM translation_jobs"
        if condition:
            sql += f" WHERE {condition}"
        sql += " ORDER BY datetime DESC"
        with _db() as conn:
            rows = conn.execute(sql, params).fetchall()
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

    # Derive output_prefix from target_language when not explicitly set
    target_lang = record.get("target_language", "French")
    output_prefix = record.get("output_prefix", "NL" if target_lang == "Dutch" else "FR")

    params = (
        record.get("id") or str(uuid.uuid4()),
        record.get("datetime", ""),
        record.get("original_filename"),
        record.get("output_filename"),
        record.get("sheet_name"),
        record.get("source_language", "German"),
        target_lang,
        output_prefix,
        record.get("user_email", ""),
        record.get("user_role", ""),
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
        record.get("excel_exported", 1),
        record.get("csv_exported", 0),
        record.get("csv_removed_column", ""),
        record.get("csv_delimiter", ";"),
        record.get("csv_encoding", "utf-8-sig"),
    )

    try:
        with _db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO translation_jobs (
                    id, datetime, original_filename, output_filename,
                    sheet_name, source_language, target_language, output_prefix,
                    user_email, user_role,
                    cells_translated, cells_skipped, residue_corrections,
                    unresolved_warnings, processing_time_seconds,
                    processing_time_formatted, estimated_cost_usd,
                    prompt_tokens, completion_tokens,
                    tm_hits, tm_misses, batch_count, avg_batch_size,
                    api_calls_reduced, glossary_hits, review_count, retry_count,
                    critical_warnings, high_warnings, medium_warnings, low_warnings,
                    total_warnings, quality_score, warning_categories,
                    excel_exported, csv_exported, csv_removed_column,
                    csv_delimiter, csv_encoding
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
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
                ("tm_total_hits",       gs.get("total_hits", 0)),
                ("tm_total_misses",     gs.get("total_misses", 0)),
                ("tm_api_calls_saved",  gs.get("total_api_calls_saved", 0)),
            ]:
                conn.execute(
                    "INSERT INTO app_metrics(key, value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )
    except Exception:
        pass


# =============================================================================
# GLOSSARY — multilingual
# =============================================================================

def db_load_glossary(target_language: str = "French") -> dict | None:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT source_term, target_term, hit_count "
                "FROM glossary_terms WHERE target_language = ? ORDER BY rowid",
                (target_language,),
            ).fetchall()

        if not rows:
            return None

        terms = {row["source_term"]: row["target_term"] for row in rows}
        total_hits = sum(row["hit_count"] for row in rows)
        term_counts = {
            row["source_term"]: row["hit_count"]
            for row in rows
            if row["hit_count"] > 0
        }
        return {
            "terms":           terms,
            "target_language": target_language,
            "stats":           {"total_hits": total_hits, "term_counts": term_counts},
        }
    except Exception:
        return None


def db_save_glossary(glossary: dict, target_language: str = "French") -> None:
    terms = glossary.get("terms", {})
    stats = glossary.get("stats", {})
    term_counts = stats.get("term_counts", {})
    now = datetime.now().isoformat(timespec="seconds")

    rows = []
    for source, target in terms.items():
        rows.append((
            source,
            target_language,
            target,
            term_counts.get(source, 0),
            now,
        ))

    try:
        with _db() as conn:
            conn.executemany(
                """
                INSERT INTO glossary_terms
                    (source_term, target_language, target_term, hit_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_term, target_language) DO UPDATE SET
                    target_term = excluded.target_term,
                    hit_count   = excluded.hit_count,
                    updated_at  = excluded.updated_at
                """,
                rows,
            )
    except Exception:
        pass


# =============================================================================
# LOGIN ACTIVITY
# =============================================================================

def db_log_login(user_email: str, role: str, session_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            conn.execute(
                """
                INSERT INTO user_logins
                    (id, user_email, role, login_time, last_seen, session_id, login_success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (str(uuid.uuid4()), user_email.strip().lower(), role, now, now, session_id, now),
            )
    except Exception:
        pass


def db_update_last_seen(user_email: str, session_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            conn.execute(
                "UPDATE user_logins SET last_seen = ? WHERE session_id = ?",
                (now, session_id),
            )
    except Exception:
        pass


def db_get_login_activity() -> list:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM user_logins ORDER BY login_time DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# =============================================================================
# ADMIN STATS
# =============================================================================

def db_get_admin_stats() -> dict:
    try:
        with _db() as conn:
            total_jobs = conn.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0]
            total_logins = conn.execute("SELECT COUNT(*) FROM user_logins").fetchone()[0]
            total_cost = conn.execute(
                "SELECT SUM(estimated_cost_usd) FROM translation_jobs"
            ).fetchone()[0]
            total_cells = conn.execute(
                "SELECT SUM(cells_translated) FROM translation_jobs"
            ).fetchone()[0]
            fr_jobs = conn.execute(
                "SELECT COUNT(*) FROM translation_jobs WHERE target_language='French'"
            ).fetchone()[0]
            nl_jobs = conn.execute(
                "SELECT COUNT(*) FROM translation_jobs WHERE target_language='Dutch'"
            ).fetchone()[0]
            jobs_by_user = conn.execute(
                """
                SELECT user_email, COUNT(*) as job_count,
                       SUM(cells_translated) as cells,
                       SUM(estimated_cost_usd) as cost
                FROM translation_jobs
                GROUP BY user_email
                ORDER BY job_count DESC
                """
            ).fetchall()
        return {
            "total_jobs":    total_jobs,
            "total_logins":  total_logins,
            "total_cost":    total_cost or 0.0,
            "total_cells":   total_cells or 0,
            "fr_jobs":       fr_jobs,
            "nl_jobs":       nl_jobs,
            "jobs_by_user":  [dict(r) for r in jobs_by_user],
        }
    except Exception:
        return {
            "total_jobs": 0, "total_logins": 0, "total_cost": 0.0,
            "total_cells": 0, "fr_jobs": 0, "nl_jobs": 0, "jobs_by_user": [],
        }


# =============================================================================
# STATUS
# =============================================================================

def db_get_status() -> dict:
    try:
        with _db() as conn:
            jobs     = conn.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0]
            tm       = conn.execute("SELECT COUNT(*) FROM translation_memory").fetchone()[0]
            glossary = conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0]
        return {
            "connected":      True,
            "jobs":           jobs,
            "tm_entries":     tm,
            "glossary_terms": glossary,
        }
    except Exception:
        return {"connected": False, "jobs": 0, "tm_entries": 0, "glossary_terms": 0}


# =============================================================================
# SEEDING
# =============================================================================

def _seed_glossary_if_empty(terms: dict, target_language: str) -> None:
    try:
        with _db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM glossary_terms WHERE target_language = ?",
                (target_language,),
            ).fetchone()[0]
            if count > 0:
                return

        now = datetime.now().isoformat(timespec="seconds")
        rows = [(de, target_language, target, 0, now) for de, target in terms.items()]
        with _db() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO glossary_terms
                    (source_term, target_language, target_term, hit_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
    except Exception:
        pass


# =============================================================================
# JSON MIGRATION (one-time, from legacy JSON files)
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

    history_file = base / "translation_history.json"
    if history_file.exists():
        try:
            import json as _json
            with open(history_file, encoding="utf-8") as f:
                records = _json.load(f)
            for rec in records:
                if "id" not in rec:
                    rec["id"] = str(uuid.uuid4())
                db_save_history_record(rec)
        except Exception:
            pass

    tm_file = base / "translation_memory.json"
    if tm_file.exists():
        try:
            import json as _json
            with open(tm_file, encoding="utf-8") as f:
                tm = _json.load(f)
            if "entries" in tm:
                db_save_translation_memory(tm)
        except Exception:
            pass

    glossary_file = base / "glossary.json"
    if glossary_file.exists():
        try:
            import json as _json
            with open(glossary_file, encoding="utf-8") as f:
                glossary = _json.load(f)
            if "terms" in glossary:
                db_save_glossary(glossary, "French")
        except Exception:
            pass
