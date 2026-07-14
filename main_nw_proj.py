import sys
import json
import time
import requests
import random
from urllib.parse import urlencode
from datetime import datetime
from datetime import datetime, timezone, timedelta
from request_tracker import tracker

URL = "https://wd0ptz13zs-1.algolianet.com/1/indexes/*/queries"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://uae.dubizzle.com",
    "referer": "https://uae.dubizzle.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

QUERY_PARAMS = {
    "x-algolia-agent": "Algolia for JavaScript (4.24.0); Browser (lite)",
    "x-algolia-api-key": "cdd839b4fdac840289e88633779e8634",
    "x-algolia-application-id": "WD0PTZ13ZS",
}

ATTRIBUTES_TO_RETRIEVE = (
    '["building","categories_v2","city","developer","coordinates",'
    '"downpayment","handover_date","images","name","neighborhoods",'
    '"project_status","slug","starting_price","absolute_url",'
    '"unit_type_categories","location","completion_percentage",'
    '"description","project_id","payment_plan_breakdown","location_path",'
    '"has_cpl_whatsapp","is_cpl_project","is_cpl_location",'
    '"has_agency_lead_whatsapp","bedrooms","bathrooms",'
    '"child_status_breakdown","is_master_project","_geoloc"]'
)

INDEX_NAME = "property_new_projects.com"
FILTERS = '("categories_v2.slug_paths":"property-for-sale/residential")'
HITS_PER_PAGE = 35


def get_page_with_retry(page: int, max_retries: int = 3) -> dict:
    algolia_params = {
        "page": page,
        "attributesToHighlight": "[]",
        "hitsPerPage": HITS_PER_PAGE,
        "attributesToRetrieve": ATTRIBUTES_TO_RETRIEVE,
        "facets": '["language"]',
        "filters": FILTERS,
    }
    payload = {
        "requests": [{
            "indexName": INDEX_NAME,
            "query": "",
            "params": urlencode(algolia_params),
        }]
    }

    for attempt in range(1, max_retries + 1):
        try:
            tracker.log_request(source="product_detail")
            r = requests.post(URL, params=QUERY_PARAMS, headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [Attempt {attempt}/{max_retries}] Page {page} failed: {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)

    return None

TARGET_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)


def filter_yesterday_hits(hits):
    filtered = []

    for hit in hits:
        created_at = hit.get("created_at")

        if created_at is None:
            continue

        try:
            dt = datetime.fromtimestamp(int(created_at), tz=timezone.utc)

            if dt.date() == TARGET_DATE:
                filtered.append(hit)

        except (ValueError, TypeError):
            pass

    return filtered

def run(start_page: int, end_page: int, output_jsonl: str) -> dict:
    print(f"Scraping new_projects | pages {start_page}-{end_page}")

    hits = []
    failed_pages = []
    total_pages = end_page - start_page + 1

    for page in range(start_page, end_page + 1):
        print(f"  Processing page {page}...")
        data = get_page_with_retry(page)

        if data is None:
            print(f"  [FAILED] Page {page} failed after retries, skipping...")
            failed_pages.append(page)
            continue

        try:
            # page_hits = data["results"][0]["hits"]
            # print(f"  Page {page}: {len(page_hits)} listings")

            # if not page_hits:
            #     print(f"  Page {page} has no results, stopping...")
            #     break

            # hits.extend(page_hits)

            page_hits = data["results"][0]["hits"]
            if not page_hits:
                print(f"  Page {page} has no results, stopping...")
                break
            filtered_hits = filter_yesterday_hits(page_hits)
            print(
                f"  Page {page}: {len(page_hits)} listings "
                f"-> kept {len(filtered_hits)}"
            )
            hits.extend(filtered_hits)
            delay = random.uniform(0.5, 2.0)
            time.sleep(delay)

        except Exception as e:
            print(f"  [ERROR] Page {page} data processing failed: {e}")
            failed_pages.append(page)

    with open(output_jsonl, "w", encoding="utf-8") as f:
        for hit in hits:
            f.write(json.dumps(hit, ensure_ascii=False) + "\n")

    if failed_pages:
        failed_file = output_jsonl.replace(".jsonl", "_failed.txt")
        with open(failed_file, "w", encoding="utf-8") as f:
            f.write(f"Category: new_projects\n")
            f.write(f"Total pages in this job: {total_pages}\n")
            f.write(f"Failed pages: {len(failed_pages)}\n\n")
            for p in failed_pages:
                f.write(f"page={p}\n")

    stats_file = f"request_stats_{start}_{end}.json"
    stats = tracker.save(stats_file)

    print(f"\n--- Combined Request Stats ---")
    print(f"Total: {stats['total_requests']} req | {stats['total_req_per_min']} req/min")
    print(f"By source: {stats['per_source']}")
    for worker, s in stats["per_worker"].items():
        print(f"  {worker}: {s['requests']} req | {s['req_per_min']} req/min")

    print(f"Saved {len(hits)} listings to {output_jsonl} | {len(failed_pages)} failed pages")

    return {
        "success": len(hits),
        "failed": len(failed_pages),
        "failed_pages": failed_pages,
        "total_pages": total_pages
    }


if __name__ == "__main__":
    if len(sys.argv) == 3:
        start = int(sys.argv[1])
        end = int(sys.argv[2])
        output = f"new_projects_{start}_{end}.jsonl"
        result = run(start, end, output)

        result_file = f"new_projects_{start}_{end}_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({**result, "start_page": start, "end_page": end,
                       "timestamp": datetime.now().isoformat()}, f, indent=2)
    else:
        print("Usage: python main.py <start_page> <end_page>")
        sys.exit(1)