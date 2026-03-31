"""
Generate synthetic test Excel files for Phase 2 multi-source trade validation.

Creates 4 files:
1. Trade_Sample_Summary.xlsx — reported values (sample) with some intentional errors
2. Trade_Source_Affirmation.xlsx — Shingensaki Affirmation data (source evidence #1)
3. Trade_Source_PriceCurrency.xlsx — Security price/currency data (source evidence #2)
4. Trade_Source_ForexConversion.xlsx — Forex conversion rates (source evidence #3)

Test scenarios:
- Direct comparisons: Trade Date, Start Date, End Date, Currency, Direction, Agency
- Single-source calculations: values derived from one source
- Cross-source calculations: JPY amounts * forex rate = reported USD amounts
- Intentional failures: some reported values are deliberately wrong
"""

import pandas as pd
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Constants ────────────────────────────────────────────────────────────────
TRADE_REF = "TOK-20240509-006395"
FOREX_RATE_JPY_USD = 0.007063  # JPY to USD rate

# Source values (ground truth from Shingensaki Affirmation)
FACE_JPY = 45_000_000_000
START_AMOUNT_JPY = 44_102_295_112
END_AMOUNT_JPY = 48_201_111_315
REPO_INTEREST_JPY = 8_318_500
START_ALL_IN_PRICE = 107.00503636
END_ALL_IN_PRICE = 161.11962260
MKT_CLOSING_PRICE = 106.81450000

# Computed USD values (correct)
FACE_USD_CORRECT = round(FACE_JPY * FOREX_RATE_JPY_USD, 2)
START_AMOUNT_USD_CORRECT = round(START_AMOUNT_JPY * FOREX_RATE_JPY_USD, 2)
END_AMOUNT_USD_CORRECT = round(END_AMOUNT_JPY * FOREX_RATE_JPY_USD, 2)

# Intentionally WRONG values for failure testing
FACE_USD_WRONG = round(FACE_USD_CORRECT * 1.05, 2)  # 5% too high
END_DATE_WRONG = "12/10/2024"  # Off by one day (should be 12/09/2024)
MKT_CLOSING_PRICE_WRONG = 106.82000000  # Slightly off


def create_sample_summary():
    """
    Sample Summary = reported values. This is what GS reported.
    Single row with many columns. Some values are intentionally wrong.
    """
    data = {
        "Trade_Ref": [TRADE_REF],
        "Account": ["01/290719"],
        "Trade_Date": ["5/9/2024"],
        "Start_Date": ["5/15/2024"],
        "End_Date": [END_DATE_WRONG],               # FAIL: should be 12/09/2024
        "Currency": ["JPY"],
        "Direction": ["US Borrows"],
        "Agency": ["PB"],
        "Repo_Rate_Pct": [0.0000],
        "Required_Margin_Rate": [0],
        "Face_JPY": [FACE_JPY],
        "Start_Amount_JPY": [START_AMOUNT_JPY],
        "End_Amount_JPY": [END_AMOUNT_JPY],
        "Repo_Interest_JPY": [REPO_INTEREST_JPY],
        "Face_USD": [FACE_USD_WRONG],                # FAIL: cross-source calc should catch this
        "Start_Amount_USD": [START_AMOUNT_USD_CORRECT],  # PASS: correct cross-source calc
        "End_Amount_USD": [END_AMOUNT_USD_CORRECT],      # PASS: correct cross-source calc
        "Start_All_In_Price": [START_ALL_IN_PRICE],
        "End_All_In_Price": [END_ALL_IN_PRICE],
        "Mkt_Closing_Price": [MKT_CLOSING_PRICE_WRONG],  # FAIL: slightly off
        "Security": ["JGB2YR #100 1.9% 03/20/2029"],
        "Security_Code": ["JP1200191939"],
        "Coupon": [1.9],
        "Maturity": ["3/20/2029"],
        "Delivery_Mode": ["JSCC"],
        "Transaction_Type": ["Repo"],
        "Quantity": [FACE_JPY],
        "Price_Value": [107.00503636],               # Should match Price_Currency source
        "Price_Currency": ["JPY"],
    }
    df = pd.DataFrame(data)

    # Also create "Attributes to test" tab
    attrs = [
        "Trade_Date", "Start_Date", "End_Date", "Currency", "Direction", "Agency",
        "Face_JPY", "Start_Amount_JPY", "End_Amount_JPY", "Repo_Interest_JPY",
        "Face_USD", "Start_Amount_USD", "End_Amount_USD",
        "Start_All_In_Price", "End_All_In_Price", "Mkt_Closing_Price",
        "Security", "Coupon", "Maturity",
        "Price_Value", "Price_Currency",
    ]
    attrs_df = pd.DataFrame({"Attributes to test": attrs})

    path = os.path.join(OUTPUT_DIR, "Trade_Sample_Summary.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sample Data", index=False)
        attrs_df.to_excel(writer, sheet_name="Attributes to test", index=False)
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")
    print(f"  Attributes to test: {len(attrs)}")
    print(f"  Expected FAILURES: End_Date, Face_USD, Mkt_Closing_Price")


def create_source_affirmation():
    """
    Source Evidence #1: Shingensaki Affirmation data.
    Contains trade details, amounts, prices, security info.
    """
    data = {
        "Trade_Ref": [TRADE_REF],
        "Account": ["01/290719"],
        "GS_Entity": ["Goldman Sachs Japan Co."],
        "Trade_Date": ["May 09, 2024"],         # Different date format than sample
        "Start_Date": ["May 15, 2024"],
        "End_Date": ["December 09, 2024"],       # The CORRECT end date
        "Currency": ["JPY"],
        "Direction": ["US Borrows"],
        "Agency": ["PB"],
        "Repo_Rate_Pct": [0.0000],
        "Required_Margin_Rate": [0],
        "Piece_Number": [1],
        "Face": [FACE_JPY],
        "Start_Amount": [START_AMOUNT_JPY],
        "End_Amount": [END_AMOUNT_JPY],
        "Repo_Interest": [REPO_INTEREST_JPY],
        "Start_All_In_Price": [START_ALL_IN_PRICE],
        "End_All_In_Price": [END_ALL_IN_PRICE],
        "Mkt_Closing_Price": [MKT_CLOSING_PRICE],  # Correct value
        "Security": ["JGB2YR #100 1.9% 03/20/2029"],
        "Security_Code": ["JP1200191939"],
        "Coupon": [1.9],
        "Maturity": ["March 20, 2029"],
        "Delivery_Mode": ["JSCC"],
        "Transaction_Type": ["Repo"],
        "Quantity": [FACE_JPY],
    }
    df = pd.DataFrame(data)
    path = os.path.join(OUTPUT_DIR, "Trade_Source_Affirmation.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_source_price_currency():
    """
    Source Evidence #2: Security price and currency data.
    Columns mirror what was described: CUSIP, GSN, ISIN, Prime_ID,
    Price_Effective_Date, Price_Type_Description, Price_Type_Qualifier,
    Price_Contributor_Partition_ID, Price_Value, Price_Currency.
    """
    data = {
        "CUSIP": ["J2860LAA8"],
        "GSN": ["GSN-JGB2YR-100"],
        "ISIN": ["JP1200191939"],
        "Prime_ID": ["PID-90847231"],
        "Price_Effective_Date": ["2024-05-09"],
        "Price_Type_Description": ["Closing Price"],
        "Price_Type_Qualifier": ["Official Close"],
        "Price_Contributor_Partition_ID": ["TSE-JGB"],
        "Price_Value": [107.00503636],
        "Price_Currency": ["JPY"],
    }
    df = pd.DataFrame(data)
    path = os.path.join(OUTPUT_DIR, "Trade_Source_PriceCurrency.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")


def create_source_forex_conversion():
    """
    Source Evidence #3: Forex conversion rates.
    Can have multiple rows for different currency pairs / dates.
    """
    data = {
        "Business_Date": ["9/18/2024", "9/18/2024", "9/18/2024"],
        "From_Currency": ["JPY", "EUR", "GBP"],
        "To_Currency": ["USD", "USD", "USD"],
        "Rate_Multiply": [FOREX_RATE_JPY_USD, 1.1165, 1.3142],
    }
    df = pd.DataFrame(data)
    path = os.path.join(OUTPUT_DIR, "Trade_Source_ForexConversion.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")
    print(f"  JPY→USD rate: {FOREX_RATE_JPY_USD}")
    print(f"  Face_USD correct: {FACE_USD_CORRECT}")
    print(f"  Face_USD wrong (in sample): {FACE_USD_WRONG}")


if __name__ == "__main__":
    print("=" * 60)
    print("Generating Phase 2 Trade Test Data")
    print("=" * 60)
    print()
    create_sample_summary()
    print()
    create_source_affirmation()
    print()
    create_source_price_currency()
    print()
    create_source_forex_conversion()
    print()
    print("=" * 60)
    print("EXPECTED TEST RESULTS:")
    print("=" * 60)
    print(f"  End_Date:          FAIL (reported '12/10/2024' vs source 'December 09, 2024')")
    print(f"  Face_USD:          FAIL (reported {FACE_USD_WRONG} vs computed {FACE_USD_CORRECT})")
    print(f"  Mkt_Closing_Price: FAIL (reported {MKT_CLOSING_PRICE_WRONG} vs source {MKT_CLOSING_PRICE})")
    print(f"  All others:        PASS")
