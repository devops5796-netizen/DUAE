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

COLUMNS_TO_DROP = ["_highlightResult"]


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


def get_city_name(city_value) -> str:
    city = parse_dict_field(city_value)
    if not city:
        return "Unknown"
    name_field = city.get("name")
    if isinstance(name_field, dict):
        return name_field.get("en", "Unknown")
    return "Unknown"


def get_category_names(categories_v2_value) -> list:
    """
    categories_v2 = [{'name': {'en': ['Apartment', 'Residential', 'Property for Sale']}, ...}]
    بترجع ['Apartment', 'Residential', 'Property for Sale'] (leaf, mid, top)
    """
    if isinstance(categories_v2_value, str):
        try:
            categories_v2_value = json.loads(categories_v2_value)
        except (json.JSONDecodeError, TypeError):
            try:
                categories_v2_value = ast.literal_eval(categories_v2_value)
            except Exception:
                return []

    if not isinstance(categories_v2_value, list) or len(categories_v2_value) == 0:
        return []

    first = categories_v2_value[0]
    if not isinstance(first, dict):
        return []

    name_field = first.get("name", {})
    return name_field.get("en", []) if isinstance(name_field, dict) else []


def sanitize_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    name = name.replace(" ", "_")
    name = re.sub(r'_+', '_', name)
    return name.strip("_")


def build_meta(names_en: list) -> dict:
    """
    names_en = [leaf, mid, top] زي ['Apartment', 'Residential', 'Property for Sale']
    """
    if len(names_en) < 2:
        return {"cat0": "Property", "cat1": "Other", "sheet": "Other"}

    leaf = names_en[0]
    mid = names_en[1]
    top = names_en[-1]

    sheet = f"{mid} ({leaf})"

    return {"cat0": "Property", "cat1": top, "sheet": sheet}


def extract_image_urls(row: pd.Series) -> list:
    if "images" in row and isinstance(row["images"], list):
        urls = []
        for item in row["images"]:
            if isinstance(item, dict) and item.get("main"):
                urls.append(item["main"])
        return urls
    return []


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
    return df


def download_images(images: list, slug_id: str = "", city: str = "", cat0: str = "", cat1: str = "") -> list:
    r2_paths = []
    uploaded = 0
    failed = 0

    if not images:
        return r2_paths

    ext = "webp"
    file_prefix = slug_id or "unknown"
    category_display = f"{cat0}/{cat1}/new_projects" if cat1 else f"{cat0}/new_projects"

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
                    output_buffer, filename=filename, folder_name="DUAE",
                    category="new_projects", file_type="images", content_type="image/webp",
                    dt=None, city=city, category_display=category_display
                )
                if r2_key:
                    r2_paths.append(r2_key)
                    uploaded += 1
                else:
                    failed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"    [ERROR] {filename}: {e}")
            failed += 1

    if uploaded or failed:
        print(f"    {file_prefix}: {uploaded} uploaded, {failed} failed out of {len(images)}")
    return r2_paths


def process_images_for_group(df: pd.DataFrame, city: str, cat0: str, cat1: str, workers: int = 2) -> pd.DataFrame:
    df = df.copy()
    n = len(df)
    results = [None] * n

    def worker(pos: int, images: list, slug_id: str) -> tuple:
        return pos, download_images(images, slug_id=slug_id, city=city, cat0=cat0, cat1=cat1)

    tasks = []
    for pos, (idx, row) in enumerate(df.iterrows()):
        images = extract_image_urls(row)
        slug_id = str(row.get("slug", idx))
        tasks.append((pos, images, slug_id))

    print(f"  Downloading images for {n} projects using {workers} workers...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker, pos, images, slug_id): pos for pos, images, slug_id in tasks}
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


def _write_excel_and_json(sheets: dict, xlsx_path: str, json_path: str) -> tuple:
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    all_records = []
    for sheet_name, df in sheets.items():
        records = df.to_dict(orient="records")
        for r in records:
            r["_sheet"] = sheet_name
        all_records.extend(records)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2, default=str)

    return xlsx_path, json_path


def process_new_projects(jsonl_files: list, output_base_dir: str,
                          upload_images: bool = True, image_workers: int = 2,
                          city_filter: str = None) -> dict:
    df = load_all_hits(jsonl_files)
    if df.empty:
        return {"total": 0, "excel_files": [], "json_files": []}

    df["_city"] = df["city"].apply(get_city_name)

    if city_filter:
        df = df[df["_city"] == city_filter]
        print(f"  Filtered to city: {city_filter} ({len(df)} rows)")
        if df.empty:
            return {"total": 0, "excel_files": [], "json_files": []}

    df["_names_en"] = df["categories_v2"].apply(get_category_names)
    meta_list = df["_names_en"].apply(build_meta)
    df["_cat0"] = meta_list.apply(lambda m: m["cat0"])
    df["_cat1"] = meta_list.apply(lambda m: m["cat1"])
    df["_sheet"] = meta_list.apply(lambda m: m["sheet"])

    if "slug" in df.columns:
        df = df.drop_duplicates(subset=["slug"], keep="first")

    excel_files = []
    json_files = []
    total = len(df)

    group_cols = ["_city", "_cat0", "_cat1"]
    should_process_images = upload_images and "images" in df.columns

    for keys, group_df in df.groupby(group_cols, dropna=False):
        city, cat0, cat1 = keys
        safe_city = sanitize_name(city)
        safe_cat0 = sanitize_name(cat0)
        safe_cat1 = sanitize_name(cat1) if pd.notna(cat1) and cat1 else None

        group_quality_report = generate_data_quality_report(group_df, len(group_df))

        path_parts = [output_base_dir, safe_city, safe_cat0]
        if safe_cat1:
            path_parts.append(safe_cat1)
        path_parts.append("new_projects")

        group_dir = os.path.join(*path_parts)
        os.makedirs(group_dir, exist_ok=True)

        if should_process_images:
            print(f"  Processing images for {safe_city}/{safe_cat0}/{safe_cat1 or ''}/new_projects ({len(group_df)} rows)...")
            group_df = process_images_for_group(group_df, city=safe_city, cat0=safe_cat0, cat1=safe_cat1, workers=image_workers)

        excel_dir = os.path.join(group_dir, "excel")
        json_dir = os.path.join(group_dir, "json")
        summary_dir = os.path.join(group_dir, "summary")
        os.makedirs(excel_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)

        main_xlsx = os.path.join(excel_dir, "new_projects.xlsx")
        main_json = os.path.join(json_dir, "new_projects.json")

        cols_to_drop = ["_city", "_cat0", "_cat1", "_sheet", "_names_en"]
        sheets = {}
        for sheet_name, sdf in group_df.groupby("_sheet"):
            sdf_clean = sdf.drop(columns=[c for c in cols_to_drop if c in sdf.columns])
            safe_sheet = sanitize_name(sheet_name)
            sheets[safe_sheet] = sdf_clean

        xlsx_path, json_path = _write_excel_and_json(sheets, main_xlsx, main_json)
        excel_files.append(xlsx_path)
        json_files.append(json_path)
        print(f"  Saved: {main_xlsx} ({len(group_df)} rows)")

        summary_file_path = os.path.join(summary_dir, "summary.txt")
        with open(summary_file_path, "w", encoding="utf-8") as f:
            f.write(f"=== new_projects ===\n")
            f.write(f"City: {safe_city}\n")
            f.write(f"Category: {safe_cat0}/{safe_cat1 or ''}\n")
            f.write(f"Total Rows: {len(group_df)}\n")
            f.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(group_quality_report)

        print(f"  Saved summary: {summary_file_path}")

    return {"total": total, "excel_files": excel_files, "json_files": json_files}