# Prompt Reference Report
## GS Data Quality Validation Application
**Date:** March 31, 2026

---

## Overview

This application uses **6 AI prompts** across a multi-stage pipeline to extract, map, validate, and report on financial data quality. All agents use **Claude claude-sonnet-4-6** (`claude-sonnet-4-6`) with a `max_tokens` of **4096** (2048 for Supplemental Rules).

---

## Pipeline Flow

```
Stage 1a: OCR Agent          ─┐
                               ├─► Stage 2: Aggregation ─► Stage 3: Validation Agent ─► Final Report
Stage 1b: Excel Agent        ─┘

Supporting:  Mapping Extraction Agent  (runs before Stage 1)
             Supplemental Rules Agent  (runs alongside Stage 3)
```

---

## Prompt 1 — OCR Extraction Agent

**Variable:** `OCR_AGENT_PROMPT`
**Function:** `run_ocr_agent()` in `agents.py`
**Purpose:** Extracts attribute values from images, screenshots, scanned PDFs, and form-based UI files.

### Parameters Passed at Runtime

| Parameter | Type | Description |
|-----------|------|-------------|
| `record_identifier` | dict | The join key used to locate the correct record (e.g., `{"key": "rpID", "value": "12345"}`) |
| `attributes` | list[str] | List of attribute names to extract |
| `supporting_doc_text` | str | Mapping rules / regulatory context text |
| `filename` | str | Name of the source evidence file |
| `image_bytes` | bytes | Raw image/PDF bytes (sent as base64 to the model) |

### Model Settings

| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-6` |
| Max Tokens | `4096` |
| Input Type | Image (base64) + Text |

### Output Format (JSON)

```json
{
  "agent": "ocr_extraction_agent",
  "status": "SUCCESS",
  "source_file": "<filename>",
  "record_identifier": {"key": "<join_key_name>", "value": "<join_key_value>"},
  "extracted_attributes": [
    {
      "attribute_name": "<attribute>",
      "extracted_value": "<value_as_seen>",
      "currency": "<USD|EUR|...>",
      "location": "<page/section/field_label>",
      "confidence": "HIGH | MEDIUM | LOW",
      "rationale": "<explanation>"
    }
  ],
  "errors": []
}
```

### Status Values
`SUCCESS` | `ERROR` | `RECORD_NOT_FOUND` | `AMBIGUOUS_MATCH`

### Key Guardrails
- Only extract clearly legible values — ambiguous values → `"ILLEGIBLE"`
- Never infer, calculate, or derive values
- Never normalize or convert values — extract exactly as they appear
- Missing fields → `"NOT_FOUND"` | Empty fields → `"BLANK"`

---

## Prompt 2 — Excel Extraction Agent

**Variable:** `EXCEL_AGENT_PROMPT`
**Function:** `run_excel_agent()` in `agents.py`
**Purpose:** Extracts attribute values from Excel spreadsheets (supplied as converted CSV text).

### Parameters Passed at Runtime

| Parameter | Type | Description |
|-----------|------|-------------|
| `record_identifier` | dict | The join key used to locate the correct row |
| `attributes` | list[str] | List of attribute names to extract |
| `supporting_doc_text` | str | Column mapping rules and sheet context |
| `filename` | str | Name of the Excel source file |
| `excel_bytes` | bytes | Raw Excel bytes (converted to CSV per sheet internally) |

### Model Settings

| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-6` |
| Max Tokens | `4096` |
| Input Type | Text (CSV) |

### Output Format (JSON)

```json
{
  "agent": "excel_extraction_agent",
  "status": "SUCCESS",
  "source_file": "<filename>",
  "record_identifier": {"key": "<join_key_name>", "value": "<join_key_value>"},
  "extracted_attributes": [
    {
      "attribute_name": "<attribute>",
      "extracted_value": "<value_as_seen>",
      "currency": "<USD|EUR|...>",
      "location": "Sheet: <name>, Column: <header>, Row: <number>",
      "confidence": "HIGH | MEDIUM | LOW",
      "rationale": "<explanation of column mapping and cell reference>"
    }
  ],
  "errors": []
}
```

### Status Values
`SUCCESS` | `ERROR` | `RECORD_NOT_FOUND` | `SHEET_NOT_FOUND` | `AMBIGUOUS_MATCH`

### Key Guardrails
- No calculations, aggregations, or transformations
- Ignore sub-total, summary, and section header rows
- Formula cells → extract the displayed/calculated value, not the formula
- Missing column → `"COLUMN_NOT_FOUND"` | Multiple row matches → flag `"AMBIGUOUS_MATCH"` | Blank cell → `"BLANK"`

---

## Prompt 3 — Mapping Extraction Agent

**Variable:** `MAPPING_EXTRACTION_PROMPT`
**Function:** Called via `nodes.py`
**Purpose:** Reads regulatory PDF text to determine how sample columns map to source evidence columns, including the join key and any transformation rules.

### Inputs Provided

| Input | Description |
|-------|-------------|
| Sample Summary | Reported values (e.g., columns: rpID, mtm, CobDate) |
| Source Evidence file | Actual source data (e.g., columns: Loan Reference Number, USD Market Value) |
| Regulatory PDF text | Field definitions, calculation rules, mapping context |

### Output Format (JSON)

```json
{
  "join_key": {
    "sample_column": "<column name in sample>",
    "source_column": "<column name in source>",
    "notes": "<any suffix/prefix handling>"
  },
  "mappings": [
    {
      "mapping_id": "M-001",
      "sample_column": "<column in sample summary>",
      "source_column": "<column in source evidence, or null>",
      "transformation": "direct | calculation | static | not_available",
      "transformation_detail": "<e.g., 'divide by 1000', 'static value: 6/30/2025'>",
      "currency": "<USD|EUR|null>",
      "source_reference": "<page/section in PDF>"
    }
  ],
  "notes": "<overall observations>"
}
```

### Transformation Types

| Type | Meaning |
|------|---------|
| `direct` | 1:1 copy from source to sample |
| `calculation` | Derived value (e.g., divide by 1000, sum two columns) |
| `static` | Hardcoded value (e.g., always `6/30/2025`) |
| `not_available` | Field not present in source data |

---

## Prompt 4 — Supplemental Rules Agent

**Variable:** `SUPPLEMENTAL_RULES_PROMPT`
**Function:** `run_supplemental_rules_agent()` in `agents.py`
**Purpose:** Analyzes column statistics to identify additional data quality rules beyond standard mapped comparisons.

### Parameters Passed at Runtime

| Parameter | Type | Description |
|-----------|------|-------------|
| `data_statistics` | dict | Statistical summary of sample and source columns |
| `column_mappings` | dict | The mappings JSON from the Mapping Extraction Agent |
| `product` | str | Product name/type for context (e.g., "Loans") |

### Model Settings

| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-6` |
| Max Tokens | `2048` |
| Input Type | Text (JSON) |

### Output Format (JSON Array)

```json
[
  {
    "rule_id": "SR-001",
    "description": "Check for null values in join key column",
    "type": "null_check | range_check | statistical_outlier | cardinality_check",
    "column": "<column_name>",
    "dataset": "sample | source",
    "threshold": null,
    "finding": "<what triggered this rule>"
  }
]
```

### Rule Types

| Type | Description |
|------|-------------|
| `null_check` | Suspicious null counts in critical columns |
| `range_check` | Unexpected value ranges (e.g., negative amounts, future dates) |
| `statistical_outlier` | Values more than 3 std deviations from the mean |
| `cardinality_check` | Unusually high or low unique value counts |

---

## Prompt 5 — Validation Agent

**Variable:** `VALIDATION_AGENT_PROMPT`
**Function:** `run_validation_agent()` in `agents.py`
**Purpose:** Compares aggregated extracted source values against reported sample values and produces a markdown audit report.

### Parameters Passed at Runtime

| Parameter | Type | Description |
|-----------|------|-------------|
| `aggregated_json` | dict | Merged output from OCR + Excel agents (Stage 2) |
| `sample_csv_text` | str | The reported values CSV (what GS reported) |
| `attributes` | list[str] | List of attributes to validate |
| `supporting_doc_text` | str | Calculation rules and mapping context |
| `record_id` | str | The primary record ID being tested |

### Model Settings

| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-6` |
| Max Tokens | `4096` |
| Input Type | Text (JSON + CSV) |

### Output Format (Markdown Table)

```
## Data Quality Report

| ID | S.No | Attribute | Reported Value | Source Value | Variance | Testing Result | Results Comment | Source Document | Location | Variance Analysis |
|----|------|-----------|----------------|--------------|----------|----------------|-----------------|-----------------|----------|-------------------|
```

### Functional Equivalences (Counted as Pass)

| Scenario | Example |
|----------|---------|
| Number/currency formatting | `1000` vs `1,000.00` vs `$1,000.00` |
| Date format differences | `2025-06-30` vs `6/30/2025` vs `30-Jun-2025` |
| Leading/trailing whitespace | `" value "` vs `"value"` |

### Key Guardrails
- If upstream agent returned `NOT_FOUND` or `ILLEGIBLE`, Source Value → `"N/A"` with explanation
- Never re-derive source values from raw files
- All monetary comparisons must be in the same currency (USD unless specified)

---

## Prompt 6 — Final Report Agent

**Variable:** `FINAL_REPORT_PROMPT`
**Function:** Called via `nodes.py`
**Purpose:** Produces the final clean audit report comparing reported vs source values using pre-computed mappings.

### Inputs Provided

| Input | Description |
|-------|-------------|
| Sample Summary CSV | Reported values (what GS reported) |
| Source Evidence CSV | Actual values from the source system |
| Column Mappings JSON | Join key and attribute mappings from Mapping Extraction Agent |

### Output Format (Markdown Table)

```
## Data Quality Report

| Record ID | S.No | Attribute | Reported Value | Source Value | Variance | Testing Result | Results Comment | Source Column | Variance Analysis |
|-----------|------|-----------|----------------|--------------|----------|----------------|-----------------|---------------|-------------------|
```

### Testing Result Values
| Value | Meaning |
|-------|---------|
| `Pass` | Values match (accounting for functional equivalences) |
| `Fail` | Material variance detected |
| `N/A` | Attribute not available in source (`not_available` mapping type) |

---

## Summary Table

| # | Prompt | Variable | Used In | Output Type | Max Tokens |
|---|--------|----------|---------|-------------|------------|
| 1 | OCR Extraction Agent | `OCR_AGENT_PROMPT` | `agents.py` | JSON | 4096 |
| 2 | Excel Extraction Agent | `EXCEL_AGENT_PROMPT` | `agents.py` | JSON | 4096 |
| 3 | Mapping Extraction Agent | `MAPPING_EXTRACTION_PROMPT` | `nodes.py` | JSON | 4096 |
| 4 | Supplemental Rules Agent | `SUPPLEMENTAL_RULES_PROMPT` | `agents.py` | JSON Array | 2048 |
| 5 | Validation Agent | `VALIDATION_AGENT_PROMPT` | `agents.py` | Markdown Table | 4096 |
| 6 | Final Report Agent | `FINAL_REPORT_PROMPT` | `nodes.py` | Markdown Table | 4096 |

---

*All prompts defined in `prompts.py`. All agents use model `claude-sonnet-4-6`.*
