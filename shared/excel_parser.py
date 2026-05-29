"""
Excel parsing utilities — stubs that delegate to app.py scan logic.
Actual heavy lifting is done by openpyxl in app.py and nl_engine.py.
"""

from nl_engine import parse_trados_xlsx


def parse_trados_tm_excel(path: str) -> list[dict]:
    """
    Parse a Trados TM Export Excel file.
    Returns list of {"source": str, "target": str, "usage_count": int}.
    """
    return parse_trados_xlsx(path)


def parse_glossary_excel(path: str, sheet_name: str, de_col: int = 0, nl_col: int = 1) -> list[dict]:
    """
    Parse a simple DE→NL glossary Excel.
    Returns list of {"source_term_de": str, "target_term_nl": str}.
    Skips header row (row 0) and strips whitespace from all terms.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet_name]
    except Exception as exc:
        raise ValueError(f"Cannot read glossary file: {exc}") from exc

    entries = []
    header_skipped = False
    for row in ws.iter_rows(values_only=True):
        if not header_skipped:
            header_skipped = True
            continue
        if not row:
            continue
        de = str(row[de_col]).strip() if row[de_col] is not None else ""
        nl = str(row[nl_col]).strip() if nl_col < len(row) and row[nl_col] is not None else ""
        if not de or not nl:
            continue
        entries.append({"source_term_de": de, "target_term_nl": nl})

    wb.close()
    return entries
