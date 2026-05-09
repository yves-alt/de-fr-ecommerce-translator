# German to French E-commerce Translator

> **Project Type:** Portfolio Prototype / Internal Tool Demo

AI-powered product localization tool that translates German Excel product data to French for e-commerce market expansion.

---

## Overview

This Streamlit web application provides an AI-powered translation workflow for e-commerce product catalogs. Designed for companies expanding from German-speaking markets to French-speaking markets.

**Key capabilities:**
- Secure login before accessing the translator
- Upload German `.xlsx` files and translate product data to French using AI
- Real-time progress tracking with residue detection and auto-correction
- Translation History dashboard with per-job statistics
- Analytics dashboard with time savings and estimated API cost
- Download the translated French Excel file with preserved formatting

---

## Features

| Feature | Description |
|---------|-------------|
| **Authentication** | Secure login page — credentials stored in secrets, never in code |
| **AI Translation** | OpenAI GPT-4o-mini for context-aware product translations |
| **Real-Time Progress** | Live updates showing row, column, and estimated time remaining |
| **Residue Detection** | Up to 3 correction passes to eliminate remaining German words |
| **Column Detection** | Two-tier fuzzy classifier maps headers to known translation targets |
| **Quality Gate** | Post-translation report: residue check, protected columns, missed columns |
| **Translation History** | JSON-backed log of all translation jobs with stats and cost |
| **Analytics** | Aggregated totals, estimated time saved, and API cost overview |

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

## Deployment — Streamlit Community Cloud

### Steps

1. Push your code to GitHub.
   - Confirm `.env` is **not** committed (check `.gitignore`)
   - Confirm no real Excel files are committed
   - Confirm `translation_history.json` is **not** committed

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

### Note on Translation History (Streamlit Cloud)

Translation history is stored in `translation_history.json` on the app server's local file system.
This file is **not persisted between redeployments** — history will reset each time the app is redeployed.
This is accepted behaviour for this version. A future version could use a persistent store (e.g. Supabase, Firebase).

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
| `.env.example` contains real values | Never (placeholders only) |
| `secrets.toml.example` is safe to commit | Yes (placeholders only) |

---

## How Credentials Are Loaded

The app reads credentials from two sources (in order):

1. **`st.secrets`** — used on Streamlit Cloud
2. **`.env` file via python-dotenv** — used for local development

```python
# No API key or password is ever hardcoded in app.py
```

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
├── .gitignore                       # Excludes .env, *.xlsx, secrets.toml, history JSON
└── README.md                        # This file
```

---

## Workflow

1. **Login** — Enter your email and password on the login page
2. **Upload** — Select your German Excel file (.xlsx)
3. **Review** — Check the Column Detection Report
4. **Translate** — Click "Translate Excel File" and watch live progress
5. **Download** — Get your translated `FR-filename.xlsx`
6. **History** — Check the Translation History dashboard
7. **Analytics** — View time saved and cost estimates

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
