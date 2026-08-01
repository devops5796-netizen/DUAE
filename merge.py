"""from pathlib import Path
import pandas as pd

files = sorted(Path("outputs").rglob("*.csv"))

print(files)

dfs = [pd.read_csv(f) for f in files]

merged = pd.concat(dfs, ignore_index=True)

merged.to_csv(
    "agencies_with_phone_all.csv",
    index=False,
    encoding="utf-8-sig"
)

merged.to_excel(
    "agencies_with_phone_all.xlsx",
    index=False
)

print(f"Merged {len(files)} files.")"""

from pathlib import Path
import pandas as pd

files = sorted(Path("outputs").rglob("*.csv"))

print(files)

dfs = [pd.read_csv(f) for f in files]

merged = pd.concat(dfs, ignore_index=True)

merged.to_csv(
    "listings_with_phone_all.csv",
    index=False,
    encoding="utf-8-sig"
)

merged.to_excel(
    "listings_with_phone_all.xlsx",
    index=False
)

print(f"Merged {len(files)} files.")