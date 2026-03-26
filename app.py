import os
import io
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pipeline import build_pipeline, STEP_META
from agents import parse_markdown_table

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GS E2E Data Quality Testing",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global ── */
.gs-header {
    background: linear-gradient(90deg, #0d3349 0%, #1a5276 100%);
    padding: 1.2rem 2rem;
    border-radius: 8px;
    margin-bottom: 1.5rem;
}
.gs-header h1 { color: white; font-size: 1.6rem; font-weight: 700; margin: 0; }
.gs-header p  { color: #a8c4d4; font-size: 0.85rem; margin: 0.2rem 0 0; }

/* ── Pipeline strip ── */
.pipeline-strip {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding: 1rem 0;
    align-items: stretch;
}
.step-card {
    flex: 1;
    min-width: 100px;
    background: #f8fafc;
    border: 2px solid #e2e8f0;
    border-radius: 10px;
    padding: 0.75rem 0.5rem;
    text-align: center;
    position: relative;
    transition: border-color 0.2s;
}
.step-card.running  { border-color: #3b82f6; background: #eff6ff; }
.step-card.complete { border-color: #22c55e; background: #f0fdf4; }
.step-card.stub     { border-color: #f59e0b; background: #fffbeb; }
.step-card.error    { border-color: #ef4444; background: #fef2f2; }

.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px; height: 28px;
    border-radius: 50%;
    font-size: 0.75rem;
    font-weight: 700;
    color: white;
    margin-bottom: 0.4rem;
}
.step-name  { font-size: 0.7rem; font-weight: 600; color: #1e293b; line-height: 1.2; margin-bottom: 0.3rem; }
.step-badge {
    display: inline-block;
    font-size: 0.6rem;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 99px;
    color: white;
    margin-bottom: 0.25rem;
}
.step-tokens { font-size: 0.6rem; color: #94a3b8; }
.step-status { font-size: 1rem; margin-top: 0.3rem; }

/* ── Connector arrow ── */
.arrow { color: #cbd5e1; font-size: 1.2rem; align-self: center; flex-shrink: 0; }

/* ── Match method badges ── */
.match-badge {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 99px;
    color: white;
}
.match-direct     { background: #22c55e; }
.match-alias      { background: #3b82f6; }
.match-calculated { background: #8b5cf6; }
.match-static     { background: #6b7280; }
.match-ocr        { background: #f59e0b; }
.match-unresolved { background: #ef4444; }
.match-not_available { background: #9ca3af; }
.match-calculation { background: #0ea5e9; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background: #0d3349; }
section[data-testid="stSidebar"] * { color: white !important; }
section[data-testid="stSidebar"] label { color: #a8c4d4 !important; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
PRODUCT_OPTIONS = ["Loans", "Derivatives", "KYC", "General"]

STATUS_ICON = {
    "pending":  "⏳",
    "running":  "🔄",
    "complete": "✅",
    "stub":     "🔲",
    "error":    "❌",
}


def render_pipeline(step_statuses: dict, container=None):
    """Render the 8-step pipeline strip as HTML cards."""
    cards_html = '<div class="pipeline-strip">'
    for i, meta in enumerate(STEP_META):
        node = meta["node"]
        status = step_statuses.get(node, "pending")
        is_stub = meta.get("stub", False) and status not in ("running",)
        if is_stub and status == "complete":
            status = "stub"

        css_class = f"step-card {status}"
        icon = STATUS_ICON.get(status, "⏳")
        badge_bg = meta["handler_color"]
        num_bg = "#0d3349" if status == "pending" else (
            "#22c55e" if status == "complete" else (
            "#3b82f6" if status == "running" else (
            "#f59e0b" if status == "stub" else "#ef4444")))

        cards_html += f"""
        <div class="{css_class}">
            <div class="step-num" style="background:{num_bg}">{meta['number']}</div>
            <div class="step-name">{meta['name']}</div>
            <div class="step-badge" style="background:{badge_bg}">{meta['handler']}</div><br>
            <div class="step-tokens">{meta['tokens']}</div>
            <div class="step-status">{icon}</div>
        </div>"""

        if i < len(STEP_META) - 1:
            cards_html += '<div class="arrow">→</div>'

    cards_html += "</div>"
    if container:
        container.markdown(cards_html, unsafe_allow_html=True)
    else:
        st.markdown(cards_html, unsafe_allow_html=True)


def style_results_df(df: pd.DataFrame) -> pd.DataFrame:
    result_col = next((c for c in df.columns if "result" in c.lower()), None)
    if result_col:
        df[result_col] = df[result_col].apply(
            lambda v: "✅ Pass" if str(v).strip().lower() == "pass"
            else ("❌ Fail" if str(v).strip().lower() == "fail"
            else ("⏳ Pending" if str(v).strip().lower() == "pending" else v))
        )
    return df


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### GS E2E Testing")
    st.markdown("---")
    st.markdown("**Product Line**")
    product = st.radio(
        "Product",
        PRODUCT_OPTIONS,
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.markdown("**Pipeline**")
    for meta in STEP_META:
        stub_tag = " 🔲" if meta.get("stub") else ""
        st.markdown(f"**{meta['number']}.** {meta['name']}{stub_tag}")
    st.markdown("---")
    st.markdown("**Orchestration:** LangGraph")
    st.markdown("**LLM:** Claude Sonnet 4.6")
    st.markdown("KPMG Advisory · March 2026")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="gs-header">
    <h1>📊 E2E Data Quality Testing</h1>
    <p>Goldman Sachs · KPMG Advisory, Data and Analytics · {product} · LangGraph 8-Step Pipeline</p>
</div>
""", unsafe_allow_html=True)

# ── Pipeline visual (initial — all pending) ────────────────────────────────────
pipeline_container = st.empty()
initial_statuses = {meta["node"]: "pending" for meta in STEP_META}
render_pipeline(initial_statuses, pipeline_container)

st.divider()

# ── File uploads ──────────────────────────────────────────────────────────────
st.subheader("Step 1 · Upload Files")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**📄 Sample Summary** *(reported values)*")
    sample_file = st.file_uploader(
        "Sample Summary",
        type=["xlsx", "csv"],
        help="e.g. Loan sample summary.xlsx — the file containing what was reported",
        key="sample_upload",
        label_visibility="collapsed",
    )
    if sample_file:
        st.caption(f"✅ {sample_file.name}")

with col2:
    st.markdown("**📊 Source Evidence** *(actual values)*")
    source_file = st.file_uploader(
        "Source Evidence",
        type=["xlsx", "csv", "jpg", "jpeg", "png"],
        help="e.g. Loan Activity Report_synthetic.xlsx or PHUB screenshot — the source to extract from",
        key="source_upload",
        label_visibility="collapsed",
    )
    if source_file:
        source_type = "ocr" if source_file.name.lower().endswith((".jpg", ".jpeg", ".png")) else "excel"
        st.caption(f"✅ {source_file.name}  ({'OCR' if source_type == 'ocr' else 'Excel'})")

with col3:
    st.markdown("**📋 Regulatory PDFs** *(comparison context)*")
    pdf_files = st.file_uploader(
        "Regulatory PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="e.g. FR 2590 instructions — provides column mappings and calculation rules",
        key="pdf_upload",
        label_visibility="collapsed",
    )
    if pdf_files:
        st.caption(f"✅ {len(pdf_files)} PDF(s): {', '.join(f.name for f in pdf_files)}")

st.divider()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("⚠️ No `ANTHROPIC_API_KEY` found. Create a `.env` file with your key.")

run_disabled = (sample_file is None or source_file is None) or not os.environ.get("ANTHROPIC_API_KEY")
run_btn = st.button(
    "▶  Run 8-Step Pipeline",
    type="primary",
    disabled=run_disabled,
    width="stretch",
)
if sample_file is None or source_file is None:
    st.info("Upload both a Sample Summary and a Source Evidence file to enable the pipeline.")

# ── Pipeline execution ────────────────────────────────────────────────────────
if run_btn and sample_file and source_file:
    graph = build_pipeline()

    _source_type = "ocr" if source_file.name.lower().endswith((".jpg", ".jpeg", ".png")) else "excel"

    # Build initial state
    initial_state = {
        "sample_bytes": sample_file.read(),
        "sample_filename": sample_file.name,
        "source_bytes": source_file.read(),
        "source_filename": source_file.name,
        "source_type": _source_type,
        "pdf_bytes_list": [f.read() for f in (pdf_files or [])],
        "pdf_filenames": [f.name for f in (pdf_files or [])],
        "product": product,
        # Step outputs (empty defaults)
        "sample_df_csv": "",
        "source_df_csv": "",
        "attributes_to_test": [],
        "ocr_results": [],
        "pdf_texts": [],
        "column_mappings": {},
        "data_statistics": {},
        "supplemental_rules": [],
        "executable_specs": [],
        "rule_results": {},
        "sample_records": [],
        "final_report": "",
        "errors": [],
        "completed_steps": [],
    }

    # Track status per node
    step_statuses = {meta["node"]: "pending" for meta in STEP_META}
    step_outputs = {}
    final_state = {}

    # Map node name → next node (to mark "running")
    node_order = [m["node"] for m in STEP_META]

    log_container = st.container()

    with log_container:
        status_box = st.status("🚀 Running pipeline...", expanded=True)

        with status_box:
            for event in graph.stream(initial_state):
                for node_name, node_output in event.items():
                    # Mark current as complete
                    step_statuses[node_name] = "complete"
                    step_outputs[node_name] = node_output
                    final_state.update(node_output)

                    # Mark next node as running
                    idx = node_order.index(node_name) if node_name in node_order else -1
                    if idx >= 0 and idx + 1 < len(node_order):
                        next_node = node_order[idx + 1]
                        step_statuses[next_node] = "running"

                    render_pipeline(step_statuses, pipeline_container)

                    meta = next((m for m in STEP_META if m["node"] == node_name), {})
                    is_stub = meta.get("stub", False)
                    icon = "🔲" if is_stub else "✅"
                    st.write(f"{icon} **Step {meta.get('number', '?')}: {meta.get('name', node_name)}** — done")

        status_box.update(label="✅ Pipeline complete!", state="complete")

    # Ensure all shown as complete
    render_pipeline({m["node"]: "complete" for m in STEP_META}, pipeline_container)

    st.divider()

    # ── Results ───────────────────────────────────────────────────────────────
    st.subheader("📋 Results")

    report_md = final_state.get("final_report", "")
    rule_results_raw = final_state.get("rule_results", {})
    raw_records = rule_results_raw.get("records", []) if isinstance(rule_results_raw, dict) else []

    if report_md:
        # Summary metrics
        df = parse_markdown_table(report_md)
        if df is not None and not df.empty:
            result_col = next((c for c in df.columns if "result" in c.lower()), None)
            total = len(df)
            passes = fails = pending = na = 0
            if result_col:
                passes  = df[result_col].str.strip().str.lower().eq("pass").sum()
                fails   = df[result_col].str.strip().str.lower().eq("fail").sum()
                pending = df[result_col].str.strip().str.lower().eq("pending").sum()
                na      = df[result_col].str.strip().str.lower().eq("n/a").sum()

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Rules Tested", total)
            m2.metric("✅ Pass",    int(passes))
            m3.metric("❌ Fail",    int(fails))
            m4.metric("⏳ Pending", int(pending))
            m5.metric("⬜ N/A",     int(na))

            if na == total and total > 0:
                st.warning(
                    "⚠️ All results are N/A. This usually means the column mappings from Step 3 "
                    "could not match sample columns to source columns. Check the **Column Mappings** "
                    "expander below — if source columns are missing, try uploading a regulatory PDF "
                    "to give the LLM more context, or verify the source file has the expected columns."
                )

            # ── Match Resolution Insights ──────────────────────────────────
            if raw_records:
                st.markdown("---")
                st.markdown("#### Match Resolution")

                # Count by match method
                method_counts = {}
                for rec in raw_records:
                    mm = rec.get("match_method", "direct")
                    method_counts[mm] = method_counts.get(mm, 0) + 1

                METHOD_LABELS = {
                    "direct": ("Direct Match", "Exact column name found in source", "#22c55e"),
                    "alias": ("Alias Match", "Resolved via variable reference (e.g. MTM -> USD Market Value)", "#3b82f6"),
                    "calculated": ("Calculated", "Computed from component columns in source", "#8b5cf6"),
                    "calculation": ("Transformation", "Source column found; formula applied before comparison", "#0ea5e9"),
                    "static": ("Static Value", "Compared against a hardcoded/constant value", "#6b7280"),
                    "ocr": ("OCR Extraction", "Value extracted from image via OCR", "#f59e0b"),
                    "not_available": ("Not Available", "No source column exists for this attribute", "#9ca3af"),
                    "unresolved": ("Unresolved", "Could not find or compute a source value", "#ef4444"),
                }

                # Render method summary as colored badges with counts
                badge_cols = st.columns(min(len(method_counts), 4))
                for idx, (method, count) in enumerate(sorted(method_counts.items(), key=lambda x: -x[1])):
                    label, description, color = METHOD_LABELS.get(method, (method.title(), "", "#6b7280"))
                    col = badge_cols[idx % len(badge_cols)]
                    col.markdown(
                        f'<div style="background:{color}; color:white; padding:12px 16px; '
                        f'border-radius:8px; margin-bottom:8px; text-align:center;">'
                        f'<div style="font-size:1.8rem; font-weight:700;">{count}</div>'
                        f'<div style="font-size:0.85rem; font-weight:600;">{label}</div>'
                        f'<div style="font-size:0.7rem; opacity:0.85;">{description}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # Detailed match justification per attribute (deduplicated)
                with st.expander("🔍 Match Justification Details", expanded=False):
                    seen_attrs = set()
                    justification_rows = []
                    for rec in raw_records:
                        attr = rec.get("attribute", "")
                        if attr in seen_attrs:
                            continue
                        seen_attrs.add(attr)
                        mm = rec.get("match_method", "direct")
                        label, _, _ = METHOD_LABELS.get(mm, (mm.title(), "", ""))
                        justification_rows.append({
                            "Sample Column": attr,
                            "Source Column": rec.get("source_column", "N/A"),
                            "Match Method": label,
                            "Justification": rec.get("match_detail", ""),
                        })
                    if justification_rows:
                        st.dataframe(pd.DataFrame(justification_rows), hide_index=True, use_container_width=True)

                # Failures deep-dive
                fail_records = [r for r in raw_records if r.get("result") == "Fail"]
                if fail_records:
                    with st.expander(f"❌ Failure Analysis ({len(fail_records)} failures)", expanded=False):
                        for rec in fail_records:
                            mm = rec.get("match_method", "direct")
                            label, _, color = METHOD_LABELS.get(mm, (mm.title(), "", "#6b7280"))
                            st.markdown(
                                f'**{rec.get("record_id", "?")}** · `{rec.get("attribute", "?")}` '
                                f'<span class="match-badge" style="background:{color}">{label}</span>',
                                unsafe_allow_html=True,
                            )
                            c1, c2, c3 = st.columns(3)
                            c1.markdown(f"**Reported:** `{rec.get('reported_value', 'N/A')}`")
                            c2.markdown(f"**Source:** `{rec.get('source_value', 'N/A')}`")
                            c3.markdown(f"**Variance:** `{rec.get('variance', 'N/A')}`")
                            st.caption(f"**Why:** {rec.get('match_detail', '')}  \n**Analysis:** {rec.get('variance_analysis', '')}")
                            st.markdown("---")

                st.markdown("---")

            display_df = style_results_df(df.copy())
            st.dataframe(display_df, hide_index=True, use_container_width=True)
        else:
            st.markdown(report_md)

        st.download_button(
            "⬇️ Download Report (Markdown)",
            data=report_md,
            file_name=f"GS_DQ_Report_{product}.md",
            mime="text/markdown",
        )

    # ── Column Mappings ───────────────────────────────────────────────────────
    mappings = final_state.get("column_mappings", {})
    if mappings:
        with st.expander("🔗 Column Mappings extracted (Step 3)", expanded=False):
            join_key = mappings.get("join_key", {})
            if join_key:
                st.markdown(f"**Join Key:** `{join_key.get('sample_column')}` → `{join_key.get('source_column')}`")
                if join_key.get("notes"):
                    st.caption(join_key["notes"])
            mapping_list = mappings.get("mappings", [])
            if mapping_list:
                st.dataframe(pd.DataFrame(mapping_list), hide_index=True)
            if mappings.get("notes"):
                st.info(mappings["notes"])

    # ── OCR Results (KYC / image source) ─────────────────────────────────────
    ocr_results = final_state.get("ocr_results", [])
    if ocr_results:
        with st.expander(f"📷 OCR Extracted Values (Step 1) — {len(ocr_results)} record(s)", expanded=False):
            for r in ocr_results:
                rid = r.get("record_identifier", {})
                st.markdown(f"**Record:** `{rid.get('value', '?')}`  —  status: `{r.get('status', '?')}`")
                attrs = r.get("extracted_attributes", [])
                if attrs:
                    st.dataframe(pd.DataFrame(attrs), hide_index=True)
                errors = r.get("errors", [])
                if errors:
                    st.error("  \n".join(errors))
                st.divider()

    # ── Per-step debug panels ─────────────────────────────────────────────────
    st.divider()
    st.subheader("🔍 Step-by-Step Outputs")

    for meta in STEP_META:
        node = meta["node"]
        output = step_outputs.get(node, {})
        stub_tag = " 🔲 Stub" if meta.get("stub") else ""
        with st.expander(
            f"Step {meta['number']}: {meta['name']}{stub_tag} — `{meta['handler']}`",
            expanded=False,
        ):
            st.caption(meta["description"])
            if output:
                st.json(output)
            else:
                st.info("No output captured.")
