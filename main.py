import sys
import json
import time
import requests
from datetime import datetime

URL = "https://wd0ptz13zs-dsn.algolia.net/1/indexes/*/queries"

PARAMS = {
    "x-algolia-agent": "Algolia for JavaScript (4.24.0); Browser (lite)",
    "x-algolia-api-key": "cdd839b4fdac840289e88633779e8634",
    "x-algolia-application-id": "WD0PTZ13ZS",
}

CATEGORIES = {
    "used_cars": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/used-cars")',
    },
    "new_cars": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/used-cars") AND ("car_condition":"new")',
    },
    "export_cars": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/used-cars") AND ("is_export_car": True)',
    },
    "rental_cars": {
        "index": "by_added_desc_rental-cars.com",
        "filter": '("category_v2.slug_paths":"motors/rental-cars")',
    },
    "motorcycles": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/motorcycles")',
    },
    "auto_accessories_parts": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/auto-accessories-parts")',
    },
    "heavy_vehicles": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/heavy-vehicles")',
    },
    "boats": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/boats")',
    },
    "number_plates": {
        "index": "by_added_desc_motors.com",
        "filter": '("category_v2.slug_paths":"motors/number-plates")',
    },
}


def get_page_with_retry(category: dict, page: int, max_retries: int = 3) -> dict:
    """
    Fetch a page with retry mechanism (3 attempts)
    Returns: dict or None if all attempts fail
    """
    payload = {
        "requests": [{
            "indexName": category["index"],
            "query": "",
            "params": f"page={page}&hitsPerPage=25&filters={category['filter']}",
        }]
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(URL, params=PARAMS, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [Attempt {attempt}/{max_retries}] Page {page} failed: {e}")
            if attempt < max_retries:
                wait_time = attempt * 2  # 2, 4, 6 seconds
                print(f"  Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
    
    # All attempts failed
    return None


def run(category_name: str, start_page: int, end_page: int, output_jsonl: str) -> dict:
    """
    Run scraper for a specific category and page range
    """
    if category_name not in CATEGORIES:
        print(f"Unknown category: {category_name}")
        return {"success": 0, "failed": 0, "failed_pages": [], "total_pages": 0}

    category = CATEGORIES[category_name]
    print(f"Scraping {category_name} | pages {start_page}-{end_page}")

    hits = []
    failed_pages = []
    total_pages = end_page - start_page + 1

    for page in range(start_page, end_page + 1):
        print(f"  Processing page {page}...")
        
        # Try to get page with retry (3 attempts)
        data = get_page_with_retry(category, page, max_retries=3)
        
        if data is None:
            # All 3 attempts failed
            print(f"  [FAILED] Page {page} failed after 3 attempts, skipping...")
            failed_pages.append(page)
            continue  # Continue to next page
        
        # Success - process the data
        try:
            page_hits = data["results"][0]["hits"]
            print(f"  Page {page}: {len(page_hits)} listings")

            if not page_hits:
                print(f"  Page {page} has no results, stopping...")
                break

            hits.extend(page_hits)
            time.sleep(0.3)  # Delay between requests
            
        except Exception as e:
            print(f"  [ERROR] Page {page} data processing failed: {e}")
            failed_pages.append(page)

    # Save data
    with open(output_jsonl, "w", encoding="utf-8") as f:
        for hit in hits:
            f.write(json.dumps(hit, ensure_ascii=False) + "\n")

    # Save failed pages
    if failed_pages:
        failed_file = output_jsonl.replace(".jsonl", "_failed.txt")
        with open(failed_file, "w", encoding="utf-8") as f:
            f.write(f"Category: {category_name}\n")
            f.write(f"Total pages in this job: {total_pages}\n")
            f.write(f"Failed pages: {len(failed_pages)}\n")
            f.write(f"Failed percentage: {(len(failed_pages)/total_pages)*100:.2f}%\n\n")
            for p in failed_pages:
                f.write(f"page={p}\n")

    print(f"Saved {len(hits)} listings to {output_jsonl} | {len(failed_pages)} failed pages")
    
    return {
        "success": len(hits), 
        "failed": len(failed_pages),
        "failed_pages": failed_pages,
        "total_pages": total_pages
    }


if __name__ == "__main__":
    if len(sys.argv) == 4:
        category_name = sys.argv[1]
        start = int(sys.argv[2])
        end = int(sys.argv[3])
        output = f"{category_name}_{start}_{end}.jsonl"
        result = run(category_name, start, end, output)
        
        # Save results as JSON
        result_file = f"{category_name}_{start}_{end}_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({
                **result,
                "category": category_name,
                "start_page": start,
                "end_page": end,
                "timestamp": datetime.now().isoformat()
            }, f, indent=2)
    else:
        print("Usage: python main.py <category_name> <start_page> <end_page>")
        sys.exit(1)