# German to French E-commerce Translator

> **Project Type:** Portfolio Prototype / Internal Tool Demo

AI-powered product localization platform that translates German Excel product data to French (and Dutch) for e-commerce market expansion. Includes Translation Memory, Batch Processing, a professional Glossary system with auto-learning, Retry System with exponential backoff, advanced Column Intelligence, a Cost Dashboard, Human Review Mode with Excel highlighting, a Premium AI Refinement layer, a Furniture Localization Engine with 30+ outdoor/garden term mappings, and a 5-Pass Quality Pipeline with Terminology Consistency and Final QA.

---

## Overview

This Streamlit web application provides a production-grade translation workflow for e-commerce product catalogs. Designed for companies expanding from German-speaking markets to French-speaking markets.

**Key capabilities:**
- Secure login before accessing the translator
- Upload German `.xlsx` files and translate product data to French or Dutch using AI
- Translation Memory: reuse past translations instantly — no API call needed
- Batch Processing: translate 15 cells per API request instead of 1
- Glossary System: enforce consistent terminology; auto-learns furniture terms from each file
- Retry System: up to 3 retries with exponential backoff on API errors and rate limits
- Column Intelligence: 3-tier classifier (exact alias → substring → camelCase word-set)
- **5-Pass Quality Pipeline**: Translation → Refinement → Residue → Consistency → Final QA
- **Furniture Localization Engine**: 30+ outdoor/garden/lounge furniture mappings applied locally (no API cost)
- **Translation Consistency Engine**: detects same-source cells translated differently and harmonizes them
- Human Review Mode: quality analysis per cell, flagged rows highlighted yellow in Excel
- Cost Dashboard: total tokens, prompt vs completion breakdown, avg cost/file and /cell, per-job bar chart
- Real-time progress tracking with batch and TM stats
- Translation History dashboard with per-job statistics
- Analytics dashboard with TM savings, batch efficiency, glossary usage, and cost trends
- Glossary Management page: view, add, and update DE→FR/NL terms
- Download the translated French/Dutch Excel file with preserved formatting

---

## Features

| Feature | Description |
|---------|-------------|
| **Authentication** | Secure login — credentials stored in secrets, never in code |
| **AI Translation** | OpenAI GPT-4o-mini for context-aware product translations (FR + NL) |
| **Translation Memory** | SQLite-backed cache: reuses past translations, tracks hits/misses/cost saved |
| **Batch Processing** | Groups 20 cells per API request — up to 20× fewer API calls |
| **Glossary System** | 166+ DE→FR/NL e-commerce terms; auto-learns furniture terms (≥2× in source); editable via UI |
| **Retry System** | Up to 3 retries with exponential backoff; rate-limit detection; notify on each retry |
| **Column Intelligence** | 3-tier classifier: T1 exact alias → T2 substring → T3 camelCase word-set (≥2 matches) |
| **5-Pass Quality Pipeline** | Pass 1 Translation → Pass 2 Refinement → Pass 3 Residue → Pass 4 Consistency → Pass 5 Final QA |
| **Furniture Localization Engine** | 30+ outdoor/garden/lounge mappings (Loungeset, Sofaelement, pulverbeschichtet, Geflecht…) applied locally — zero API cost |
| **Translation Consistency Engine** | Detects when the same German source was translated differently across the file; harmonizes all instances; fixes known wrong AI variants (e.g. "rotin synthétique" → "résine tressée") |
| **Premium AI Refinement** | Optional second AI pass on name, materialDetail, qualityDetail, deliveryScope, variantName — produces natural, premium copy; skips short texts, colors, and dimensions automatically |
| **Final QA Scan** | Full-file local scan after all passes: flags empty cells with source content and any residue that slipped through; never blocks download |
| **Human Review Mode** | Quality analysis per cell; flags German residue, lost `<br>`, name violations; yellow highlight in Excel |
| **Cost Dashboard** | Total tokens, prompt vs completion breakdown, avg cost/file and /cell, per-job bar chart |
| **Real-Time Progress** | Live updates showing batch number, TM hits, cells queued, active pass |
| **Residue Detection** | Up to 3 correction passes to eliminate remaining German words |
| **Quality Gate** | Post-translation report: residue, TM stats, batch info, protected columns |
| **Analytics** | TM hit rate, cost saved, batch efficiency, top glossary terms, cost trends |
| **Glossary Management** | Add/update DE→FR/NL terms, view usage counts, reset to defaults |
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

# Admin account
ADMIN_EMAIL=your_admin_email_here
ADMIN_PASSWORD=your_admin_password_here

# Guest demo account
GUEST_EMAIL=your_guest_email_here
GUEST_PASSWORD=your_guest_password_here
```

> **Never commit `.env` to Git.** It is already in `.gitignore`.

> **Legacy key names** (`APP_USER_EMAIL` / `APP_USER_PASSWORD`) are still supported for the admin account — existing Streamlit Cloud deployments continue to work without changes.

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

## Batch Processing & Parallel Translation

Instead of sending one API request per cell, the app groups cells into batches and sends multiple batches concurrently.

**Default settings:** batch size 15 cells · 3 concurrent batches (configurable via Advanced Settings).

**How it works:**
1. All non-empty cells are pre-scanned.
2. Cells found in Translation Memory are served instantly — zero API calls.
3. Remaining cells are grouped by column type and split into batches.
4. Up to N batches are submitted to OpenAI in parallel via `ThreadPoolExecutor`.
5. Each batch worker returns its translations, token counts, and glossary hits.
6. The main thread accumulates all results and applies them to the Excel workbook sequentially — no concurrent writes.
7. The model returns a JSON array of exactly N strings; if the count mismatches (retry up to 2×), falls back to single-cell translation for that batch only.

**Concurrency settings (Advanced Settings):**
| Setting | Range | Default | Effect |
|---------|-------|---------|--------|
| Batch size | 5–30 | 15 | Cells per API request |
| Max concurrent batches | 1–5 | 3 | Parallel API calls; set to 1 for sequential mode |

**Safety guarantees:**
- Excel workbook is only written from the main thread — never concurrently.
- SQLite (TM, history, glossary) is only updated from the main thread after all batches complete.
- A batch failure never fails the whole file — only affected cells fall back to source text.
- Row numbers, column structure, `<br>` tags, and Excel formatting are fully preserved.
- Row 1 (headers) is never touched.
- Protected columns (`articleNumber`, `sku`, `productId`) are never translated.
- Set max concurrent batches to 1 to reproduce the old sequential behaviour exactly.

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

## Premium AI Refinement

After initial batch translation, an optional second AI pass elevates selected columns from "technically correct" to "natural premium French e-commerce copy".

**Why it exists:**
Some outputs from a single translation pass are correct but still sound slightly literal or German in style. For example:

| German | First pass | After refinement |
|--------|-----------|-----------------|
| `Spanplatte, foliert` | `Panneau de particules, décoré` | `Panneau de particules revêtu` |
| `Gestell aus Metall, pulverbeschichtet` | `Structure en métal, laquée par poudrage` | `Structure en métal laquée par poudrage` |

**Target columns:**
- `name` — product names
- `materialDetail` — material descriptions
- `qualityDetail` — quality information
- `deliveryScope` — delivery scope
- `variantName` — product variant names

**Cells automatically skipped (no refinement cost):**
- Short texts under 20 characters
- Single-word outputs (clean glossary hits)
- Pure color values
- Dimensions, measurements, and percentages
- All other columns (articleNumber, colorDetail, etc.)

**Safety rules enforced per cell:**
- `<br>` tag count must be identical in the refined output — any mismatch discards the refinement
- `name` column: refinement is discarded if the result is longer than the original
- Empty results are always discarded

**How to use:**
The refinement is enabled by default. Toggle it off in **Advanced settings → Premium French Refinement Enabled** to skip it and reduce API cost.

**Cost impact:**
Roughly 5–15% extra tokens compared to translation-only mode, depending on how many long-text cells are present. Refinement tokens are included in the Cost Dashboard totals.

---

## 5-Pass Quality Pipeline

Every translation job runs through up to five sequential passes. The first three are always active; Passes 4 and 5 can be toggled off in Advanced settings.

| Pass | Name | Cost | What it does |
|------|------|------|--------------|
| **1** | Initial Translation | API | Batch-translate all cells via GPT-4o-mini; serve TM/glossary hits locally |
| **2** | Premium Refinement | API (optional) | Second AI pass on long-text columns to produce natural e-commerce copy |
| **3** | Residue Check | Local + API | Local furniture term fix first; AI fix for any remaining German words (max 2 attempts) |
| **4** | Consistency Pass | Local | Harmonize same-source inconsistencies; fix known wrong AI variants — zero API cost |
| **5** | Final QA | Local | Full-file scan: flag empty cells and any residue that slipped through earlier passes — zero API cost, never blocks download |

A **Quality Pipeline** status panel is shown in the Results section after each job, indicating which passes ran and their outcomes.

---

## Furniture Localization Engine

A local, regex-based replacement layer applied after initial translation (Pass 1) and again during residue checking (Pass 3). Covers 30+ German outdoor, lounge, and garden furniture terms that the general AI translation tends to handle inconsistently.

**Example mappings:**

| German | French | Dutch |
|--------|--------|-------|
| Loungeset | salon de jardin | loungeset |
| Sofaelement | module de canapé | bankmodule |
| Gartenessgruppe | ensemble de jardin | tuineetset |
| pulverbeschichtet | thermolaqué | gepoedercoat |
| Geflecht / Polyrattan | résine tressée | kunststof vlechtwerk |
| Tischgestell | piètement de table | tafelpoot |
| Set bestehend aus | ensemble composé de | set bestaande uit |
| Absetzung | bordure contrastante | contrasterende rand |

All replacements use word-boundary regex (no partial matches) and are applied longest-match first.

---

## Translation Consistency Engine

After refinement (Pass 4), a two-stage local pass ensures terminology is uniform across the entire file.

**Stage 1 — Same source → same translation:**
- Scans all translated cells and groups them by their (normalized) German source text.
- Any group where the same German text produced different translations gets harmonized.
- Glossary takes priority; otherwise the most-frequent translation wins.

**Stage 2 — Hard variant replacement:**
- Fixes known wrong AI-generated variants such as "rotin synthétique" → "résine tressée" or "laqué par poudre" → "thermolaqué".
- Applied with word-boundary regex — no unintended partial replacements.

Both stages run entirely locally with no API calls.

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

# Admin account
ADMIN_EMAIL    = "your_admin_email_here"
ADMIN_PASSWORD = "your_admin_password_here"

# Guest demo account
GUEST_EMAIL    = "your_guest_email_here"
GUEST_PASSWORD = "your_guest_password_here"
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

Two accounts are supported:
- **Admin** — reads `ADMIN_EMAIL` / `ADMIN_PASSWORD` (falls back to legacy `APP_USER_EMAIL` / `APP_USER_PASSWORD`)
- **Guest** — reads `GUEST_EMAIL` / `GUEST_PASSWORD`

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

## Jira Integration

The platform includes an optional Jira workflow integration that automates the international content team's translation ticket process.

### What it does

| Step | Manual workflow | With Jira Integration |
|------|-----------------|----------------------|
| Find ticket | Open Jira, search manually | Search by JQL in the app |
| Get file | Download Excel from ticket | Click "Download and translate" |
| Translate | CAT tool / external AI | Existing AI pipeline (unchanged) |
| Upload results | Attach files to ticket manually | Click "Upload XLSX" / "Upload CSV" / "Upload both" |
| Comment | Write comment manually | Auto-generated comment (optional) |
| Status change | Change ticket status manually | Apply transition from dropdown (optional) |

### Setup

1. Get a Jira API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)

2. Add credentials to `.env` (local) or Streamlit Secrets (cloud):

```env
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_EMAIL=your-email@home24.de
JIRA_API_TOKEN=your-api-token-here

# Optional: default JQL query
JIRA_TRANSLATION_JQL=project = LOCALIZATION AND status = 'To Do' ORDER BY created DESC
```

### Workflow

1. Go to **Jira Tickets** in the sidebar (Admin or Standard User only — Guest has no access)
2. Enter a JQL query and click **Search**
3. Select a ticket from the results table
4. Select the Excel attachment to translate
5. Click **Download and translate** — the file is downloaded and the Translator page opens automatically
6. Translate as normal (French or Dutch)
7. After translation, scroll down to **Upload to Jira**:
   - Click **Upload XLSX**, **Upload CSV**, or **Upload both**
   - Optionally check "Add Jira comment after upload"
   - Optionally apply a status transition (e.g. In Progress → Ready for SAP Upload)

### Safety rules

- No automatic file uploads or ticket changes — every action requires an explicit button click
- Tickets are never closed automatically
- The Jira API token is never exposed in the UI or logs
- Guest accounts cannot access the Jira integration
- Downloaded files are held in memory only — never written to disk

---

## Project Structure

```
de-fr-ecommerce-translator/
├── app.py                           # Main Streamlit application
├── intelligence.py                  # Translation intelligence engine (consistency, furniture terms, glossary auto-learn)
├── database.py                      # SQLite backend (history, TM, glossary, Jira metadata, migrations)
├── jira_client.py                   # Jira REST API client (v3)
├── glossary.json                    # 166+ DE→FR furniture/e-commerce terms
├── requirements.txt                 # Python dependencies
├── .env.example                     # Local config template (no real values)
├── .streamlit/
│   └── secrets.toml.example         # Streamlit Cloud secrets template
├── .gitignore                       # Excludes .env, *.xlsx, *.db
└── README.md                        # This file
```

**Runtime files (not committed):**
- `localization_platform.db` — SQLite database (history, TM, glossary)

---

## Workflow

1. **Login** — Enter your email and password
2. **Upload** — Select your German Excel file (.xlsx) and choose target language (French / Dutch)
3. **Review** — Check the Column Detection summary; admin users can expand the full report
4. **Configure** — Adjust batch size, concurrency, refinement, consistency, and QA in Advanced settings
5. **Translate** — Click "Run Translation →" and watch live batch progress
6. **Pass 1** — Batch translation via GPT-4o-mini; TM/glossary hits served instantly
7. **Pass 2** — Premium Refinement on long-text columns (if enabled)
8. **Pass 3** — Residue check: local furniture-term fix first, then AI fix for persistent German words
9. **Pass 4** — Consistency pass: harmonize recurring terms across the file (if enabled)
10. **Pass 5** — Final QA scan: flag empty cells and residue missed by earlier passes (if enabled)
11. **Review results** — Quality Pipeline status, TM hits, batch stats, glossary matches, warnings
12. **Download** — Get your translated `FR-filename.xlsx` (or `NL-filename.xlsx`)
13. **Analytics** — Track TM savings, batch efficiency, and glossary usage
14. **Glossary** — View and extend your terminology library

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
