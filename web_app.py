# web_app.py
import streamlit as st
import pandas as pd
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter
from openpyxl.comments import Comment
import os
from pathlib import Path

# Import your modules
from parsers.customs_parser import parse_customs
from parsers.invoice_parser import InvoiceParser
from parsers.bl_parser import BLParser
from matchers.field_matcher import match_line
from models import CustomsLine, InvoiceLine, BLLine

# --- Excel Export Helper ---
def to_excel(df: pd.DataFrame):
    output = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Verification Report"

    headers = df.columns.tolist()
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")

    for row_idx, row in enumerate(df.itertuples(), 2):
        status = row.status_code  # 'ok', 'warn', 'error'
        for col_idx, value in enumerate(row[1:], 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=str(value))

            if status == "ok":
                cell.fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
            elif status == "warn":
                cell.fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
            elif status == "error":
                cell.fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")

            if headers[col_idx - 1] in ["Part#", "Desc", "Origin"]:
                snippet = f"ใบขนฯ: {row.customs_snippet}\nInvoice: {row.invoice_snippet}"
                cell.comment = Comment(snippet[:200] + "...", "SparePart Verify POC")

    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_length + 2, 30)

    wb.save(output)
    return output.getvalue()

# Page config
st.set_page_config(
    page_title="SparePart Verify POC — TRU Automotive",
    page_icon="🔍",
    layout="wide",
)

st.markdown(
    """
    <style>
    .header {text-align: center; color: #004080; margin-bottom: 1rem;}
    .status-ok {color: #155724; background-color: #d4edda; padding: 0.2rem 0.5rem; border-radius: 4px;}
    .status-warn {color: #856404; background-color: #fff3cd; padding: 0.2rem 0.5rem; border-radius: 4px;}
    .status-error {color: #721c24; background-color: #f8d7da; padding: 0.2rem 0.5rem; border-radius: 4px;}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<h1 class="header">🔍 SparePart Verify POC</h1>', unsafe_allow_html=True)
st.markdown('<p style="text-align: center; color: #666;">Verify Customs ↔ Invoice ↔ B/L Consistency | TRU Automotive</p>', unsafe_allow_html=True)
st.divider()

with st.sidebar:
    st.header("ℹ️ Instructions")
    st.markdown("""
    1. Upload **ใบขนฯ**, **Invoice**, and **B/L** (PDF)  
    2. Click **Verify Documents**  
    3. ✅ Green = match, 🟡 yellow = fuzzy, 🔴 red = mismatch  
    4. Double-click any row to see source snippets
    """)

col1, col2, col3 = st.columns(3)
customs_path = col1.file_uploader("📄 ใบขนฯ (Customs Form)", type=["pdf"])
invoice_path = col2.file_uploader("🧾 Invoice", type=["pdf"])
bl_path = col3.file_uploader("📦 B/L", type=["pdf"])

if "results_df" not in st.session_state:
    st.session_state.results_df = None

st.divider()
if st.button("✔️ Verify Documents", type="primary", disabled=not (customs_path and invoice_path and bl_path)):
    try:
        temp_dir = Path("temp_upload")
        temp_dir.mkdir(exist_ok=True)

        customs_file = temp_dir / "customs.pdf"
        invoice_file = temp_dir / "invoice.pdf"
        bl_file = temp_dir / "bl.pdf"

        for f, path in [(customs_path, customs_file), (invoice_path, invoice_file), (bl_path, bl_file)]:
            with open(path, "wb") as out:
                out.write(f.getvalue())

        with st.spinner("🔍 Parsing documents..."):
            customs_lines = parse_customs(str(customs_file))
            invoice_lines = InvoiceParser().parse(str(invoice_file))
            bl_data = BLParser().parse(str(bl_file))

        results = []
        total = min(len(customs_lines), len(invoice_lines))
        for i in range(total):
            c_line = customs_lines[i]
            inv_line = invoice_lines[i] if i < len(invoice_lines) else None

            if not inv_line:
                result = {
                    "Line": c_line.line_no,
                    "Part#": c_line.part_no,
                    "Desc": c_line.desc_en[:30],
                    "Qty": f"{c_line.qty}",
                    "Unit": c_line.unit,
                    "Total EUR": f"{c_line.price_eur:.2f}",
                    "Origin": c_line.origin.value,
                    "Status": "🔴 Missing",
                    "Status Code": "error",
                    "customs_snippet": _format_customs_snippet(c_line),
                    "invoice_snippet": "⚠️ Not found",
                }
            else:
                match_res = match_line(inv_line, c_line)
                status_map = {"ok": "✅ Match", "warn": "🟡 Review", "error": "🔴 Mismatch"}
                status_code = match_res["status"]
                result = {
                    "Line": c_line.line_no,
                    "Part#": c_line.part_no,
                    "Desc": c_line.desc_en[:30],
                    "Qty": f"{c_line.qty}",
                    "Unit": c_line.unit,
                    "Total EUR": f"{c_line.price_eur:.2f}",
                    "Origin": c_line.origin.value,
                    "Status": status_map[status_code],
                    "Status Code": status_code,
                    "customs_snippet": _format_customs_snippet(c_line),
                    "invoice_snippet": _format_invoice_snippet(inv_line),
                }
            results.append(result)

        df = pd.DataFrame(results)
        st.session_state.results_df = df

        ok = (df["Status Code"] == "ok").sum()
        warn = (df["Status Code"] == "warn").sum()
        err = (df["Status Code"] == "error").sum()

        st.subheader("📊 Verification Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("✅ Matched", ok)
        c2.metric("🟡 Warnings", warn)
        c3.metric("🔴 Errors", err)
        c4.metric("📄 Total", len(df))

        if err > 0:
            st.error(f"❗ {err} critical mismatches found — review before customs submission")
        elif warn > 0:
            st.warning(f"⚠️ {warn} items need human review")
        else:
            st.success("✅ All items match — ready for customs filing!")

    except Exception as e:
        st.error(f"❌ Error during verification: {str(e)}")
        st.exception(e)

if st.session_state.results_df is not None:
    df = st.session_state.results_df

    st.divider()
    st.subheader("🔍 Line-by-Line Verification")

    st.dataframe(
        df[["Line", "Part#", "Desc", "Qty", "Unit", "Total EUR", "Origin", "Status"]],
        column_config={
            "Line": st.column_config.NumberColumn("Line", width="small"),
            "Part#": st.column_config.TextColumn("Part#", width="small"),
            "Desc": st.column_config.TextColumn("Description", width="medium"),
            "Qty": st.column_config.TextColumn("Qty", width="small"),
            "Unit": st.column_config.TextColumn("Unit", width="small"),
            "Total EUR": st.column_config.TextColumn("Total EUR", width="small"),
            "Origin": st.column_config.TextColumn("Origin", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
        },
        hide_index=True,
        height=400,
    )

    st.divider()
    st.subheader("📥 Export Report")
    excel_bytes = to_excel(df)
    st.download_button(
        label="📥 Download Excel Report",
        data=excel_bytes,
        file_name=f"verification_report_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    st.divider()
    st.subheader("🔍 View Line Details")
    if not df.empty:
        selected_line_no = st.selectbox(
            "Select line to inspect:",
            options=df["Line"].tolist(),
            format_func=lambda x: f"Line {x}",
        )
        if selected_line_no:
            r = df[df["Line"] == selected_line_no].iloc[0]
            st.markdown(f"### Line {selected_line_no} — `{r['Part#']}`")
            st.markdown(f"**Status**: {r['Status']}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("📄 **ใบขนฯ (Customs)**")
                st.code(r["customs_snippet"], language=None)
            with c2:
                st.markdown("🧾 **Invoice**")
                st.code(r["invoice_snippet"], language=None)

def _format_customs_snippet(line: CustomsLine) -> str:
    return (
        f"Line {line.line_no} | HS: {line.hs_code}\n"
        f"Part: {line.part_no} | Desc: {line.desc_en}\n"
        f"Qty: {line.qty} {line.unit} | Total: EUR {line.price_eur:.2f}\n"
        f"Origin: {line.origin.value} | invno# {line.invoice_no}"
    )

def _format_invoice_snippet(line: InvoiceLine) -> str:
    return (
        f"Line {line.line_no} | Part: {line.part_no}\n"
        f"Desc: {line.desc_en}\n"
        f"Qty: {line.qty} {line.unit} | Unit: {line.unit_price} | Total: {line.total_eur}\n"
        f"Origin: {line.origin_raw}\n"
        f"Delivery: {line.delivery_no}"
    )