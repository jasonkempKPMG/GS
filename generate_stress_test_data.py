"""
Generate synthetic stress-test Excel files for multi-source trade validation.

Creates 6 files:
1. Stress_Sample_Summary.xlsx   — 5 trade records (reported values, some intentionally wrong)
2. Trade_Confirmations.xlsx     — Main trade details with DIFFERENT column names
3. Market_Prices.xlsx           — 18 rows, multiple securities/dates, lookup by ISIN+date
4. FX_Rates.xlsx                — 14 rows, multiple currency pairs/dates, filtered lookup
5. Collateral_Positions.xlsx    — Posted collateral per trade + distractors
6. Interest_Accruals.xlsx       — Rate schedules per trade + distractors

Intentional errors (8 across 5 trades):
  #1  Trade 2 (EUR)  End_Date             off by 1 day
  #2  Trade 3 (USD)  Notional_USD         wrong FX rate used (500,250,000 vs 500,000,000)
  #3  Trade 1 (JPY)  Counterparty         name mismatch ("Goldman Sachs Japan" vs "...Co., Ltd.")
  #4  Trade 4 (GBP)  Price                stale price (wrong date: 96.81 vs 96.345)
  #5  Trade 5 (CHF)  Accrued_Interest     wrong day count (365 vs 360)
  #6  Trade 2 (EUR)  Collateral_Value_USD unexplained variance
  #7  Trade 3 (USD)  Coupon_Rate          wrong value (1.5 vs 1.625)
  #8  Trade 1 (JPY)  Maturity_Date        off by 1 month
"""

import pandas as pd
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── FX Rates (ground truth) ─────────────────────────────────────────────────
FX = {
    ("JPY", "2024-05-09"): 0.006450,
    ("EUR", "2024-06-12"): 1.0850,
    ("USD", "2024-07-01"): 1.0000,
    ("GBP", "2024-08-05"): 1.2750,
    ("CHF", "2024-09-02"): 1.1350,
}

# ── Trade ground truth ───────────────────────────────────────────────────────
TRADES = [
    {  # Trade 1 — JPY Repo
        "id": "REPO-2024-00101",
        "cp_source": "Goldman Sachs Japan Co., Ltd.",
        "cp_sample": "Goldman Sachs Japan",  # ERROR #3
        "trade_date": "2024-05-09",
        "start_date": "2024-05-15",
        "end_date": "2024-12-09",
        "ccy": "JPY",
        "direction": "Borrow",
        "notional": 45_000_000_000,
        "rate": 0.0000,
        "margin": 102.00,
        "security": "JGB 2Y #100 1.9% 03/20/2029",
        "isin": "JP1200191939",
        "coupon": 1.9,
        "maturity_source": "2029-03-20",
        "maturity_sample": "04/20/2029",  # ERROR #8 (off by 1 month)
        "settlement": "JSCC",
        "day_count": "ACT/365",
        "accrual_days": 209,
        "accrued_correct": 0.00,  # zero rate
        "price": 107.0050,
        "price_source_name": "TSE",
        "collateral_local": 46_800_000_000,
        "collateral_ccy": "JPY",
    },
    {  # Trade 2 — EUR Bond Repo
        "id": "REPO-2024-00102",
        "cp_source": "Deutsche Bank AG",
        "cp_sample": "Deutsche Bank AG",
        "trade_date": "2024-06-12",
        "start_date": "2024-06-14",
        "end_date": "2024-09-14",
        "end_date_sample": "09/15/2024",  # ERROR #1 (off by 1 day)
        "ccy": "EUR",
        "direction": "Lend",
        "notional": 250_000_000,
        "rate": 3.2500,
        "margin": 105.00,
        "security": "DBR 0.5% 02/15/2028",
        "isin": "DE0001102481",
        "coupon": 0.5,
        "maturity_source": "2028-02-15",
        "settlement": "Euroclear",
        "day_count": "ACT/360",
        "accrual_days": 92,
        "accrued_correct": round(250_000_000 * 3.25 / 100 * 92 / 360, 2),
        "price": 99.2300,
        "price_source_name": "Eurex",
        "collateral_local": 263_250_000,
        "collateral_ccy": "EUR",
        "collateral_usd_sample": 283_500_000.00,  # ERROR #6 (correct: 285,626,250)
    },
    {  # Trade 3 — USD Treasury Repo
        "id": "REPO-2024-00103",
        "cp_source": "JP Morgan Securities LLC",
        "cp_sample": "JP Morgan Securities LLC",
        "trade_date": "2024-07-01",
        "start_date": "2024-07-03",
        "end_date": "2024-10-03",
        "ccy": "USD",
        "direction": "Borrow",
        "notional": 500_000_000,
        "notional_usd_sample": 500_250_000.00,  # ERROR #2 (correct: 500,000,000)
        "rate": 5.3750,
        "margin": 100.00,
        "security": "UST 1.625% 05/15/2031",
        "isin": "US91282CCB46",
        "coupon_source": 1.625,
        "coupon_sample": 1.5,  # ERROR #7
        "maturity_source": "2031-05-15",
        "settlement": "Fedwire",
        "day_count": "ACT/360",
        "accrual_days": 92,
        "accrued_correct": round(500_000_000 * 5.375 / 100 * 92 / 360, 2),
        "price": 98.7500,
        "price_source_name": "TRACE",
        "collateral_local": 500_000_000,
        "collateral_ccy": "USD",
    },
    {  # Trade 4 — GBP Gilt Repo
        "id": "REPO-2024-00104",
        "cp_source": "Barclays Capital Securities Ltd",
        "cp_sample": "Barclays Capital Securities Ltd",
        "trade_date": "2024-08-05",
        "start_date": "2024-08-07",
        "end_date": "2024-11-07",
        "ccy": "GBP",
        "direction": "Lend",
        "notional": 150_000_000,
        "rate": 4.7500,
        "margin": 103.00,
        "security": "UKT 0.875% 10/22/2029",
        "isin": "GB00BKPSLZ79",
        "coupon": 0.875,
        "maturity_source": "2029-10-22",
        "settlement": "CREST",
        "day_count": "ACT/365",
        "accrual_days": 92,
        "accrued_correct": round(150_000_000 * 4.75 / 100 * 92 / 365, 2),
        "price_correct": 96.3450,  # correct (trade date 2024-08-05)
        "price_sample": 96.8100,   # ERROR #4 (stale, from 2024-08-02)
        "price_source_name": "LSE",
        "collateral_local": 155_000_000,
        "collateral_ccy": "GBP",
    },
    {  # Trade 5 — CHF Bond Repo (zero coupon)
        "id": "REPO-2024-00105",
        "cp_source": "UBS AG Zurich",
        "cp_sample": "UBS AG Zurich",
        "trade_date": "2024-09-02",
        "start_date": "2024-09-04",
        "end_date": "2024-12-04",
        "ccy": "CHF",
        "direction": "Borrow",
        "notional": 100_000_000,
        "rate": 1.5000,
        "margin": 101.50,
        "security": "SWISS 0% 06/22/2030",
        "isin": "CH0224397163",
        "coupon": 0.0,  # zero coupon edge case
        "maturity_source": "2030-06-22",
        "settlement": "SIX SIS",
        "day_count": "ACT/360",
        "accrual_days": 91,
        "accrued_correct": round(100_000_000 * 1.5 / 100 * 91 / 360, 2),  # 379,166.67
        "accrued_sample": round(100_000_000 * 1.5 / 100 * 91 / 365, 2),   # ERROR #5 (373,972.60)
        "price": 94.1500,
        "price_source_name": "SIX",
        "collateral_local": 101_500_000,
        "collateral_ccy": "CHF",
    },
]


def _notional_usd(t):
    """Correct Notional_USD for a trade."""
    return round(t["notional"] * FX[(t["ccy"], t["trade_date"])], 2)


def _collateral_usd(t):
    """Correct Collateral_Amount_USD for a trade."""
    return round(t["collateral_local"] * FX[(t["ccy"], t["trade_date"])], 2)


def _margin_excess(t):
    """Correct Margin_Excess_Deficit = Collateral_USD - Notional_USD."""
    return round(_collateral_usd(t) - _notional_usd(t), 2)


def _sample_date(iso_date):
    """Convert YYYY-MM-DD to MM/DD/YYYY for sample summary."""
    y, m, d = iso_date.split("-")
    return f"{int(m)}/{int(d)}/{y}"


# ── File generators ──────────────────────────────────────────────────────────

def create_sample_summary():
    """Stress_Sample_Summary.xlsx — 5 trades, 22 columns, 8 intentional errors."""
    rows = []
    for t in TRADES:
        # Resolve per-trade overrides for error injection
        end_date = t.get("end_date_sample", _sample_date(t["end_date"]))
        counterparty = t.get("cp_sample", t["cp_source"])
        notional_usd = t.get("notional_usd_sample", _notional_usd(t))
        coupon = t.get("coupon_sample", t.get("coupon_source", t.get("coupon")))
        if "maturity_sample" in t:
            maturity = t["maturity_sample"]  # already in sample format
        else:
            maturity = _sample_date(t["maturity_source"])
        price = t.get("price_sample", t.get("price_correct", t.get("price")))
        accrued = t.get("accrued_sample", t["accrued_correct"])
        collateral_usd = t.get("collateral_usd_sample", _collateral_usd(t))
        margin = round(collateral_usd - notional_usd, 2)

        rows.append({
            "Trade_ID": t["id"],
            "Counterparty": counterparty,
            "Trade_Date": _sample_date(t["trade_date"]),
            "Start_Date": _sample_date(t["start_date"]),
            "End_Date": end_date,
            "Currency": t["ccy"],
            "Direction": t["direction"],
            "Notional_Amount": t["notional"],
            "Notional_USD": notional_usd,
            "Rate_Pct": t["rate"],
            "Price": price,
            "Price_Source_Name": t["price_source_name"],
            "Accrued_Interest": accrued,
            "Collateral_Value_USD": collateral_usd,
            "Margin_Excess_Deficit": margin,
            "Security_Name": t["security"],
            "ISIN": t["isin"],
            "Coupon_Rate": coupon,
            "Maturity_Date": maturity,
            "Settlement_Type": t["settlement"],
            "Day_Count": t["day_count"],
            "Quantity": t["notional"],
        })

    df = pd.DataFrame(rows)

    attrs = [
        "Counterparty", "Trade_Date", "Start_Date", "End_Date",
        "Currency", "Direction", "Notional_Amount", "Notional_USD",
        "Rate_Pct", "Price", "Price_Source_Name", "Accrued_Interest",
        "Collateral_Value_USD", "Margin_Excess_Deficit",
        "Security_Name", "ISIN", "Coupon_Rate", "Maturity_Date",
        "Settlement_Type", "Day_Count", "Quantity",
    ]
    attrs_df = pd.DataFrame({"Attributes to test": attrs})

    path = os.path.join(OUTPUT_DIR, "Stress_Sample_Summary.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sample Data", index=False)
        attrs_df.to_excel(writer, sheet_name="Attributes to test", index=False)
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_trade_confirmations():
    """Trade_Confirmations.xlsx — Date format: 'Month DD, YYYY'. Mismatched column names."""
    from datetime import datetime

    def _long_date(iso):
        dt = datetime.strptime(iso, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")

    # 5 real trades + 3 distractors
    rows = []
    for t in TRADES:
        rows.append({
            "Ref_Number": t["id"],
            "CP_Legal_Name": t["cp_source"],
            "Effective_Date": _long_date(t["trade_date"]),
            "Value_Date": _long_date(t["start_date"]),
            "Termination_Date": _long_date(t["end_date"]),
            "Trade_Ccy": t["ccy"],
            "Borrow_Lend": t["direction"],
            "Principal_Balance": t["notional"],
            "Repo_Rate": t["rate"],
            "Margin_Ratio": t.get("margin", 100.0),
            "Instrument_Description": t["security"],
            "ISIN_Code": t["isin"],
            "Coupon_Pct": t.get("coupon_source", t.get("coupon")),
            "Bond_Maturity": _long_date(t["maturity_source"]),
            "Settlement_Method": t["settlement"],
            "Accrued_Int_Local": t["accrued_correct"],
        })

    # Distractor rows
    distractors = [
        ("REPO-2024-00201", "Citibank NA", "2024-03-15", "2024-03-18", "2024-06-18",
         "USD", "Lend", 200_000_000, 5.25, 102.0, "UST 2.5% 01/31/2027",
         "US91282CDB87", 2.5, "2027-01-31", "Fedwire", 1_250_000.00),
        ("REPO-2024-00202", "HSBC Securities Inc", "2024-04-22", "2024-04-24", "2024-07-24",
         "EUR", "Borrow", 175_000_000, 3.0, 104.0, "DBR 1.0% 08/15/2027",
         "DE0001102440", 1.0, "2027-08-15", "Euroclear", 750_000.00),
        ("REPO-2024-00203", "Nomura Securities Intl", "2024-05-01", "2024-05-06", "2024-08-06",
         "JPY", "Borrow", 30_000_000_000, 0.05, 101.0, "JGB 5Y #159 0.1% 12/20/2028",
         "JP1051591LG2", 0.1, "2028-12-20", "JSCC", 15_000_000.00),
    ]
    for d in distractors:
        rows.append({
            "Ref_Number": d[0], "CP_Legal_Name": d[1],
            "Effective_Date": _long_date(d[2]), "Value_Date": _long_date(d[3]),
            "Termination_Date": _long_date(d[4]), "Trade_Ccy": d[5],
            "Borrow_Lend": d[6], "Principal_Balance": d[7],
            "Repo_Rate": d[8], "Margin_Ratio": d[9],
            "Instrument_Description": d[10], "ISIN_Code": d[11],
            "Coupon_Pct": d[12], "Bond_Maturity": _long_date(d[13]),
            "Settlement_Method": d[14], "Accrued_Int_Local": d[15],
        })

    df = pd.DataFrame(rows)
    path = os.path.join(OUTPUT_DIR, "Trade_Confirmations.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_market_prices():
    """Market_Prices.xlsx — Date format: YYYY-MM-DD. Multiple dates per ISIN."""
    rows = [
        # Trade 1 — JP1200191939 (3 dates)
        ("JP1200191939", "2024-05-08", 106.8500, "JPY", "TSE", 106.82, 106.88),
        ("JP1200191939", "2024-05-09", 107.0050, "JPY", "TSE", 106.98, 107.03),  # correct
        ("JP1200191939", "2024-05-10", 107.1200, "JPY", "TSE", 107.09, 107.15),
        # Trade 2 — DE0001102481 (2 dates)
        ("DE0001102481", "2024-06-11", 99.1800, "EUR", "Eurex", 99.15, 99.21),
        ("DE0001102481", "2024-06-12", 99.2300, "EUR", "Eurex", 99.20, 99.26),  # correct
        # Trade 3 — US91282CCB46 (2 dates)
        ("US91282CCB46", "2024-06-28", 98.6800, "USD", "TRACE", 98.65, 98.71),
        ("US91282CCB46", "2024-07-01", 98.7500, "USD", "TRACE", 98.72, 98.78),  # correct
        # Trade 4 — GB00BKPSLZ79 (3 dates — stale price trap)
        ("GB00BKPSLZ79", "2024-08-02", 96.8100, "GBP", "LSE", 96.78, 96.84),   # stale (ERROR #4 uses this)
        ("GB00BKPSLZ79", "2024-08-05", 96.3450, "GBP", "LSE", 96.32, 96.37),   # correct
        ("GB00BKPSLZ79", "2024-08-06", 96.2900, "GBP", "LSE", 96.26, 96.32),
        # Trade 5 — CH0224397163 (2 dates)
        ("CH0224397163", "2024-09-02", 94.1500, "CHF", "SIX", 94.12, 94.18),    # correct
        ("CH0224397163", "2024-09-03", 94.2000, "CHF", "SIX", 94.17, 94.23),
        # Distractor ISINs
        ("US912810SV17", "2024-07-01", 101.2500, "USD", "TRACE", 101.22, 101.28),
        ("FR0014006OJ7", "2024-06-12", 98.5000, "EUR", "Euronext", 98.47, 98.53),
        ("IT0005542797", "2024-06-12", 97.3500, "EUR", "MTS", 97.32, 97.38),
        ("AU0000XCLWP3", "2024-08-05", 102.7500, "AUD", "ASX", 102.72, 102.78),
        ("CA135087N777", "2024-07-01", 99.8750, "CAD", "TMX", 99.845, 99.905),
        ("XS2530506974", "2024-09-02", 95.6250, "EUR", "Eurex", 95.595, 95.655),
    ]

    df = pd.DataFrame(rows, columns=[
        "Instrument_ISIN", "Valuation_Date", "Close_Px", "Px_Ccy",
        "Price_Source", "Bid_Px", "Ask_Px",
    ])
    path = os.path.join(OUTPUT_DIR, "Market_Prices.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_fx_rates():
    """FX_Rates.xlsx — Date format: DD-Mon-YYYY. Multiple pairs per date."""
    from datetime import datetime

    def _dd_mon_yyyy(iso):
        dt = datetime.strptime(iso, "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")

    rows = [
        # 09-May-2024
        ("09-May-2024", "JPY", "USD", 0.006450, "Bloomberg"),
        ("09-May-2024", "EUR", "USD", 1.0780, "Bloomberg"),
        ("09-May-2024", "GBP", "USD", 1.2530, "Bloomberg"),
        # 12-Jun-2024
        ("12-Jun-2024", "EUR", "USD", 1.0850, "Bloomberg"),
        ("12-Jun-2024", "JPY", "USD", 0.006380, "Bloomberg"),
        ("12-Jun-2024", "GBP", "USD", 1.2710, "Bloomberg"),
        # 01-Jul-2024
        ("01-Jul-2024", "USD", "USD", 1.0000, "Bloomberg"),
        ("01-Jul-2024", "EUR", "USD", 1.0820, "Bloomberg"),
        # 05-Aug-2024
        ("05-Aug-2024", "GBP", "USD", 1.2750, "Bloomberg"),
        ("05-Aug-2024", "EUR", "USD", 1.0910, "Bloomberg"),
        ("05-Aug-2024", "CHF", "USD", 1.1400, "Bloomberg"),
        # 02-Sep-2024
        ("02-Sep-2024", "CHF", "USD", 1.1350, "Bloomberg"),
        ("02-Sep-2024", "JPY", "USD", 0.006900, "Bloomberg"),
        ("02-Sep-2024", "GBP", "USD", 1.2680, "Bloomberg"),
    ]

    df = pd.DataFrame(rows, columns=[
        "Rate_Date", "Base_Ccy", "Quote_Ccy", "Spot_Rate", "Rate_Source",
    ])
    path = os.path.join(OUTPUT_DIR, "FX_Rates.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_collateral_positions():
    """Collateral_Positions.xlsx — Date format: DD/MM/YYYY (ambiguous!)."""

    def _dd_mm_yyyy(iso):
        y, m, d = iso.split("-")
        return f"{d}/{m}/{y}"

    rows = []
    for t in TRADES:
        rows.append({
            "Reference_ID": t["id"],
            "Collateral_Type": "Government Bond",
            "Collateral_Ccy": t["collateral_ccy"],
            "Collateral_Amount_Local": t["collateral_local"],
            "Collateral_Amount_USD": _collateral_usd(t),
            "Posting_Date": _dd_mm_yyyy(t["start_date"]),
        })

    # Distractors
    rows.append({
        "Reference_ID": "REPO-2024-00201",
        "Collateral_Type": "Government Bond",
        "Collateral_Ccy": "USD",
        "Collateral_Amount_Local": 204_000_000,
        "Collateral_Amount_USD": 204_000_000.00,
        "Posting_Date": "18/03/2024",
    })
    rows.append({
        "Reference_ID": "REPO-2024-00202",
        "Collateral_Type": "Corporate Bond",
        "Collateral_Ccy": "EUR",
        "Collateral_Amount_Local": 182_000_000,
        "Collateral_Amount_USD": 197_470_000.00,
        "Posting_Date": "24/04/2024",
    })

    df = pd.DataFrame(rows)
    path = os.path.join(OUTPUT_DIR, "Collateral_Positions.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_interest_accruals():
    """Interest_Accruals.xlsx — Date format: YYYYMMDD (no separators)."""

    def _yyyymmdd(iso):
        return iso.replace("-", "")

    rows = []
    for t in TRADES:
        day_base = 365 if "365" in t["day_count"] else 360
        rows.append({
            "Deal_Reference": t["id"],
            "Accrual_Start": _yyyymmdd(t["start_date"]),
            "Accrual_End": _yyyymmdd(t["end_date"]),
            "Day_Count_Convention": t["day_count"],
            "Annual_Rate_Pct": t["rate"],
            "Accrual_Days": t["accrual_days"],
            "Accrued_Amount": t["accrued_correct"],
        })

    # Distractors
    rows.append({
        "Deal_Reference": "REPO-2024-00201",
        "Accrual_Start": "20240318", "Accrual_End": "20240618",
        "Day_Count_Convention": "ACT/360",
        "Annual_Rate_Pct": 5.25, "Accrual_Days": 92,
        "Accrued_Amount": 1_333_333.33,
    })
    rows.append({
        "Deal_Reference": "REPO-2024-00202",
        "Accrual_Start": "20240424", "Accrual_End": "20240724",
        "Day_Count_Convention": "ACT/360",
        "Annual_Rate_Pct": 3.00, "Accrual_Days": 91,
        "Accrued_Amount": 665_277.78,
    })

    df = pd.DataFrame(rows)
    path = os.path.join(OUTPUT_DIR, "Interest_Accruals.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("Generating Stress Test Data (5 trades, 5 source files, 8 errors)")
    print("=" * 70)
    print()
    create_sample_summary()
    print()
    create_trade_confirmations()
    print()
    create_market_prices()
    print()
    create_fx_rates()
    print()
    create_collateral_positions()
    print()
    create_interest_accruals()
    print()
    print("=" * 70)
    print("EXPECTED FAILURES (8):")
    print("=" * 70)
    print("  #1  Trade 2 (EUR)  End_Date             09/15/2024 vs Sep 14 (off by 1 day)")
    print("  #2  Trade 3 (USD)  Notional_USD         500,250,000 vs 500,000,000 (wrong FX)")
    print("  #3  Trade 1 (JPY)  Counterparty         'Goldman Sachs Japan' vs '...Co., Ltd.'")
    print("  #4  Trade 4 (GBP)  Price                96.81 vs 96.345 (stale price)")
    print("  #5  Trade 5 (CHF)  Accrued_Interest     373,972.60 vs 379,166.67 (ACT/365 vs 360)")
    print("  #6  Trade 2 (EUR)  Collateral_Value_USD 283,500,000 vs 285,626,250")
    print("  #7  Trade 3 (USD)  Coupon_Rate          1.5 vs 1.625")
    print("  #8  Trade 1 (JPY)  Maturity_Date        04/20/2029 vs 03/20/2029 (off by 1 month)")
    print()
    print(f"  All other ~102 comparisons should PASS")
    print()
    print("FILES TO UPLOAD:")
    print("  Sample:  Stress_Sample_Summary.xlsx")
    print("  Sources: Trade_Confirmations.xlsx")
    print("           Market_Prices.xlsx")
    print("           FX_Rates.xlsx")
    print("           Collateral_Positions.xlsx")
    print("           Interest_Accruals.xlsx")
