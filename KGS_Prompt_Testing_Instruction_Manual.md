# Prompt Testing Instruction Manual

**Prepared for:** KPMG KGS Team  
**Subject:** E2E Data Quality Testing — Manual Prompt Chain Testing  
**Test Case:** FR 2590 — Line Item 15 (JAPAN SECURITIES CLEARING CORPORATION)

---

## 1. Overview

This document provides step-by-step instructions for testing a chain of 9 prompts that perform end-to-end data quality validation on regulatory financial reports. The prompts are designed to be run sequentially on the GSAI platform — each prompt's output becomes input to the next prompt in the chain.

The prompt chain validates reported values in a sample summary against source evidence documents by: mapping evidence files to attributes, building a validation plan, extracting data from source files, calculating tested values, comparing against reported values, and generating a final audit report.

### Prompt Chain Flow

```
Prompt 1 (Evidence Mapping)
    |
    v
Prompt 2 (Validation Plan)
    |
    +-----------+-----------+
    |           |           |
    v           v           v
Prompt 3     Prompt 4     Prompt 5
(Image)      (Structured) (Unstructured)
    |           |           |
    +-----------+-----------+
                |
                v
          Prompt 5a (Extraction Concatenation)
                |
                v
          Prompt 6 (Attribute Tester / Calculation Engine)
                |
                v
          Prompt 7 (Variance Comparison)
                |
                v
          Prompt 8 (Report Generator)
```

---

## 2. Platform and Model Requirements

| Setting | Value |
|---------|-------|
| Platform | GSAI |
| Default Model | **Opus 4.6** |
| Exception | **Prompt 3 only** — use **Gemini 3.0 Flash Vision** (required for image/screenshot extraction) |

Use Opus 4.6 for every prompt except Prompt 3. Prompt 3 requires a vision-capable model to read screenshots and images, which is why Gemini 3.0 Flash Vision is used.

---

## 3. Folder Structure and File Locations

All testing materials are located in the **"Prompt Development"** folder on the shared site. The folder is organized as follows:

```
Prompt Development/
├── Prompt 1/
│   ├── Prompt 1              (static prompt text)
│   ├── Prompt 1 Parameters   (parameter instructions and placeholders)
│   ├── Prompt 1 Output       (expected output schema/format)
│   ├── Prompt 1 Full Test    (complete test with sample inputs and outputs)
│   └── [relevant test files]
│
├── Prompt 2/
│   ├── Prompt 2
│   ├── Prompt 2 Parameters
│   ├── Prompt 2 Output
│   ├── Prompt 2 Full Test
│   └── [relevant test files]
│
├── Prompt 3/
│   ├── Prompt 3
│   ├── Prompt 3 Parameters
│   ├── Prompt 3 Output
│   ├── Prompt 3 Full Test
│   └── [relevant test files]
│
├── Prompt 4/
│   ├── Prompt 4
│   ├── Prompt 4 Parameters
│   ├── Prompt 4 Output
│   ├── Prompt 4 Full Test
│   └── [relevant test files]
│
├── Prompt 5/
│   ├── Prompt 5
│   ├── Prompt 5 Parameters
│   ├── Prompt 5 Output
│   ├── Prompt 5 Full Test
│   └── [relevant test files]
│
├── Prompt 5a/
│   ├── Prompt 5a
│   ├── Prompt 5a Parameters
│   ├── Prompt 5a Output
│   ├── Prompt 5a Full Test
│   └── [relevant test files]
│
├── Prompt 6/
│   ├── Prompt 6
│   ├── Prompt 6 Parameters
│   ├── Prompt 6 Output
│   ├── Prompt 6 Full Test
│   └── [relevant test files]
│
├── Prompt 7/
│   ├── Prompt 7
│   ├── Prompt 7 Parameters
│   ├── Prompt 7 Output
│   ├── Prompt 7 Full Test
│   └── [relevant test files]
│
└── Prompt 8/
    ├── Prompt 8
    ├── Prompt 8 Parameters
    ├── Prompt 8 Output
    ├── Prompt 8 Full Test
    └── [relevant test files]
```

### About the Test Files in Each Folder

Each prompt folder contains source evidence files and/or sample data files that are relevant to that specific prompt's test. These files are specific to the **Line Item 15** test case and are included so each prompt can be tested independently without needing to gather files from elsewhere. When testing a different line item, you would substitute the appropriate files for that line item.

---

## 4. Files in Each Folder — What They Are For

Each folder contains four standard documents plus supporting files:

| File | Purpose |
|------|---------|
| **Prompt X** | The static prompt text. Copy and paste this into the GSAI system/prompt field. This does not change between test cases. |
| **Prompt X Parameters** | Describes the parameters (inputs) the prompt expects. Shows placeholders where you paste in data. |
| **Prompt X Output** | Documents the expected output format/schema. Use this to verify the model's response is correctly structured. |
| **Prompt X Full Test** | A complete end-to-end example for this prompt using Line Item 15 data. Contains the prompt, filled-in parameters, and the expected output. Use this as a reference to compare your results against. |

---

## 5. How to Run a Prompt

Follow these steps for each prompt in the chain:

### Step 1 — Open a New GSAI Session
Start a new conversation on GSAI. Select the correct model:
- **Opus 4.6** for all prompts except Prompt 3
- **Gemini 3.0 Flash Vision** for Prompt 3

### Step 2 — Copy the Static Prompt
Open the **"Prompt X"** file from the relevant folder. Copy the entire prompt text.

### Step 3 — Fill In the Parameters
Open the **"Prompt X Parameters"** file. It will list each parameter with a placeholder (e.g., `[PASTE JSON HERE]`). Replace each placeholder with the actual data:
- For the first prompt in the chain (Prompt 1), use the raw input files.
- For all subsequent prompts, the primary input is the **output from the previous prompt** — copy the JSON output from the prior step and paste it into the appropriate parameter slot.
- Some prompts also require uploading source evidence files (images, Excel files, PDFs). These are noted in the parameter instructions.

### Step 4 — Submit and Capture the Output
Paste the complete prompt (static text + filled parameters) into GSAI and submit. Copy the full output — you will need it as input for the next prompt in the chain.

### Step 5 — Validate the Output
Compare the output against the **"Prompt X Output"** file to verify the structure is correct (all expected fields present, correct format). Optionally compare against the **"Prompt X Full Test"** file to see if the values are reasonable for the Line Item 15 test case.

---

## 6. Prompt-by-Prompt Execution Guide

### Prompt 1 — Evidence Mapping

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Maps source evidence files to the attributes they can validate |
| Parameters | (1) Master input table defining attributes and evidence types, (2) Comma-separated list of available source evidence files with extensions |
| Output | JSON containing mapping results, unmapped evidence types, unmapped files, and flags |
| Feeds Into | Prompt 2 |

**What to do:** Provide the master input table and the list of source evidence files. The model will determine which files correspond to which attributes.

**What to check:** Verify every source file is accounted for. Check that no files are listed under "unmapped_files" unless they genuinely have no matching attribute. Review any flags the model raises.

---

### Prompt 2 — Validation Plan

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Creates a detailed validation plan defining how each attribute should be tested |
| Parameters | (1) Reporting instruction PDFs (BIS document and IDH Guidelines), (2) Prompt 1 output JSON (evidence mapping), (3) Transaction identifier columns only from the sample summary (no reported values) |
| Output | JSON containing transaction identifiers and a validation plan array with classification (Direct/Aggregated), formulas, and extraction steps per attribute |
| Feeds Into | Prompts 3, 4, and 5 |

**What to do:** Upload both reporting instruction documents (BIS and IDH Guidelines). Paste the Prompt 1 output JSON. Paste only the identifier columns from the transaction sample row — do not include reported value columns (e.g., Reported_Value, Notional, MTM, Balance).

**What to check:** Verify each attribute has a classification of either "Direct" or "Aggregated." For Aggregated attributes, confirm there is a formula. Confirm the transaction identifiers are correctly extracted. Verify BIS was used as the primary source for formulas where applicable.

**Important:** Parameter 3 must contain only identifier fields (Trade Reference ID, Counterparty Name, COB Date, Trade Date, etc.). Reported values are intentionally excluded to prevent answer leakage — they do not appear until Prompt 7.

---

### Prompt 3 — Image Extractor

| Field | Value |
|-------|-------|
| Model | **Gemini 3.0 Flash Vision** |
| Purpose | Extracts data from image-based source evidence (screenshots, scanned documents) |
| Parameters | (1) Source image file + filename, (2) Validation plan JSON (Prompt 2 output) |
| Output | JSON with extracted values, locations, confidence scores, and rationale per sub-attribute |
| Feeds Into | Prompt 5a |

**What to do:** Upload one image file at a time along with its filename. Paste the validation plan JSON from Prompt 2. Run this prompt once per image file.

**What to check:** Verify extracted values match what you can see in the image. Confirm the model did not extract values from search bars, filter panels, or toolbar elements — these are explicitly banned as they represent query inputs, not source evidence. Check that NOT_FOUND values are genuinely not present in the image.

**Important:** This is the only prompt that uses Gemini 3.0 Flash Vision. Run it for each image file separately. For the Line Item 15 test case, image files include screenshots like Aster_Contract_Browser.png, Choice_Price_Data_Browser.png, FX_Rate_Data_Browser.png, and JGBCC_JSCC_Merger_Reference.png.

---

### Prompt 4 — Structured Data Extractor

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Extracts data from structured source evidence (Excel/CSV files) |
| Parameters | (1) Source Excel data (pasted as CSV or uploaded) + filename, (2) Validation plan JSON (Prompt 2 output) |
| Output | JSON with extracted values, sheet/column/row locations, and confidence scores per sub-attribute |
| Feeds Into | Prompt 5a |

**What to do:** Open the Excel file, copy the relevant sheet data, and paste it. Include the filename. Paste the validation plan JSON from Prompt 2. Run once per structured file.

**What to check:** Verify the correct row was identified using the join key. Confirm column mappings are correct. Check that values match the actual cell contents in the spreadsheet.

---

### Prompt 5 — Unstructured Data Extractor

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Extracts data from unstructured source evidence (PDFs, Word documents) |
| Parameters | (1) Source document (uploaded PDF/Word) + filename, (2) Validation plan JSON (Prompt 2 output) |
| Output | JSON with extracted values, page/section locations, verbatim quotes, and confidence scores per sub-attribute |
| Feeds Into | Prompt 5a |

**What to do:** Upload the PDF or document file. Paste the validation plan JSON from Prompt 2. Run once per unstructured file.

**What to check:** Verify extracted values are present in the document at the stated locations. Confirm verbatim quotes actually appear in the source. Check that page and section references are accurate.

---

### Prompt 5a — Extraction Concatenation

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Merges all extraction outputs from Prompts 3, 4, and 5 into a single consolidated JSON |
| Parameters | All extraction JSON outputs from Prompts 3, 4, and 5 (pasted with labels identifying which file each came from) |
| Output | Consolidated JSON with all extractions unified, a summary table, and flags for any issues |
| Feeds Into | Prompt 6 |

**What to do:** Collect all the extraction outputs (from every run of Prompts 3, 4, and 5) and paste them into this prompt. Label each one with the source file it came from.

**What to check:** Verify all extraction results are present — nothing was dropped. Confirm values were not modified during concatenation. Review the summary table for completeness. Check flags for any issues that need resolution before proceeding.

**Important:** This prompt does not modify, recalculate, or fill in any values. It is purely a consolidation step.

---

### Prompt 6 — Attribute Tester / Calculation Engine

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Applies validation logic — direct lookups for Direct attributes, formula calculations for Aggregated attributes |
| Parameters | (1) Validation plan JSON (Prompt 2 output), (2) Concatenated extractions JSON (Prompt 5a output) |
| Output | JSON with tested values, calculation steps, formula objects (expression/source/rationale), confidence, and flags per attribute |
| Feeds Into | Prompt 7 |

**What to do:** Paste the validation plan from Prompt 2 and the concatenated extractions from Prompt 5a.

**What to check:**
- For **Direct** attributes: the tested value should match the extracted value from the source.
- For **Aggregated** attributes: verify the formula is correct and the arithmetic is shown step-by-step with actual substituted values.
- The formula field should be an object with three sub-fields: `expression` (the formula), `source` (where it was found), and `rationale` (why it applies).
- For date attributes where the exact date was NOT_FOUND: check that fallback start/end dates were used and the tested value shows as "RANGE: [start_date] to [end_date]".
- Calculation steps should be clean — no self-corrections or restarts in the output.

---

### Prompt 7 — Variance Comparison

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Compares tested values (from Prompt 6) against reported values (from the sample summary) and determines Pass/Fail with rationale |
| Parameters | (1) Reporting instruction PDFs (BIS and IDH Guidelines), (2) Prompt 6 output JSON (attribute tester results), (3) Full transaction sample row from sample summary (this is where reported values first appear) |
| Output | JSON with comparison results, variance amounts, Pass/Fail/Unable_to_Test determinations, confidence scores, and variance rationale per attribute |
| Feeds Into | Prompt 8 |

**What to do:** Upload the reporting instruction documents again. Paste the Prompt 6 output. Paste the full transaction sample row including reported values.

**What to check:**
- Reported values should come from the sample summary row, not from any prior prompt.
- Variance calculations should be correct (numerical difference for amounts, day difference for dates).
- Formatting differences (e.g., 1000 vs 1,000.00) should result in Pass, not Fail.
- Date range comparisons: if the tested value is "RANGE: [start] to [end]" and the reported date falls within that range, the result should be Pass with MEDIUM confidence.
- Every result (Pass, Fail, or Unable_to_Test) should have a confidence score — not just failures.
- BIS citations should take priority over IDH citations when both documents address the same rule.

---

### Prompt 8 — Report Generator

| Field | Value |
|-------|-------|
| Model | Opus 4.6 |
| Purpose | Compiles all results into a single comprehensive audit report in markdown table format |
| Parameters | (1) Prompt 7 output JSON (variance comparison results) |
| Output | Markdown report with header section, comprehensive results table, summary statistics, and items requiring review |
| Feeds Into | Nothing — this is the final output |

**What to do:** Paste the Prompt 7 output JSON.

**What to check:**
- The report should contain a single comprehensive markdown table with 11 columns: Attribute, Classification, Reported Value, Tested Value, Variance, Result, Confidence, Calculation Rationale, Variance Rationale, Citations, Flags.
- Summary statistics should accurately count Pass/Fail/Unable_to_Test results.
- Any flags should be short tags (e.g., REVIEW_REQUIRED, FX_CONVERSION_APPLIED) — long explanatory text should appear in the rationale columns, not in the flags column.
- Items marked REVIEW_REQUIRED should be listed in a separate section at the bottom.

---

## 7. Key Concepts to Understand

### Direct vs. Aggregated Attributes

- **Direct**: The reported value maps 1:1 to a single source value. Testing is a straightforward comparison (e.g., Product Type, Counterparty Name).
- **Aggregated**: The reported value is calculated from one or more source values using a formula (e.g., Reported Balance = Face Amount * FX Rate). Testing requires applying the formula and comparing the result.

### Document Priority

When both reporting instruction documents are provided (BIS and IDH Guidelines):
- **BIS (internal methodology)** takes priority — it reflects how the firm actually implements reporting rules.
- **IDH Guidelines (regulatory)** serves as the baseline when BIS is silent on a topic.

### Date Range Fallback

If an exact date is not found in the source evidence, but start and end dates exist that bracket the expected date:
- The tested value will show as "RANGE: [start_date] to [end_date]"
- If the reported date falls within the range, the result is **Pass** with **MEDIUM** confidence
- If the reported date falls outside the range, the result is **Fail**

### Answer Leakage Prevention

Reported values (the "answers" being tested) are intentionally withheld from the model until Prompt 7. This prevents the extraction and calculation steps from being biased by knowing what the expected answer is. Prompt 2 Parameter 3 contains only identifier columns — no reported values.

### REVIEW_REQUIRED Flag

When the model encounters situations that need human judgment (ambiguous extractions, low confidence values, discrepancies between sources), it flags them as REVIEW_REQUIRED. These items are surfaced in the final Prompt 8 report under "Items Requiring Review."

---

## 8. Troubleshooting

| Issue | Resolution |
|-------|------------|
| Model returns markdown-fenced JSON (```json ... ```) | Re-run and emphasize the prompt instruction "Return ONLY a valid JSON object with NO markdown fences" |
| Prompt 3 extracts values from a search bar or filter panel | This is a known issue. The prompt includes a hard ban on search filter extraction. If it still happens, re-run with Gemini 3.0 Flash Vision and note the issue. |
| Output JSON is malformed or truncated | The response may have hit a token limit. Try breaking the prompt into smaller pieces or reducing the amount of pasted data. |
| Prompt 6 calculation_steps contain self-corrections ("let me recalculate...") | Re-run. The prompt instructs the model to show only the final clean arithmetic. |
| Prompt 7 shows null confidence for Pass results | Re-run. The prompt requires confidence scoring for all results (Pass, Fail, and Unable_to_Test). |
| Flags contain paragraph-length explanations | Prompt 8 should clean these up — long text moves to rationale columns, flags remain as short tags. If Prompt 8 doesn't fix it, note the issue. |

---

## 9. Quick Reference — Execution Checklist

Use this checklist to track your progress through the chain:

- [ ] **Prompt 1** — Evidence Mapping (Opus 4.6) — Output captured
- [ ] **Prompt 2** — Validation Plan (Opus 4.6) — Output captured
- [ ] **Prompt 3** — Image Extractor (Gemini 3.0 Flash Vision) — Run for each image file — All outputs captured
- [ ] **Prompt 4** — Structured Data Extractor (Opus 4.6) — Run for each Excel file — All outputs captured
- [ ] **Prompt 5** — Unstructured Data Extractor (Opus 4.6) — Run for each PDF/document — All outputs captured
- [ ] **Prompt 5a** — Extraction Concatenation (Opus 4.6) — All extractions merged — Output captured
- [ ] **Prompt 6** — Attribute Tester (Opus 4.6) — Output captured
- [ ] **Prompt 7** — Variance Comparison (Opus 4.6) — Output captured
- [ ] **Prompt 8** — Report Generator (Opus 4.6) — Final report generated

---

## 10. Notes

- Each prompt folder contains test files specific to the **Line Item 15** test case. These files are included for convenience so you can run each prompt independently. When testing a different line item, substitute the appropriate source evidence files and sample data for that line item.
- Prompts 3, 4, and 5 may each need to be run multiple times — once per source file of that type (images for Prompt 3, Excel files for Prompt 4, PDFs for Prompt 5). Collect all outputs before moving to Prompt 5a.
- Always start a new GSAI conversation for each prompt. Do not run multiple prompts in the same conversation — this avoids context contamination.
- Save every output. You will need outputs from earlier prompts as inputs to later prompts.
