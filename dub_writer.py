import pandas as pd
import json
import ast
import os
import re
import io
import requests as req
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from r2_uploader import upload_buffer
from datetime import datetime

CAR_CATEGORIES = {"used_cars", "rental_cars"}

CONDITION_FIELD = "car_condition"  
EXPORT_FIELD = "is_export_car"
NEW_VALUE = "new"

COLUMNS_TO_DROP = [
    "photo", "photo_thumbnails", "photos", "_highlightResult",
    "site_categories_slug_tree", "category_slug_tree", "category_tree",
    "category", "permalink"
]

def parse_dict_field(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                return ast.literal_eval(value)
            except Exception:
                return {}
    return {}


def get_city_name(site_value) -> str:
    site = parse_dict_field(site_value)
    return site.get("en", "Unknown")


def get_category_names(category_v2_value) -> list:
    cat = parse_dict_field(category_v2_value)
    return cat.get("names_en", [])


def sanitize_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    name = name.replace(" ", "_")
    return name.strip()


def extract_sheet_name(names_en: list) -> str:
    if not names_en:
        return "Other"
    if len(names_en) == 2:
        return names_en[1]
    
    level2 = names_en[2]
    if len(names_en) >= 4:
        level3 = names_en[3]
        return f"{level2} ({level3})"
    return level2


def generate_data_quality_report(df: pd.DataFrame, total_rows: int) -> str:
    report_lines = ["--- Data Quality Report ---"]
    for col in df.columns:
        missing = df[col].isna().sum() + (df[col] == '').sum()
        pct = (missing / total_rows) * 100 if total_rows > 0 else 0
        report_lines.append(f'  {col}: {missing} empty ({pct:.2f}%)')
    return "\n".join(report_lines)


def load_all_hits(jsonl_files: list) -> pd.DataFrame:
    rows = []
    for path in jsonl_files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    df = pd.DataFrame(rows)

    existing_cols = [c for c in COLUMNS_TO_DROP if c in df.columns]
    if existing_cols:
        df = df.drop(columns=existing_cols)
        print(f"  Dropped columns: {existing_cols}")

    return df


def download_images(images: list, slug: str = "", category: str = "", id_prod: str = "",
                     city: str = "", cat0: str = "", cat1: str = "") -> list:
    r2_paths = []
    uploaded = 0
    failed = 0

    if not images or not isinstance(images, list):
        return r2_paths

    ext = "webp"
    slug = slug or "unknown"
    file_prefix = id_prod if id_prod else slug

    # نجمع cat0/cat1 في مسار واحد عشان يتوافق مع باقي الهيكل (city/cat0/cat1/images/...)
    category_display = f"{cat0}/{cat1}" if cat0 and cat1 else (cat1 or cat0)

    for idx, img_url in enumerate(images, start=1):
        filename = f"{file_prefix}-{idx}.{ext}"
        try:
            r = req.get(img_url, timeout=15)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                output_buffer = io.BytesIO()
                img = img.convert("RGB")
                img.save(output_buffer, format="WEBP", quality=100, method=6)
                output_buffer.seek(0)

                r2_key = upload_buffer(
                    output_buffer,
                    filename=filename,
                    folder_name="DUAE",
                    category=category,
                    file_type="images",
                    content_type="image/webp",
                    dt=None,
                    city=city,
                    category_display=category_display
                )
                if r2_key:
                    r2_paths.append(r2_key)
                    uploaded += 1
                else:
                    failed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"    [ERROR] {filename} image {idx}: {e}")
            failed += 1

    if uploaded or failed:
        print(f"    {file_prefix}: {uploaded} uploaded, {failed} failed out of {len(images)}")
    return r2_paths


def process_images_for_group(df: pd.DataFrame, category: str, city: str, cat0: str, cat1: str,
                              workers: int = 2) -> pd.DataFrame:
    df = df.copy()
    n = len(df)
    results = [None] * n

    def worker(pos: int, images: list, slug: str, id_prod: str) -> tuple:
        r2_paths = download_images(
            images, slug=slug, category=category, id_prod=id_prod,
            city=city, cat0=cat0, cat1=cat1
        )
        return pos, r2_paths

    tasks = []
    for pos, (idx, row) in enumerate(df.iterrows()):
        images = row.get("photo_mains", [])
        id_prod = str(row.get("id", idx))
        slug = id_prod
        tasks.append((pos, images, slug, id_prod))

    print(f"  Downloading images for {n} products using {workers} workers...")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker, pos, images, slug, id_prod): pos for pos, images, slug, id_prod in tasks}

        completed = 0
        for future in as_completed(futures):
            try:
                pos, r2_paths = future.result(timeout=120)
                results[pos] = r2_paths
            except Exception as e:
                pos = futures[future]
                print(f"    [ERROR] Task {pos} failed: {e}")
                results[pos] = []

            completed += 1
            if completed % 50 == 0 or completed == n:
                print(f"    Progress: {completed}/{n}")

    df["images_r2_paths"] = results
    return df


def _write_excel_and_json(sheets: dict, xlsx_path: str) -> tuple:
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    json_path = xlsx_path.replace(".xlsx", ".json")
    all_records = []
    for sheet_name, df in sheets.items():
        records = df.to_dict(orient="records")
        for r in records:
            r["_sheet"] = sheet_name
        all_records.extend(records)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2, default=str)

    return xlsx_path, json_path

def split_used_cars(df: pd.DataFrame) -> dict:
    if CONDITION_FIELD not in df.columns:
        print(f"  ⚠️ Column '{CONDITION_FIELD}' not found, skipping split.")
        return {"used_cars": df}
    if EXPORT_FIELD not in df.columns:
        print(f"  ⚠️ Column '{EXPORT_FIELD}' not found, skipping split.")
        return {"used_cars": df}

    is_new = df[CONDITION_FIELD] == NEW_VALUE
    is_export = df[EXPORT_FIELD] == True

    new_cars_df = df[is_new].copy()
    export_cars_df = df[is_export].copy()
    used_cars_df = df[~is_new & ~is_export].copy()

    overlap = (is_new & is_export).sum()

    print(f"  Split used_cars: new={len(new_cars_df)}, export={len(export_cars_df)}, "
          f"used={len(used_cars_df)}, overlap(new+export)={overlap}")

    return {
        "new_cars": new_cars_df,
        "export_cars": export_cars_df,
        "used_cars": used_cars_df,
    }

def _process_dataframe(df: pd.DataFrame, category_name: str, output_base_dir: str,
                        upload_images: bool, image_workers: int) -> dict:
    if df.empty:
        return {"excel_files": [], "json_files": []}

    df = df.copy()
    df["_city"] = df["site"].apply(get_city_name)
    df["_names_en"] = df["category_v2"].apply(get_category_names)
    df["_cat0"] = df["_names_en"].apply(lambda n: n[0] if len(n) > 0 else "Unknown")

    df["_cat1"] = category_name

    if "id" in df.columns:
        df = df.drop_duplicates(subset=["id"], keep="first")

    excel_files = []
    json_files = []

    for (city, cat0, cat1), group_df in df.groupby(["_city", "_cat0", "_cat1"]):
        safe_city = sanitize_name(city)
        safe_cat0 = sanitize_name(cat0)
        safe_cat1 = sanitize_name(cat1)

        group_quality_report = generate_data_quality_report(group_df, len(group_df))

        city_dir = os.path.join(output_base_dir, safe_city, safe_cat0, safe_cat1)
        os.makedirs(city_dir, exist_ok=True)

        if upload_images and "photo_mains" in group_df.columns:
            print(f"  Processing images for {safe_city}/{safe_cat0}/{safe_cat1} ({len(group_df)} products)...")
            group_df = process_images_for_group(
                group_df, category=category_name, city=safe_city,
                cat0=safe_cat0, cat1=safe_cat1, workers=image_workers
            )

        excel_dir = os.path.join(city_dir, "excel")
        json_dir = os.path.join(city_dir, "json")
        summary_dir = os.path.join(city_dir, "summary")
        os.makedirs(excel_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)

        is_car_split = category_name in CAR_CATEGORIES or category_name in {"new_cars", "export_cars", "used_cars"}

        if is_car_split:
            group_df = group_df.copy()
            group_df["_manufacturer"] = group_df["category_v2"].apply(get_category_names).apply(
                lambda n: n[2] if len(n) > 2 else "Unknown"
            )
            group_df["_model"] = group_df["category_v2"].apply(get_category_names).apply(
                lambda n: n[3] if len(n) > 3 else "Unknown"
            )

            main_xlsx = os.path.join(excel_dir, f"{safe_cat1}.xlsx")
            sheets = {}
            for manufacturer, m_df in group_df.groupby("_manufacturer"):
                cols_to_drop = ["_manufacturer", "_model", "_city", "_cat0", "_cat1", "_names_en"]
                m_df_clean = m_df.drop(columns=[c for c in cols_to_drop if c in m_df.columns])
                safe_mfr = sanitize_name(manufacturer)
                sheets[safe_mfr] = m_df_clean

            xlsx_path, json_path = _write_excel_and_json(sheets, main_xlsx)
            excel_files.append(xlsx_path)
            json_files.append(json_path)
            print(f"    Saved main: {main_xlsx} ({len(group_df)} rows)")

            by_mfr_dir = os.path.join(excel_dir, "by_manufacturer")
            by_mfr_json_dir = os.path.join(json_dir, "by_manufacturer")
            os.makedirs(by_mfr_dir, exist_ok=True)
            os.makedirs(by_mfr_json_dir, exist_ok=True)

            for manufacturer, m_df in group_df.groupby("_manufacturer"):
                safe_mfr = sanitize_name(manufacturer)
                mfr_xlsx = os.path.join(by_mfr_dir, f"{safe_mfr}.xlsx")

                sheets = {}
                for model, model_df in m_df.groupby("_model"):
                    cols_to_drop = ["_manufacturer", "_model", "_city", "_cat0", "_cat1", "_names_en"]
                    model_df_clean = model_df.drop(columns=[c for c in cols_to_drop if c in model_df.columns])
                    safe_model = sanitize_name(model)[:31]
                    sheets[safe_model] = model_df_clean

                xlsx_path, json_path = _write_excel_and_json(sheets, mfr_xlsx)
                excel_files.append(xlsx_path)
                json_files.append(json_path)
                print(f"    Saved by manufacturer: {mfr_xlsx} ({len(m_df)} rows)")

        else:
            group_df = group_df.copy()
            group_df["_sheet_name"] = group_df["category_v2"].apply(get_category_names).apply(extract_sheet_name)

            main_xlsx = os.path.join(excel_dir, f"{safe_cat1}.xlsx")
            sheets = {}
            for sheet_name, sdf in group_df.groupby("_sheet_name"):
                cols_to_drop = ["_sheet_name", "_city", "_cat0", "_cat1", "_names_en"]
                sdf_clean = sdf.drop(columns=[c for c in cols_to_drop if c in sdf.columns])
                safe_sheet = sanitize_name(sheet_name)[:31]
                sheets[safe_sheet] = sdf_clean

            xlsx_path, json_path = _write_excel_and_json(sheets, main_xlsx)
            excel_files.append(xlsx_path)
            json_files.append(json_path)
            print(f"  Saved main: {main_xlsx} ({len(group_df)} rows)")

        summary_file_path = os.path.join(summary_dir, "summary.txt")
        with open(summary_file_path, "w", encoding="utf-8") as f:
            f.write(f"=== {category_name} ===\n")
            f.write(f"City: {safe_city}\n")
            f.write(f"Category: {safe_cat0}/{safe_cat1}\n")
            f.write(f"Total Rows: {len(group_df)}\n")
            f.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(group_quality_report)

        print(f"  Saved summary: {summary_file_path}")

    return {"excel_files": excel_files, "json_files": json_files}


def process_category(category_name: str, jsonl_files: list, output_base_dir: str,
                      upload_images: bool = True, image_workers: int = 2) -> dict:
    df = load_all_hits(jsonl_files)
    if df.empty:
        return {"total": 0, "excel_files": [], "json_files": []}

    total = len(df)
    excel_files = []
    json_files = []

    if category_name == "used_cars":
        splits = split_used_cars(df)
        for split_name, split_df in splits.items():
            if split_df.empty:
                continue
            result = _process_dataframe(split_df, split_name, output_base_dir, upload_images, image_workers)
            excel_files.extend(result["excel_files"])
            json_files.extend(result["json_files"])
    else:
        result = _process_dataframe(df, category_name, output_base_dir, upload_images, image_workers)
        excel_files.extend(result["excel_files"])
        json_files.extend(result["json_files"])

    return {"total": total, "excel_files": excel_files, "json_files": json_files}