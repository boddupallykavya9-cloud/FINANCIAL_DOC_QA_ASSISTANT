# Financial Document Q&A Assistant

Small Streamlit app that accepts PDF and Excel financial documents, extracts text and tables, attempts to normalize basic financial metrics (Income Statement / Balance Sheet / Cash Flow), and provides a simple question-answer interface. Optionally integrates with a **local Ollama** model for natural answers.

## Features
- Upload PDF / Excel files
- Extract text + tables (pdfplumber, pandas)
- Heuristic extraction of common metrics (revenue, net income, total assets)
- Rule-based QA (fast & offline)
- Optional: send context + question to a local Ollama API for richer, conversational answers

## Quick setup (Linux / Windows / Mac)

1. Clone the repo and create venv:
```bash
git clone <your-repo-url>
cd <repo>
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt