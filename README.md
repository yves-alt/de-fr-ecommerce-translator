# German to French E-commerce Translator

> **Project Type:** Portfolio Prototype / Internal Tool Demo

AI-powered product localization platform that translates German Excel product data to French for e-commerce market expansion. Includes Translation Memory, Batch Processing, a professional Glossary system, Retry System with exponential backoff, advanced Column Intelligence, a Cost Dashboard, and Human Review Mode with Excel highlighting.

---

## Overview

This Streamlit web application provides a production-grade translation workflow for e-commerce product catalogs. Designed for companies expanding from German-speaking markets to French-speaking markets.

**Key capabilities:**
- Secure login before accessing the translator
- Upload German `.xlsx` files and translate product data to French using AI
- Translation Memory: reuse past translations instantly — no API call needed
- Batch Processing: translate 20 cells per API request instead of 1
- Glossary System: enforce consistent terminology across every translation
- Retry System: up to 3 retries with exponential backoff on API errors and rate limits
- Column Intelligence: 3-tier classifier (exact alias → substring → camelCase word-set)
- Human Review Mode: quality analysis per cell, flagged rows highlighted yellow in Excel
- Cost Dashboard: total tokens, prompt vs completion breakdown, avg cost/file and /cell, per-job bar chart
- Real-time progress tracking with batch and TM stats
- Translation History dashboard with per-job statistics
- Analytics dashboard with TM savings, batch efficiency, glossary usage, and cost trends
- Glossary Management page: view, add, and update DE→FR terms
- Download the translated French Excel file with preserved formatting

---

## Features

| Feature | Description |
|---------|-------------|
| **Authentication** | Secure login — credentials stored in secrets, never in code |
| **AI Translation** | OpenAI GPT-4o-mini for context-aware product translations |
| **Translation Memory** | SQLite-backed cache: reuses past translations, tracks hits/misses/cost saved |
| **Batch Processing** | Groups 20 cells per API request — up to 20× fewer API calls |
| **Glossary System** | 35+ DE→FR e-commerce terms injected into every prompt; editable via UI |
| **Retry System** | Up to 3 retries with exponential backoff; rate-limit detection; notify on each retry |
| **Column Intelligence** | 3-tier classifier: T1 exact alias → T2 substring → T3 camelCase word-set (≥2 matches) |
| **Human Review Mode** | Quality analysis per cell; flags German residue, lost `<br>`, name violations; yellow highlight in Excel |
| **Cost Dashboard** | Total tokens, prompt vs completion breakdown, avg cost/file and /cell, per-job bar chart |
| **Real-Time Progress** | Live updates showing batch number, TM hits, cells queued |
| **Residue Detection** | Up to 3 correction passes to eliminate remaining German words |
| **Quality Gate** | Post-translation report: residue, TM stats, batch info, protected columns |
| **Analytics** | TM hit rate, cost saved, batch efficiency, top glossary terms, cost trends |
| **Glossary Management** | Add/update DE→FR terms, view usage counts, reset to defaults |
| **Translation History** | SQLite-backed log of all jobs with TM hits, batch count, cost, and quality scores |

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

The app maintains a local SQLite database (`localization_platform.db`) that stores the translation memory, history, and glossary.

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

The database is ignored by Git and persists across app restarts. On Streamlit Cloud the filesystem is ephemeral, so the database resets on each deployment — this is the same behaviour as the previous JSON files.

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

The app ships with 166 German→French e-commerce and furniture term mappings stored in the SQLite database.

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

Glossary terms are stored in the SQLite database and seeded automatically from `DEFAULT_GLOSSARY_TERMS` on first run. On Streamlit Cloud the database resets on deployment, so the glossary is re-seeded from code each time.

---

## Retry System

All OpenAI API calls are wrapped in `_api_call_with_retry()` with exponential backoff.

**How it works:**
1. Any API call that raises an exception is retried up to `MAX_API_RETRIES` (3) times.
2. The delay doubles on each retry: 1s → 2s → 4s.
3. If a rate-limit error (`429`) is detected, the delay is multiplied by 4× instead.
4. A `notify_fn` callback is fired on each retry — used to increment the session retry counter.
5. If all attempts fail, the exception is re-raised and the batch falls back to single-cell mode.

**Constants:**
- `MAX_API_RETRIES = 3` — max retries per API call
- `RETRY_BASE_DELAY = 1.0` — starting backoff in seconds (doubles each attempt)

---

## Column Intelligence (3-Tier)

Headers are matched to canonical column names through three tiers, in order:

| Tier | Method | Example |
|------|--------|---------|
| **T1** | Exact alias match (case-insensitive) | `"farbe"` → `colorDetail` |
| **T2** | Substring match | `"colorinfo"` → `colorDetail` |
| **T3** | camelCase word-set match (≥2 words overlap) | `"couleurDetail"` → `colorDetail` |

T3 splits camelCase, PascalCase, and snake_case headers into word tokens before matching against `CANONICAL_WORD_SETS`. At least 2 words must overlap for a match to avoid false positives.

---

## Human Review Mode

After translation, every cell is analysed by `analyze_translation_quality()`.

**Checks performed:**
| Check | Trigger |
|-------|---------|
| German residue | Any German word found in the translation |
| Identical output | Translation unchanged from source |
| Too short | Translation < 40% the length of source (min 3 chars) |
| Lost `<br>` tags | Source had `<br>` tags that are missing in translation |
| Name too long | `name` column translation > 40 chars |
| Name has comma | `name` column translation contains a comma |

**Output:**
- Flagged cells are highlighted **yellow** (`#FFF9C4`) in the downloaded Excel file.
- A "Review Recommended" expander appears in the Translator page listing every flagged cell with the reason.
- `review_count` is stored in translation history for future reference.

---

## Cost Dashboard

The Analytics page includes a dedicated Cost Dashboard section.

**Metrics shown:**
- Total tokens used (prompt + completion) across all jobs
- Prompt token count with calculated input cost
- Completion token count with calculated output cost
- Average cost per file and per cell
- Per-job cost bar chart (when more than 1 job has cost data)

**GPT-4o-mini pricing used:**
- Input: $0.15 / 1M tokens
- Output: $0.60 / 1M tokens

---

## Deployment — Streamlit Community Cloud

### Steps

1. Push your code to GitHub.
   - Confirm `.env` is **not** committed (check `.gitignore`)
   - Confirm no real Excel files are committed
   - Confirm `localization_platform.db` is **not** committed (excluded by `.gitignore`)

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

Translation history, Translation Memory, and the Glossary are stored in a local SQLite database (`localization_platform.db`) on the app server. The database is initialised automatically on startup and the glossary is seeded from code if empty.

The database **resets on each redeployment** because Streamlit Cloud uses an ephemeral filesystem — this is expected behaviour. A future version could use a persistent store (e.g. Supabase, Firebase) for cross-deployment persistence.

---

## Security Rules

| Rule | Status |
|------|--------|
| `.env` committed to Git | Never |
| Real API key in source code | Never |
| Login password in source code | Never |
| Real Excel/product files on GitHub | Never |
| `secrets.toml` committed | Never (gitignored) |
| `localization_platform.db` committed | Never (gitignored) |
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
├── database.py                      # SQLite backend (history, TM, glossary)
├── .gitignore                       # Excludes .env, *.xlsx, *.db
└── README.md                        # This file
```

**Runtime files (not committed):**
- `localization_platform.db` — SQLite database (history, TM, glossary)

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
