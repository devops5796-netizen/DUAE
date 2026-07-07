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

CAR_CATEGORIES = {"motors_used_cars", "motors_rental_cars"}


def parse_dict_field(value):
    """Parse dictionary field from string or dict"""
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
    """Extract city name from site field"""
    site = parse_dict_field(site_value)
    return site.get("en", "Unknown")


def get_category_names(category_v2_value) -> list:
    """Extract category names from category_v2 field"""
    cat = parse_dict_field(category_v2_value)
    return cat.get("names_en", [])


def sanitize_name(name: str) -> str:
    """Sanitize name for file/folder names - replace spaces with underscores"""
    # Replace spaces and special characters with underscore
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    return name.strip()


def extract_sheet_name(names_en: list) -> str:
    """Extract sheet name from category names"""
    if not names_en or len(names_en) < 3:
        return "Other"
    level2 = names_en[2]
    if len(names_en) >= 4:
        level3 = names_en[3]
        return f"{level2} ({level3})"
    return level2


def generate_data_quality_report(df: pd.DataFrame, total_rows: int) -> str:
    """
    Generate data quality report with empty values count and percentage for each column
    """
    report_lines = []
    report_lines.append("--- Data Quality Report ---")
    
    for col in df.columns:
        # Count missing values (NaN) and empty strings
        missing = df[col].isna().sum() + (df[col] == '').sum()
        pct = (missing / total_rows) * 100 if total_rows > 0 else 0
        report_lines.append(f'  {col}: {missing} empty ({pct:.2f}%)')
    
    return "\n".join(report_lines)


def load_all_hits(jsonl_files: list) -> pd.DataFrame:
    """Load all hits from multiple JSONL files"""
    rows = []
    for path in jsonl_files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return pd.DataFrame(rows)


def download_images(images: list, slug: str = "", category: str = "") -> list:
    """Download and upload images to R2"""
    r2_paths = []
    uploaded = 0
    failed = 0

    if not images or not isinstance(images, list):
        return r2_paths

    ext = "webp"
    slug = slug or "unknown"

    for idx, img_url in enumerate(images, start=1):
        filename = f"{slug}-{idx}.{ext}"
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
                    category=category,
                    file_type="images",
                    content_type="image/webp"
                )
                if r2_key:
                    r2_paths.append(r2_key)
                    uploaded += 1
                else:
                    failed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"    [ERROR] {slug} image {idx}: {e}")
            failed += 1

    if uploaded or failed:
        print(f"    {slug}: {uploaded} uploaded, {failed} failed out of {len(images)}")
    return r2_paths


def process_images_for_group(df: pd.DataFrame, category: str, workers: int = 8) -> pd.DataFrame:
    """Process images for a group of products using multithreading"""
    df = df.copy()
    n = len(df)
    results = [None] * n 

    def worker(pos: int, images: list, slug: str) -> tuple:
        r2_paths = download_images(images, slug=slug, category=category)
        return pos, r2_paths

    tasks = []
    for pos, (idx, row) in enumerate(df.iterrows()):
        images = row.get("photo_mains", [])
        slug = str(row.get("objectID", idx))
        tasks.append((pos, images, slug))

    print(f"  Downloading images for {n} products using {workers} workers...")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker, pos, images, slug): pos for pos, images, slug in tasks}

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
    """Write Excel and JSON files from sheets"""
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


def process_category(category_name: str, jsonl_files: list, output_base_dir: str,
                      upload_images: bool = True, image_workers: int = 8) -> dict:
    """
    Process category data and generate Excel/JSON files with the structure:
    {city}/Motors/{category_name}/excel/...
    {city}/Motors/{category_name}/json/...
    {city}/Motors/{category_name}/summary/summary.txt
    """
    df = load_all_hits(jsonl_files)
    if df.empty:
        return {"total": 0, "excel_files": [], "json_files": []}

    df["_city"] = df["site"].apply(get_city_name)
    df["_names_en"] = df["category_v2"].apply(get_category_names)
    df["_cat0"] = df["_names_en"].apply(lambda n: n[0] if len(n) > 0 else "Unknown")
    df["_cat1"] = df["_names_en"].apply(lambda n: n[1] if len(n) > 1 else "Unknown")

    if "objectID" in df.columns:
        df = df.drop_duplicates(subset=["objectID"], keep="first")

    excel_files = []
    json_files = []
    total = len(df)

    # Generate data quality report for the entire DataFrame
    quality_report = generate_data_quality_report(df, total)

    # Group by city and main category (cat0)
    for (city, cat0), city_df in df.groupby(["_city", "_cat0"]):
        safe_city = sanitize_name(city)  # "Al Ain" -> "Al_Ain"
        
        # Use the category name as-is (used_cars, rental_cars, etc.)
        category_display = category_name  # Keep original category name
        
        # Create path: {city}/Motors/{category_name}
        city_dir = os.path.join(output_base_dir, safe_city, "Motors", category_display)
        os.makedirs(city_dir, exist_ok=True)
        
        # Process images if needed
        if upload_images and "photo_mains" in city_df.columns:
            print(f"  Processing images for {safe_city}/{category_display} ({len(city_df)} products)...")
            city_df = process_images_for_group(city_df, category=category_name, workers=image_workers)

        # Create subdirectories
        excel_dir = os.path.join(city_dir, "excel")
        json_dir = os.path.join(city_dir, "json")
        summary_dir = os.path.join(city_dir, "summary")
        os.makedirs(excel_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)

        # Process car categories (split by manufacturer)
        if category_name in CAR_CATEGORIES:
            city_df = city_df.copy()
            city_df["_manufacturer"] = city_df["category_v2"].apply(get_category_names).apply(
                lambda n: n[2] if len(n) > 2 else "Unknown"
            )
            city_df["_model"] = city_df["category_v2"].apply(get_category_names).apply(
                lambda n: n[3] if len(n) > 3 else "Unknown"
            )

            # Save main file: excel/{category_name}.xlsx
            main_xlsx = os.path.join(excel_dir, f"{category_display}.xlsx")
            main_json = os.path.join(json_dir, f"{category_display}.json")
            
            sheets = {}
            for manufacturer, m_df in city_df.groupby("_manufacturer"):
                cols_to_drop = ["_manufacturer", "_model", "_city", "_cat0", "_cat1"]
                m_df_clean = m_df.drop(columns=[c for c in cols_to_drop if c in m_df.columns])
                safe_mfr = sanitize_name(manufacturer)
                sheets[safe_mfr] = m_df_clean
            
            xlsx_path, json_path = _write_excel_and_json(sheets, main_xlsx)
            excel_files.append(xlsx_path)
            json_files.append(json_path)
            print(f"    Saved main: {main_xlsx} ({len(city_df)} rows)")

            # Save by manufacturer files: excel/by_manufacturer/Nissan.xlsx
            by_mfr_dir = os.path.join(excel_dir, "by_manufacturer")
            by_mfr_json_dir = os.path.join(json_dir, "by_manufacturer")
            os.makedirs(by_mfr_dir, exist_ok=True)
            os.makedirs(by_mfr_json_dir, exist_ok=True)

            for manufacturer, m_df in city_df.groupby("_manufacturer"):
                safe_mfr = sanitize_name(manufacturer)
                mfr_xlsx = os.path.join(by_mfr_dir, f"{safe_mfr}.xlsx")
                mfr_json = os.path.join(by_mfr_json_dir, f"{safe_mfr}.json")
                
                sheets = {}
                for model, model_df in m_df.groupby("_model"):
                    cols_to_drop = ["_manufacturer", "_model", "_city", "_cat0", "_cat1"]
                    model_df_clean = model_df.drop(columns=[c for c in cols_to_drop if c in model_df.columns])
                    safe_model = sanitize_name(model)[:31]
                    sheets[safe_model] = model_df_clean
                
                xlsx_path, json_path = _write_excel_and_json(sheets, mfr_xlsx)
                excel_files.append(xlsx_path)
                json_files.append(json_path)
                print(f"    Saved by manufacturer: {mfr_xlsx} ({len(m_df)} rows)")

        else:
            # For non-car categories
            city_df = city_df.copy()
            city_df["_sheet_name"] = city_df["category_v2"].apply(get_category_names).apply(extract_sheet_name)

            main_xlsx = os.path.join(excel_dir, f"{category_display}.xlsx")
            sheets = {}
            for sheet_name, sdf in city_df.groupby("_sheet_name"):
                cols_to_drop = ["_sheet_name", "_city", "_cat0", "_cat1"]
                sdf_clean = sdf.drop(columns=[c for c in cols_to_drop if c in sdf.columns])
                safe_sheet = sanitize_name(sheet_name)[:31]
                sheets[safe_sheet] = sdf_clean

            xlsx_path, json_path = _write_excel_and_json(sheets, main_xlsx)
            excel_files.append(xlsx_path)
            json_files.append(json_path)
            print(f"  Saved main: {main_xlsx} ({len(city_df)} rows)")

        # Save summary file for this city and category
        summary_file_path = os.path.join(summary_dir, "summary.txt")
        with open(summary_file_path, "w", encoding="utf-8") as f:
            f.write(f"=== {category_name} ===\n")
            f.write(f"City: {safe_city}\n")
            f.write(f"Category: {category_display}\n")
            f.write(f"Total Rows: {len(city_df)}\n")
            f.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(quality_report)
        
        print(f"  Saved summary: {summary_file_path}")

    return {"total": total, "excel_files": excel_files, "json_files": json_files}