"""
Generate synthetic test data for MTM Calculation Verification testing.

Purpose:
    This creates two paired Excel files that test whether the AI system can:
    1. Read the reference PDF to learn the MTM calculation formula
    2. Extract raw component variables (Shares, Price, FX Rate) from the source evidence
    3. Apply the formula: MTM (USD) = Shares × Local Market Price × FX Rate to USD
    4. Compare the calculated MTM against the reported MTM value
    5. Correctly flag Pass (match) and Fail (variance) cases

File 1 — Sample Summary (reported values):
    "Loan MTM Sample Summary_calculation_test.xlsx"
    Contains only the final MTM value that was reported to the regulator.
    NO component variables are present — the system cannot do a direct extraction.

File 2 — Source Evidence (calculation inputs):
    "Loan MTM Source Evidence_calculation_test.xlsx"
    Contains Shares, Local Market Price, Currency, FX Rate to USD.
    Does NOT contain a pre-computed USD Market Value column.
    The system must compute MTM = Shares × Local Market Price × FX Rate to USD
    and compare against the reported MTM in File 1.

Test Design (10 records):
    Records C001–C006: USD-denominated loans (FX Rate = 1.0)
        C001–C004: PASS — calculated MTM matches reported MTM exactly
        C005:      FAIL — reported MTM is inflated (~25% over-stated); source price
                          would yield 95,509.00 but reporter used a stale/wrong price
        C006:      FAIL — reporter used wrong notional; source quantity × price gives
                          173,361.00 but 200,000.00 was reported

    Records C007–C010: EUR-denominated loans (FX Rate ≈ 1.08 EUR/USD)
        C007–C008: PASS — calculated MTM (Shares × EUR Price × FX Rate) matches
        C009:      FAIL — reporter forgot to apply FX conversion; used local EUR amount
                          directly instead of converting to USD (common real-world error)
        C010:      FAIL — reporter forgot to apply FX conversion; same class of error
                          as C009 but on a different position
"""

import pandas as pd
from datetime import date

# ── Test records ──────────────────────────────────────────────────────────────

RECORDS = [
    # (loan_id, rpID, rpName, shares, local_price, currency, fx_rate, reported_mtm, pass_fail, error_type)
    # USD loans — Pass
    ("LOAN-C001", 1633001, "Thrivent Financial", 100_000, 0.916200, "USD", 1.000000, 91_620.00,     "Pass", None),
    ("LOAN-C002", 1633001, "Thrivent Financial", 200_000, 1.124822, "USD", 1.000000, 224_964.40,    "Pass", None),
    ("LOAN-C003", 1633001, "Thrivent Financial", 250_000, 1.072779, "USD", 1.000000, 268_194.75,    "Pass", None),
    ("LOAN-C004", 1633001, "Thrivent Financial", 500_000, 1.029237, "USD", 1.000000, 514_618.50,    "Pass", None),

    # USD loans — Fail
    # C005: Source has 125,000 shares @ 0.764072 → correct MTM = 95,509.00
    #       Reported MTM = 119,386.25 (reporter applied a stale price of ~0.955090)
    ("LOAN-C005", 1633001, "Thrivent Financial", 125_000, 0.764072, "USD", 1.000000, 119_386.25,    "Fail", "Stale/wrong price used — reported MTM overstated by ~25%"),

    # C006: Source has 200,000 shares @ 0.866805 → correct MTM = 173,361.00
    #       Reported MTM = 200,000.00 (reporter used incorrect notional/round lot)
    ("LOAN-C006", 1633001, "Thrivent Financial", 200_000, 0.866805, "USD", 1.000000, 200_000.00,    "Fail", "Wrong notional applied — reported MTM overstated by ~26,639"),

    # EUR loans — Pass (FX Rate = 1.08 EUR/USD)
    # C007: 100,000 shares × 0.9500 EUR × 1.08 = 102,600.00 USD
    ("LOAN-C007", 1966810, "PIMCO Fixed Income", 100_000, 0.950000, "EUR", 1.080000, 102_600.00,    "Pass", None),

    # C008: 200,000 shares × 1.0500 EUR × 1.08 = 226,800.00 USD
    ("LOAN-C008", 1966810, "PIMCO Fixed Income", 200_000, 1.050000, "EUR", 1.080000, 226_800.00,    "Pass", None),

    # EUR loans — Fail (FX conversion not applied)
    # C009: 150,000 × 0.8800 EUR × 1.08 = 142,560.00 USD (correct)
    #       Reported = 132,000.00  (reporter computed 150,000 × 0.88 = 132,000, skipping FX)
    ("LOAN-C009", 1966810, "PIMCO Fixed Income", 150_000, 0.880000, "EUR", 1.080000, 132_000.00,    "Fail", "FX conversion omitted — reporter used local EUR amount as USD directly"),

    # C010: 100,000 × 1.1500 EUR × 1.08 = 124,200.00 USD (correct)
    #       Reported = 115,000.00  (reporter computed 100,000 × 1.15 = 115,000, skipping FX)
    ("LOAN-C010", 1966810, "PIMCO Fixed Income", 100_000, 1.150000, "EUR", 1.080000, 115_000.00,    "Fail", "FX conversion omitted — reporter used local EUR amount as USD directly"),
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
    """
    File 1: Loan MTM Sample Summary — reported MTM values only.
    The AI must validate these MTM values by computing them from File 2.
    """
    rows = []
    for i, (loan_id, rp_id, rp_name, shares, local_price, ccy, fx_rate,
             reported_mtm, pass_fail, error_type) in enumerate(RECORDS, start=1):
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
    File 2: Loan Activity Report — raw calculation inputs.
    No pre-computed USD Market Value — the AI must calculate:
        MTM (USD) = Shares × Local Market Price × FX Rate to USD
    """
    rows = []
    for loan_id, rp_id, rp_name, shares, local_price, ccy, fx_rate, \
            reported_mtm, pass_fail, error_type in RECORDS:
        sec_id, sec_name = SECURITY_INFO[loan_id]
        rows.append({
            "Account Number":       ACCOUNT_NUMBERS[loan_id],
            "Account":              rp_name,
            "Loan Reference Number": loan_id,
            "Broker ID":            BROKER_IDS[loan_id],
            "Security ID":          sec_id,
            "Security Name":        sec_name,
            "Shares":               shares,
            "Local Market Price":   local_price,
            # NOTE: USD Market Value is intentionally ABSENT.
            # The system must compute it as: Shares × Local Market Price × FX Rate to USD
            "Currency":             ccy,
            "FX Rate to USD":       fx_rate,
            "Country":              "US" if ccy == "USD" else "DE",
            "CC":                   ccy,
        })
    return pd.DataFrame(rows)


def build_testing_attributes() -> pd.DataFrame:
    """Sheet 2 listing the attributes under test."""
    return pd.DataFrame({
        "testing attributes": ["", "MTM", "Counterparty", "CobDate"]
    })


def build_ground_truth() -> pd.DataFrame:
    """
    Developer reference sheet (not used by the AI system).
    Documents the expected outcome for each test record.
    """
    rows = []
    for i, (loan_id, rp_id, rp_name, shares, local_price, ccy, fx_rate,
             reported_mtm, pass_fail, error_type) in enumerate(RECORDS, start=1):
        correct_mtm = round(shares * local_price * fx_rate, 2)
        variance = round(reported_mtm - correct_mtm, 2)
        rows.append({
            "Sample":           i,
            "SourceRefID":      loan_id,
            "Shares":           shares,
            "Local Market Price": local_price,
            "Currency":         ccy,
            "FX Rate to USD":   fx_rate,
            "Correct MTM (USD)": correct_mtm,
            "Reported MTM (USD)": reported_mtm,
            "Variance":         variance,
            "Expected Result":  pass_fail,
            "Error Description": error_type or "—",
        })
    return pd.DataFrame(rows)


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
    ground_truth_df = build_ground_truth()

    with pd.ExcelWriter(source_path, engine="openpyxl") as writer:
        # Row 0-3: header block (mirrors the Loan Activity Report format)
        header_rows = pd.DataFrame({
            "Loan Activity Report": [
                "Goldman Sachs Agency Lending",
                "Loan Detail and collateralization report",
                f"as of {COB_DATE.strftime('%m/%d/%Y')}",
                "",
            ]
        })
        header_rows.to_excel(writer, sheet_name="Loan Activity Report", index=False, header=True)
        # Append actual data below header block
        source_df.to_excel(
            writer, sheet_name="Loan Activity Report",
            index=False, header=True, startrow=5
        )
        # Ground truth on a separate hidden sheet (reference only)
        ground_truth_df.to_excel(writer, sheet_name="Ground Truth (Dev Only)", index=False)

    print(f"\nCreated: {source_path}")
    print(source_df.to_string(index=False))

    print("\n── Ground Truth ──────────────────────────────────────────────────────")
    print(ground_truth_df.to_string(index=False))


if __name__ == "__main__":
    main()
