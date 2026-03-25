"""
LangGraph pipeline definition for the GS E2E Data Quality Testing workflow.
Defines the GraphState schema and the 8-node StateGraph.
"""
from typing import TypedDict, Annotated
import operator
from langgraph.graph import StateGraph, END

from nodes import (
    step1_load_data,
    step2_extract_pdfs,
    step3_generate_rules,
    step4a_compute_stats,
    step4b_supplemental_rules,
    step5_translate_rules,
    step6_apply_rules,
    step7_sampling,
    step8_final_report,
)


# ── State schema ──────────────────────────────────────────────────────────────
class GraphState(TypedDict):
    # ── Inputs (set by UI before running) ────────────────────────────────────
    sample_bytes: bytes        # Sample summary — reported values
    sample_filename: str
    source_bytes: bytes        # Source evidence — actual values to extract from
    source_filename: str
    source_type: str           # "excel" or "ocr"
    pdf_bytes_list: list       # Regulatory PDFs — context for mappings/rules
    pdf_filenames: list
    product: str

    # ── Step outputs ──────────────────────────────────────────────────────────
    sample_df_csv: str         # Step 1 — sample summary as CSV
    source_df_csv: str         # Step 1 — source evidence as CSV (if excel)
    attributes_to_test: list   # Step 1 — from "Attributes to test" tab
    ocr_results: list          # Step 1 — extracted values from image source (OCR path only)
    pdf_texts: list            # Step 2 — extracted PDF text
    column_mappings: list      # Step 3 — join keys + column mappings from PDFs
    data_statistics: dict      # Step 4a (stub)
    supplemental_rules: list   # Step 4b (stub)
    executable_specs: list     # Step 5 (stub)
    rule_results: dict         # Step 6 (stub)
    sample_records: list       # Step 7 (stub)
    final_report: str          # Step 8

    # ── Tracking ──────────────────────────────────────────────────────────────
    errors: list
    completed_steps: list


# ── Build graph ───────────────────────────────────────────────────────────────
def build_pipeline() -> StateGraph:
    graph = StateGraph(GraphState)

    # Add all 8 (+ sub-steps) nodes
    graph.add_node("step1_load_data",            step1_load_data)
    graph.add_node("step2_extract_pdfs",         step2_extract_pdfs)
    graph.add_node("step3_generate_rules",       step3_generate_rules)
    graph.add_node("step4a_compute_stats",       step4a_compute_stats)
    graph.add_node("step4b_supplemental_rules",  step4b_supplemental_rules)
    graph.add_node("step5_translate_rules",      step5_translate_rules)
    graph.add_node("step6_apply_rules",          step6_apply_rules)
    graph.add_node("step7_sampling",             step7_sampling)
    graph.add_node("step8_final_report",         step8_final_report)

    # Linear edges
    graph.set_entry_point("step1_load_data")
    graph.add_edge("step1_load_data",           "step2_extract_pdfs")
    graph.add_edge("step2_extract_pdfs",        "step3_generate_rules")
    graph.add_edge("step3_generate_rules",      "step4a_compute_stats")
    graph.add_edge("step4a_compute_stats",      "step4b_supplemental_rules")
    graph.add_edge("step4b_supplemental_rules", "step5_translate_rules")
    graph.add_edge("step5_translate_rules",     "step6_apply_rules")
    graph.add_edge("step6_apply_rules",         "step7_sampling")
    graph.add_edge("step7_sampling",            "step8_final_report")
    graph.add_edge("step8_final_report",        END)

    return graph.compile()


# Node display metadata for the UI
STEP_META = [
    {
        "node": "step1_load_data",
        "number": "1",
        "name": "Load Transaction Data",
        "handler": "Python",
        "handler_color": "#1e40af",
        "tokens": "0 tokens",
        "description": "Reads sample summary + source evidence into DataFrames",
    },
    {
        "node": "step2_extract_pdfs",
        "number": "2",
        "name": "Upload PDFs to Platform",
        "handler": "Python",
        "handler_color": "#1e40af",
        "tokens": "0 tokens",
        "description": "Extracts text from regulatory PDFs for context",
    },
    {
        "node": "step3_generate_rules",
        "number": "3",
        "name": "Generate Column Mappings",
        "handler": "LLM",
        "handler_color": "#7c3aed",
        "tokens": "Medium",
        "description": "PDFs → join keys + column mappings between sample & source",
    },
    {
        "node": "step4a_compute_stats",
        "number": "4a",
        "name": "Compute Data Statistics",
        "handler": "Python",
        "handler_color": "#1e40af",
        "tokens": "0 tokens",
        "description": "Quartiles, value counts, cardinality ratios",
        "stub": True,
    },
    {
        "node": "step4b_supplemental_rules",
        "number": "4b",
        "name": "Generate Supplemental Rules",
        "handler": "LLM",
        "handler_color": "#7c3aed",
        "tokens": "Low 2k-5k",
        "description": "Decide which statistical findings are meaningful rules",
        "stub": True,
    },
    {
        "node": "step5_translate_rules",
        "number": "5",
        "name": "Translate to Executable Spec",
        "handler": "LLM",
        "handler_color": "#7c3aed",
        "tokens": "Low 5k-10k",
        "description": "Map rules to column names and pandas expressions",
        "stub": True,
    },
    {
        "node": "step6_apply_rules",
        "number": "6",
        "name": "Apply Rules on Full Dataset",
        "handler": "Python",
        "handler_color": "#1e40af",
        "tokens": "0 tokens",
        "description": "Filter and count operations on all rows",
        "stub": True,
    },
    {
        "node": "step7_sampling",
        "number": "7",
        "name": "Execute Sampling Algorithm",
        "handler": "Python",
        "handler_color": "#1e40af",
        "tokens": "0 tokens",
        "description": "Multi-phase deterministic sampling",
        "stub": True,
    },
    {
        "node": "step8_final_report",
        "number": "8",
        "name": "Generate Final Report",
        "handler": "LLM",
        "handler_color": "#7c3aed",
        "tokens": "Low 5k-15k",
        "description": "Format and merge outputs into markdown audit table",
    },
]
