"""
German to French E-commerce Translator
AI-powered product localization tool prototype for e-commerce platforms.
Translates German product data to French for market expansion.

Author: Yves Koulle Banga
This is a portfolio demonstration project.
"""

import streamlit as st
import os
import re
import tempfile
import time
from io import BytesIO
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

CANDIDATE_SHEETS = ["Tabelle1", "Translations", "Sheet1"]

COLUMNS_TO_TRANSLATE = [
    "name",
    "colorDetail",
    "deliveryScope",
    "materialDetail",
    "otherMeasurements",
    "qualityDetail",
    "textileCompositionCover1",
    "variantName",
]

OPENAI_MODEL = "gpt-4o-mini"

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

# Column headers that must NEVER be translated
PROTECTED_KEYWORDS = [
    "articlenumber", "article_number", "sku", "productid", "product_id",
]

# Headers containing these keywords are flagged as "possibly missed" if not matched
IMPORTANT_KEYWORDS = [
    "name", "color", "colour", "delivery", "measurement",
    "quality", "textile", "composition", "material", "variant",
]

# Tier 1: header normalized to lowercase must EQUAL one of these aliases
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

# Tier 2: header normalized to lowercase must CONTAIN one of these substrings
# Processed in order; first match wins. More specific entries listed first.
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
# CUSTOM CSS - VIBRANT DESIGN
# =============================================================================

def inject_custom_css():
    """Inject custom CSS for vibrant Home24-style design."""
    st.markdown("""
    <style>
        /* Import Google Font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* Main app styling */
        .stApp {
            background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
            font-family: 'Inter', sans-serif;
        }

        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* Header with gradient */
        .header-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 16px;
            padding: 40px 32px;
            margin-bottom: 24px;
            text-align: center;
            box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
        }

        .header-logo {
            max-width: 160px;
            margin-bottom: 16px;
            filter: brightness(0) invert(1);
        }

        .header-title {
            font-size: 32px;
            font-weight: 700;
            color: #ffffff;
            margin: 0 0 8px 0;
            letter-spacing: -0.5px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .header-subtitle {
            font-size: 16px;
            color: rgba(255,255,255,0.9);
            margin: 0;
            font-weight: 400;
        }

        .header-badge {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 16px;
            backdrop-filter: blur(10px);
        }

        /* Card styling */
        .card {
            background: #ffffff;
            border-radius: 16px;
            padding: 24px;
            margin: 16px 0;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            border: 1px solid #e2e8f0;
        }

        .card-header {
            font-size: 18px;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid #f1f5f9;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .card-header-icon {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }

        /* Info box */
        .info-box {
            background: linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%);
            border-radius: 12px;
            padding: 16px 20px;
            margin: 12px 0;
            border-left: 4px solid #3b82f6;
        }

        .info-box p {
            margin: 0;
            color: #1e40af;
            font-size: 14px;
            line-height: 1.6;
        }

        /* Stats grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
            margin: 20px 0;
        }

        .stat-card {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 1px solid #e2e8f0;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        }

        .stat-value {
            font-size: 36px;
            font-weight: 700;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .stat-label {
            font-size: 12px;
            color: #64748b;
            margin: 6px 0 0 0;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-weight: 600;
        }

        .stat-card.success {
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
            border-color: #a7f3d0;
        }

        .stat-card.success .stat-value {
            background: linear-gradient(135deg, #059669 0%, #10b981 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .stat-card.warning {
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            border-color: #fde68a;
        }

        .stat-card.warning .stat-value {
            background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* Progress card */
        .progress-card {
            background: linear-gradient(135deg, #fafafa 0%, #f5f5f5 100%);
            border-radius: 12px;
            padding: 20px;
            margin: 16px 0;
            border: 1px solid #e5e5e5;
        }

        .progress-title {
            font-size: 14px;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .progress-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 16px;
        }

        .progress-stat {
            background: white;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            border: 1px solid #e2e8f0;
        }

        .progress-stat-value {
            font-size: 20px;
            font-weight: 700;
            color: #667eea;
            margin: 0;
        }

        .progress-stat-label {
            font-size: 10px;
            color: #94a3b8;
            margin: 4px 0 0 0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .progress-current {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 8px;
            padding: 12px 16px;
            margin: 12px 0;
            font-size: 13px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .progress-time {
            display: flex;
            gap: 20px;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #e2e8f0;
        }

        .time-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: #64748b;
        }

        .time-value {
            font-weight: 600;
            color: #1e293b;
        }

        /* Success message */
        .success-message {
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
            border: 1px solid #a7f3d0;
            border-radius: 12px;
            padding: 20px 24px;
            margin: 20px 0;
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .success-message .icon {
            font-size: 28px;
            background: #10b981;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .success-message .text {
            color: #065f46;
            font-weight: 600;
            font-size: 16px;
        }

        /* Warning message */
        .warning-message {
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            border: 1px solid #fde68a;
            border-radius: 12px;
            padding: 20px 24px;
            margin: 20px 0;
        }

        .warning-message .text {
            color: #92400e;
            font-weight: 600;
            font-size: 15px;
        }

        /* Button styling */
        .stButton > button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 14px 32px !important;
            font-weight: 600 !important;
            font-size: 16px !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
        }

        .stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.5) !important;
        }

        .stDownloadButton > button {
            background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 16px 32px !important;
            font-weight: 600 !important;
            font-size: 16px !important;
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4) !important;
        }

        .stDownloadButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 8px 25px rgba(16, 185, 129, 0.5) !important;
        }

        /* File uploader */
        .stFileUploader > div {
            border-radius: 12px !important;
        }

        /* Progress bar customization */
        .stProgress > div > div {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            border-radius: 10px;
        }

        /* Warning details */
        .warning-detail {
            background: #fffef0;
            border-radius: 8px;
            padding: 14px;
            margin: 10px 0;
            font-size: 13px;
            border-left: 3px solid #f59e0b;
        }

        .warning-detail strong {
            color: #b45309;
        }

        /* Footer */
        .footer-container {
            margin-top: 60px;
            padding-bottom: 30px;
        }

        .footer-divider {
            height: 1px;
            background: linear-gradient(to right, transparent, #e2e8f0, transparent);
            margin-bottom: 30px;
        }

        .footer-content {
            text-align: center;
            padding: 20px 0;
        }

        .footer-powered {
            font-size: 14px;
            color: #64748b;
            margin: 0 0 8px 0;
            font-weight: 400;
        }

        .footer-name {
            font-weight: 600;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .footer-email {
            display: inline-block;
            font-size: 13px;
            color: #667eea;
            text-decoration: none;
            padding: 8px 20px;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            transition: all 0.2s ease;
            margin-top: 4px;
        }

        .footer-email:hover {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: transparent;
        }

        .footer-version {
            text-align: center;
            font-size: 11px;
            color: #cbd5e1;
            margin: 20px 0 0 0;
            letter-spacing: 0.5px;
        }

        /* Note box */
        .note-box {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border-radius: 8px;
            padding: 12px 16px;
            margin: 16px 0;
            font-size: 13px;
            color: #92400e;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Hide default elements */
        div[data-testid="stDecoration"] {
            display: none;
        }

        /* Uploaded file badge */
        .file-badge {
            background: linear-gradient(135deg, #ddd6fe 0%, #c4b5fd 100%);
            color: #5b21b6;
            padding: 10px 20px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 14px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin: 12px 0;
        }
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# UI COMPONENTS
# =============================================================================

def render_header():
    """Render the app header with gradient background."""
    logo_path = Path(__file__).parent / "home24_logo.png"

    header_html = '<div class="header-container">'

    if logo_path.exists():
        # Logo will be rendered via st.image
        pass

    header_html += '''
        <h1 class="header-title">German to French Excel Translator</h1>
        <p class="header-subtitle">AI-powered e-commerce product localization prototype</p>
        <span class="header-badge">🚀 Powered by GPT-4o</span>
    </div>
    '''

    st.markdown(header_html, unsafe_allow_html=True)


def render_stats(stats):
    """Render the statistics cards."""
    warning_class = "warning" if stats["unresolved_warnings"] > 0 else "success"

    st.markdown(f'''
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
    ''', unsafe_allow_html=True)


def format_time(seconds):
    """Format seconds into MM:SS string."""
    return str(timedelta(seconds=int(seconds)))[2:7]


def render_column_report(classification: dict):
    """Render the Column Detection Report card (shown before translation starts)."""
    to_translate = classification["to_translate"]
    protected    = classification["protected"]
    ignored      = classification["ignored"]
    possible_missed = classification["possible_missed"]

    st.markdown('''
    <div class="card">
        <div class="card-header">
            <div class="card-header-icon">🔎</div>
            Column Detection Report
        </div>
    </div>
    ''', unsafe_allow_html=True)

    if to_translate:
        items_html = ""
        for header, (_, canonical) in to_translate.items():
            if header == canonical:
                items_html += f"<li><code>{header}</code></li>"
            else:
                items_html += f"<li><code>{header}</code> → matched as <em>{canonical}</em></li>"
        st.markdown(f'''
        <div class="info-box">
            <p><strong>✅ Columns selected for translation ({len(to_translate)}):</strong></p>
            <ul style="margin:8px 0 0 0;padding-left:20px;">{items_html}</ul>
        </div>
        ''', unsafe_allow_html=True)
    else:
        st.markdown('''
        <div class="warning-message">
            <div class="text">⚠️ No translatable columns detected in this sheet.</div>
        </div>
        ''', unsafe_allow_html=True)

    if protected:
        prot_list = " ".join(f"<code>{h}</code>" for h in protected)
        st.markdown(f'''
        <div class="info-box">
            <p><strong>🔒 Protected (never translated):</strong> {prot_list}</p>
        </div>
        ''', unsafe_allow_html=True)

    if possible_missed:
        missed_html = " ".join(f"<code>{h}</code>" for h in possible_missed)
        st.markdown(f'''
        <div class="warning-message">
            <div class="text">⚠️ Possible missed translation column(s): {missed_html}</div>
            <br><small style="color:#92400e;">These columns look important but did not match any
            known pattern. Check the column names in the file.</small>
        </div>
        ''', unsafe_allow_html=True)

    if ignored:
        with st.expander(f"Ignored columns ({len(ignored)})"):
            st.markdown(", ".join(f"`{h}`" for h in ignored))


def render_footer():
    """Render the app footer with branding."""
    st.markdown('''
    <div class="footer-container">
        <div class="footer-divider"></div>
        <div class="footer-content">
            <p class="footer-powered">Built by <span class="footer-name">Yves Koulle Banga</span></p>
            <a href="https://github.com/yves-alt" class="footer-email">github.com/yves-alt</a>
        </div>
        <p class="footer-version">E-commerce Translator Prototype v2.3</p>
    </div>
    ''', unsafe_allow_html=True)


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_product_name(name: str) -> str:
    """Clean and validate a product name (max 40 chars, no commas/brackets)."""
    if not name:
        return name

    name = " ".join(name.split())
    name = name.replace(",", "")
    name = " ".join(name.split())
    name = re.sub(r'\([^)]*\)', '', name)
    name = name.replace("(", "").replace(")", "")
    name = " ".join(name.split())
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = name.replace("[", "").replace("]", "")
    name = " ".join(name.split())

    if len(name) > 40:
        truncated = name[:40]
        last_space = truncated.rfind(" ")
        if last_space > 20:
            name = truncated[:last_space]
        else:
            name = truncated

    return name.strip()


def detect_german_residue(text: str) -> list[str]:
    """Detect German words remaining in translated text."""
    if not text:
        return []

    detected = []
    text_lower = text.lower()

    masked_text = text_lower
    for acceptable in FRENCH_ACCEPTABLE_WORDS:
        masked_text = masked_text.replace(acceptable.lower(), "X" * len(acceptable))

    for word in GERMAN_RESIDUE_WORDS:
        word_lower = word.lower()

        if word_lower in [w.lower() for w in FRENCH_ACCEPTABLE_WORDS]:
            continue

        pattern = re.compile(r'\b' + re.escape(word_lower) + r'\b', re.IGNORECASE)
        if pattern.search(masked_text):
            detected.append(word)

    return detected


# =============================================================================
# TRANSLATION FUNCTIONS
# =============================================================================

def _get_api_key() -> str | None:
    """Return API key — tries st.secrets first (Streamlit Cloud), then .env (local)."""
    try:
        key = st.secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY")


def get_openai_client():
    """Initialize OpenAI client from Streamlit secrets or .env file."""
    api_key = _get_api_key()
    if not api_key:
        st.error(
            "⚠️ **OPENAI_API_KEY not configured.**\n\n"
            "- **Locally:** add `OPENAI_API_KEY=sk-...` to your `.env` file.\n"
            "- **Streamlit Cloud:** go to App settings → Secrets and add:\n"
            "  ```\n  OPENAI_API_KEY = \"sk-...\"\n  ```"
        )
        st.stop()
    return OpenAI(api_key=api_key)


def translate_text(client, text: str, column_name: str) -> str:
    """Translate German text to French using ChatGPT."""
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
- Short and appealing for e-commerce
- Remove ALL German words completely
- "Sofa" must become "Canapé"
- "Sessel" must become "Fauteuil"
- "Ecksofa" must become "Canapé d'angle"
- "Sitzer" must become "places" (e.g., "3-Sitzer" = "3 places")
- Use only French words
Return ONLY the translated text, nothing else."""
    elif column_name == "materialDetail":
        system_prompt = """You are a professional translator for Home24 France e-commerce.
Translate the German material description to natural French following these rules:
- "Bezug" = "Revêtement"
- "Webstoff" = "tissu tissé"
- "Strukturstoff" = "tissu structuré"
- "Füße" = "Pieds"
- "Gestell" = "Structure"
- "Buche" = "hêtre"
- "Eiche" = "chêne"
- "lackiert" = "verni"
- "geölt" = "huilé"
- "Holz" = "bois"
- "Metall" = "métal"
- Preserve <br> tags exactly as they appear
- Keep the same structure (e.g., "Label: Value<br>Label: Value")
Return ONLY the translated text, nothing else."""
    else:
        system_prompt = """You are a professional translator for Home24 France e-commerce.
Translate the German text to natural French following these rules:
- Use natural French, not literal translation
- Remove all German traces - translate ALL German words
- Preserve useful product information
- Preserve <br> tags exactly as they appear
- Keep the same structure and formatting
- Common translations:
  - "Bezug" = "Revêtement"
  - "Füße" = "Pieds"
  - "Buche" = "hêtre"
  - "inkl." = "inclus"
Return ONLY the translated text, nothing else."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Translate this German text to French:\n\n{text}"}
            ],
            temperature=0.3,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return text


def fix_german_residue(client, text: str, column_name: str) -> str:
    """Fix German residue by sending back to ChatGPT."""
    if not text:
        return text

    extra_rules = ""
    if column_name == "name":
        extra_rules = """
- Maximum 40 characters
- No commas, brackets or parentheses
- "Sofa" must become "Canapé"
- "Sessel" must become "Fauteuil"
- "Ecksofa" must become "Canapé d'angle"
- "Sitzer" must become "places\""""
    elif column_name == "materialDetail":
        extra_rules = """
- "Bezug" = "Revêtement"
- "Webstoff" = "tissu tissé"
- "Füße" = "Pieds"
- "Buche" = "hêtre"
- "lackiert" = "verni"
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
                {"role": "user", "content": fix_prompt}
            ],
            temperature=0.2,
            max_tokens=500
        )
        corrected = response.choices[0].message.content.strip()

        if column_name == "name":
            corrected = validate_product_name(corrected)

        return corrected
    except Exception:
        return text


# =============================================================================
# EXCEL PROCESSING WITH PROGRESS
# =============================================================================

def detect_target_sheet(sheet_names: list) -> str | None:
    """
    Return the auto-selected sheet name, or None if the caller must show a picker.
    Priority: CANDIDATE_SHEETS in order → single-sheet workbook → None (multi-sheet, no match).
    """
    for name in CANDIDATE_SHEETS:
        if name in sheet_names:
            return name
    if len(sheet_names) == 1:
        return sheet_names[0]
    return None


def detect_columns(worksheet) -> dict:
    """Read first row to detect column names and their indices. Works on read-only worksheets."""
    columns = {}
    for row in worksheet.iter_rows(min_row=1, max_row=1):
        for cell in row:
            if cell.value is not None:
                columns[str(cell.value).strip()] = cell.column
    return columns


def classify_columns(all_columns: dict) -> dict:
    """
    Classify worksheet headers into four buckets.

    Returns:
        to_translate:    {header: (col_idx, canonical_name)}
        protected:       {header: col_idx}
        ignored:         {header: col_idx}
        possible_missed: [header, ...]
    """
    to_translate   = {}
    protected      = {}
    ignored        = {}
    possible_missed = []

    for header, col_idx in all_columns.items():
        normalized = header.strip().lower()

        # --- Protected: never translate ---
        if any(pk in normalized for pk in PROTECTED_KEYWORDS):
            protected[header] = col_idx
            continue

        # --- Tier 1: exact alias equality ---
        canonical = None
        for can, aliases in TRANSLATE_ALIASES_T1.items():
            if normalized in aliases:
                canonical = can
                break

        # --- Tier 2: substring match (only if Tier 1 missed) ---
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


def process_excel_with_progress(uploaded_file, progress_bar, progress_container, sheet_name: str, column_classification: dict):
    """Process the uploaded Excel file with real-time progress tracking."""
    client = get_openai_client()

    stats = {
        "cells_translated": 0,
        "cells_skipped": 0,
        "residue_corrections": 0,
        "unresolved_warnings": 0,
        "warning_details": []
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        workbook = load_workbook(filename=tmp_path, data_only=False)

        worksheet = workbook[sheet_name]
        stats["sheet_name"] = sheet_name

        # to_translate: {header: (col_idx, canonical_name)}
        to_translate = column_classification["to_translate"]

        if not to_translate:
            raise ValueError("No translatable columns found in the file.")

        total_rows = worksheet.max_row - 1
        total_cells = total_rows * len(to_translate)
        processed_cells = 0

        start_time = time.time()

        # =================================================================
        # PHASE 1: Translation
        # =================================================================
        for row_num in range(2, worksheet.max_row + 1):
            row_index = row_num - 1

            for col_header, (col_idx, canonical) in to_translate.items():
                processed_cells += 1
                elapsed = time.time() - start_time
                progress = processed_cells / total_cells

                if processed_cells > 0:
                    time_per_cell = elapsed / processed_cells
                    remaining_cells = total_cells - processed_cells
                    estimated_remaining = time_per_cell * remaining_cells
                else:
                    estimated_remaining = 0

                progress_bar.progress(progress * 0.7)

                progress_container.markdown(f'''
                <div class="progress-card">
                    <div class="progress-title">⚡ Translation in progress — sheet: <strong>{sheet_name}</strong></div>
                    <div class="progress-grid">
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["cells_translated"]}</p>
                            <p class="progress-stat-label">Translated</p>
                        </div>
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["cells_skipped"]}</p>
                            <p class="progress-stat-label">Skipped</p>
                        </div>
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["residue_corrections"]}</p>
                            <p class="progress-stat-label">Residue Fixes</p>
                        </div>
                    </div>
                    <div class="progress-current">
                        <span>📍 Row {row_index} / {total_rows}</span>
                        <span>📝 {col_header}</span>
                    </div>
                    <div class="progress-time">
                        <div class="time-item">
                            ⏱️ Elapsed: <span class="time-value">{format_time(elapsed)}</span>
                        </div>
                        <div class="time-item">
                            ⏳ Remaining: <span class="time-value">~{format_time(estimated_remaining)}</span>
                        </div>
                        <div class="time-item">
                            📊 Progress: <span class="time-value">{int(progress * 100)}%</span>
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)

                cell = worksheet.cell(row=row_num, column=col_idx)
                original_value = cell.value

                if original_value is None or str(original_value).strip() == "":
                    stats["cells_skipped"] += 1
                    continue

                translated = translate_text(client, original_value, canonical)

                if canonical == "name":
                    translated = validate_product_name(translated)

                cell.value = translated
                stats["cells_translated"] += 1

        # =================================================================
        # PHASE 2: German Residue Check
        # =================================================================
        residue_check_cells = 0
        total_residue_cells = total_rows * len(to_translate)

        for row_num in range(2, worksheet.max_row + 1):
            row_index = row_num - 1

            for col_header, (col_idx, canonical) in to_translate.items():
                residue_check_cells += 1
                elapsed = time.time() - start_time
                progress = 0.7 + (residue_check_cells / total_residue_cells) * 0.25

                progress_bar.progress(progress)

                progress_container.markdown(f'''
                <div class="progress-card">
                    <div class="progress-title">🔍 Checking German residue — sheet: <strong>{sheet_name}</strong></div>
                    <div class="progress-grid">
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["cells_translated"]}</p>
                            <p class="progress-stat-label">Translated</p>
                        </div>
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["cells_skipped"]}</p>
                            <p class="progress-stat-label">Skipped</p>
                        </div>
                        <div class="progress-stat">
                            <p class="progress-stat-value">{stats["residue_corrections"]}</p>
                            <p class="progress-stat-label">Residue Fixes</p>
                        </div>
                    </div>
                    <div class="progress-current">
                        <span>🔎 Checking row {row_index} / {total_rows}</span>
                        <span>📝 {col_header}</span>
                    </div>
                    <div class="progress-time">
                        <div class="time-item">
                            ⏱️ Elapsed: <span class="time-value">{format_time(elapsed)}</span>
                        </div>
                        <div class="time-item">
                            📊 Progress: <span class="time-value">{int(progress * 100)}%</span>
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)

                cell = worksheet.cell(row=row_num, column=col_idx)
                cell_value = cell.value

                if cell_value is None or str(cell_value).strip() == "":
                    continue

                text = str(cell_value)
                detected = detect_german_residue(text)

                if detected:
                    corrected = fix_german_residue(client, text, canonical)
                    stats["residue_corrections"] += 1

                    detected_2 = detect_german_residue(corrected)
                    if detected_2:
                        corrected = fix_german_residue(client, corrected, canonical)
                        stats["residue_corrections"] += 1

                        detected_3 = detect_german_residue(corrected)
                        if detected_3:
                            corrected = fix_german_residue(client, corrected, canonical)
                            stats["residue_corrections"] += 1

                            detected_4 = detect_german_residue(corrected)
                            if detected_4:
                                stats["unresolved_warnings"] += 1
                                stats["warning_details"].append({
                                    "row": row_num,
                                    "column": col_header,
                                    "text": corrected[:50] + "..." if len(corrected) > 50 else corrected,
                                    "residue": detected_4[:3]
                                })

                    cell.value = corrected

        # =================================================================
        # PHASE 3: Final Scan
        # =================================================================
        progress_bar.progress(0.98)
        elapsed = time.time() - start_time

        progress_container.markdown(f'''
        <div class="progress-card">
            <div class="progress-title">✅ Final verification...</div>
            <div class="progress-grid">
                <div class="progress-stat">
                    <p class="progress-stat-value">{stats["cells_translated"]}</p>
                    <p class="progress-stat-label">Translated</p>
                </div>
                <div class="progress-stat">
                    <p class="progress-stat-value">{stats["cells_skipped"]}</p>
                    <p class="progress-stat-label">Skipped</p>
                </div>
                <div class="progress-stat">
                    <p class="progress-stat-value">{stats["residue_corrections"]}</p>
                    <p class="progress-stat-label">Residue Fixes</p>
                </div>
            </div>
            <div class="progress-time">
                <div class="time-item">
                    ⏱️ Total time: <span class="time-value">{format_time(elapsed)}</span>
                </div>
                <div class="time-item">
                    📊 Progress: <span class="time-value">98%</span>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        for row_num in range(2, worksheet.max_row + 1):
            for col_header, (col_idx, canonical) in to_translate.items():
                cell = worksheet.cell(row=row_num, column=col_idx)
                cell_value = cell.value

                if cell_value is None or str(cell_value).strip() == "":
                    continue

                text = str(cell_value)
                detected = detect_german_residue(text)

                if detected:
                    corrected = fix_german_residue(client, text, canonical)
                    stats["residue_corrections"] += 1

                    final_detected = detect_german_residue(corrected)
                    if final_detected:
                        existing = any(
                            w["row"] == row_num and w["column"] == col_header
                            for w in stats["warning_details"]
                        )
                        if not existing:
                            stats["unresolved_warnings"] += 1
                            stats["warning_details"].append({
                                "row": row_num,
                                "column": col_header,
                                "text": corrected[:50] + "..." if len(corrected) > 50 else corrected,
                                "residue": final_detected[:3]
                            })

                    cell.value = corrected

        progress_bar.progress(1.0)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        workbook.close()

        stats["total_time"] = format_time(time.time() - start_time)
        stats["quality_gate"] = {
            "no_residue":        stats["unresolved_warnings"] == 0,
            "protected_columns": list(column_classification["protected"].keys()),
            "possible_missed":   column_classification["possible_missed"],
            "translated_columns": list(to_translate.keys()),
        }

        return output, stats

    finally:
        os.unlink(tmp_path)


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main Streamlit application."""

    st.set_page_config(
        page_title="DE-FR E-commerce Translator",
        page_icon="🌐",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    inject_custom_css()
    render_header()

    # Check for API key
    if not _get_api_key():
        st.markdown('''
        <div class="warning-message">
            <div class="text">⚠️ OPENAI_API_KEY not configured.</div>
            <br>
            <small style="color:#92400e;">
            <strong>Locally:</strong> add <code>OPENAI_API_KEY=sk-...</code> to your <code>.env</code> file.<br>
            <strong>Streamlit Cloud:</strong> go to App settings → Secrets and add:<br>
            <code>OPENAI_API_KEY = "sk-..."</code>
            </small>
        </div>
        ''', unsafe_allow_html=True)
        st.stop()

    # Upload section
    st.markdown('''
    <div class="card">
        <div class="card-header">
            <div class="card-header-icon">📁</div>
            Upload Excel File
        </div>
    </div>
    ''', unsafe_allow_html=True)

    st.markdown('''
    <div class="info-box">
        <p>Upload a German Excel file. The app will auto-detect the sheet to translate
        (<strong>Tabelle1</strong>, <strong>Translations</strong>, or <strong>Sheet1</strong>).
        For other sheet names, you will be asked to choose.</p>
    </div>
    ''', unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Choose Excel file",
        type=["xlsx"],
        label_visibility="collapsed"
    )

    if uploaded_file is not None:
        st.markdown(f'''
        <div class="file-badge">
            📄 {uploaded_file.name}
        </div>
        ''', unsafe_allow_html=True)

        output_filename = f"FR-{uploaded_file.name}"

        # Resolve target sheet + classify columns in a single workbook peek
        wb_peek = load_workbook(BytesIO(uploaded_file.getvalue()), read_only=True, data_only=True)
        available_sheets = wb_peek.sheetnames

        auto_sheet = detect_target_sheet(available_sheets)

        if auto_sheet is not None:
            selected_sheet = auto_sheet
        else:
            selected_sheet = st.selectbox(
                "Multiple sheets found — select the sheet to translate:",
                available_sheets,
                key="sheet_selector"
            )

        peek_headers = detect_columns(wb_peek[selected_sheet])
        wb_peek.close()

        classification = classify_columns(peek_headers)

        st.markdown(f'''
        <div class="info-box">
            <p>Processing sheet: <strong>{selected_sheet}</strong></p>
        </div>
        ''', unsafe_allow_html=True)

        render_column_report(classification)

        # Translation section
        st.markdown('''
        <div class="card">
            <div class="card-header">
                <div class="card-header-icon">🚀</div>
                Translation
            </div>
        </div>
        ''', unsafe_allow_html=True)

        st.markdown('''
        <div class="note-box">
            ⚠️ Please keep this page open while the translation is running.
        </div>
        ''', unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            translate_button = st.button(
                "🌐 Translate Excel File",
                type="primary",
                use_container_width=True
            )

        if translate_button:
            progress_bar = st.progress(0)
            progress_container = st.empty()

            try:
                output_bytes, stats = process_excel_with_progress(
                    uploaded_file,
                    progress_bar,
                    progress_container,
                    selected_sheet,
                    classification
                )

                progress_container.empty()
                progress_bar.empty()

                # Results section
                st.markdown('''
                <div class="card">
                    <div class="card-header">
                        <div class="card-header-icon">📊</div>
                        Results
                    </div>
                </div>
                ''', unsafe_allow_html=True)

                render_stats(stats)

                # Quality Gate
                qg = stats.get("quality_gate", {})
                st.markdown('''
                <div class="card">
                    <div class="card-header">
                        <div class="card-header-icon">🛡️</div>
                        Quality Gate
                    </div>
                </div>
                ''', unsafe_allow_html=True)

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
                st.markdown(f'''
                <div style="background:#f8fafc;border-radius:12px;padding:8px 16px;border:1px solid #e2e8f0;margin:16px 0;">
                    <table style="width:100%;border-collapse:collapse;">{gate_html}</table>
                </div>
                ''', unsafe_allow_html=True)

                processed_sheet = stats.get("sheet_name", "unknown")
                if stats["unresolved_warnings"] == 0:
                    st.markdown(f'''
                    <div class="success-message">
                        <span class="icon">✓</span>
                        <div>
                            <span class="text">Translation complete!</span><br>
                            <small style="color: #065f46;">Sheet processed: <strong>{processed_sheet}</strong> • No German residue detected • Total time: {stats.get("total_time", "N/A")}</small>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                else:
                    st.markdown(f'''
                    <div class="warning-message">
                        <span class="text">⚠️ Translation complete with {stats["unresolved_warnings"]} warning(s).</span><br>
                        <small>Sheet processed: <strong>{processed_sheet}</strong> • Some cells may need manual review • Total time: {stats.get("total_time", "N/A")}</small>
                    </div>
                    ''', unsafe_allow_html=True)

                    with st.expander("View Warning Details"):
                        for warning in stats["warning_details"]:
                            st.markdown(f'''
                            <div class="warning-detail">
                                <strong>Row {warning["row"]}</strong> — Column: <code>{warning["column"]}</code><br>
                                Text: <em>{warning["text"]}</em><br>
                                Detected: <code>{", ".join(warning["residue"])}</code>
                            </div>
                            ''', unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    st.download_button(
                        label=f"📥 Download {output_filename}",
                        data=output_bytes,
                        file_name=output_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

            except ValueError as e:
                st.error(f"Error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")

    render_footer()


if __name__ == "__main__":
    main()
