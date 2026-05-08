# German to French E-commerce Translator

> **Project Type:** Portfolio Prototype / Demo Application

AI-powered product localization tool that translates German Excel product data to French for e-commerce market expansion.

---

## Overview

This Streamlit web application demonstrates an AI-powered translation workflow for e-commerce product catalogs. It's designed for companies expanding from German-speaking markets to French-speaking markets.

**Key capabilities:**
- Upload German Excel files (.xlsx) containing product data
- Automatically translate product information from German to French using AI
- Download the translated French Excel file with preserved formatting

---

## Features

| Feature | Description |
|---------|-------------|
| **AI Translation** | Uses OpenAI GPT-4o-mini for natural, context-aware translations |
| **Real-Time Progress** | Live updates showing current row, column, and time remaining |
| **German Residue Detection** | Automatically detects and fixes remaining German words |
| **Smart Validation** | Product names validated (max 40 chars, no commas/brackets) |
| **Structure Preservation** | Excel formatting, formulas, and structure remain intact |
| **Secure Configuration** | API keys loaded from secrets — never hardcoded in source code |

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **Python 3.8+** | Core programming language |
| **Streamlit** | Web application framework |
| **openpyxl** | Excel file manipulation |
| **OpenAI API** | AI translation engine (GPT-4o-mini) |
| **python-dotenv** | Local environment variable loading |

---

## Local Setup

### Prerequisites

- Python 3.8 or higher
- An OpenAI API key ([Get one here](https://platform.openai.com/api-keys))

### Installation

```bash
# Clone the repository
git clone https://github.com/yves-alt/de-fr-ecommerce-translator.git
cd de-fr-ecommerce-translator

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure your API key locally

```bash
cp .env.example .env
```

Edit `.env` and add your real key:

```env
OPENAI_API_KEY=sk-proj-your-real-key-here
```

> **Never commit `.env` to Git.** It is already listed in `.gitignore`.

### Run locally

```bash
streamlit run app.py
```

The app opens at **http://localhost:8501**

---

## Deployment — Streamlit Community Cloud

> **Before deploying, read the security rules below.**

### Steps

1. Push your code to a **public or private GitHub repository**
   - Make sure `.env` is **not** committed (it is gitignored)
   - Make sure real Excel files are **not** committed (`.xlsx` is gitignored)

2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**

3. Connect your GitHub repository and set:
   - **Main file path:** `app.py`

4. Before clicking Deploy, open **Advanced settings → Secrets** and paste:

```toml
OPENAI_API_KEY = "sk-proj-your-real-key-here"
```

5. Click **Deploy**

The app reads `OPENAI_API_KEY` from Streamlit secrets on Cloud, and from `.env` locally. No key is ever stored in the source code.

---

## How the API Key is Loaded

The app uses a safe fallback system in this order:

1. **`st.secrets["OPENAI_API_KEY"]`** — used on Streamlit Cloud
2. **`.env` file via python-dotenv** — used for local development
3. **Error message** — shown in the app if neither source provides a key

```python
# No API key is ever hardcoded in app.py
```

---

## Security Rules

| Rule | Status |
|------|--------|
| `.env` committed to Git | Never |
| Real API key in source code | Never |
| Real Excel/product files on GitHub | Never |
| API key in `secrets.toml` committed | Never (gitignored) |
| `.env.example` contains a placeholder only | Yes |
| `.streamlit/secrets.toml.example` is safe to commit | Yes (placeholder only) |

---

## Input Requirements

- Excel file format: `.xlsx`
- Must contain a sheet named **"Tabelle1"**
- First row must contain column headers

### Supported Columns

| Column | Description |
|--------|-------------|
| `name` | Product name (max 40 chars) |
| `colorDetail` | Color information |
| `deliveryScope` | Delivery contents |
| `materialDetail` | Material description |
| `otherMeasurements` | Dimensions |
| `qualityDetail` | Quality information |
| `textileCompositionCover1` | Textile composition |
| `variantName` | Product variant name |

---

## Project Structure

```
de-fr-ecommerce-translator/
├── app.py                          # Main Streamlit application
├── requirements.txt                # Python dependencies
├── .env.example                    # Local config template (no real keys)
├── .streamlit/
│   └── secrets.toml.example        # Streamlit Cloud secrets template
├── .gitignore                      # Excludes .env, *.xlsx, secrets.toml
└── README.md                       # This file
```

---

## Workflow

1. **Upload** — Select your German Excel file (.xlsx)
2. **Translate** — Click the "Translate Excel File" button
3. **Monitor** — Watch real-time progress tracking
4. **Download** — Get your translated file (FR-filename.xlsx)

---

## Safety Features

| Rule | Description |
|------|-------------|
| `articleNumber` never translated | Product IDs remain unchanged |
| Row 1 never modified | Headers stay in original language |
| Selective translation | Only specified columns are processed |
| Sheet preservation | Only "Tabelle1" is processed |
| German residue check | Triple-check to remove remaining German words |
| Original file safety | Input file is never modified |

---

## Author

**Yves Koulle Banga**

- GitHub: [@yves-alt](https://github.com/yves-alt)

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

## Disclaimer

This is a **portfolio demonstration project**. It showcases AI-powered translation capabilities for e-commerce localization workflows. Not intended for production use without proper security review and testing.
