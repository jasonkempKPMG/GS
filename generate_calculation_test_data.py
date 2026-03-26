"""
Generate synthetic test data for MTM Calculation Verification testing.

Purpose:
    Creates two paired Excel files whose reported MTM values cannot be
    validated by simple field-to-field extraction. The AI system must:

    1. Consult the reference PDF to find the MTM calculation formula.
    2. If the formula is not explicitly stated in the PDF, infer it from
       the column names and attributes available in the source evidence.
    3. Apply the discovered formula to compute MTM from components.
    4. Compare the computed MTM against the reported MTM and flag variances.

    The system — not the data — determines what formula to use and which
    records pass or fail.

File 1 — Sample Summary (reported values):
    "Loan MTM Sample Summary_calculation_test.xlsx"
    Contains the final MTM values as reported to the regulator.
    No component variables are present; direct extraction is impossible.

File 2 — Source Evidence (calculation inputs):
    "Loan MTM Source Evidence_calculation_test.xlsx"
    Contains Shares, Local Market Price, Currency, FX Rate to USD.
    No pre-computed USD Market Value column — the system must derive it.
"""

import pandas as pd
from datetime import date

# ── Test records ──────────────────────────────────────────────────────────────
# (loan_id, rpID, rpName, shares, local_price, currency, fx_rate, reported_mtm)
# reported_mtm is the value GS submitted; some match the formula, some do not.
# The model must discover this on its own — no Pass/Fail metadata is embedded.

RECORDS = [
    # USD loans — reported MTM matches Shares × Local Market Price × FX Rate
    ("LOAN-C001", 1633001, "Thrivent Financial", 100_000, 0.916200, "USD", 1.000000, 91_620.00),
    ("LOAN-C002", 1633001, "Thrivent Financial", 200_000, 1.124822, "USD", 1.000000, 224_964.40),
    ("LOAN-C003", 1633001, "Thrivent Financial", 250_000, 1.072779, "USD", 1.000000, 268_194.75),
    ("LOAN-C004", 1633001, "Thrivent Financial", 500_000, 1.029237, "USD", 1.000000, 514_618.50),

    # USD loans — reported MTM does NOT match the formula
    ("LOAN-C005", 1633001, "Thrivent Financial", 125_000, 0.764072, "USD", 1.000000, 119_386.25),
    ("LOAN-C006", 1633001, "Thrivent Financial", 200_000, 0.866805, "USD", 1.000000, 200_000.00),

    # EUR loans — reported MTM matches Shares × Local Market Price × FX Rate
    ("LOAN-C007", 1966810, "PIMCO Fixed Income", 100_000, 0.950000, "EUR", 1.080000, 102_600.00),
    ("LOAN-C008", 1966810, "PIMCO Fixed Income", 200_000, 1.050000, "EUR", 1.080000, 226_800.00),

    # EUR loans — reported MTM does NOT match (FX conversion not applied)
    ("LOAN-C009", 1966810, "PIMCO Fixed Income", 150_000, 0.880000, "EUR", 1.080000, 132_000.00),
    ("LOAN-C010", 1966810, "PIMCO Fixed Income", 100_000, 1.150000, "EUR", 1.080000, 115_000.00),
]

COB_DATE = date(2025, 6, 30)

# Security / CUSIP mapping (synthetic)
SECURITY_INFO = {
    "LOAN-C001": ("05675MC001", "CORP BOND ALPHA 2026"),
    "LOAN-C002": ("05675MC002", "CORP BOND BETA 2027"),
    "LOAN-C003": ("05675MC003", "CORP BOND GAMMA 2026"),
    "LOAN-C004": ("05675MC004", "CORP BOND DELTA 2028"),
    "LOAN-C005": ("05675MC005", "CORP BOND EPSILON 2025"),
    "LOAN-C006": ("05675MC006", "CORP BOND ZETA 2026"),
    "LOAN-C007": ("05675MC007", "EUR SOVEREIGN 2027"),
    "LOAN-C008": ("05675MC008", "EUR SOVEREIGN 2028"),
    "LOAN-C009": ("05675MC009", "EUR COVERED BOND 2026"),
    "LOAN-C010": ("05675MC010", "EUR COVERED BOND 2027"),
}

BROKER_IDS = {
    "LOAN-C001": "CGB", "LOAN-C002": "BARC", "LOAN-C003": "BARC", "LOAN-C004": "JPMB",
    "LOAN-C005": "WFS",  "LOAN-C006": "BS",   "LOAN-C007": "CGB",  "LOAN-C008": "BARC",
    "LOAN-C009": "JPMB", "LOAN-C010": "WFS",
}

ACCOUNT_NUMBERS = {
    "LOAN-C001": "RF01", "LOAN-C002": "RF02", "LOAN-C003": "RF03", "LOAN-C004": "RF04",
    "LOAN-C005": "RF05", "LOAN-C006": "RF06", "LOAN-C007": "RF07", "LOAN-C008": "RF08",
    "LOAN-C009": "RF09", "LOAN-C010": "RF10",
}


def build_sample_summary() -> pd.DataFrame:
    """File 1: Loan MTM Sample Summary — reported MTM values only."""
    rows = []
    for i, (loan_id, rp_id, rp_name, shares, local_price, ccy, fx_rate,
             reported_mtm) in enumerate(RECORDS, start=1):
        rows.append({
            "Sample":       i,
            "CobDate":      COB_DATE,
            "rpID":         rp_id,
            "rpName":       rp_name,
            "SourceRefID":  loan_id,
            "mtm":          reported_mtm,
        })
    return pd.DataFrame(rows)


def build_source_evidence() -> pd.DataFrame:
    """
    File 2: Loan Activity Report — raw calculation inputs only.
    USD Market Value is intentionally absent; the system must derive it.
    """
    rows = []
    for loan_id, rp_id, rp_name, shares, local_price, ccy, fx_rate, \
            reported_mtm in RECORDS:
        sec_id, sec_name = SECURITY_INFO[loan_id]
        rows.append({
            "Account Number":        ACCOUNT_NUMBERS[loan_id],
            "Account":               rp_name,
            "Loan Reference Number": loan_id,
            "Broker ID":             BROKER_IDS[loan_id],
            "Security ID":           sec_id,
            "Security Name":         sec_name,
            "Shares":                shares,
            "Local Market Price":    local_price,
            "Currency":              ccy,
            "FX Rate to USD":        fx_rate,
            "Country":               "US" if ccy == "USD" else "DE",
            "CC":                    ccy,
        })
    return pd.DataFrame(rows)


def build_testing_attributes() -> pd.DataFrame:
    """Sheet 2 listing the attributes under test."""
    return pd.DataFrame({
        "testing attributes": ["", "MTM", "Counterparty", "CobDate"]
    })


def main():
    sample_path = "Loan MTM Sample Summary_calculation_test.xlsx"
    source_path = "Loan MTM Source Evidence_calculation_test.xlsx"

    # ── File 1: Sample Summary ────────────────────────────────────────────────
    sample_df = build_sample_summary()
    attrs_df = build_testing_attributes()

    with pd.ExcelWriter(sample_path, engine="openpyxl") as writer:
        sample_df.to_excel(writer, sheet_name="Sheet1", index=False)
        attrs_df.to_excel(writer, sheet_name="Sheet2", index=False)

    print(f"Created: {sample_path}")
    print(sample_df.to_string(index=False))

    # ── File 2: Source Evidence ───────────────────────────────────────────────
    source_df = build_source_evidence()

    with pd.ExcelWriter(source_path, engine="openpyxl") as writer:
        header_rows = pd.DataFrame({
            "Loan Activity Report": [
                "Goldman Sachs Agency Lending",
                "Loan Detail and collateralization report",
                f"as of {COB_DATE.strftime('%m/%d/%Y')}",
                "",
            ]
        })
        header_rows.to_excel(writer, sheet_name="Loan Activity Report", index=False, header=True)
        source_df.to_excel(
            writer, sheet_name="Loan Activity Report",
            index=False, header=True, startrow=5
        )

    print(f"\nCreated: {source_path}")
    print(source_df.to_string(index=False))


if __name__ == "__main__":
    main()
