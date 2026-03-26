import json
import base64
import io
import pandas as pd
from anthropic import Anthropic
from prompts import OCR_AGENT_PROMPT, EXCEL_AGENT_PROMPT, VALIDATION_AGENT_PROMPT, SUPPLEMENTAL_RULES_PROMPT

MODEL = "claude-sonnet-4-6"


def _client():
    return Anthropic()


def _parse_json_response(text: str) -> dict:
    """Extract JSON from a model response, stripping any markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening fence
        lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


def _detect_header_row(xl: pd.ExcelFile, sheet: str, max_scan: int = 20) -> int:
    """
    Auto-detect the header row in an Excel sheet by finding the first row
    where most cells are non-null strings (not 'Unnamed'). Handles files
    with title/metadata rows before the actual data headers.
    """
    df_raw = xl.parse(sheet, header=None, nrows=max_scan)
    if df_raw.empty:
        return 0
    best_row = 0
    best_score = 0
    for i in range(min(max_scan, len(df_raw))):
        row_vals = df_raw.iloc[i]
        non_null = row_vals.dropna()
        if len(non_null) < 2:
            continue
        # Score: count of non-null string values that look like headers (not pure numbers)
        str_count = sum(
            1 for v in non_null
            if isinstance(v, str) and v.strip() and not v.startswith("Unnamed")
        )
        # Prefer rows with many string values (headers) vs few (metadata/title rows)
        if str_count > best_score:
            best_score = str_count
            best_row = i
    return best_row


def excel_to_csv_text(excel_bytes: bytes, filename: str) -> dict[str, str]:
    """Convert all sheets of an Excel file to a dict of {sheet_name: csv_text}.
    Auto-detects the header row to handle files with metadata/title rows at the top."""
    xl = pd.ExcelFile(io.BytesIO(excel_bytes))
    sheets = {}
    for sheet in xl.sheet_names:
        header_row = _detect_header_row(xl, sheet)
        df = xl.parse(sheet, header=header_row)
        # Drop fully-empty rows that may appear between header and data
        df = df.dropna(how="all").reset_index(drop=True)
        sheets[sheet] = df.to_csv(index=False)
    return sheets


def run_ocr_agent(
    image_bytes: bytes,
    filename: str,
    attributes: list[str],
    record_identifier: dict,
    supporting_doc_text: str,
) -> dict:
    """Stage 1a: Extract attributes from an image/screenshot using OCR."""
    client = _client()

    media_type = "image/jpeg"
    if filename.lower().endswith(".png"):
        media_type = "image/png"

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    user_message = f"""Please extract the following attributes from the source evidence image.

**Record Identifier:** {json.dumps(record_identifier)}

**Attributes to Extract:** {json.dumps(attributes)}

**Supporting Document (mapping rules):**
{supporting_doc_text}

**Source Evidence File:** {filename}

The image is attached below. Extract each attribute exactly as it appears and return the standardized JSON output."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=OCR_AGENT_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_message},
                ],
            }
        ],
    )

    return _parse_json_response(response.content[0].text)


def run_excel_agent(
    excel_bytes: bytes,
    filename: str,
    attributes: list[str],
    record_identifier: dict,
    supporting_doc_text: str,
) -> dict:
    """Stage 1b: Extract attributes from an Excel file."""
    client = _client()

    sheets = excel_to_csv_text(excel_bytes, filename)
    sheets_text = ""
    for sheet_name, csv_content in sheets.items():
        sheets_text += f"\n\n--- Sheet: {sheet_name} ---\n{csv_content}"

    user_message = f"""Please extract the following attributes from the source evidence Excel file.

**Record Identifier:** {json.dumps(record_identifier)}

**Attributes to Extract:** {json.dumps(attributes)}

**Supporting Document (mapping rules):**
{supporting_doc_text}

**Source Evidence File:** {filename}

**Excel File Contents (all sheets as CSV):**
{sheets_text}

Extract each attribute exactly as it appears in the cells and return the standardized JSON output."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=EXCEL_AGENT_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_json_response(response.content[0].text)


def aggregate(ocr_result: dict | None, excel_result: dict | None) -> dict:
    """Stage 2: Merge outputs from Stage 1a and 1b agents into aggregated JSON."""
    record_identifier = {}
    extraction_results = []
    agent_errors = []

    for result in [ocr_result, excel_result]:
        if result is None:
            continue

        # Capture record identifier
        if result.get("record_identifier"):
            record_identifier = result["record_identifier"]

        # Propagate errors
        if result.get("status") not in ("SUCCESS", None):
            agent_errors.append(
                {
                    "agent": result.get("agent", "unknown"),
                    "status": result.get("status"),
                    "errors": result.get("errors", []),
                }
            )

        # Merge extracted attributes
        for attr in result.get("extracted_attributes", []):
            extraction_results.append(
                {
                    "attribute_name": attr.get("attribute_name"),
                    "extracted_value": attr.get("extracted_value"),
                    "currency": attr.get("currency"),
                    "source_agent": result.get("agent"),
                    "source_file": result.get("source_file"),
                    "location": attr.get("location"),
                    "confidence": attr.get("confidence"),
                    "rationale": attr.get("rationale"),
                }
            )

    return {
        "record_identifier": record_identifier,
        "extraction_results": extraction_results,
        "agent_errors": agent_errors,
    }


def run_validation_agent(
    aggregated_json: dict,
    sample_csv_text: str,
    attributes: list[str],
    supporting_doc_text: str,
    record_id: str = "",
) -> str:
    """Stage 3: Compare extracted values against reported values, return markdown report."""
    client = _client()

    user_message = f"""Please validate the extracted source values against the reported values and generate a Data Quality Report.

**Record being tested:** {record_id}
**Attributes to validate:** {json.dumps(attributes)}

**Aggregated Extraction JSON (from Stage 2):**
```json
{json.dumps(aggregated_json, indent=2)}
```

**Financial Data Sample (reported values — CSV format):**
{sample_csv_text}

**Supporting Document (calculation rules and mappings):**
{supporting_doc_text}

Generate the markdown Data Quality Report table as specified."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=VALIDATION_AGENT_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


def run_supplemental_rules_agent(
    data_statistics: dict,
    column_mappings: dict,
    product: str,
) -> list:
    """Generate supplemental data quality rules based on column statistics."""
    client = _client()

    user_message = f"""Analyze the following data statistics and column mappings for {product} data quality testing.
Identify any supplemental rules worth checking beyond the standard column comparisons.

**Column Mappings:**
```json
{json.dumps(column_mappings, indent=2)}
```

**Data Statistics:**
```json
{json.dumps(data_statistics, indent=2)}
```

Return the supplemental rules JSON array."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SUPPLEMENTAL_RULES_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    try:
        result = _parse_json_response(response.content[0].text)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def parse_markdown_table(md_text: str) -> pd.DataFrame | None:
    """Parse a markdown table string into a pandas DataFrame."""
    lines = [l.strip() for l in md_text.strip().split("\n") if l.strip()]
    # Find the header row (contains pipes)
    table_lines = [l for l in lines if l.startswith("|")]
    if len(table_lines) < 3:
        return None

    # Remove separator row (---|---...)
    header_line = table_lines[0]
    data_lines = [l for l in table_lines[2:]]  # skip separator at index 1

    def parse_row(line):
        return [c.strip() for c in line.strip("|").split("|")]

    headers = parse_row(header_line)
    rows = [parse_row(l) for l in data_lines]

    # Pad rows to header length
    n = len(headers)
    rows = [r[:n] + [""] * max(0, n - len(r)) for r in rows]

    return pd.DataFrame(rows, columns=headers)
