import json
import os
import pandas as pd

def run(input_json: str):
    if not os.path.exists(input_json):
        print(f"ERROR: '{input_json}' not found!")
        return {"columns": 0, "df": pd.DataFrame()}

    rows = []
    with open(input_json, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    if not rows:
        print("ERROR: No data found in file!")
        return {"columns": 0, "df": pd.DataFrame()}

    df = pd.DataFrame(rows)
    
    print(f"STEP 3 DONE: {len(df)} rows, {len(df.columns)} columns")
    
    return {"columns": len(df.columns), "df": df}