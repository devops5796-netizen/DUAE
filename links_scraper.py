import json
import random
import time
import pandas as pd
from scrapling import StealthyFetcher

BASE_URL = "https://qatarsale.com"
BASE_PRODUCT_URL = "https://qatarsale.com/ar/product"


def extract_products_from_state(page, source_url: str) -> list:
    rows = []
    try:
        script = page.find("script", {"id": "serverApp-state"})
        if not script:
            return []

        raw = (script.text
               .replace("&q;", '"')
               .replace("&l;", "<")
               .replace("&g;", ">")
               .replace("&a;", "&")
               .replace("&s;", "'"))

        data = json.loads(raw)

        if "ProductList" not in data:
            return []

        products  = data["ProductList"]["list"]
        defs_meta = {str(d["id"]): d["label"] for d in data["ProductList"].get("defsMetaData", [])}

        for product in products:
            specs = {defs_meta[k]: v for k, v in product.get("definitions", {}).items() if k in defs_meta}
            row   = {k: v for k, v in product.items() if k != "definitions"}
            row.update(specs)
            row["source_url"]  = source_url
            row["product_url"] = f"{BASE_PRODUCT_URL}/{product.get('uri', '')}" if product.get("uri") else ""
            rows.append(row)

    except Exception as e:
        print(f"  Error parsing state: {e}")

    return rows


def run(listing_url: str, start_page: int, end_page: int, output_csv: str):
    print("\n" + "="*50)
    print("STEP 1: Scraping listing pages for links...")
    print("="*50)

    all_rows     = []
    failed_pages = {}
    success_count = 0

    for page_num in range(start_page, end_page + 1):
        url = f"{listing_url}&page={page_num}"
        print(f"Page {page_num}/{end_page}: {url}")

        for attempt in range(3):
            try:
                page = StealthyFetcher.fetch(
                    url,
                    headless=True,
                    network_idle=True,
                    timeout=60000,
                    wait_for_idle_network_timeout=10000
                )

                rows = extract_products_from_state(page, url)

                if rows:
                    all_rows.extend(rows)
                    success_count += 1
                    print(f"  ✓ Found {len(rows)} products")
                    break
                else:
                    failed_pages[f"Page {page_num}"] = "No products found"
                    print(f"  ⚠ No products found")
                    break

            except Exception as e:
                if attempt < 2:
                    print(f"  Attempt {attempt+1} failed, retrying...")
                    time.sleep(3)
                else:
                    failed_pages[f"Page {page_num}"] = str(e)
                    print(f"  Error: {e}")

        if page_num < end_page:
            time.sleep(random.uniform(2.0, 5.0))

    df = pd.DataFrame(all_rows)
    
    # deduplicate
    if "product_url" in df.columns:
        df = df.drop_duplicates(subset=["product_url"], keep="first")

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"  Saved {len(df)} products to {output_csv}")

    return {
        "success":      success_count,
        "failed":       len(failed_pages),
        "total_links":  len(df)
    }


if __name__ == "__main__":
    result = run(
        listing_url="https://qatarsale.com/ar/products/wrist_watches-watches?basic_search:StatusFilter=0",
        start_page=1,
        end_page=5,
        output_csv="product_links.csv",
    )