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
import re
import json
import random
import math
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pypdf import PdfReader
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agents import excel_to_csv_text, _parse_json_response, run_ocr_agent, run_supplemental_rules_agent
from prompts import MAPPING_EXTRACTION_PROMPT, FINAL_REPORT_PROMPT

MODEL = "claude-sonnet-4-6"


def _llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=MODEL,
        max_tokens=4096,
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )


# ── Comparison helpers ────────────────────────────────────────────────────────

def _normalize_value(val):
    """Strip currency/commas, parse as float or date for comparison. Returns None for missing."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "none", "", "blank", "n/a", "not_found", "column_not_found", "illegible"):
        return None
    # Strip currency symbols and commas
    cleaned = re.sub(r'[$€£¥,]', '', s).strip()
    # Try numeric
    try:
        return float(cleaned)
    except ValueError:
        pass
    # Try common date formats
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d-%b-%Y', '%d/%m/%Y', '%Y/%m/%d', '%B %d, %Y']:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return cleaned.lower()


def _compare_values(reported, source):
    """
    Compare two raw values after normalization.
    Returns (result, variance, comment, variance_analysis).
    result is 'Pass', 'Fail', or 'N/A'.
    """
    n_rep = _normalize_value(reported)
    n_src = _normalize_value(source)

    if n_rep is None and n_src is None:
        return 'Pass', 'None', 'Both values absent', 'No variance detected'
    if n_rep is None:
        return 'Fail', 'N/A', f'Reported value is missing; source={source}', \
               f'Variance detected. Reported=None, Source={source}'
    if n_src is None:
        return 'Fail', 'N/A', f'Source value is missing; reported={reported}', \
               f'Variance detected. Reported={reported}, Source=None'

    if n_rep == n_src:
        return 'Pass', '0', 'Values match', 'No variance detected'

    # Both numeric
    if isinstance(n_rep, float) and isinstance(n_src, float):
        variance = n_rep - n_src
        return (
            'Fail', f'{variance:g}',
            f'Variance of {variance:,.2f}',
            f'Variance of {variance:,.2f} detected. Reported={reported}, Source={source}',
        )

    # Both dates
    if hasattr(n_rep, 'toordinal') and hasattr(n_src, 'toordinal'):
        delta = (n_rep - n_src).days
        return (
            'Fail', str(delta),
            f'Date difference of {delta} day(s)',
            f'Variance of {delta} day(s) detected. Reported={reported}, Source={source}',
        )

    # String mismatch
    return (
        'Fail', 'N/A',
        f'Mismatch: reported="{reported}", source="{source}"',
        f'Variance detected. Reported="{reported}", Source="{source}"',
    )


def _apply_calculation(source_val, transformation_detail: str):
    """
    Attempt to apply a simple scalar calculation from transformation_detail text.
    Returns (computed_value, success). Falls back to (None, False) for complex formulas.
    """
    if not transformation_detail or not isinstance(source_val, (int, float)):
        return None, False
    detail = transformation_detail.lower().strip()
    divide_match = re.search(r'divide\s+by\s+([\d.]+)', detail)
    multiply_match = re.search(r'(?:multiply|times)\s+by\s+([\d.]+)', detail)
    if divide_match:
        factor = float(divide_match.group(1))
        return (source_val / factor, True) if factor != 0 else (None, False)
    if multiply_match:
        factor = float(multiply_match.group(1))
        return source_val * factor, True
    if re.search(r'negate|multiply by -1|\* ?-1', detail):
        return -source_val, True
    return None, False


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


# ── Step 4a: Compute Data Statistics ──────────────────────────────────────────
def step4a_compute_stats(state: dict) -> dict:
    """
    Python only — computes per-column statistics (dtype, nulls, uniques, quartiles)
    for both sample and source DataFrames. Used by Step 4b for rule generation.
    """
    stats = {}
    errors = list(state.get("errors", []))

    for label, csv_text in [("sample", state.get("sample_df_csv", "")),
                             ("source", state.get("source_df_csv", ""))]:
        if not csv_text:
            continue
        try:
            df = pd.read_csv(io.StringIO(csv_text))
            col_stats = {}
            for col in df.columns:
                s = df[col]
                entry = {
                    "dtype": str(s.dtype),
                    "null_count": int(s.isna().sum()),
                    "unique_count": int(s.nunique()),
                    "row_count": len(s),
                }
                if pd.api.types.is_numeric_dtype(s):
                    non_null = s.dropna()
                    if len(non_null) > 0:
                        entry.update({
                            "min": float(non_null.min()),
                            "max": float(non_null.max()),
                            "mean": round(float(non_null.mean()), 4),
                            "std": round(float(non_null.std()), 4) if len(non_null) > 1 else 0.0,
                            "q25": float(non_null.quantile(0.25)),
                            "q75": float(non_null.quantile(0.75)),
                        })
                col_stats[col] = entry
            stats[label] = {"row_count": len(df), "column_count": len(df.columns), "columns": col_stats}
        except Exception as e:
            errors.append(f"Step 4a — stats error for {label}: {str(e)}")

    return {
        "data_statistics": stats,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step4a_compute_stats"],
    }


# ── Step 4b: Generate Supplemental Rules ──────────────────────────────────────
def step4b_supplemental_rules(state: dict) -> dict:
    """
    LLM — reviews the data statistics and column mappings to identify additional
    rules worth checking (null checks, range checks, statistical outliers).
    """
    data_statistics = state.get("data_statistics", {})
    column_mappings = state.get("column_mappings", {})
    product = state.get("product", "General")
    errors = list(state.get("errors", []))

    supplemental_rules = []
    if data_statistics and column_mappings:
        try:
            supplemental_rules = run_supplemental_rules_agent(
                data_statistics=data_statistics,
                column_mappings=column_mappings,
                product=product,
            )
        except Exception as e:
            errors.append(f"Step 4b — supplemental rules error: {str(e)}")

    return {
        "supplemental_rules": supplemental_rules,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step4b_supplemental_rules"],
    }


# ── Step 5: Translate Rules to Executable Specification ───────────────────────
def step5_translate_rules(state: dict) -> dict:
    """
    Python only — validates each column mapping against the actual DataFrame columns
    and produces a clean, execution-ready list of comparison tasks (executable_specs).
    """
    column_mappings = state.get("column_mappings", {})
    sample_csv = state.get("sample_df_csv", "")
    source_csv = state.get("source_df_csv", "")
    source_type = state.get("source_type", "excel")
    errors = list(state.get("errors", []))

    if not column_mappings or not isinstance(column_mappings, dict):
        errors.append("Step 5 — no column mappings available from Step 3.")
        return {
            "executable_specs": [],
            "errors": errors,
            "completed_steps": state.get("completed_steps", []) + ["step5_translate_rules"],
        }

    try:
        sample_df = pd.read_csv(io.StringIO(sample_csv)) if sample_csv else pd.DataFrame()
        source_df = pd.read_csv(io.StringIO(source_csv)) if source_csv and source_type == "excel" else pd.DataFrame()

        executable_specs = []
        for mapping in column_mappings.get("mappings", []):
            sample_col = mapping.get("sample_column")
            source_col = mapping.get("source_column")
            transformation = mapping.get("transformation", "direct")

            sample_col_found = bool(sample_col and sample_col in sample_df.columns)
            source_col_found = bool(
                source_col and (
                    (not source_df.empty and source_col in source_df.columns)
                    or source_type == "ocr"
                )
            )

            executable_specs.append({
                "mapping_id": mapping.get("mapping_id", ""),
                "sample_column": sample_col,
                "source_column": source_col,
                "transformation": transformation,
                "transformation_detail": mapping.get("transformation_detail", ""),
                "currency": mapping.get("currency"),
                "sample_col_found": sample_col_found,
                "source_col_found": source_col_found,
            })
    except Exception as e:
        errors.append(f"Step 5 — translation error: {str(e)}")
        executable_specs = []

    return {
        "executable_specs": executable_specs,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step5_translate_rules"],
    }


# ── Step 6: Apply Rules on Full Dataset ───────────────────────────────────────
def step6_apply_rules(state: dict) -> dict:
    """
    Python only — joins sample and source on the join key, then compares each
    mapped column row-by-row using normalized value comparison. Handles direct,
    static, calculation, and not_available transformation types. Supports both
    Excel and OCR source paths.
    """
    executable_specs = state.get("executable_specs", [])
    column_mappings = state.get("column_mappings", {})
    sample_csv = state.get("sample_df_csv", "")
    source_csv = state.get("source_df_csv", "")
    source_type = state.get("source_type", "excel")
    ocr_results = state.get("ocr_results", [])
    errors = list(state.get("errors", []))

    _empty = {"records": [], "summary": {"total": 0, "pass": 0, "fail": 0, "na": 0, "pending": 0}}

    # Filter out any leftover stub entries
    valid_specs = [s for s in executable_specs if isinstance(s, dict) and "sample_column" in s]
    if not valid_specs or not sample_csv:
        errors.append("Step 6 — missing executable specs or sample data; skipping comparison.")
        return {
            "rule_results": _empty,
            "errors": errors,
            "completed_steps": state.get("completed_steps", []) + ["step6_apply_rules"],
        }

    join_key = column_mappings.get("join_key", {}) if isinstance(column_mappings, dict) else {}
    join_key_sample = join_key.get("sample_column", "")
    join_key_source = join_key.get("source_column", "")

    try:
        sample_df = pd.read_csv(io.StringIO(sample_csv))
    except Exception as e:
        errors.append(f"Step 6 — failed to parse sample CSV: {str(e)}")
        return {
            "rule_results": _empty,
            "errors": errors,
            "completed_steps": state.get("completed_steps", []) + ["step6_apply_rules"],
        }

    # Fall back to first column if join key not found
    if not join_key_sample or join_key_sample not in sample_df.columns:
        join_key_sample = sample_df.columns[0]

    all_records: list[dict] = []

    def _build_comp(record_id, i, spec, reported_val, source_val, result, variance, comment, va, src_col_display):
        return {
            "record_id": record_id,
            "s_no": i,
            "attribute": spec.get("sample_column") or "",
            "reported_value": "" if (reported_val is None or (isinstance(reported_val, float) and math.isnan(reported_val))) else str(reported_val),
            "source_value": str(source_val) if source_val is not None else "",
            "variance": variance,
            "result": result,
            "comment": comment,
            "source_column": src_col_display,
            "variance_analysis": va,
        }

    if source_type == "excel" and source_csv:
        try:
            source_df = pd.read_csv(io.StringIO(source_csv))
        except Exception as e:
            errors.append(f"Step 6 — failed to parse source CSV: {str(e)}")
            source_df = pd.DataFrame()

        if not join_key_source or (not source_df.empty and join_key_source not in source_df.columns):
            join_key_source = source_df.columns[0] if not source_df.empty else ""

        for _, sample_row in sample_df.iterrows():
            record_id = str(sample_row.get(join_key_sample, "")).strip()
            if not record_id or record_id.lower() == "nan":
                continue

            # Find matching source row — try exact match, then strip trailing ".0"
            source_row = None
            if not source_df.empty and join_key_source:
                src_ids = source_df[join_key_source].astype(str).str.strip()
                mask = src_ids == record_id
                if not mask.any() and "." in record_id:
                    clean_id = record_id.rstrip("0").rstrip(".")
                    mask = src_ids.str.rstrip("0").str.rstrip(".") == clean_id
                matched = source_df[mask]
                source_row = matched.iloc[0] if len(matched) > 0 else None

            for i, spec in enumerate(valid_specs, 1):
                sample_col = spec.get("sample_column")
                source_col = spec.get("source_column")
                transformation = spec.get("transformation", "direct")
                detail = spec.get("transformation_detail", "")
                reported_val = sample_row.get(sample_col) if sample_col else None

                if transformation == "not_available":
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A — not in source file", "N/A", "N/A",
                        "Attribute not available in source",
                        "Not applicable — no source column", "N/A",
                    ))
                elif transformation == "static":
                    m = re.search(r'(?:static value[:\s]+)(.+)', detail, re.IGNORECASE)
                    static_val = m.group(1).strip() if m else detail.strip()
                    result, variance, comment, va = _compare_values(reported_val, static_val)
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        static_val, result, variance, comment, va,
                        f"Static: {detail}",
                    ))
                elif source_row is not None and source_col and not source_df.empty and source_col in source_df.columns:
                    raw_source = source_row.get(source_col)
                    if transformation == "calculation":
                        computed, success = _apply_calculation(_normalize_value(raw_source), detail)
                        if success:
                            result, variance, comment, va = _compare_values(reported_val, computed)
                            all_records.append(_build_comp(
                                record_id, i, spec, reported_val,
                                computed, result, variance, comment, va, source_col,
                            ))
                        else:
                            all_records.append(_build_comp(
                                record_id, i, spec, reported_val,
                                raw_source, "Pending", "N/A",
                                "Calculation requires manual review",
                                "Calculation — manual review needed", source_col,
                            ))
                    else:  # direct
                        result, variance, comment, va = _compare_values(reported_val, raw_source)
                        all_records.append(_build_comp(
                            record_id, i, spec, reported_val,
                            raw_source, result, variance, comment, va, source_col,
                        ))
                else:
                    if source_row is None:
                        msg = f"No matching record in source for '{record_id}'"
                    else:
                        msg = f"Source column '{source_col}' not found"
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Fail", "N/A", msg, msg, source_col or "N/A",
                    ))

    elif source_type == "ocr" and ocr_results:
        # Build a lookup: record_id → ocr_record
        ocr_lookup = {}
        for ocr in ocr_results:
            rid = str(ocr.get("record_identifier", {}).get("value", "")).strip()
            if rid:
                ocr_lookup[rid] = ocr

        for _, sample_row in sample_df.iterrows():
            record_id = str(sample_row.get(join_key_sample, "")).strip()
            if not record_id or record_id.lower() == "nan":
                continue

            ocr_record = ocr_lookup.get(record_id)

            for i, spec in enumerate(valid_specs, 1):
                sample_col = spec.get("sample_column")
                source_col = spec.get("source_column")
                transformation = spec.get("transformation", "direct")
                reported_val = sample_row.get(sample_col) if sample_col else None

                if transformation == "not_available":
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A — not in source file", "N/A", "N/A",
                        "Attribute not available in source",
                        "Not applicable — no source column", "N/A",
                    ))
                    continue

                if ocr_record is None:
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Fail", "N/A",
                        f"No OCR record found for '{record_id}'",
                        "No OCR record found", source_col or "N/A",
                    ))
                    continue

                # Search extracted_attributes by attribute_name (case-insensitive)
                attr_match = None
                for attr in ocr_record.get("extracted_attributes", []):
                    if attr.get("attribute_name", "").lower() == (sample_col or "").lower():
                        attr_match = attr
                        break

                if attr_match is None:
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Fail", "N/A",
                        f"Attribute '{sample_col}' not found in OCR results",
                        "Attribute not found in OCR extraction", source_col or "N/A",
                    ))
                    continue

                extracted_val = attr_match.get("extracted_value")
                if extracted_val in ("NOT_FOUND", "BLANK", "ILLEGIBLE", "COLUMN_NOT_FOUND"):
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        f"N/A ({extracted_val})", "Fail", "N/A",
                        f"OCR extraction issue: {extracted_val}",
                        f"OCR issue: {extracted_val}",
                        source_col or attr_match.get("location", "N/A"),
                    ))
                else:
                    result, variance, comment, va = _compare_values(reported_val, extracted_val)
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        extracted_val, result, variance, comment, va,
                        source_col or attr_match.get("location", "N/A"),
                    ))

    # Compute summary counts
    total = len(all_records)
    pass_count = sum(1 for r in all_records if r["result"] == "Pass")
    fail_count = sum(1 for r in all_records if r["result"] == "Fail")
    na_count = sum(1 for r in all_records if r["result"] == "N/A")
    pending_count = sum(1 for r in all_records if r["result"] == "Pending")

    return {
        "rule_results": {
            "records": all_records,
            "summary": {"total": total, "pass": pass_count, "fail": fail_count, "na": na_count, "pending": pending_count},
        },
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step6_apply_rules"],
    }


# ── Step 7: Execute Sampling Algorithm ────────────────────────────────────────
def step7_sampling(state: dict) -> dict:
    """
    Python only — selects which records to include in the final report.
    Strategy: all records with any Fail/Pending result are mandatory; a
    proportional sample of passing records is added up to a cap of 200 total.
    """
    rule_results = state.get("rule_results", {})
    errors = list(state.get("errors", []))

    records_flat = rule_results.get("records", []) if isinstance(rule_results, dict) else []
    if not records_flat:
        return {
            "sample_records": [],
            "errors": errors,
            "completed_steps": state.get("completed_steps", []) + ["step7_sampling"],
        }

    # Group by record_id
    record_groups: dict[str, list] = defaultdict(list)
    for comp in records_flat:
        record_groups[comp["record_id"]].append(comp)

    fail_ids = []
    pass_ids = []
    for record_id, comps in record_groups.items():
        results = {c["result"] for c in comps}
        if "Fail" in results or "Pending" in results:
            fail_ids.append(record_id)
        else:
            pass_ids.append(record_id)

    # Always include all failures; sample passes proportionally
    max_pass = max(10, len(fail_ids))
    sampled_passes = random.sample(pass_ids, min(max_pass, len(pass_ids)))
    sampled_ids = fail_ids + sampled_passes

    # Cap total at 200
    if len(sampled_ids) > 200:
        sampled_ids = fail_ids[:200] + sampled_passes[:max(0, 200 - len(fail_ids))]

    return {
        "sample_records": sampled_ids,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step7_sampling"],
    }


# ── Step 8: Generate Final Report ────────────────────────────────────────────
def step8_final_report(state: dict) -> dict:
    """
    Generates the final audit report.
    Primary path: if Step 6 produced real rule_results, formats them directly
    into a markdown table (deterministic, full-dataset, no hallucination risk).
    Fallback path: LLM comparison for cases where Steps 5-6 did not run or failed.
    """
    rule_results = state.get("rule_results", {})
    has_real_results = (
        isinstance(rule_results, dict)
        and "records" in rule_results
        and len(rule_results.get("records", [])) > 0
    )

    if has_real_results:
        all_rows = rule_results["records"]
        sample_ids = set(state.get("sample_records") or [])

        # Filter to sampled records if Step 7 produced a selection
        rows = [r for r in all_rows if r["record_id"] in sample_ids] if sample_ids else all_rows

        try:
            df = pd.DataFrame(rows)
            df = df.rename(columns={
                "record_id": "Record ID",
                "s_no": "S.No",
                "attribute": "Attribute",
                "reported_value": "Reported Value",
                "source_value": "Source Value",
                "variance": "Variance",
                "result": "Testing Result",
                "comment": "Results Comment",
                "source_column": "Source Column",
                "variance_analysis": "Variance Analysis",
            })
            ordered_cols = [
                "Record ID", "S.No", "Attribute", "Reported Value", "Source Value",
                "Variance", "Testing Result", "Results Comment", "Source Column", "Variance Analysis",
            ]
            df = df[[c for c in ordered_cols if c in df.columns]]
            report_md = "## Data Quality Report\n\n" + df.to_markdown(index=False)
        except Exception as e:
            report_md = f"## Data Quality Report\n\n**Error formatting report:** {str(e)}"

        return {
            "final_report": report_md,
            "completed_steps": state.get("completed_steps", []) + ["step8_final_report"],
        }

    # ── Fallback: LLM comparison (used when Steps 5-6 were skipped or failed) ──
    sample_csv = state.get("sample_df_csv", "")
    source_csv = state.get("source_df_csv", "")
    mappings = state.get("column_mappings", {})
    source_filename = state.get("source_filename", "source file")
    attributes_to_test = state.get("attributes_to_test", [])
    ocr_results = state.get("ocr_results", [])
    source_type = state.get("source_type", "excel")

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
