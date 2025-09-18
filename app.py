# app.py
import streamlit as st
from utils import (
    extract_from_pdf,
    extract_from_excel,
    normalize_financial_data,
    simple_qa_answer,
    build_document_summary_text,
)
import json
import os
import tempfile
import requests

st.set_page_config(page_title="Financial Doc Q&A Assistant", layout="wide")

st.title("💬 Financial Document Q&A Assistant")

# Sidebar - settings
st.sidebar.header("Settings")
use_ollama = st.sidebar.checkbox("Use local Ollama for natural answers (optional)", value=False)
ollama_url = st.sidebar.text_input("Ollama URL (if enabled)", value="http://localhost:11434/api/generate")
ollama_model = st.sidebar.text_input("Ollama model name", value="llama2")  # change as required

uploaded_files = st.file_uploader("Upload PDF or Excel files (multiple allowed)", accept_multiple_files=True, type=["pdf","xls","xlsx"], help="Upload financial statements: Income statement, Balance sheet, Cash flow.")
process_button = st.button("Process uploaded documents")

if "extracted_data" not in st.session_state:
    st.session_state["extracted_data"] = {}
if "doc_texts" not in st.session_state:
    st.session_state["doc_texts"] = {}
if "convo" not in st.session_state:
    st.session_state["convo"] = []

if process_button:
    if not uploaded_files:
        st.warning("Please upload one or more PDF/Excel files first.")
    else:
        progress = st.progress(0)
        total = len(uploaded_files)
        all_financials = {}
        doc_texts = {}
        for i, uploaded in enumerate(uploaded_files):
            fname = uploaded.name
            suffix = fname.split(".")[-1].lower()
            st.info(f"Processing {fname}...")
            with tempfile.NamedTemporaryFile(delete=False, suffix="."+suffix) as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = tmp.name
            try:
                if suffix == "pdf":
                    text, tables = extract_from_pdf(tmp_path)
                else:
                    text, tables = extract_from_excel(tmp_path)
                doc_texts[fname] = {"text": text, "tables": tables}
                fin = normalize_financial_data(text, tables)
                all_financials[fname] = fin
                st.success(f"Extracted from {fname}: {len(fin)} metric groups found.")
            except Exception as e:
                st.error(f"Failed to process {fname}: {e}")
            progress.progress(int((i+1)/total*100))
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        st.session_state["extracted_data"] = all_financials
        st.session_state["doc_texts"] = doc_texts
        st.success("Document processing completed.")

# Show extracted summary
if st.session_state["extracted_data"]:
    st.subheader("Extracted financial metrics (preview)")
    for fname, fin in st.session_state["extracted_data"].items():
        st.markdown(f"**{fname}**")
        if not fin:
            st.write("_No clear metrics found. Try another document or check that the document contains standard statement tables._")
            continue
        # show summary table as JSON for quick view
        st.json(fin)

    st.markdown("---")
    st.subheader("Ask questions about the uploaded documents")
    col1, col2 = st.columns([3,1])
    with col1:
        question = st.text_input("Ask a question (e.g. 'What was revenue in 2023?')", key="question_input")
        ask = st.button("Ask")
    with col2:
        selected_doc = st.selectbox("Select document (or 'all')", options=["all"] + list(st.session_state["extracted_data"].keys()))

    if "history" not in st.session_state:
        st.session_state["history"] = []

    if ask and question.strip():
        # Build context from extracted data
        if selected_doc == "all":
            context = build_document_summary_text(st.session_state["extracted_data"])
        else:
            context = build_document_summary_text({selected_doc: st.session_state["extracted_data"][selected_doc]})
        # Try rule-based first
        answer, confidence = simple_qa_answer(question, st.session_state["extracted_data"], selected_doc)
        source = "rule-based"
        if confidence < 0.6 and use_ollama:
            # send to Ollama (if configured). We wrap doc context and question.
            prompt = f"""You are a financial assistant. Answer clearly and concisely.
Document extracted summary:
{context}

User question:
{question}

Provide the best possible factual answer using the document. If not answerable, say you couldn't find it.
"""
            try:
                payload = {
                    "model": ollama_model,
                    "prompt": prompt,
                    "max_tokens": 512
                }
                resp = requests.post(ollama_url, json=payload, timeout=20)
                if resp.ok:
                    j = resp.json()
                    # Ollama responses vary; try to extract text
                    if isinstance(j, dict) and "text" in j:
                        answer_llm = j["text"]
                    else:
                        # fallback
                        answer_llm = j.get("response") or str(j)
                    answer = answer_llm
                    source = "ollama"
                else:
                    st.warning(f"Ollama request failed: {resp.status_code} {resp.text}")
            except Exception as e:
                st.warning(f"Error calling Ollama: {e}")

        entry = {"question": question, "answer": answer, "source": source}
        st.session_state["history"].append(entry)

    # Show conversation history
    if st.session_state.get("history"):
        st.markdown("### Conversation")
        for turn in reversed(st.session_state["history"]):
            st.markdown(f"**Q:** {turn['question']}")
            st.markdown(f"**A:** {turn['answer']}  \n*({turn['source']})*")