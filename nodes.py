"""
LangGraph node implementations for each of the 8 pipeline steps.
Each node receives the full GraphState and returns a partial state dict.

Design: multi-source comparison
  - sample_bytes  = Sample Summary (reported values)
  - source_files  = List of Source Evidence files (actual values — Excel or image, one or more)
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

    # Load ALL source evidence files into source_data
    source_data = {}
    source_files = state.get("source_files", [])
    supporting_doc = "\n".join(state.get("pdf_texts", []))

    for src in source_files:
        label = src["label"]
        src_type = src["type"]
        src_bytes = src["bytes"]
        src_filename = src["filename"]

        if src_type == "excel":
            try:
                if src_filename.lower().endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(src_bytes))
                    csv_text = df.to_csv(index=False)
                else:
                    sheets = excel_to_csv_text(src_bytes, src_filename)
                    csv_text = next(iter(sheets.values()))
                source_data[label] = {
                    "type": "excel",
                    "csv": csv_text,
                    "filename": src_filename,
                }
            except Exception as e:
                errors.append(f"Step 1 — source load error for '{label}': {str(e)}")

        elif src_type == "ocr":
            # Run OCR for each sample record on this image source
            ocr_results_for_source = []
            if sample_csv:
                try:
                    sample_df = pd.read_csv(io.StringIO(sample_csv))
                    id_col = sample_df.columns[0]
                    ocr_attributes = attributes_to_test if attributes_to_test else [
                        c for c in sample_df.columns if c != id_col
                    ]
                    for _, row in sample_df.iterrows():
                        record_id = str(row[id_col]).strip()
                        if not record_id or record_id.lower() == "nan":
                            continue
                        try:
                            result = run_ocr_agent(
                                image_bytes=src_bytes,
                                filename=src_filename,
                                attributes=ocr_attributes,
                                record_identifier={"key": id_col, "value": record_id},
                                supporting_doc_text=supporting_doc or "Extract the listed attributes from the image.",
                            )
                            result["source_label"] = label
                            ocr_results_for_source.append(result)
                        except Exception as e:
                            ocr_results_for_source.append({
                                "agent": "ocr_extraction_agent",
                                "status": "ERROR",
                                "source_label": label,
                                "record_identifier": {"key": id_col, "value": record_id},
                                "extracted_attributes": [],
                                "errors": [str(e)],
                            })
                except Exception as e:
                    errors.append(f"Step 1 — OCR loop error for '{label}': {str(e)}")

            source_data[label] = {
                "type": "ocr",
                "filename": src_filename,
                "ocr_results": ocr_results_for_source,
            }

    return {
        "sample_df_csv": sample_csv,
        "source_data": source_data,
        "attributes_to_test": attributes_to_test,
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
    LLM — reads the regulatory PDFs plus all source file schemas and extracts:
    - The join key per source (how to match records between sample and each source)
    - Column mappings (sample column → source label + source column + transformation rule)
    - Cross-source calculation formulas when values span multiple sources
    Output stored as column_mappings (a dict with join_key + mappings list).
    """
    pdf_texts = state.get("pdf_texts", [])
    sample_csv = state.get("sample_df_csv", "")
    source_data = state.get("source_data", {})

    # First 6 rows of each file (header + 5 data rows)
    def preview(csv_text, n=6):
        lines = csv_text.strip().split("\n")
        return "\n".join(lines[:n])

    combined_pdf = "\n\n".join(pdf_texts)
    if len(combined_pdf) > 50000:
        combined_pdf = combined_pdf[:50000] + "\n\n[... truncated ...]"

    # Build source previews for ALL sources
    source_previews = ""
    for label, src_entry in source_data.items():
        if src_entry.get("type") == "excel":
            source_previews += f"\n\n### Source: '{label}' (Excel: {src_entry.get('filename', '')})\n"
            source_previews += f"```\n{preview(src_entry.get('csv', ''))}\n```\n"
        elif src_entry.get("type") == "ocr":
            ocr_results = src_entry.get("ocr_results", [])
            if ocr_results:
                sample_attrs = ocr_results[0].get("extracted_attributes", [])
                attr_summary = [f"  - {a.get('attribute_name', '?')}: {a.get('extracted_value', '?')}" for a in sample_attrs[:20]]
                source_previews += f"\n\n### Source: '{label}' (Image/OCR: {src_entry.get('filename', '')})\n"
                source_previews += "Extracted attributes (first record):\n" + "\n".join(attr_summary) + "\n"
            else:
                source_previews += f"\n\n### Source: '{label}' (Image/OCR: {src_entry.get('filename', '')})\n"
                source_previews += "[OCR extraction returned no results]\n"

    user_msg = f"""Extract the join key and column mappings between the Sample Summary and the Source Evidence files.
Each source is identified by a **source label** — use these labels in your mappings.
Use the regulatory PDF text as context to understand what each field means and how they relate.
If a reported value requires data from MULTIPLE sources (e.g., amount * forex rate), use "cross_source_calculation".

**Sample Summary (reported values) — first 5 rows:**
```
{preview(sample_csv)}
```

**Source Evidence Files:**
{source_previews if source_previews else "[No source data available]"}

**Regulatory PDF Context:**
{combined_pdf if combined_pdf else "[No regulatory PDFs provided]"}

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

    def _compute_df_stats(df, label):
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
        return {"row_count": len(df), "column_count": len(df.columns), "columns": col_stats}

    # Sample stats
    sample_csv = state.get("sample_df_csv", "")
    if sample_csv:
        try:
            stats["sample"] = _compute_df_stats(pd.read_csv(io.StringIO(sample_csv)), "sample")
        except Exception as e:
            errors.append(f"Step 4a — stats error for sample: {str(e)}")

    # Per-source stats (Excel sources only — OCR sources don't have tabular data)
    source_data = state.get("source_data", {})
    for label, src_entry in source_data.items():
        if src_entry.get("type") == "excel" and src_entry.get("csv"):
            try:
                stats[f"source:{label}"] = _compute_df_stats(
                    pd.read_csv(io.StringIO(src_entry["csv"])), label
                )
            except Exception as e:
                errors.append(f"Step 4a — stats error for source '{label}': {str(e)}")

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
    source_data = state.get("source_data", {})
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

        # Cache parsed source DataFrames by label
        source_dfs = {}
        for label, src_entry in source_data.items():
            if src_entry.get("type") == "excel" and src_entry.get("csv"):
                try:
                    source_dfs[label] = pd.read_csv(io.StringIO(src_entry["csv"]))
                except Exception:
                    pass

        executable_specs = []
        for mapping in column_mappings.get("mappings", []):
            sample_col = mapping.get("sample_column")
            source_col = mapping.get("source_column")
            source_label = mapping.get("source_label")
            transformation = mapping.get("transformation", "direct")
            cross_source_refs = mapping.get("cross_source_refs", [])

            sample_col_found = bool(sample_col and sample_col in sample_df.columns)

            # Validate source column exists in the named source
            src_entry = source_data.get(source_label, {})
            if src_entry.get("type") == "excel":
                src_df = source_dfs.get(source_label, pd.DataFrame())
                source_col_found = bool(source_col and source_col in src_df.columns)
            elif src_entry.get("type") == "ocr":
                source_col_found = True  # OCR attributes matched by name at runtime
            else:
                source_col_found = False

            # Validate cross-source refs
            refs_valid = all(
                ref.get("source_label") in source_data for ref in cross_source_refs
            )

            executable_specs.append({
                "mapping_id": mapping.get("mapping_id", ""),
                "sample_column": sample_col,
                "source_column": source_col,
                "source_label": source_label,
                "transformation": transformation,
                "transformation_detail": mapping.get("transformation_detail", ""),
                "cross_source_refs": cross_source_refs,
                "currency": mapping.get("currency"),
                "sample_col_found": sample_col_found,
                "source_col_found": source_col_found,
                "refs_valid": refs_valid,
            })
    except Exception as e:
        errors.append(f"Step 5 — translation error: {str(e)}")
        executable_specs = []

    return {
        "executable_specs": executable_specs,
        "errors": errors,
        "completed_steps": state.get("completed_steps", []) + ["step5_translate_rules"],
    }


# ── Multi-source resolution helpers ──────────────────────────────────────────

def _resolve_source_value(source_data, source_label, source_col, record_id, join_key_info):
    """
    Resolve a value from any source (Excel or OCR) by label, column, and record ID.
    join_key_info is the join_key dict from column_mappings (has source_keys list).
    Returns (value, found: bool).
    """
    src_entry = source_data.get(source_label)
    if not src_entry:
        return None, False

    if src_entry["type"] == "excel":
        csv_text = src_entry.get("csv", "")
        if not csv_text:
            return None, False
        df = pd.read_csv(io.StringIO(csv_text))

        # Find the join key column for this source
        jk_col = None
        source_keys = join_key_info.get("source_keys", []) if join_key_info else []
        for sk in source_keys:
            if sk.get("source_label") == source_label:
                jk_col = sk.get("source_column")
                break
        # Fallback: legacy single source_column format
        if not jk_col:
            jk_col = join_key_info.get("source_column") if join_key_info else None

        if jk_col and jk_col in df.columns:
            # Match by join key
            src_ids = df[jk_col].astype(str).str.strip()
            mask = src_ids == str(record_id).strip()
            if not mask.any() and "." in str(record_id):
                clean_id = str(record_id).rstrip("0").rstrip(".")
                mask = src_ids.str.rstrip("0").str.rstrip(".") == clean_id
            matched = df[mask]
            if matched.empty:
                return None, False
            if source_col and source_col in df.columns:
                return matched.iloc[0][source_col], True
            return None, False
        elif jk_col is None:
            # Broadcast source (no join key, e.g., forex table) — use first row
            if source_col and source_col in df.columns:
                return df.iloc[0][source_col], True
            return None, False
        else:
            # Join key column not found in this source
            if source_col and source_col in df.columns:
                return df.iloc[0][source_col], True
            return None, False

    elif src_entry["type"] == "ocr":
        for ocr_record in src_entry.get("ocr_results", []):
            rid = str(ocr_record.get("record_identifier", {}).get("value", "")).strip()
            if rid == str(record_id).strip():
                # Search by source_column name (attribute_name in OCR)
                search_name = source_col or ""
                for attr in ocr_record.get("extracted_attributes", []):
                    attr_name = attr.get("attribute_name", "")
                    if attr_name.lower() == search_name.lower():
                        val = attr.get("extracted_value")
                        if val in ("NOT_FOUND", "BLANK", "ILLEGIBLE", "COLUMN_NOT_FOUND"):
                            return None, False
                        return val, True
                return None, False
        return None, False

    return None, False


def _safe_eval_formula(formula: str, variables: dict):
    """
    Safely evaluate a simple arithmetic formula with named variables.
    Supports: +, -, *, /, parentheses, and numeric literals.
    """
    import ast
    import operator as op

    # Replace variable names with their values (sort by length desc to avoid partial replacement)
    expr = formula
    for name in sorted(variables.keys(), key=len, reverse=True):
        expr = expr.replace(name, str(variables[name]))

    allowed_ops = {
        ast.Add: op.add, ast.Sub: op.sub,
        ast.Mult: op.mul, ast.Div: op.truediv,
        ast.USub: op.neg,
    }

    tree = ast.parse(expr, mode='eval')

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.operand))
        else:
            raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    return _eval(tree)


def _apply_cross_source_calculation(spec, source_data, record_id, join_key_info):
    """
    Resolve a cross-source calculation. The spec contains:
    - cross_source_refs: [{"source_label": "X", "source_column": "Y", "alias": "A"}, ...]
    - transformation_detail: formula like "start_amount * forex_rate"
    Returns (computed_value, success, detail_msg).
    """
    refs = spec.get("cross_source_refs", [])
    detail = spec.get("transformation_detail", "")

    resolved = {}
    for ref in refs:
        val, found = _resolve_source_value(
            source_data, ref["source_label"], ref["source_column"],
            record_id, join_key_info
        )
        if not found:
            return None, False, f"Could not resolve {ref['alias']} from {ref['source_label']}.{ref['source_column']}"
        norm = _normalize_value(val)
        if not isinstance(norm, (int, float)):
            return None, False, f"Non-numeric value for {ref['alias']}: {val}"
        resolved[ref["alias"]] = norm

    try:
        result = _safe_eval_formula(detail, resolved)
        return result, True, f"Computed: {detail} = {result}"
    except Exception as e:
        return None, False, f"Formula evaluation error: {e}"


# ── Step 6: Apply Rules on Full Dataset ───────────────────────────────────────
def step6_apply_rules(state: dict) -> dict:
    """
    Python only — for each sample record and each mapping spec, resolves the
    source value from the correct named source (Excel or OCR), applies
    transformations (direct, calculation, cross_source_calculation, static),
    and compares against the reported value. Unified loop handles all source types.
    """
    executable_specs = state.get("executable_specs", [])
    column_mappings = state.get("column_mappings", {})
    sample_csv = state.get("sample_df_csv", "")
    source_data = state.get("source_data", {})
    errors = list(state.get("errors", []))

    _empty = {"records": [], "summary": {"total": 0, "pass": 0, "fail": 0, "na": 0, "pending": 0}}

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

    try:
        sample_df = pd.read_csv(io.StringIO(sample_csv))
    except Exception as e:
        errors.append(f"Step 6 — failed to parse sample CSV: {str(e)}")
        return {
            "rule_results": _empty,
            "errors": errors,
            "completed_steps": state.get("completed_steps", []) + ["step6_apply_rules"],
        }

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
            "source_document": spec.get("source_label", ""),
            "variance_analysis": va,
        }

    for _, sample_row in sample_df.iterrows():
        record_id = str(sample_row.get(join_key_sample, "")).strip()
        if not record_id or record_id.lower() == "nan":
            continue

        for i, spec in enumerate(valid_specs, 1):
            sample_col = spec.get("sample_column")
            source_col = spec.get("source_column")
            source_label = spec.get("source_label", "")
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

            elif transformation == "cross_source_calculation":
                computed, success, msg = _apply_cross_source_calculation(
                    spec, source_data, record_id, join_key
                )
                if success:
                    result, variance, comment, va = _compare_values(reported_val, computed)
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        computed, result, variance, comment, va,
                        f"Calc: {detail}",
                    ))
                else:
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Pending", "N/A", msg, msg, source_col or "N/A",
                    ))

            elif transformation == "calculation":
                # Single-source calculation
                raw_source, found = _resolve_source_value(
                    source_data, source_label, source_col, record_id, join_key
                )
                if found:
                    computed, success = _apply_calculation(_normalize_value(raw_source), detail)
                    if success:
                        result, variance, comment, va = _compare_values(reported_val, computed)
                        all_records.append(_build_comp(
                            record_id, i, spec, reported_val,
                            computed, result, variance, comment, va, source_col or "N/A",
                        ))
                    else:
                        all_records.append(_build_comp(
                            record_id, i, spec, reported_val,
                            raw_source, "Pending", "N/A",
                            "Calculation requires manual review",
                            "Calculation — manual review needed", source_col or "N/A",
                        ))
                else:
                    msg = f"Source value not found in '{source_label}'.'{source_col}'"
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Fail", "N/A", msg, msg, source_col or "N/A",
                    ))

            else:  # "direct"
                raw_source, found = _resolve_source_value(
                    source_data, source_label, source_col, record_id, join_key
                )
                if found:
                    result, variance, comment, va = _compare_values(reported_val, raw_source)
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        raw_source, result, variance, comment, va, source_col or "N/A",
                    ))
                else:
                    msg = f"Source value not found in '{source_label}'.'{source_col}'"
                    all_records.append(_build_comp(
                        record_id, i, spec, reported_val,
                        "N/A", "Fail", "N/A", msg, msg, source_col or "N/A",
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
    source_data = state.get("source_data", {})

    # Determine if any source is OCR-only (affects whether we use programmatic or LLM path)
    has_any_ocr = any(s.get("type") == "ocr" for s in source_data.values())
    has_real_results = (
        isinstance(rule_results, dict)
        and "records" in rule_results
        and len(rule_results.get("records", [])) > 0
    )

    # Use programmatic report when we have real results (works for all source types now)
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
                "source_document": "Source Document",
                "variance_analysis": "Variance Analysis",
            })
            ordered_cols = [
                "Record ID", "S.No", "Attribute", "Reported Value", "Source Value",
                "Variance", "Testing Result", "Results Comment", "Source Document",
                "Source Column", "Variance Analysis",
            ]
            df = df[[c for c in ordered_cols if c in df.columns]]
            report_md = "## Data Quality Report\n\n" + df.to_markdown(index=False)
        except Exception as e:
            report_md = f"## Data Quality Report\n\n**Error formatting report:** {str(e)}"

        return {
            "final_report": report_md,
            "completed_steps": state.get("completed_steps", []) + ["step8_final_report"],
        }

    # ── Fallback: LLM comparison (used when Steps 5-6 did not produce results) ──
    sample_csv = state.get("sample_df_csv", "")
    mappings = state.get("column_mappings", {})
    attributes_to_test = state.get("attributes_to_test", [])

    def preview(csv_text, n=20):
        lines = csv_text.strip().split("\n")
        return "\n".join(lines[:n])

    attr_instruction = (
        f"**IMPORTANT — Only test these specific attributes: {attributes_to_test}. "
        f"Ignore all other columns in the sample. Only these attributes should appear in the report.**"
        if attributes_to_test else
        "Test all mapped attributes."
    )

    # Build source evidence section for all sources
    source_evidence_text = ""
    for label, src_entry in source_data.items():
        if src_entry.get("type") == "excel" and src_entry.get("csv"):
            source_evidence_text += f"\n\n### Source: '{label}' (Excel: {src_entry.get('filename', '')})\n"
            source_evidence_text += f"```\n{preview(src_entry['csv'])}\n```\n"
        elif src_entry.get("type") == "ocr":
            ocr_results = src_entry.get("ocr_results", [])
            if ocr_results:
                source_evidence_text += f"\n\n### Source: '{label}' (OCR: {src_entry.get('filename', '')})\n"
                source_evidence_text += f"```json\n{json.dumps(ocr_results, indent=2)}\n```\n"

    user_msg = f"""Compare the Sample Summary (reported values) against the Source Evidence files (actual values) using the column mappings below. Generate the Data Quality Report.

{attr_instruction}

**Column Mappings (from Step 3):**
```json
{json.dumps(mappings, indent=2)}
```

**Sample Summary — reported values (first 20 rows):**
```
{preview(sample_csv)}
```

**Source Evidence Files:**
{source_evidence_text if source_evidence_text else "[No source data available]"}

Each mapping specifies a source_label indicating which source file to use.
For cross_source_calculation mappings, apply the formula using values from multiple sources.
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
