"""
German to French E-commerce Translator
AI-powered product localization tool for e-commerce platforms.
Translates German product data to French for market expansion.

Author: Yves Koulle Banga
"""

import streamlit as st
import os
import re
import json
import uuid
import hmac
import tempfile
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from openpyxl import load_workbook
from openai import OpenAI

load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_FILE = Path(__file__).parent / "translation_history.json"

CANDIDATE_SHEETS = ["Tabelle1", "Translations", "Sheet1"]

COLUMNS_TO_TRANSLATE = [
    "name", "colorDetail", "deliveryScope", "materialDetail",
    "otherMeasurements", "qualityDetail", "textileCompositionCover1", "variantName",
]

OPENAI_MODEL = "gpt-4o-mini"
_INPUT_COST_PER_TOKEN  = 0.15 / 1_000_000   # GPT-4o-mini pricing
_OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000
MANUAL_SECONDS_PER_CELL = 45

GERMAN_RESIDUE_WORDS = [
    "mit", "ohne", "und", "oder", "für", "aus", "inkl", "inklusive",
    "bei", "zur", "zum", "vom", "von", "samt", "sowie",
    "Maße", "Masse", "Breite", "Höhe", "Hoehe", "Tiefe", "Länge", "Laenge",
    "Bezug", "Gestell", "Füße", "Fuesse", "Fuße", "Beine",
    "Sitz", "Rücken", "Ruecken", "Armlehne", "Armlehnen",
    "Schublade", "Schubladen", "Türen", "Tueren", "Tür", "Tuer",
    "Polster", "Polsterung", "Lehne",
    "Holz", "Metall", "Kunststoff", "Stoff", "Leder", "Glas",
    "Webstoff", "Strukturstoff", "Samtstoff", "Velours",
    "Eiche", "Buche", "Kiefer", "Nussbaum", "Ahorn", "Birke",
    "Massiv", "massiv", "Furnier",
    "lackiert", "geölt", "geoelt", "gebeizt", "natur",
    "dunkelgrau", "hellgrau", "dunkelbraun", "hellbraun",
    "dunkelblau", "hellblau", "dunkelgrün", "hellgrün",
    "Sand", "sand", "Sandbeige", "Anthrazit",
    "weiß", "weiss", "schwarz", "grün", "gruen", "blau", "rot", "gelb",
    "grau", "braun", "creme", "Creme",
    "Lindgrün", "Moosgrün", "Mintgrün",
    "Bettwäsche", "Bettwasche", "Kissen", "Decke", "Matratze",
    "Baumwolle", "Leinen", "Wolle", "Seide", "Polyester",
    "Sofa", "Couch", "Sessel", "Tisch", "Stuhl", "Stühle", "Stuehle",
    "Schrank", "Bett", "Regal", "Lampe", "Kommode",
    "Sitzer", "Ecksofa", "Schlafsofa", "Longchair",
    "teilig", "Stück", "Stueck", "Set",
    "groß", "gross", "klein", "hoch", "niedrig", "breit", "schmal",
    "höhenverstellbar", "hoehenverstellbar", "ausziehbar", "klappbar",
    "Lieferumfang", "Hinweis", "Achtung", "Wichtig",
    "Zierkissen", "Dekoration",
]

FRENCH_ACCEPTABLE_WORDS = [
    "beige", "taupe", "polyester", "set", "bouclé", "boucle",
]

PROTECTED_KEYWORDS = [
    "articlenumber", "article_number", "sku", "productid", "product_id",
]

IMPORTANT_KEYWORDS = [
    "name", "color", "colour", "delivery", "measurement",
    "quality", "textile", "composition", "material", "variant",
]

TRANSLATE_ALIASES_T1 = {
    "name":                     ["name", "productname", "product_name"],
    "colorDetail":              ["colordetail", "colourdetail", "color_detail", "colour_detail"],
    "deliveryScope":            ["deliveryscope", "delivery_scope", "lieferumfang"],
    "materialDetail":           ["materialdetail", "materialdetails", "material_detail", "compositionmatiere"],
    "otherMeasurements":        ["othermeasurements", "other_measurements", "masse", "abmessungen"],
    "qualityDetail":            ["qualitydetail", "quality_detail"],
    "textileCompositionCover1": [
        "textilecompositioncover1", "textilecompositioncover",
        "textilecomposition",       "textecomposition",
        "compositioncover",         "compositioncover1",
        "textecompositioncover1",
    ],
    "variantName":              ["variantname", "variant_name", "variantenname"],
}

TRANSLATE_ALIASES_T2 = {
    "textileCompositionCover1": ["textilecomposition", "textecomposition", "textilcomposition", "textile", "textil", "composition"],
    "materialDetail":           ["material"],
    "colorDetail":              ["color", "colour"],
    "deliveryScope":            ["delivery"],
    "otherMeasurements":        ["measurement"],
    "qualityDetail":            ["quality"],
    "variantName":              ["variant"],
    "name":                     ["productname"],
}


# =============================================================================
# AUTHENTICATION
# =============================================================================

def _get_credentials() -> tuple[str, str]:
    """Return (email, password) from st.secrets or environment."""
    try:
        email    = st.secrets.get("APP_USER_EMAIL", "")
        password = st.secrets.get("APP_USER_PASSWORD", "")
        if email and password:
            return str(email), str(password)
    except Exception:
        pass
    return os.environ.get("APP_USER_EMAIL", ""), os.environ.get("APP_USER_PASSWORD", "")


def verify_credentials(input_email: str, input_password: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    stored_email, stored_password = _get_credentials()
    if not stored_email or not stored_password:
        return False
    email_ok    = hmac.compare_digest(input_email.strip().lower(), stored_email.strip().lower())
    password_ok = hmac.compare_digest(input_password, stored_password)
    return email_ok and password_ok


# =============================================================================
# HISTORY
# =============================================================================

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history_record(record: dict) -> None:
    history = load_history()
    history.insert(0, record)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError:
        pass  # Streamlit Cloud ephemeral FS — silently skip


# =============================================================================
# CUSTOM CSS
# =============================================================================

def inject_custom_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        .stApp { background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%); font-family: 'Inter', sans-serif; }
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        header { visibility: hidden; }

        /* ─── Header (login page) ─── */
        .header-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 16px; padding: 40px 32px; margin-bottom: 24px;
            text-align: center; box-shadow: 0 10px 40px rgba(102,126,234,0.3);
        }
        .header-title { font-size: 28px; font-weight: 700; color: #fff; margin: 0 0 8px; letter-spacing: -0.5px; }
        .header-subtitle { font-size: 15px; color: rgba(255,255,255,0.85); margin: 0; }
        .header-badge {
            display: inline-block; background: rgba(255,255,255,0.2); color: white;
            padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600;
            margin-top: 14px; backdrop-filter: blur(10px);
        }

        /* ─── Page header (authenticated) ─── */
        .page-header { margin-bottom: 24px; }
        .page-title { font-size: 24px; font-weight: 700; color: #1e293b; margin: 0 0 4px; }
        .page-subtitle { font-size: 14px; color: #64748b; margin: 0; }

        /* ─── Cards ─── */
        .card {
            background: #fff; border-radius: 16px; padding: 24px; margin: 16px 0;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08); border: 1px solid #e2e8f0;
        }
        .card-header {
            font-size: 17px; font-weight: 600; color: #1e293b; margin-bottom: 16px;
            padding-bottom: 12px; border-bottom: 2px solid #f1f5f9;
            display: flex; align-items: center; gap: 10px;
        }
        .card-header-icon {
            width: 32px; height: 32px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px;
        }

        /* ─── Info / warning / success boxes ─── */
        .info-box {
            background: linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%);
            border-radius: 12px; padding: 16px 20px; margin: 12px 0; border-left: 4px solid #3b82f6;
        }
        .info-box p { margin: 0; color: #1e40af; font-size: 14px; line-height: 1.6; }

        .warning-message {
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            border: 1px solid #fde68a; border-radius: 12px; padding: 20px 24px; margin: 20px 0;
        }
        .warning-message .text { color: #92400e; font-weight: 600; font-size: 15px; }

        .success-message {
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
            border: 1px solid #a7f3d0; border-radius: 12px; padding: 20px 24px; margin: 20px 0;
            display: flex; align-items: center; gap: 14px;
        }
        .success-message .icon {
            font-size: 22px; background: #10b981; width: 44px; height: 44px;
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
        }
        .success-message .text { color: #065f46; font-weight: 600; font-size: 15px; }

        .note-box {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border-radius: 8px; padding: 12px 16px; margin: 16px 0; font-size: 13px; color: #92400e;
        }

        /* ─── Stats grid (translator results) ─── */
        .stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 20px 0; }
        .stat-card {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border-radius: 12px; padding: 20px; text-align: center; border: 1px solid #e2e8f0;
        }
        .stat-card.success { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border-color: #a7f3d0; }
        .stat-card.warning { background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border-color: #fde68a; }
        .stat-value {
            font-size: 32px; font-weight: 700; margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .stat-card.success .stat-value { background: linear-gradient(135deg, #059669 0%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .stat-card.warning .stat-value { background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .stat-label { font-size: 11px; color: #64748b; margin: 6px 0 0; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }

        /* ─── Progress card ─── */
        .progress-card {
            background: linear-gradient(135deg, #fafafa 0%, #f5f5f5 100%);
            border-radius: 12px; padding: 20px; margin: 16px 0; border: 1px solid #e5e5e5;
        }
        .progress-title { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }
        .progress-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
        .progress-stat { background: white; border-radius: 8px; padding: 12px; text-align: center; border: 1px solid #e2e8f0; }
        .progress-stat-value { font-size: 20px; font-weight: 700; color: #667eea; margin: 0; }
        .progress-stat-label { font-size: 10px; color: #94a3b8; margin: 4px 0 0; text-transform: uppercase; letter-spacing: 0.5px; }
        .progress-current {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;
            border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 13px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .progress-time { display: flex; gap: 20px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e2e8f0; }
        .time-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #64748b; }
        .time-value { font-weight: 600; color: #1e293b; }

        /* ─── Warning detail ─── */
        .warning-detail {
            background: #fffef0; border-radius: 8px; padding: 14px; margin: 10px 0;
            font-size: 13px; border-left: 3px solid #f59e0b;
        }
        .warning-detail strong { color: #b45309; }

        /* ─── File badge ─── */
        .file-badge {
            background: linear-gradient(135deg, #ddd6fe 0%, #c4b5fd 100%); color: #5b21b6;
            padding: 10px 20px; border-radius: 10px; font-weight: 600; font-size: 14px;
            display: inline-flex; align-items: center; gap: 8px; margin: 12px 0;
        }

        /* ─── Analytics metric cards ─── */
        .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0; }
        .metrics-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 20px 0; }
        .metric-card {
            background: white; border-radius: 14px; padding: 24px 16px; text-align: center;
            border: 1px solid #e2e8f0; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }
        .metric-value {
            font-size: 28px; font-weight: 700; margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .metric-value.green { background: linear-gradient(135deg, #059669 0%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .metric-value.orange { background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .metric-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin: 8px 0 0; }
        .metric-sub { font-size: 11px; color: #94a3b8; margin: 4px 0 0; }

        /* ─── Login page ─── */
        .login-card {
            background: white; border-radius: 20px; padding: 40px;
            box-shadow: 0 8px 40px rgba(102,126,234,0.15); border: 1px solid #e2e8f0; text-align: center;
        }
        .login-title { font-size: 22px; font-weight: 700; color: #1e293b; margin: 0 0 6px; }
        .login-subtitle { font-size: 13px; color: #64748b; margin: 0 0 28px; }

        /* ─── Sidebar ─── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%) !important;
        }
        [data-testid="stSidebar"] * { color: #cbd5e1 !important; }
        [data-testid="stSidebar"] hr { border-color: #334155 !important; }
        [data-testid="stSidebar"] .stRadio label { font-size: 14px !important; font-weight: 500 !important; }
        [data-testid="stSidebar"] .stButton > button {
            background: rgba(255,255,255,0.08) !important;
            color: #94a3b8 !important; border: 1px solid #334155 !important;
            box-shadow: none !important; font-size: 13px !important;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(239,68,68,0.15) !important; color: #fca5a5 !important;
            border-color: #ef4444 !important; transform: none !important;
        }
        .sidebar-brand { text-align: center; padding: 16px 0 8px; }
        .sidebar-brand-icon { font-size: 32px; }
        .sidebar-brand-name { font-size: 15px; font-weight: 700; color: white !important; margin: 6px 0 2px; }
        .sidebar-brand-sub { font-size: 10px; color: #475569 !important; text-transform: uppercase; letter-spacing: 1px; }
        .sidebar-user-info {
            background: rgba(255,255,255,0.05); border-radius: 10px; padding: 12px; margin: 8px 0; text-align: center;
        }
        .sidebar-user-label { font-size: 10px; color: #475569 !important; text-transform: uppercase; letter-spacing: 0.5px; display: block; }
        .sidebar-user-email { font-size: 11px; color: #94a3b8 !important; margin-top: 4px; word-break: break-all; display: block; }

        /* ─── History ─── */
        .history-empty { text-align: center; padding: 60px 20px; color: #94a3b8; font-size: 15px; }
        .history-cloud-note {
            background: linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%);
            border-radius: 10px; padding: 12px 16px; margin: 16px 0; font-size: 12px;
            color: #1e40af; border-left: 3px solid #3b82f6;
        }

        /* ─── Buttons ─── */
        .stButton > button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            color: white !important; border: none !important; border-radius: 12px !important;
            padding: 12px 28px !important; font-weight: 600 !important; font-size: 15px !important;
            transition: all 0.3s ease !important; box-shadow: 0 4px 15px rgba(102,126,234,0.4) !important;
        }
        .stButton > button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(102,126,234,0.5) !important; }
        .stDownloadButton > button {
            background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
            color: white !important; border: none !important; border-radius: 12px !important;
            padding: 14px 28px !important; font-weight: 600 !important; font-size: 15px !important;
            box-shadow: 0 4px 15px rgba(16,185,129,0.4) !important;
        }
        .stDownloadButton > button:hover { transform: translateY(-2px) !important; }

        /* ─── Progress bar ─── */
        .stProgress > div > div { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; border-radius: 10px; }

        /* ─── Footer ─── */
        .footer-container { margin-top: 60px; padding-bottom: 30px; }
        .footer-divider { height: 1px; background: linear-gradient(to right, transparent, #e2e8f0, transparent); margin-bottom: 24px; }
        .footer-content { text-align: center; }
        .footer-powered { font-size: 13px; color: #64748b; margin: 0 0 4px; }
        .footer-name {
            font-weight: 600;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .footer-version { text-align: center; font-size: 11px; color: #cbd5e1; margin: 16px 0 0; letter-spacing: 0.5px; }

        div[data-testid="stDecoration"] { display: none; }
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# UI COMPONENTS
# =============================================================================

def render_header():
    st.markdown("""
    <div class="header-container">
        <h1 class="header-title">German → French Excel Translator</h1>
        <p class="header-subtitle">AI-powered e-commerce product localization</p>
        <span class="header-badge">Powered by GPT-4o-mini</span>
    </div>
    """, unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div class="page-header">
        <h1 class="page-title">{title}</h1>
        {'<p class="page-subtitle">' + subtitle + '</p>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)


def render_stats(stats: dict):
    warning_class = "warning" if stats["unresolved_warnings"] > 0 else "success"
    st.markdown(f"""
    <div class="stats-grid">
        <div class="stat-card">
            <p class="stat-value">{stats["cells_translated"]}</p>
            <p class="stat-label">Cells Translated</p>
        </div>
        <div class="stat-card">
            <p class="stat-value">{stats["cells_skipped"]}</p>
            <p class="stat-label">Cells Skipped</p>
        </div>
        <div class="stat-card success">
            <p class="stat-value">{stats["residue_corrections"]}</p>
            <p class="stat-label">Residue Fixed</p>
        </div>
        <div class="stat-card {warning_class}">
            <p class="stat-value">{stats["unresolved_warnings"]}</p>
            <p class="stat-label">Warnings</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


def format_time(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))[2:7]


def render_column_report(classification: dict):
    to_translate    = classification["to_translate"]
    protected       = classification["protected"]
    ignored         = classification["ignored"]
    possible_missed = classification["possible_missed"]

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-header-icon">🔎</div>
            Column Detection Report
        </div>
    </div>
    """, unsafe_allow_html=True)

    if to_translate:
        items_html = ""
        for header, (_, canonical) in to_translate.items():
            if header == canonical:
                items_html += f"<li><code>{header}</code></li>"
            else:
                items_html += f"<li><code>{header}</code> → matched as <em>{canonical}</em></li>"
        st.markdown(f"""
        <div class="info-box">
            <p><strong>Columns selected for translation ({len(to_translate)}):</strong></p>
            <ul style="margin:8px 0 0;padding-left:20px;">{items_html}</ul>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="warning-message">
            <div class="text">No translatable columns detected in this sheet.</div>
        </div>
        """, unsafe_allow_html=True)

    if protected:
        prot_list = " ".join(f"<code>{h}</code>" for h in protected)
        st.markdown(f"""
        <div class="info-box">
            <p><strong>Protected (never translated):</strong> {prot_list}</p>
        </div>
        """, unsafe_allow_html=True)

    if possible_missed:
        missed_html = " ".join(f"<code>{h}</code>" for h in possible_missed)
        st.markdown(f"""
        <div class="warning-message">
            <div class="text">Possible missed columns: {missed_html}</div>
            <br><small style="color:#92400e;">These look important but did not match any known pattern.</small>
        </div>
        """, unsafe_allow_html=True)

    if ignored:
        with st.expander(f"Ignored columns ({len(ignored)})"):
            st.markdown(", ".join(f"`{h}`" for h in ignored))


def render_sidebar() -> str:
    """Render dark sidebar navigation. Returns selected page name."""
    with st.sidebar:
        st.markdown("""
        <div class="sidebar-brand">
            <div class="sidebar-brand-icon">🌐</div>
            <div class="sidebar-brand-name">DE→FR Translator</div>
            <div class="sidebar-brand-sub">Home24 Internal Tool</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        page = st.radio(
            "Navigation",
            ["Translator", "Translation History", "Analytics"],
            key="nav_radio",
            label_visibility="collapsed",
        )

        st.markdown("---")

        email, _ = _get_credentials()
        st.markdown(f"""
        <div class="sidebar-user-info">
            <span class="sidebar-user-label">Logged in as</span>
            <span class="sidebar-user-email">{email}</span>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Logout", key="logout_btn", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

    return page


def render_footer():
    st.markdown("""
    <div class="footer-container">
        <div class="footer-divider"></div>
        <div class="footer-content">
            <p class="footer-powered">Built by <span class="footer-name">Yves Koulle Banga</span></p>
        </div>
        <p class="footer-version">E-commerce Translator — v3.0</p>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# VALIDATION
# =============================================================================

def validate_product_name(name: str) -> str:
    if not name:
        return name
    name = " ".join(name.split())
    name = name.replace(",", "")
    name = re.sub(r'\([^)]*\)', '', name)
    name = name.replace("(", "").replace(")", "")
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = name.replace("[", "").replace("]", "")
    name = " ".join(name.split())
    if len(name) > 40:
        truncated = name[:40]
        last_space = truncated.rfind(" ")
        name = truncated[:last_space] if last_space > 20 else truncated
    return name.strip()


def detect_german_residue(text: str) -> list[str]:
    if not text:
        return []
    detected = []
    masked = text.lower()
    for acceptable in FRENCH_ACCEPTABLE_WORDS:
        masked = masked.replace(acceptable.lower(), "X" * len(acceptable))
    for word in GERMAN_RESIDUE_WORDS:
        word_lower = word.lower()
        if word_lower in [w.lower() for w in FRENCH_ACCEPTABLE_WORDS]:
            continue
        if re.compile(r'\b' + re.escape(word_lower) + r'\b', re.IGNORECASE).search(masked):
            detected.append(word)
    return detected


# =============================================================================
# API KEY + CLIENT
# =============================================================================

def _get_api_key() -> str | None:
    try:
        key = st.secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY")


def get_openai_client():
    api_key = _get_api_key()
    if not api_key:
        st.error(
            "**OPENAI_API_KEY not configured.**\n\n"
            "- **Locally:** add `OPENAI_API_KEY=sk-...` to your `.env` file.\n"
            "- **Streamlit Cloud:** App settings → Secrets."
        )
        st.stop()
    return OpenAI(api_key=api_key)


# =============================================================================
# TRANSLATION FUNCTIONS
# =============================================================================

def translate_text(client, text: str, column_name: str, token_counter: dict | None = None) -> str:
    if not text or str(text).strip() == "":
        return text
    text = str(text).strip()

    if column_name == "name":
        system_prompt = """You are a professional translator for Home24 France e-commerce.
Translate the German product name to French following these STRICT rules:
- Maximum 40 characters total
- No commas allowed
- No brackets or parentheses allowed
- Natural, commercial French product name
- "Sofa" must become "Canapé"
- "Sessel" must become "Fauteuil"
- "Ecksofa" must become "Canapé d'angle"
- "Sitzer" must become "places" (e.g., "3-Sitzer" = "3 places")
- Use only French words
Return ONLY the translated text, nothing else."""
    elif column_name == "materialDetail":
        system_prompt = """You are a professional translator for Home24 France e-commerce.
Translate the German material description to natural French:
- "Bezug" = "Revêtement"
- "Webstoff" = "tissu tissé"
- "Strukturstoff" = "tissu structuré"
- "Füße" = "Pieds"
- "Gestell" = "Structure"
- "Buche" = "hêtre"
- "Eiche" = "chêne"
- "lackiert" = "verni"
- "geölt" = "huilé"
- Preserve <br> tags exactly as they appear
Return ONLY the translated text, nothing else."""
    else:
        system_prompt = """You are a professional translator for Home24 France e-commerce.
Translate the German text to natural French:
- Use natural French, not literal translation
- Remove all German traces
- Preserve <br> tags exactly as they appear
- "Bezug" = "Revêtement" / "Füße" = "Pieds" / "Buche" = "hêtre" / "inkl." = "inclus"
Return ONLY the translated text, nothing else."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Translate to French:\n\n{text}"},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        if token_counter is not None and response.usage:
            token_counter["prompt_tokens"]     += response.usage.prompt_tokens
            token_counter["completion_tokens"] += response.usage.completion_tokens
        return response.choices[0].message.content.strip()
    except Exception:
        return text


def fix_german_residue(client, text: str, column_name: str, token_counter: dict | None = None) -> str:
    if not text:
        return text

    extra_rules = ""
    if column_name == "name":
        extra_rules = """
- Maximum 40 characters, no commas or brackets
- "Sofa" → "Canapé" / "Sessel" → "Fauteuil" / "Sitzer" → "places\""""
    elif column_name == "materialDetail":
        extra_rules = """
- "Bezug" = "Revêtement" / "Füße" = "Pieds" / "Buche" = "hêtre" / "lackiert" = "verni"
- Preserve <br> tags exactly"""

    fix_prompt = f"""This French text still contains German words.
Rewrite it as clean, natural French for Home24 France.
Replace ALL German words with French equivalents.
{extra_rules}

Text: {text}

Return ONLY the corrected French text."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You remove German words from French texts for Home24 France e-commerce."},
                {"role": "user", "content": fix_prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        if token_counter is not None and response.usage:
            token_counter["prompt_tokens"]     += response.usage.prompt_tokens
            token_counter["completion_tokens"] += response.usage.completion_tokens
        corrected = response.choices[0].message.content.strip()
        if column_name == "name":
            corrected = validate_product_name(corrected)
        return corrected
    except Exception:
        return text


# =============================================================================
# EXCEL PROCESSING
# =============================================================================

def detect_target_sheet(sheet_names: list) -> str | None:
    for name in CANDIDATE_SHEETS:
        if name in sheet_names:
            return name
    if len(sheet_names) == 1:
        return sheet_names[0]
    return None


def detect_columns(worksheet) -> dict:
    columns = {}
    for row in worksheet.iter_rows(min_row=1, max_row=1):
        for cell in row:
            if cell.value is not None:
                columns[str(cell.value).strip()] = cell.column
    return columns


def classify_columns(all_columns: dict) -> dict:
    to_translate    = {}
    protected       = {}
    ignored         = {}
    possible_missed = []

    for header, col_idx in all_columns.items():
        normalized = header.strip().lower()

        if any(pk in normalized for pk in PROTECTED_KEYWORDS):
            protected[header] = col_idx
            continue

        canonical = None
        for can, aliases in TRANSLATE_ALIASES_T1.items():
            if normalized in aliases:
                canonical = can
                break

        if canonical is None:
            for can, substrings in TRANSLATE_ALIASES_T2.items():
                if any(sub in normalized for sub in substrings):
                    canonical = can
                    break

        if canonical is not None:
            to_translate[header] = (col_idx, canonical)
        else:
            ignored[header] = col_idx
            if any(ik in normalized for ik in IMPORTANT_KEYWORDS):
                possible_missed.append(header)

    return {
        "to_translate":    to_translate,
        "protected":       protected,
        "ignored":         ignored,
        "possible_missed": possible_missed,
    }


def process_excel_with_progress(
    uploaded_file, progress_bar, progress_container,
    sheet_name: str, column_classification: dict
) -> tuple[BytesIO, dict]:
    client = get_openai_client()

    token_counter = {"prompt_tokens": 0, "completion_tokens": 0}
    stats = {
        "cells_translated": 0,
        "cells_skipped": 0,
        "residue_corrections": 0,
        "unresolved_warnings": 0,
        "warning_details": [],
        "sheet_name": sheet_name,
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        workbook  = load_workbook(filename=tmp_path, data_only=False)
        worksheet = workbook[sheet_name]
        to_translate = column_classification["to_translate"]

        if not to_translate:
            raise ValueError("No translatable columns found in the file.")

        total_rows  = worksheet.max_row - 1
        total_cells = total_rows * len(to_translate)
        processed   = 0
        start_time  = time.time()

        # ── Phase 1: Translation ──────────────────────────────────────────────
        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                processed += 1
                elapsed   = time.time() - start_time
                progress  = processed / total_cells
                eta       = (elapsed / processed) * (total_cells - processed) if processed else 0

                progress_bar.progress(progress * 0.7)
                progress_container.markdown(f"""
                <div class="progress-card">
                    <div class="progress-title">⚡ Translating — sheet: <strong>{sheet_name}</strong></div>
                    <div class="progress-grid">
                        <div class="progress-stat"><p class="progress-stat-value">{stats["cells_translated"]}</p><p class="progress-stat-label">Translated</p></div>
                        <div class="progress-stat"><p class="progress-stat-value">{stats["cells_skipped"]}</p><p class="progress-stat-label">Skipped</p></div>
                        <div class="progress-stat"><p class="progress-stat-value">{stats["residue_corrections"]}</p><p class="progress-stat-label">Residue Fixes</p></div>
                    </div>
                    <div class="progress-current">
                        <span>Row {row_num - 1} / {total_rows}</span>
                        <span>{col_header}</span>
                    </div>
                    <div class="progress-time">
                        <div class="time-item">Elapsed: <span class="time-value">{format_time(elapsed)}</span></div>
                        <div class="time-item">Remaining: <span class="time-value">~{format_time(eta)}</span></div>
                        <div class="time-item">Progress: <span class="time-value">{int(progress * 100)}%</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                cell = worksheet.cell(row=row_num, column=col_idx)
                if cell.value is None or str(cell.value).strip() == "":
                    stats["cells_skipped"] += 1
                    continue

                translated = translate_text(client, cell.value, canonical, token_counter)
                if canonical == "name":
                    translated = validate_product_name(translated)
                cell.value = translated
                stats["cells_translated"] += 1

        # ── Phase 2: Residue check ────────────────────────────────────────────
        checked = 0
        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                checked += 1
                elapsed  = time.time() - start_time
                progress = 0.7 + (checked / total_cells) * 0.25

                progress_bar.progress(progress)
                progress_container.markdown(f"""
                <div class="progress-card">
                    <div class="progress-title">🔍 Checking residue — sheet: <strong>{sheet_name}</strong></div>
                    <div class="progress-grid">
                        <div class="progress-stat"><p class="progress-stat-value">{stats["cells_translated"]}</p><p class="progress-stat-label">Translated</p></div>
                        <div class="progress-stat"><p class="progress-stat-value">{stats["cells_skipped"]}</p><p class="progress-stat-label">Skipped</p></div>
                        <div class="progress-stat"><p class="progress-stat-value">{stats["residue_corrections"]}</p><p class="progress-stat-label">Residue Fixes</p></div>
                    </div>
                    <div class="progress-current">
                        <span>Row {row_num - 1} / {total_rows}</span>
                        <span>{col_header}</span>
                    </div>
                    <div class="progress-time">
                        <div class="time-item">Elapsed: <span class="time-value">{format_time(elapsed)}</span></div>
                        <div class="time-item">Progress: <span class="time-value">{int(progress * 100)}%</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                cell = worksheet.cell(row=row_num, column=col_idx)
                if cell.value is None or str(cell.value).strip() == "":
                    continue

                text = str(cell.value)
                for _ in range(3):
                    detected = detect_german_residue(text)
                    if not detected:
                        break
                    text = fix_german_residue(client, text, canonical, token_counter)
                    stats["residue_corrections"] += 1
                else:
                    detected = detect_german_residue(text)
                    if detected:
                        stats["unresolved_warnings"] += 1
                        stats["warning_details"].append({
                            "row": row_num,
                            "column": col_header,
                            "text": text[:50] + "..." if len(text) > 50 else text,
                            "residue": detected[:3],
                        })

                cell.value = text

        # ── Phase 3: Final pass ───────────────────────────────────────────────
        progress_bar.progress(0.98)
        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                cell = worksheet.cell(row=row_num, column=col_idx)
                if cell.value is None or str(cell.value).strip() == "":
                    continue
                text     = str(cell.value)
                detected = detect_german_residue(text)
                if detected:
                    corrected = fix_german_residue(client, text, canonical, token_counter)
                    stats["residue_corrections"] += 1
                    if detect_german_residue(corrected):
                        already = any(
                            w["row"] == row_num and w["column"] == col_header
                            for w in stats["warning_details"]
                        )
                        if not already:
                            stats["unresolved_warnings"] += 1
                            stats["warning_details"].append({
                                "row": row_num, "column": col_header,
                                "text": corrected[:50] + "..." if len(corrected) > 50 else corrected,
                                "residue": detect_german_residue(corrected)[:3],
                            })
                    cell.value = corrected

        progress_bar.progress(1.0)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        workbook.close()

        elapsed_seconds = time.time() - start_time
        stats["total_time"]      = format_time(elapsed_seconds)
        stats["elapsed_seconds"] = elapsed_seconds
        stats["prompt_tokens"]   = token_counter["prompt_tokens"]
        stats["completion_tokens"] = token_counter["completion_tokens"]

        total_tokens = token_counter["prompt_tokens"] + token_counter["completion_tokens"]
        if total_tokens > 0:
            stats["estimated_cost_usd"] = round(
                token_counter["prompt_tokens"]     * _INPUT_COST_PER_TOKEN +
                token_counter["completion_tokens"] * _OUTPUT_COST_PER_TOKEN,
                4,
            )
        else:
            stats["estimated_cost_usd"] = None

        stats["quality_gate"] = {
            "no_residue":         stats["unresolved_warnings"] == 0,
            "protected_columns":  list(column_classification["protected"].keys()),
            "possible_missed":    column_classification["possible_missed"],
            "translated_columns": list(to_translate.keys()),
        }

        return output, stats

    finally:
        os.unlink(tmp_path)


# =============================================================================
# PAGE: LOGIN
# =============================================================================

def login_page():
    render_header()

    _, col, _ = st.columns([1, 1.8, 1])
    with col:
        st.markdown("""
        <div class="login-card">
            <div class="login-title">Sign In</div>
            <div class="login-subtitle">Internal access — Home24 e-commerce tools</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            email_input    = st.text_input("Email", placeholder="your@email.com")
            password_input = st.text_input("Password", type="password")
            submitted      = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            _, stored_pw = _get_credentials()
            if not stored_pw:
                st.error("App credentials are not configured. Check Streamlit secrets or your .env file.")
            elif verify_credentials(email_input, password_input):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid email or password.")

    render_footer()


# =============================================================================
# PAGE: TRANSLATOR
# =============================================================================

def translator_page():
    render_page_header(
        "German → French Translator",
        "Upload a German Excel file to begin translation",
    )

    if not _get_api_key():
        st.markdown("""
        <div class="warning-message">
            <div class="text">OPENAI_API_KEY not configured.</div>
            <br>
            <small style="color:#92400e;">
            <strong>Locally:</strong> add <code>OPENAI_API_KEY=sk-...</code> to your <code>.env</code> file.<br>
            <strong>Streamlit Cloud:</strong> App settings → Secrets.
            </small>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    st.markdown("""
    <div class="card">
        <div class="card-header"><div class="card-header-icon">📁</div>Upload Excel File</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="info-box">
        <p>Upload a German <code>.xlsx</code> file. The app auto-detects the sheet
        (<strong>Tabelle1</strong>, <strong>Translations</strong>, or <strong>Sheet1</strong>).
        For other sheet names you will be asked to choose.</p>
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Choose Excel file", type=["xlsx"], label_visibility="collapsed")

    if uploaded_file is not None:
        st.markdown(f'<div class="file-badge">📄 {uploaded_file.name}</div>', unsafe_allow_html=True)

        output_filename = f"FR-{uploaded_file.name}"

        wb_peek        = load_workbook(BytesIO(uploaded_file.getvalue()), read_only=True, data_only=True)
        available_sheets = wb_peek.sheetnames
        auto_sheet     = detect_target_sheet(available_sheets)

        if auto_sheet is not None:
            selected_sheet = auto_sheet
        else:
            selected_sheet = st.selectbox(
                "Multiple sheets found — select the sheet to translate:",
                available_sheets,
                key="sheet_selector",
            )

        peek_headers   = detect_columns(wb_peek[selected_sheet])
        wb_peek.close()
        classification = classify_columns(peek_headers)

        st.markdown(f"""
        <div class="info-box">
            <p>Processing sheet: <strong>{selected_sheet}</strong></p>
        </div>
        """, unsafe_allow_html=True)

        render_column_report(classification)

        st.markdown("""
        <div class="card">
            <div class="card-header"><div class="card-header-icon">🚀</div>Translation</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="note-box">Keep this page open while translation is running.</div>', unsafe_allow_html=True)

        _, btn_col, _ = st.columns([1, 2, 1])
        with btn_col:
            translate_button = st.button("🌐 Translate Excel File", type="primary", use_container_width=True)

        if translate_button:
            progress_bar       = st.progress(0)
            progress_container = st.empty()

            try:
                output_bytes, stats = process_excel_with_progress(
                    uploaded_file, progress_bar, progress_container,
                    selected_sheet, classification,
                )
                progress_container.empty()
                progress_bar.empty()

                # Save to history
                save_history_record({
                    "id":                       str(uuid.uuid4()),
                    "datetime":                 datetime.now().isoformat(timespec="seconds"),
                    "original_filename":        uploaded_file.name,
                    "output_filename":          output_filename,
                    "sheet_name":               selected_sheet,
                    "source_language":          "German",
                    "target_language":          "French",
                    "cells_translated":         stats["cells_translated"],
                    "cells_skipped":            stats["cells_skipped"],
                    "residue_corrections":      stats["residue_corrections"],
                    "unresolved_warnings":      stats["unresolved_warnings"],
                    "processing_time_seconds":  stats["elapsed_seconds"],
                    "processing_time_formatted": stats["total_time"],
                    "estimated_cost_usd":       stats.get("estimated_cost_usd"),
                    "prompt_tokens":            stats.get("prompt_tokens"),
                    "completion_tokens":        stats.get("completion_tokens"),
                })

                # Results
                st.markdown("""
                <div class="card">
                    <div class="card-header"><div class="card-header-icon">📊</div>Results</div>
                </div>
                """, unsafe_allow_html=True)
                render_stats(stats)

                # Quality gate
                qg = stats.get("quality_gate", {})
                st.markdown("""
                <div class="card">
                    <div class="card-header"><div class="card-header-icon">🛡️</div>Quality Gate</div>
                </div>
                """, unsafe_allow_html=True)

                gate_rows = [
                    ("✅" if qg.get("no_residue") else "⚠️",
                     "German residue",
                     "None detected" if qg.get("no_residue") else "Residue found — see warnings below"),
                    ("✅", "Row 1 (headers)", "Untouched"),
                    ("✅" if qg.get("protected_columns") else "ℹ️",
                     "Protected columns",
                     ", ".join(qg.get("protected_columns", [])) or "None found in sheet"),
                    ("⚠️" if qg.get("possible_missed") else "✅",
                     "Missed columns check",
                     ", ".join(qg.get("possible_missed", [])) or "All important columns accounted for"),
                ]
                gate_html = "".join(
                    f"<tr><td style='padding:6px 12px;font-size:16px;'>{icon}</td>"
                    f"<td style='padding:6px 12px;font-weight:600;color:#1e293b;'>{label}</td>"
                    f"<td style='padding:6px 12px;color:#64748b;font-size:13px;'>{value}</td></tr>"
                    for icon, label, value in gate_rows
                )
                st.markdown(f"""
                <div style="background:#f8fafc;border-radius:12px;padding:8px 16px;border:1px solid #e2e8f0;margin:16px 0;">
                    <table style="width:100%;border-collapse:collapse;">{gate_html}</table>
                </div>
                """, unsafe_allow_html=True)

                processed_sheet = stats.get("sheet_name", "")
                cost_str = f"${stats['estimated_cost_usd']:.4f}" if stats.get("estimated_cost_usd") is not None else "cost unavailable"

                if stats["unresolved_warnings"] == 0:
                    st.markdown(f"""
                    <div class="success-message">
                        <span class="icon">✓</span>
                        <div>
                            <span class="text">Translation complete!</span><br>
                            <small style="color:#065f46;">Sheet: <strong>{processed_sheet}</strong> · No residue · Time: {stats.get("total_time")} · Est. cost: {cost_str}</small>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="warning-message">
                        <span class="text">Translation complete with {stats["unresolved_warnings"]} warning(s).</span><br>
                        <small>Sheet: <strong>{processed_sheet}</strong> · Time: {stats.get("total_time")} · Est. cost: {cost_str}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    with st.expander("View Warning Details"):
                        for w in stats["warning_details"]:
                            st.markdown(f"""
                            <div class="warning-detail">
                                <strong>Row {w["row"]}</strong> — Column: <code>{w["column"]}</code><br>
                                Text: <em>{w["text"]}</em><br>
                                Detected: <code>{", ".join(w["residue"])}</code>
                            </div>
                            """, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                _, dl_col, _ = st.columns([1, 2, 1])
                with dl_col:
                    st.download_button(
                        label=f"📥 Download {output_filename}",
                        data=output_bytes,
                        file_name=output_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

            except ValueError as e:
                st.error(f"Error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")


# =============================================================================
# PAGE: TRANSLATION HISTORY
# =============================================================================

def history_page():
    render_page_header(
        "Translation History",
        "All previous translation jobs — most recent first",
    )

    history = load_history()

    st.markdown("""
    <div class="history-cloud-note">
        On Streamlit Community Cloud, history is stored in the app's ephemeral file system
        and will reset after each redeployment. This is expected behaviour for this version.
    </div>
    """, unsafe_allow_html=True)

    if not history:
        st.markdown("""
        <div class="history-empty">
            No translations yet. Go to the <strong>Translator</strong> to get started.
        </div>
        """, unsafe_allow_html=True)
        return

    # Summary bar
    total_files  = len(history)
    total_cells  = sum(r.get("cells_translated", 0) for r in history)
    total_time_s = sum(r.get("processing_time_seconds", 0) for r in history)
    costs        = [r["estimated_cost_usd"] for r in history if r.get("estimated_cost_usd") is not None]
    total_cost   = sum(costs) if costs else None

    cost_display = f"${total_cost:.4f}" if total_cost is not None else "Unavailable"

    st.markdown(f"""
    <div class="metrics-grid">
        <div class="metric-card">
            <p class="metric-value">{total_files}</p>
            <p class="metric-label">Files Translated</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{total_cells:,}</p>
            <p class="metric-label">Total Cells</p>
        </div>
        <div class="metric-card">
            <p class="metric-value green">{format_time(total_time_s)}</p>
            <p class="metric-label">Total Time</p>
        </div>
        <div class="metric-card">
            <p class="metric-value orange">{cost_display}</p>
            <p class="metric-label">Total Est. Cost</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Table
    rows = []
    for r in history:
        dt_raw  = r.get("datetime", "")
        dt_disp = dt_raw[:16].replace("T", " ") if dt_raw else ""
        cost    = r.get("estimated_cost_usd")
        rows.append({
            "Date / Time":      dt_disp,
            "Original File":    r.get("original_filename", ""),
            "Sheet":            r.get("sheet_name", ""),
            "Translated":       r.get("cells_translated", 0),
            "Skipped":          r.get("cells_skipped", 0),
            "Residue Fixes":    r.get("residue_corrections", 0),
            "Warnings":         r.get("unresolved_warnings", 0),
            "Time":             r.get("processing_time_formatted", ""),
            "Est. Cost (USD)":  f"${cost:.4f}" if cost is not None else "N/A",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)


# =============================================================================
# PAGE: ANALYTICS
# =============================================================================

def analytics_page():
    render_page_header(
        "Analytics",
        "Aggregated statistics across all translation jobs",
    )

    history = load_history()

    if not history:
        st.markdown("""
        <div class="history-empty">
            No data yet. Complete a translation to see analytics.
        </div>
        """, unsafe_allow_html=True)
        return

    # Aggregate
    total_files       = len(history)
    total_translated  = sum(r.get("cells_translated", 0) for r in history)
    total_skipped     = sum(r.get("cells_skipped", 0) for r in history)
    total_residue     = sum(r.get("residue_corrections", 0) for r in history)
    total_warnings    = sum(r.get("unresolved_warnings", 0) for r in history)
    total_time_s      = sum(r.get("processing_time_seconds", 0) for r in history)
    costs             = [r["estimated_cost_usd"] for r in history if r.get("estimated_cost_usd") is not None]
    total_cost        = sum(costs) if costs else None

    # Time saved estimate: manual = 45s × translated cells
    manual_time_s   = total_translated * MANUAL_SECONDS_PER_CELL
    saved_s         = manual_time_s - total_time_s
    saved_display   = format_time(max(saved_s, 0)) if total_translated > 0 else "—"
    manual_display  = format_time(manual_time_s) if total_translated > 0 else "—"
    actual_display  = format_time(total_time_s)
    cost_display    = f"${total_cost:.4f}" if total_cost is not None else "Unavailable"

    # Section 1: Volume
    st.markdown("#### Volume")
    st.markdown(f"""
    <div class="metrics-grid">
        <div class="metric-card">
            <p class="metric-value">{total_files}</p>
            <p class="metric-label">Files Translated</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{total_translated:,}</p>
            <p class="metric-label">Cells Translated</p>
            <p class="metric-sub">Target: French</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{total_skipped:,}</p>
            <p class="metric-label">Cells Skipped</p>
            <p class="metric-sub">Empty or unchanged</p>
        </div>
        <div class="metric-card">
            <p class="metric-value orange">{total_warnings}</p>
            <p class="metric-label">Unresolved Warnings</p>
            <p class="metric-sub">Need manual review</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Section 2: Quality
    st.markdown("#### Quality")
    st.markdown(f"""
    <div class="metrics-grid-3">
        <div class="metric-card">
            <p class="metric-value green">{total_residue}</p>
            <p class="metric-label">Residue Fixes</p>
            <p class="metric-sub">German words auto-corrected</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{total_translated:,}</p>
            <p class="metric-label">Source Language</p>
            <p class="metric-sub">German (DE)</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{total_translated:,}</p>
            <p class="metric-label">Target Language</p>
            <p class="metric-sub">French (FR)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Section 3: Time & Cost
    st.markdown("#### Time & Cost")
    st.markdown(f"""
    <div class="metrics-grid">
        <div class="metric-card">
            <p class="metric-value">{actual_display}</p>
            <p class="metric-label">Total Processing Time</p>
            <p class="metric-sub">Actual machine time</p>
        </div>
        <div class="metric-card">
            <p class="metric-value">{manual_display}</p>
            <p class="metric-label">Est. Manual Time</p>
            <p class="metric-sub">@ 45 sec / cell</p>
        </div>
        <div class="metric-card">
            <p class="metric-value green">{saved_display}</p>
            <p class="metric-label">Estimated Time Saved</p>
            <p class="metric-sub">Manual minus actual</p>
        </div>
        <div class="metric-card">
            <p class="metric-value orange">{cost_display}</p>
            <p class="metric-label">Estimated API Cost</p>
            <p class="metric-sub">GPT-4o-mini pricing</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if total_cost is None:
        st.markdown("""
        <div class="info-box">
            <p><strong>Note on API cost:</strong> Estimated cost is unavailable for translations
            completed before token tracking was added. Future translations will include cost estimates.</p>
        </div>
        """, unsafe_allow_html=True)

    # Savings callout
    if total_translated > 0 and saved_s > 0:
        saved_hours = saved_s / 3600
        st.markdown(f"""
        <div class="success-message">
            <span class="icon">⏱</span>
            <div>
                <span class="text">Estimated {saved_hours:.1f} hours saved</span><br>
                <small style="color:#065f46;">
                    Assuming {MANUAL_SECONDS_PER_CELL}s manual translation per cell across
                    {total_translated:,} translated cells.
                </small>
            </div>
        </div>
        """, unsafe_allow_html=True)


# =============================================================================
# MAIN
# =============================================================================

def main():
    is_auth = st.session_state.get("authenticated", False)

    st.set_page_config(
        page_title="DE-FR E-commerce Translator",
        page_icon="🌐",
        layout="wide",
        initial_sidebar_state="expanded" if is_auth else "collapsed",
    )

    inject_custom_css()

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        login_page()
        return

    page = render_sidebar()

    if page == "Translator":
        translator_page()
    elif page == "Translation History":
        history_page()
    elif page == "Analytics":
        analytics_page()

    render_footer()


if __name__ == "__main__":
    main()
