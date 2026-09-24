"""
new_projects_listings.py

For each project produced by main_nw_proj.py (new_projects scraper), fetch all
listings (ads) that live inside that project across the three property
categories (residential / commercial / land), keep only the ones posted
"yesterday" (Asia/Dubai), split them into sheets by categories.slug_paths
(e.g. "residential-apartment", "commercial-shop"), write one
<project-name>.xlsx + <project-name>.json per project (no images), upload
them to R2, and build one summary.json for the whole run.

Usage:
    python new_projects_listings.py <projects_jsonl_file> [more_files...]

    or import and call run(jsonl_files) / run_with_projects(projects) directly.
"""

import ast
import io
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from r2_uploader import upload_buffer
from request_tracker import tracker

# =============================================================================
# Config
# =============================================================================

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://dubai.dubizzle.com",
    "referer": "https://dubai.dubizzle.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# NOTE: this is Dubizzle's own Algolia proxy (algolia.dubizzle.com), NOT the
# direct Algolia endpoint used in main_nw_proj.py. The proxy injects the API
# key / application ID server-side, so no x-algolia-api-key /
# x-algolia-application-id is needed here.
LISTINGS_URL = "https://algolia.dubizzle.com/1/indexes/*/queries"
LISTINGS_QUERY_PARAMS = {
    "x-algolia-agent": "Algolia for JavaScript (4.24.0); Browser (lite)",
}

HITS_PER_PAGE = 25

ATTRIBUTES_TO_RETRIEVE = (
    '["id","category_id","objectID","name","property_reference","price",'
    '"featured_listing","has_tour_url","has_video_url","is_verified","listed_by",'
    '"categories","agent","bedrooms","bathrooms","size","plot_area","neighborhoods",'
    '"city","building","photos","promoted","tour_360","photos_count","added",'
    '"video_url","has_dld_history","tour_url","highlighted_ad","has_whatsapp_number",'
    '"has_agents_whatsapp","has_sms_number","short_url","absolute_url","category_id",'
    '"badges","room_type","uuid","can_chat","chat_enabled","is_premium_ad",'
    '"description_short","completion_status","is_verified_user","agent_profile",'
    '"payment_frequency","furnished","is_developer_listing","sale_type","sale_type_2",'
    '"handover_date","payment_plan","original_price","amount_paid","property_info",'
    '"is_emirati_agent","external_id","special_amenities","is_price_hidden",'
    '"area_prime_slot_id","_geoloc","price_drop"]'
)

CATEGORY_QUERIES = {
    "residential": {
        "index": "by_verification_feature_asc_property-for-sale-residential.com",
        "path": "property-for-sale/residential",
    },
    "commercial": {
        "index": "by_verification_feature_asc_property-for-sale-commercial.com",
        "path": "property-for-sale/commercial",
    },
    "land": {
        "index": "by_verification_feature_asc_property-for-sale-land.com",
        "path": "property-for-sale/land",
    },
}

R2_CATEGORY_PATH = "property/property-for-sale/new-projects"

DUBAI_NOW = datetime.now(ZoneInfo("Asia/Dubai"))
TARGET_DATE = DUBAI_NOW.date() - timedelta(days=1)


# =============================================================================
# Small dict/string helpers
# =============================================================================

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


def sanitize_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    name = name.replace(" ", "_")
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def get_name_en(value) -> str:
    d = parse_dict_field(value)
    return (d.get("en") or "").strip()


# =============================================================================
# Date filtering (as provided)
# =============================================================================

def _get_url(absolute_url_value):
    """Extract URL string from absolute_url field (dict or string)."""
    if isinstance(absolute_url_value, dict):
        return absolute_url_value.get("en") or absolute_url_value.get("ar")
    if isinstance(absolute_url_value, str):
        return absolute_url_value
    return None


def extract_date_from_url(url: str):
    """Extract posted date from dubizzle URL path like /2026/7/1/ or /2026/12/25/"""
    if not url:
        return None
    match = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime(year, month, day).date()
        except ValueError:
            return None
    return None


def get_date_from_timestamp(timestamp_value):
    """Convert Unix timestamp to Dubai date."""
    if timestamp_value is None:
        return None
    try:
        dt = datetime.fromtimestamp(int(timestamp_value), tz=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Dubai")).date()
    except (ValueError, TypeError):
        return None


def filter_yesterday_hits(hits):
    filtered = []

    for hit in hits:
        post_date = None

        post_date = get_date_from_timestamp(hit.get("created_at"))

        if post_date is None:
            url = _get_url(hit.get("absolute_url"))
            post_date = extract_date_from_url(url)

        if post_date is None:
            continue

        if post_date == TARGET_DATE:
            filtered.append(hit)

    return filtered


# =============================================================================
# Project identity: which neighborhood id + which building id represent it,
# and whether a fetched listing actually belongs to this project.
# =============================================================================

def get_project_name_en(project: dict) -> str:
    name_en = get_name_en(project.get("name"))
    if name_en:
        return name_en
    return project.get("slug") or "Unknown Project"


def get_project_building_id(project: dict):
    building = parse_dict_field(project.get("building"))
    return building.get("id")


def get_project_neighborhood_id(project: dict):
    """
    Pick the most specific neighborhood id for this project: the one whose
    name matches the project's own name exactly (e.g. "Binghatti Skyrise"),
    falling back to the last id in the list (Dubizzle orders neighborhoods
    broad -> specific, e.g. ["Business Bay", "Binghatti Skyrise"]).
    """
    project_name_en = get_project_name_en(project).lower()
    neighborhoods = parse_dict_field(project.get("neighborhoods"))
    ids = neighborhoods.get("ids") or []
    names_en = (neighborhoods.get("name") or {}).get("en") or []

    for nid, nname in zip(ids, names_en):
        if nname and nname.strip().lower() == project_name_en:
            return nid

    return ids[-1] if ids else None


def belongs_to_project(hit: dict, project_name_en: str) -> bool:
    """
    Post-filter: the fetch itself is broad (building.id OR neighborhoods.ids),
    so this makes sure a hit actually belongs to THIS project and not a
    different project/building sharing the same neighborhood.
    """
    if not project_name_en:
        return False
    project_name_en = project_name_en.strip().lower()

    building = hit.get("building") or {}
    building_name = get_name_en(building.get("name")) if isinstance(building, dict) else ""
    if building_name and building_name.strip().lower().startswith(project_name_en):
        return True

    neighborhoods = hit.get("neighborhoods") or {}
    names_en = (neighborhoods.get("name") or {}).get("en") or [] if isinstance(neighborhoods, dict) else []
    for n in names_en:
        if n and n.strip().lower() == project_name_en:
            return True

    return False


# =============================================================================
# Listings fetch (per project, per category, paginated)
# =============================================================================

def build_filters(category_path: str, city_id, building_id, neighborhood_id):
    id_conditions = []
    if building_id:
        id_conditions.append(f"building.id={building_id}")
    if neighborhood_id:
        id_conditions.append(f"neighborhoods.ids={neighborhood_id}")

    if not id_conditions or not city_id:
        return None

    id_filter = " OR ".join(id_conditions)
    return (
        f'("categories_v2.slug_paths":"{category_path}") '
        f'AND ("city.id"={city_id}) '
        f'AND ({id_filter}) '
        f"AND allowed_pages:lpv"
    )


def _get_listings_page(index_name: str, filters: str, page: int, source: str, max_retries: int = 3) -> dict:
    algolia_params = {
        "page": page,
        "attributesToHighlight": "[]",
        "hitsPerPage": HITS_PER_PAGE,
        "attributesToRetrieve": ATTRIBUTES_TO_RETRIEVE,
        "clickAnalytics": "true",
        "facets": '["language"]',
        "filters": filters,
    }
    payload = {
        "requests": [
            {
                "indexName": index_name,
                "query": "",
                "params": urlencode(algolia_params),
            }
        ]
    }

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(LISTINGS_URL, params=LISTINGS_QUERY_PARAMS, headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            tracker.log_request(source=source, success=True)
            return r.json()
        except Exception as e:
            tracker.log_request(source=source, success=False)
            print(f"      [Attempt {attempt}/{max_retries}] {source} page {page} failed: {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)

    return None


def get_category_listings(filters: str, index_name: str, category_name: str) -> list:
    """Paginate a single category (residential/commercial/land) for one project."""
    hits = []
    page = 0
    while True:
        data = _get_listings_page(index_name, filters, page, source=f"listings_{category_name}")
        if data is None:
            print(f"      [FAILED] {category_name} page {page} failed after retries, stopping category.")
            break

        try:
            result = data["results"][0]
            page_hits = result.get("hits", [])
            nb_pages = result.get("nbPages", 1)
        except (KeyError, IndexError):
            break

        hits.extend(page_hits)

        if not page_hits or page + 1 >= nb_pages:
            break

        page += 1
        time.sleep(random.uniform(0.3, 1.0))

    return hits


def get_project_listings(project: dict) -> list:
    """Fetch all listings (residential + commercial + land) that belong to one project."""
    city = parse_dict_field(project.get("city"))
    city_id = city.get("id")

    building_id = get_project_building_id(project)
    neighborhood_id = get_project_neighborhood_id(project)
    project_name_en = get_project_name_en(project)

    if not city_id or (not building_id and not neighborhood_id):
        print(f"    [SKIP] Project missing city.id / building.id / neighborhoods.ids: {project.get('slug')}")
        return []

    all_hits = []
    for category_name, cfg in CATEGORY_QUERIES.items():
        filters = build_filters(cfg["path"], city_id, building_id, neighborhood_id)
        if not filters:
            continue

        raw_hits = get_category_listings(filters, cfg["index"], category_name)
        matched = [h for h in raw_hits if belongs_to_project(h, project_name_en)]
        print(f"      {category_name}: {len(raw_hits)} fetched -> {len(matched)} matched to project")
        all_hits.extend(matched)
        time.sleep(random.uniform(0.3, 1.0))

    return all_hits


# =============================================================================
# Sheet splitting (categories.slug_paths -> "residential-apartment" etc.)
# =============================================================================

def get_sheet_name(categories_value) -> str:
    cat = parse_dict_field(categories_value)
    slug_paths = cat.get("slug_paths", [])
    if not slug_paths:
        return "Other"

    parts = slug_paths[0].split("/")  # e.g. property-for-sale/residential/apartment
    if len(parts) >= 3:
        return f"{parts[1]}-{parts[2]}"
    if len(parts) == 2:
        return parts[1]
    return "Other"


# =============================================================================
# Write local excel/json + upload to R2
# =============================================================================

def _write_excel_and_json(sheets: dict, xlsx_path: str, json_path: str) -> tuple:
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    all_records = []
    for sheet_name, df in sheets.items():
        records = df.to_dict(orient="records")
        for r in records:
            r["_sheet"] = sheet_name
        all_records.extend(records)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2, default=str)

    return xlsx_path, json_path


def _upload_file_to_r2(local_path: str, filename: str, file_type: str, content_type: str, dt: datetime) -> str | None:
    with open(local_path, "rb") as f:
        buffer = io.BytesIO(f.read())
    return upload_buffer(
        buffer,
        filename=filename,
        folder_name="DUAE",
        file_type=file_type,
        content_type=content_type,
        dt=dt,
        category_path=R2_CATEGORY_PATH,
    )


def process_project(project: dict, output_dir: str, dt: datetime, upload_to_r2: bool = True) -> dict | None:
    project_name = sanitize_name(get_project_name_en(project))
    print(f"  Processing project: {project_name}")

    hits = get_project_listings(project)
    print(f"    Total matched listings: {len(hits)}")

    filtered = filter_yesterday_hits(hits)
    print(f"    Listings posted yesterday ({TARGET_DATE}): {len(filtered)}")

    if not filtered:
        return None

    df = pd.DataFrame(filtered)
    if "_highlightResult" in df.columns:
        df = df.drop(columns=["_highlightResult"])

    df["_sheet"] = df["categories"].apply(get_sheet_name)

    if "id" in df.columns:
        df = df.drop_duplicates(subset=["id"], keep="first")

    sheets = {}
    for sheet_name, sdf in df.groupby("_sheet"):
        sdf_clean = sdf.drop(columns=["_sheet"])
        safe_sheet = sanitize_name(sheet_name)[:31]
        sheets[safe_sheet] = sdf_clean

    excel_dir = os.path.join(output_dir, "excel")
    json_dir = os.path.join(output_dir, "json")
    os.makedirs(excel_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    xlsx_path = os.path.join(excel_dir, f"{project_name}.xlsx")
    json_path = os.path.join(json_dir, f"{project_name}.json")
    _write_excel_and_json(sheets, xlsx_path, json_path)
    print(f"    Saved locally: {xlsx_path} ({len(df)} rows, {len(sheets)} sheet(s))")

    r2_excel_key = None
    r2_json_key = None
    if upload_to_r2:
        r2_excel_key = _upload_file_to_r2(
            xlsx_path,
            f"{project_name}.xlsx",
            "excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            dt,
        )
        r2_json_key = _upload_file_to_r2(json_path, f"{project_name}.json", "json", "application/json", dt)
        print(f"    Uploaded to R2: {r2_excel_key} | {r2_json_key}")

    return {
        "project_name": project_name,
        "project_slug": project.get("slug"),
        "listings_count": int(len(df)),
        "sheets": {name: int(len(sdf)) for name, sdf in sheets.items()},
        "r2_excel_key": r2_excel_key,
        "r2_json_key": r2_json_key,
    }


# =============================================================================
# Run: load projects, process each, build + upload summary
# =============================================================================

def load_projects(jsonl_files: list) -> list:
    projects = []
    for path in jsonl_files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    projects.append(json.loads(line))
    return projects


def build_summary(project_results: list, dt: datetime) -> dict:
    return {
        "scraped_at": dt.isoformat(),
        "target_date": TARGET_DATE.strftime("%Y-%m-%d"),
        "saved_to_R2_date": dt.strftime("%Y-%m-%d"),
        "category_path": R2_CATEGORY_PATH,
        "total_projects_with_listings": len(project_results),
        "total_listings": sum(p["listings_count"] for p in project_results),
        "projects": project_results,
    }


def run_with_projects(projects: list, output_base_dir: str = "output/new_projects_listings",
                       upload_to_r2: bool = True) -> dict:
    print(f"Loaded {len(projects)} projects | target date (Dubai): {TARGET_DATE}")

    dt = datetime.now(timezone.utc)
    results = []

    for i, project in enumerate(projects, start=1):
        print(f"[{i}/{len(projects)}]", end=" ")
        try:
            result = process_project(project, output_base_dir, dt, upload_to_r2=upload_to_r2)
            if result:
                results.append(result)
        except Exception as e:
            print(f"  [ERROR] Project failed: {project.get('slug')}: {e}")

    summary = build_summary(results, dt)
    summary_dir = os.path.join(output_base_dir, "summary")
    os.makedirs(summary_dir, exist_ok=True)
    summary_path = os.path.join(summary_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(
        f"\nSaved summary: {summary_path} "
        f"({summary['total_projects_with_listings']} projects, {summary['total_listings']} listings)"
    )

    if upload_to_r2:
        r2_summary_key = _upload_file_to_r2(summary_path, "summary.json", "summary", "application/json", dt)
        print(f"Uploaded summary to R2: {r2_summary_key}")

    return summary


def run(new_projects_jsonl_files: list, output_base_dir: str = "output/new_projects_listings",
        upload_to_r2: bool = True) -> dict:
    projects = load_projects(new_projects_jsonl_files)
    return run_with_projects(projects, output_base_dir=output_base_dir, upload_to_r2=upload_to_r2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python new_projects_listings.py <projects_jsonl_file> [more_files...]")
        sys.exit(1)

    run(sys.argv[1:])