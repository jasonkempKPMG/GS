"""
LangGraph node implementations for each of the 8 pipeline steps.
Each node receives the full GraphState and returns a partial state dict.

Design: two-file comparison
  - sample_bytes  = Sample Summary (reported values)
  - source_bytes  = Source Evidence (actual values — Excel or image)
  - pdf_bytes_list = Regulatory PDFs (context for how to compare the two)
"""
import io
import os
import json
import pandas as pd
from pypdf import PdfReader
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agents import excel_to_csv_text, _parse_json_response, run_ocr_agent
from prompts import MAPPING_EXTRACTION_PROMPT, FINAL_REPORT_PROMPT

MODEL = "claude-sonnet-4-6"


def _llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=MODEL,
        max_tokens=4096,
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )


# ── Step 1: Load Transaction Data ─────────────────────────────────────────────
def step1_load_data(state: dict) -> dict:
    """
    Python only — loads BOTH the sample summary (reported values) and the
    source evidence (actual values) into CSV strings for downstream nodes.
    """
    errors = list(state.get("errors", []))
    sample_csv = ""
    source_csv = ""

    # Load sample summary (reported values) + read "Attributes to test" tab
    attributes_to_test = []
    try:
        sample_bytes = state["sample_bytes"]
        sample_filename = state.get("sample_filename", "sample.xlsx")
        if sample_filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(sample_bytes))
            sample_csv = df.to_csv(index=False)
        else:
            xl = pd.ExcelFile(io.BytesIO(sample_bytes))
            # First sheet = sample records
            sample_csv = xl.parse(xl.sheet_names[0]).to_csv(index=False)
            # Look for an "attributes to test" tab (any sheet after the first)
            for sheet_name in xl.sheet_names[1:]:
                if "attrib" in sheet_name.lower() or "test" in sheet_name.lower():
                    attr_df = xl.parse(sheet_name, header=None)
                    # Flatten all non-null values into a list, skip header-like rows
                    for val in attr_df.values.flatten():
                        val_str = str(val).strip()
                        if val_str and val_str.lower() not in ("nan", "attributes to test", "attribute"):
                            attributes_to_test.append(val_str)
                    break
    except Exception as e:
        errors.append(f"Step 1 — sample load error: {str(e)}")

    # Load source evidence (actual values) — only if Excel; OCR handled in step 1b via agents.py
    source_type = state.get("source_type", "excel")
    if source_type == "excel":
        try:
            source_bytes = state["source_bytes"]
            source_filename = state.get("source_filename", "source.xlsx")
            if source_filename.lower().endswith(".csv"):
                df = pd.read_csv(io.BytesIO(source_bytes))
                source_csv = df.to_csv(index=False)
            else:
                sheets = excel_to_csv_text(source_bytes, source_filename)
                source_csv = next(iter(sheets.values()))
        except Exception as e:
            errors.append(f"Step 1 — source load error: {str(e)}")

    # If source is an image, run OCR agent for each record in the sample now
    ocr_results = []
    if source_type == "ocr" and sample_csv:
        source_bytes = state.get("source_bytes", b"")
        source_filename = state.get("source_filename", "source.jpg")
        supporting_doc = "\n".join(state.get("pdf_texts", []))  # use PDFs if already extracted

        try:
            sample_df = pd.read_csv(io.StringIO(sample_csv))
            # Find the ID column — first column is usually the key
            id_col = sample_df.columns[0]
            # Use explicit attributes list if available, otherwise extract all sample columns
            ocr_attributes = attributes_to_test if attributes_to_test else [c for c in sample_df.columns if c != id_col]
            for _, row in sample_df.iterrows():
                record_id = str(row[id_col]).strip()
                if not record_id or record_id.lower() == "nan":
                    continue
                try:
                    result = run_ocr_agent(
                        image_bytes=source_bytes,
                        filename=source_filename,
                        attributes=ocr_attributes,
                        record_identifier={"key": id_col, "value": record_id},
                        supporting_doc_text=supporting_doc or "Extract the listed attributes from the image.",
                    )
                    ocr_results.append(result)
                except Exception as e:
                    ocr_results.append({
                        "agent": "ocr_extraction_agent",
                        "status": "ERROR",
                        "record_identifier": {"key": id_col, "value": record_id},
                        "extracted_attributes": [],
                        "errors": [str(e)],
                    })
        except Exception as e:
            errors.append(f"Step 1 — OCR loop error: {str(e)}")

    return {
        "sample_df_csv": sample_csv,
        "source_df_csv": source_csv,
        "attributes_to_test": attributes_to_test,
        "ocr_results": ocr_results,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step1_load_data"],
    }


# ── Step 2: Upload PDFs to Platform ──────────────────────────────────────────
def step2_extract_pdfs(state: dict) -> dict:
    """
    Python only — extracts text from regulatory PDF bytes using pypdf.
    PDFs provide context for how to compare sample vs source (column mappings,
    calculation rules, join keys). Not data sources themselves.
    """
    pdf_bytes_list = state.get("pdf_bytes_list", [])
    pdf_filenames = state.get("pdf_filenames", [])
    pdf_texts = []

    for i, pdf_bytes in enumerate(pdf_bytes_list):
        fname = pdf_filenames[i] if i < len(pdf_filenames) else f"document_{i+1}.pdf"
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text_parts = [p.extract_text() for p in reader.pages if p.extract_text()]
            pdf_texts.append(f"=== {fname} ===\n" + "\n\n".join(text_parts))
        except Exception as e:
            pdf_texts.append(f"=== {fname} ===\n[ERROR extracting text: {str(e)}]")

    return {
        "pdf_texts": pdf_texts,
        "completed_steps": state.get("completed_steps", []) + ["step2_extract_pdfs"],
    }


# ── Step 3: Generate Column Mappings from PDFs ────────────────────────────────
def step3_generate_rules(state: dict) -> dict:
    """
    LLM — reads the regulatory PDFs plus both file schemas and extracts:
    - The join key (how to match records between sample and source)
    - Column mappings (sample column → source column + transformation rule)
    Output stored as column_mappings (a dict with join_key + mappings list).
    """
    pdf_texts = state.get("pdf_texts", [])
    sample_csv = state.get("sample_df_csv", "")
    source_csv = state.get("source_df_csv", "")

    # First 6 rows of each file (header + 5 data rows)
    def preview(csv_text, n=6):
        lines = csv_text.strip().split("\n")
        return "\n".join(lines[:n])

    combined_pdf = "\n\n".join(pdf_texts)
    if len(combined_pdf) > 50000:
        combined_pdf = combined_pdf[:50000] + "\n\n[... truncated ...]"

    user_msg = f"""Extract the join key and column mappings between the Sample Summary and Source Evidence files.
Use the regulatory PDF text as context to understand what each field means and how they relate.

**Sample Summary (reported values) — first 5 rows:**
```
{preview(sample_csv)}
```

**Source Evidence (actual values) — first 5 rows:**
```
{preview(source_csv) if source_csv else "[No Excel source — OCR source, column names not available at this stage]"}
```

**Regulatory PDF Context:**
{combined_pdf}

Return the JSON mapping object."""

    try:
        llm = _llm()
        response = llm.invoke([
            SystemMessage(content=MAPPING_EXTRACTION_PROMPT),
            HumanMessage(content=user_msg),
        ])
        mappings = _parse_json_response(response.content)
        if isinstance(mappings, list):
            # Fallback: model returned a list instead of the expected object
            mappings = {"join_key": {}, "mappings": mappings, "notes": ""}
    except Exception as e:
        mappings = {
            "join_key": {},
            "mappings": [],
            "notes": f"ERROR extracting mappings: {str(e)}",
        }

    return {
        "column_mappings": mappings,
        "completed_steps": state.get("completed_steps", []) + ["step3_generate_rules"],
    }


# ── Step 4a: Compute Data Statistics (STUB) ───────────────────────────────────
def step4a_compute_stats(state: dict) -> dict:
    return {
        "data_statistics": {
            "status": "stub",
            "message": "Step 4a: Compute Data Statistics — not yet implemented.",
            "planned": "Quartiles, value counts, cardinality ratios on both sample and source.",
        },
        "completed_steps": state.get("completed_steps", []) + ["step4a_compute_stats"],
    }


# ── Step 4b: Generate Supplemental Rules (STUB) ───────────────────────────────
def step4b_supplemental_rules(state: dict) -> dict:
    return {
        "supplemental_rules": [{
            "status": "stub",
            "message": "Step 4b: Generate Supplemental Rules — not yet implemented.",
            "planned": "LLM identifies statistical anomalies in the data as additional rules.",
        }],
        "completed_steps": state.get("completed_steps", []) + ["step4b_supplemental_rules"],
    }


# ── Step 5: Translate Rules to Executable Specification (STUB) ────────────────
def step5_translate_rules(state: dict) -> dict:
    return {
        "executable_specs": [{
            "status": "stub",
            "message": "Step 5: Translate Rules to Executable Specification — not yet implemented.",
            "planned": "LLM converts column mappings into pandas merge + comparison expressions.",
        }],
        "completed_steps": state.get("completed_steps", []) + ["step5_translate_rules"],
    }


# ── Step 6: Apply Rules on Full Dataset (STUB) ────────────────────────────────
def step6_apply_rules(state: dict) -> dict:
    return {
        "rule_results": {
            "status": "stub",
            "message": "Step 6: Apply Rules on Full Dataset — not yet implemented.",
            "planned": "Join sample and source on join key, compare mapped columns row by row.",
        },
        "completed_steps": state.get("completed_steps", []) + ["step6_apply_rules"],
    }


# ── Step 7: Execute Sampling Algorithm (STUB) ─────────────────────────────────
def step7_sampling(state: dict) -> dict:
    return {
        "sample_records": [{
            "status": "stub",
            "message": "Step 7: Execute Sampling Algorithm — not yet implemented.",
            "planned": "Multi-phase deterministic sampling: overlap, proportional, fallback.",
        }],
        "completed_steps": state.get("completed_steps", []) + ["step7_sampling"],
    }


# ── Step 8: Generate Final Report ────────────────────────────────────────────
def step8_final_report(state: dict) -> dict:
    """
    LLM — compares the sample summary (reported) against the source evidence
    (actual) using the column mappings from Step 3, then produces a markdown
    audit table with Pass/Fail/N/A per attribute per record.
    """
    sample_csv = state.get("sample_df_csv", "")
    source_csv = state.get("source_df_csv", "")
    mappings = state.get("column_mappings", {})
    source_filename = state.get("source_filename", "source file")
    attributes_to_test = state.get("attributes_to_test", [])
    ocr_results = state.get("ocr_results", [])
    source_type = state.get("source_type", "excel")

    # Limit rows sent to LLM to save tokens
    def preview(csv_text, n=20):
        lines = csv_text.strip().split("\n")
        return "\n".join(lines[:n])

    attr_instruction = (
        f"**IMPORTANT — Only test these specific attributes: {attributes_to_test}. "
        f"Ignore all other columns in the sample. Only these attributes should appear in the report.**"
        if attributes_to_test else
        "Test all mapped attributes."
    )

    if source_type == "ocr" and ocr_results:
        user_msg = f"""Compare the Sample Summary (reported values) against the OCR-extracted Source Evidence (actual values) using the column mappings below. Generate the Data Quality Report.

{attr_instruction}

**Column Mappings (from Step 3):**
```json
{json.dumps(mappings, indent=2)}
```

**Sample Summary — reported values (first 20 rows):**
```
{preview(sample_csv)}
```

**OCR-Extracted Source Evidence ({source_filename}) — actual values extracted from image:**
```json
{json.dumps(ocr_results, indent=2)}
```

Each OCR result contains a `record_identifier` (the join key) and `extracted_attributes` (list of {{attribute, value}} pairs).
Match each sample record to the OCR result with the same record identifier.
For ONLY the specified attributes, compare reported vs OCR-extracted value and determine Pass/Fail.
Generate the markdown Data Quality Report table."""
    else:
        user_msg = f"""Compare the Sample Summary (reported values) against the Source Evidence (actual values) using the column mappings below. Generate the Data Quality Report.

{attr_instruction}

**Column Mappings (from Step 3):**
```json
{json.dumps(mappings, indent=2)}
```

**Sample Summary — reported values (first 20 rows):**
```
{preview(sample_csv)}
```

**Source Evidence ({source_filename}) — actual values (first 20 rows):**
```
{preview(source_csv) if source_csv else "[Source is an image/OCR — no structured data available]"}
```

For each record in the sample, find the matching row in the source using the join key.
For ONLY the specified attributes, compare reported vs source value and determine Pass/Fail.
Generate the markdown Data Quality Report table."""

    try:
        llm = _llm()
        response = llm.invoke([
            SystemMessage(content=FINAL_REPORT_PROMPT),
            HumanMessage(content=user_msg),
        ])
        report_md = response.content
    except Exception as e:
        report_md = f"## Data Quality Report\n\n**Error generating report:** {str(e)}"

    return {
        "final_report": report_md,
        "completed_steps": state.get("completed_steps", []) + ["step8_final_report"],
    }
