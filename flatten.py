import json
import os
import pandas as pd

def run(input_json: str, output_csv: str):
    print("\n" + "="*50)
    print("STEP 3: Flattening specifications JSON...")
    print("="*50)

    if not os.path.exists(input_json):
        print(f"ERROR: '{input_json}' not found!")
        return {"columns": 0}

    rows = []
    with open(input_json, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    if not rows:
        print("ERROR: No data found in file!")
        return {"columns": 0}

    df = pd.DataFrame(rows)
    specs_expanded = pd.json_normalize(
        df["specifications"].apply(lambda x: x if isinstance(x, dict) else {})
    )
    df = pd.concat([df, specs_expanded], axis=1)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"STEP 3 DONE: Saved to '{output_csv}' with {len(df.columns)} columns")
    return {"columns": len(df.columns)}