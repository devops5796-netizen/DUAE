import pandas as pd
import os

def write(sheets: dict, output_path: str) -> None:
    if not sheets:
        print("Empty sheets, no Excel created.")
        return
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if df is None or df.empty:
                print(f"  Skipping '{sheet_name}' — no data")
                continue
            safe = sheet_name[:31].replace("/","-").replace("\\","-").replace("*","").replace("?","").replace("[","").replace("]","")
            df.to_excel(writer, sheet_name=safe, index=False)
            print(f"  Sheet '{safe}': {len(df)} rows")
    print(f"Excel saved: {output_path}")


def write_single(df: pd.DataFrame, sheet_name: str, output_path: str) -> None:
    write({sheet_name: df}, output_path)