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
| **Secure Configuration** | API keys stored in environment variables, never in code |

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **Python 3.8+** | Core programming language |
| **Streamlit** | Web application framework |
| **openpyxl** | Excel file manipulation |
| **OpenAI API** | AI translation engine (GPT-4o-mini) |
| **python-dotenv** | Secure environment variable management |

---

## Installation

### Prerequisites

- Python 3.8 or higher
- An OpenAI API key ([Get one here](https://platform.openai.com/api-keys))

### Setup

```bash
# Clone the repository
git clone https://github.com/yves-alt/de-fr-ecommerce-translator.git
cd de-fr-ecommerce-translator

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your OpenAI API key
```

---

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your-openai-api-key-here
```

> **Security:** Never commit the `.env` file. It's already included in `.gitignore`.

---

## Usage

### Start the Application

```bash
streamlit run app.py
```

The app opens automatically at: **http://localhost:8501**

### Workflow

1. **Upload** — Select your German Excel file (.xlsx)
2. **Translate** — Click the "Translate Excel File" button
3. **Monitor** — Watch real-time progress tracking
4. **Download** — Get your translated file (FR-filename.xlsx)

---

## Input Requirements

- Excel file format: `.xlsx`
- Must contain a sheet named **"Tabelle1"**
- First row must contain column headers

### Supported Columns

The following columns are automatically translated when present:

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

## Deployment Options

### Local Development
```bash
streamlit run app.py
```

### Streamlit Cloud
1. Push code to GitHub (without `.env`)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repository
4. Add `OPENAI_API_KEY` in Secrets (Settings → Secrets)

### Docker (Optional)
```bash
docker build -t de-fr-translator .
docker run -p 8501:8501 -e OPENAI_API_KEY=your-key de-fr-translator
```

---

## Project Structure

```
de-fr-ecommerce-translator/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .gitignore          # Git ignore rules
└── README.md           # Documentation
```

---

## Demo

To test the application, create a sample Excel file with:
- Sheet name: "Tabelle1"
- Columns: `articleNumber`, `name`, `colorDetail`, `materialDetail`
- Sample German product data

---

## Author

**Yves Koulle Banga**

- GitHub: [@yves-alt](https://github.com/yves-alt)

---

## License

MIT License - See [LICENSE](LICENSE) for details.

---

## Disclaimer

This is a **portfolio demonstration project**. It showcases AI-powered translation capabilities for e-commerce localization workflows. Not intended for production use without proper security review and testing.
