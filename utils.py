# utils.py
import re
import pdfplumber
import pandas as pd
from io import BytesIO
import openpyxl

number_re = re.compile(r"[-+]?\$\s?[\d,]+(?:\.\d+)?|[-+]?\d[\d,]*(?:\.\d+)?")

def clean_number_string(s):
    if s is None:
        return None
    s = str(s)
    s = s.replace(",", "")
    s = s.replace("$", "")
    s = s.replace("(", "-")
    s = s.replace(")", "")
    s = s.strip()
    try:
        if s == "":
            return None
        val = float(s)
        return val
    except:
        # try to extract digits
        m = re.search(r"-?[\d]+(?:\.\d+)?", s)
        if m:
            try:
                return float(m.group(0))
            except:
                return None
        return None

def extract_numbers_from_text(text):
    found = number_re.findall(text or "")
    cleaned = []
    for f in found:
        val = clean_number_string(f)
        if val is not None:
            cleaned.append(val)
    return cleaned

def extract_from_pdf(path):
    """Return (full_text, list_of_tables_as_dataframes). Uses pdfplumber to extract text and tables."""
    text_parts = []
    tables = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                text_parts.append(txt)
            # try to extract table(s)
            try:
                tbl = page.extract_table()
                if tbl:
                    # convert to dataframe
                    df = pd.DataFrame(tbl[1:], columns=tbl[0])
                    tables.append(df)
            except Exception:
                pass
    full_text = "\n".join(text_parts)
    return full_text, tables

def extract_from_excel(path):
    """Return (concatenated_text, list_of_tables). Uses pandas read_excel to parse sheets."""
    try:
        xl = pd.read_excel(path, sheet_name=None, header=None)
    except Exception as e:
        # try with engine openpyxl
        xl = pd.read_excel(path, sheet_name=None, header=None, engine="openpyxl")
    texts = []
    tables = []
    for sheet_name, df in xl.items():
        # record a CSV preview
        texts.append(f"Sheet: {sheet_name}\n{df.head(20).to_string()}")
        # store the dataframe as a table if it looks like numeric
        tables.append(df)
    return "\n\n".join(texts), tables

def find_keywords_in_text(text, keywords):
    text_low = (text or "").lower()
    for k in keywords:
        if k.lower() in text_low:
            return True
    return False

def normalize_financial_data(text, tables):
    """
    Attempt to detect Income Statement, Balance Sheet, Cash Flow patterns and extract
    key metrics into a structured dict:
    { "Income Statement": { period1: {"Revenue": val, "Net Income": val,...}, ... }, ... }
    This is heuristic: it looks for keywords and numeric columns.
    """
    result = {}
    # Heuristic: search for statement keywords in text
    if find_keywords_in_text(text, ["income statement", "statement of operations", "profit and loss", "revenue"]):
        # parse tables for revenue/net income keywords
        is_fin = extract_metrics_from_tables(tables, ["revenue", "net income", "gross profit", "operating income", "total revenue", "profit"])
        if is_fin:
            result["Income Statement"] = is_fin
    if find_keywords_in_text(text, ["balance sheet", "assets", "liabilities", "equity"]):
        bs = extract_metrics_from_tables(tables, ["total assets", "total liabilities", "shareholders' equity", "equity"])
        if bs:
            result["Balance Sheet"] = bs
    if find_keywords_in_text(text, ["cash flow", "cash flows", "net cash", "cash and cash equivalents"]):
        cf = extract_metrics_from_tables(tables, ["net cash provided", "net cash", "cash flows from operating", "cash and cash equivalents"])
        if cf:
            result["Cash Flow"] = cf

    # fallback: try to find common metric names anywhere in tables
    fallback = extract_metrics_from_tables(tables, ["revenue", "net income", "total assets"])
    if fallback and not result:
        result["Extracted"] = fallback

    return result

def extract_metrics_from_tables(tables, metric_keywords):
    """
    Look for metric keywords in row labels of tables. Return mapping of detected metrics per period if possible.
    """
    metrics = {}
    for df in tables:
        try:
            # convert all to string
            df2 = df.copy()
            df2 = df2.fillna("").astype(str)
            # try find header columns that look like years or periods
            header_like = []
            # If first row contains years (like 2023, 2022)
            possible_header = df2.iloc[0].tolist()
            for j, v in enumerate(possible_header):
                if re.search(r"20\d{2}|FY|Q[1-4]", v):
                    header_like.append((j, v))
            # If header_like found, then rows probably metrics
            for idx in range(df2.shape[0]):
                row0 = df2.iloc[idx,0].lower() if df2.shape[1] > 0 else ""
                for kw in metric_keywords:
                    if kw.lower() in row0:
                        # collect row numbers across columns
                        row_vals = {}
                        for col in range(1, df2.shape[1]):  # assume first col labels, rest numeric
                            heading = df2.iloc[0, col] if df2.shape[0] > 0 else f"col{col}"
                            val_raw = df2.iloc[idx, col]
                            val = clean_number_string(val_raw)
                            if val is not None:
                                key = str(heading).strip()
                                row_vals[key] = val
                        metrics[row0.strip()] = row_vals
        except Exception:
            continue
    return metrics if metrics else None

def build_document_summary_text(extracted_data):
    """Return a compact text summary of extracted_data suitable to send to an LLM."""
    parts = []
    for fname, sections in extracted_data.items():
        parts.append(f"Document: {fname}")
        for secname, metrics in sections.items():
            parts.append(f"Section: {secname}")
            if isinstance(metrics, dict):
                for metric_label, values in metrics.items():
                    parts.append(f"- {metric_label}: {values}")
            else:
                parts.append(str(metrics))
    return "\n".join(parts)

def simple_qa_answer(question, extracted_data, selected_doc="all"):
    """
    A simple rule-based QA:
    - parse question for metric words (revenue, profit, net income, assets)
    - parse for year (e.g., 2023) or 'latest'
    - look into extracted_data and return value if found
    Returns (answer_text, confidence_float 0..1)
    """
    q = question.lower()
    metrics_candidates = ["revenue", "net income", "net loss", "profit", "total assets", "cash", "operating income", "gross profit"]
    metric = None
    for m in metrics_candidates:
        if m in q:
            metric = m
            break
    year_match = re.search(r"(20\d{2})", q)
    year = year_match.group(1) if year_match else None
    latest = "latest" in q or "most recent" in q or ("last" in q and re.search(r"last (year|quarter|q[1-4])", q))

    # select docs
    docs = extracted_data if selected_doc == "all" else {selected_doc: extracted_data.get(selected_doc, {})}
    # search
    for fname, sections in docs.items():
        for secname, metrics in sections.items():
            # metrics is dict: labels -> {period: value}
            if isinstance(metrics, dict):
                for label, periods in metrics.items():
                    if metric and metric in label:
                        # if year asked, try to find key with that year
                        if year:
                            for k, v in periods.items():
                                if year in str(k):
                                    return f"{label} for {year} is {v}", 0.9
                        # else latest: choose highest-order key or first
                        if latest:
                            # pick the first numeric found
                            for k, v in periods.items():
                                return f"{label} (most recent found: {k}) = {v}", 0.8
                        # else try any match
                        for k, v in periods.items():
                            return f"{label} ({k}) = {v}", 0.7
    # fallback: try text search for dollar amounts
    for fname, sections in docs.items():
        text = ""
        # try to assemble text
        if isinstance(sections, dict):
            text = str(sections)
        else:
            text = sections
        numbers = extract_numbers_from_text(text)
        if numbers:
            return f"I found numbers in the document but couldn't map them precisely to your question. Examples: {numbers[:5]}", 0.4

    return "I couldn't find a precise answer in the extracted data.", 0.0