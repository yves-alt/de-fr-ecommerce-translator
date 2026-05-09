# German to French E-commerce Translator

> **Project Type:** Portfolio Prototype / Internal Tool Demo

AI-powered product localization platform that translates German Excel product data to French for e-commerce market expansion. Includes Translation Memory, Batch Processing, and a professional Glossary system.

---

## Overview

This Streamlit web application provides a production-grade translation workflow for e-commerce product catalogs. Designed for companies expanding from German-speaking markets to French-speaking markets.

**Key capabilities:**
- Secure login before accessing the translator
- Upload German `.xlsx` files and translate product data to French using AI
- Translation Memory: reuse past translations instantly — no API call needed
- Batch Processing: translate 20 cells per API request instead of 1
- Glossary System: enforce consistent terminology across every translation
- Real-time progress tracking with batch and TM stats
- Translation History dashboard with per-job statistics
- Analytics dashboard with TM savings, batch efficiency, and glossary usage
- Glossary Management page: view, add, and update DE→FR terms
- Download the translated French Excel file with preserved formatting

---

## Features

| Feature | Description |
|---------|-------------|
| **Authentication** | Secure login — credentials stored in secrets, never in code |
| **AI Translation** | OpenAI GPT-4o-mini for context-aware product translations |
| **Translation Memory** | JSON-backed cache: reuses past translations, tracks hits/misses/cost saved |
| **Batch Processing** | Groups 20 cells per API request — up to 20× fewer API calls |
| **Glossary System** | 35+ DE→FR e-commerce terms injected into every prompt; editable via UI |
| **Real-Time Progress** | Live updates showing batch number, TM hits, cells queued |
| **Residue Detection** | Up to 3 correction passes to eliminate remaining German words |
| **Column Detection** | Two-tier fuzzy classifier maps headers to known translation targets |
| **Quality Gate** | Post-translation report: residue, TM stats, batch info, protected columns |
| **Analytics** | TM hit rate, cost saved, batch efficiency, top glossary terms |
| **Glossary Management** | Add/update DE→FR terms, view usage counts, reset to defaults |
| **Translation History** | JSON-backed log of all jobs with TM hits, batch count, and cost |

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| Python 3.8+ | Core language |
| Streamlit | Web application framework |
| openpyxl | Excel file manipulation |
| OpenAI API | AI translation engine (GPT-4o-mini) |
| python-dotenv | Local environment variable loading |
| pandas | History table display |

---

## Local Setup

### Prerequisites

- Python 3.8 or higher
- An OpenAI API key

### Installation

```bash
git clone https://github.com/yves-alt/de-fr-ecommerce-translator.git
cd de-fr-ecommerce-translator

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Configure credentials locally

```bash
cp .env.example .env
```

Edit `.env` and fill in your real values:

```env
OPENAI_API_KEY=sk-proj-your-real-key-here
APP_USER_EMAIL=your@email.com
APP_USER_PASSWORD=your-secure-password
```

> **Never commit `.env` to Git.** It is already in `.gitignore`.

### Run locally

```bash
streamlit run app.py
```

App opens at **http://localhost:8501** — you will see the login page first.

---

## Translation Memory

The app maintains a local `translation_memory.json` file that grows with every translation.

**How it works:**
1. Before sending a cell to OpenAI, the app checks whether the same German text (trimmed, space-normalized) already exists in memory for the same column type.
2. If found → the stored French translation is reused immediately. No API call made.
3. If not found → translated via OpenAI, then saved to memory for future use.

**Memory is keyed by:** `{column_type}:{normalized_source_text}`

Column types are: `name`, `materialDetail`, `other` — ensuring translations are never reused across incompatible contexts (e.g., a product name translation won't be reused for a material description).

**Statistics tracked:**
- Total memory hits (API calls avoided)
- Total memory misses (API calls made)
- Estimated cost saved

`translation_memory.json` is ignored by Git and persists across app restarts and multiple files.

---

## Batch Processing

Instead of sending one API request per cell, the app groups cells into batches.

**Default batch size:** 20 cells per request (configurable per translation via Advanced Settings).

**How it works:**
1. All non-empty cells are pre-scanned.
2. Cells found in Translation Memory are served instantly.
3. Remaining cells are grouped by column type and sent in batches of up to 20.
4. The model returns a JSON array of exactly N translated strings.
5. If the count mismatches (retry up to 2×), falls back to single-cell translation for that batch.

**Safety guarantees:**
- A batch failure never fails the whole file — only affected cells fall back.
- Row numbers, column structure, `<br>` tags, and Excel formatting are fully preserved.
- Row 1 (headers) is never touched.
- Protected columns (`articleNumber`, `sku`, `productId`) are never translated.

---

## Glossary System

The app ships with 35+ German→French e-commerce term mappings in `glossary.json`.

**Default terms include:**

| German | French |
|--------|--------|
| Bezug | Revêtement |
| Gestell | Structure |
| Füße | Pieds |
| Buche | hêtre |
| Eiche | chêne |
| dunkelgrau | gris foncé |
| hellgrau | gris clair |
| Sofa | Canapé |
| Sessel | Fauteuil |
| Ecksofa | Canapé d'angle |
| Bettwäsche | linge de lit |
| Baumwolle | coton |

**How it works:**
- Before each batch translation, the top 25 glossary terms are injected into the system prompt.
- The AI is instructed to always use these terms consistently.
- Glossary hit counts are tracked and shown in Analytics.

**Glossary Management page:**
- View all current terms with usage counts
- Add or update terms via a simple form
- Reset to built-in defaults at any time

`glossary.json` is ignored by Git by default. Remove it from `.gitignore` if you want to commit custom terminology to version control and share it with your team.

---

## Deployment — Streamlit Community Cloud

### Steps

1. Push your code to GitHub.
   - Confirm `.env` is **not** committed (check `.gitignore`)
   - Confirm no real Excel files are committed
   - Confirm `translation_history.json`, `translation_memory.json` are **not** committed

2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**

3. Connect your GitHub repository:
   - **Main file path:** `app.py`

4. Open **Advanced settings → Secrets** and paste:

```toml
OPENAI_API_KEY = "sk-proj-your-real-key-here"
APP_USER_EMAIL = "your@email.com"
APP_USER_PASSWORD = "your-secure-password"
```

5. Click **Deploy**

### Note on persistence (Streamlit Cloud)

Translation history, Translation Memory, and the Glossary are stored in local JSON files on the app server.
These files **reset on each redeployment** — this is expected behaviour for this version.
A future version could use a persistent store (e.g. Supabase, Firebase) for cross-deployment persistence.

---

## Security Rules

| Rule | Status |
|------|--------|
| `.env` committed to Git | Never |
| Real API key in source code | Never |
| Login password in source code | Never |
| Real Excel/product files on GitHub | Never |
| `secrets.toml` committed | Never (gitignored) |
| `translation_history.json` committed | Never (gitignored) |
| `translation_memory.json` committed | Never (gitignored) |
| `.env.example` contains real values | Never (placeholders only) |

---

## How Credentials Are Loaded

The app reads credentials from two sources (in order):

1. **`st.secrets`** — used on Streamlit Cloud
2. **`.env` file via python-dotenv** — used for local development

Passwords are compared with `hmac.compare_digest` (constant-time) to prevent timing attacks.

---

## Supported Columns

| Column | Description |
|--------|-------------|
| `name` | Product name (max 40 chars, no commas/brackets) |
| `colorDetail` | Color information |
| `deliveryScope` | Delivery contents |
| `materialDetail` | Material description |
| `otherMeasurements` | Dimensions |
| `qualityDetail` | Quality information |
| `textileCompositionCover1` | Textile composition |
| `variantName` | Product variant name |

Column headers are matched via a two-tier fuzzy classifier (exact alias → substring). Headers containing `articleNumber`, `sku`, or `productId` are **protected** and never modified.

---

## Project Structure

```
de-fr-ecommerce-translator/
├── app.py                           # Main Streamlit application
├── requirements.txt                 # Python dependencies
├── .env.example                     # Local config template (no real values)
├── .streamlit/
│   └── secrets.toml.example         # Streamlit Cloud secrets template
├── .gitignore                       # Excludes .env, *.xlsx, JSON data files
└── README.md                        # This file
```

**Runtime files (not committed):**
- `translation_history.json` — job log
- `translation_memory.json` — TM cache
- `glossary.json` — terminology (optional to commit)

---

## Workflow

1. **Login** — Enter your email and password
2. **Upload** — Select your German Excel file (.xlsx)
3. **Review** — Check the Column Detection Report
4. **Translate** — Click "Run Translation →" and watch live batch progress
5. **Review results** — See TM hits, batch stats, glossary matches
6. **Download** — Get your translated `FR-filename.xlsx`
7. **Analytics** — Track TM savings, batch efficiency, and glossary usage
8. **Glossary** — View and extend your terminology library

---

## Author

**Yves Koulle Banga**

- GitHub: [@yves-alt](https://github.com/yves-alt)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Disclaimer

This is a **portfolio demonstration project** showcasing AI-powered translation capabilities for e-commerce localization. Not intended for production use without a proper security review.
