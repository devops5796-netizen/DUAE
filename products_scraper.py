import json
import os
import threading
import pandas as pd
import requests as req
from PIL import Image
import io
from r2_uploader import upload_buffer

from scrapling import StealthyFetcher
from concurrent.futures import ThreadPoolExecutor, as_completed

def parse_product(page) -> dict:
    state_script = page.find("script#serverApp-state")
    
    if not state_script:
        return {}

    try:
        raw = (
            state_script.text
            .replace("&q;", '"')
            .replace("&l;", "<")
            .replace("&g;", ">")
            .replace("&a;", "&")
            .replace("&s;", "'")
        )
        state_data = json.loads(raw)
    except Exception as e:
        print(f"  Failed to parse state: {e}")
        return {}

    if "product" not in state_data or "product" not in state_data["product"]:
        return {}

    product = state_data["product"]["product"]
    
    defs_meta = {str(d["id"]): d["label"] for d in state_data["product"].get("defsMetaData", [])}
    specs = {defs_meta[k]: v for k, v in product.get("definitions", {}).items() if k in defs_meta}

    phones, whatsapps = [], []
    owner = product.get("owner", {})
    for phone_data in owner.get("phones", []):
        number = phone_data.get("phone", "").strip()
        if not number:
            continue
        contact_by = phone_data.get("contactBy", 0)
        if contact_by in (0, 2):
            phones.append(number)
        if contact_by in (1, 2):
            whatsapps.append(number)

    row = {k: v for k, v in product.items() if k != "definitions"}
    row.update(specs)
    row["phones"] = phones
    row["whatsapps"] = whatsapps

    return row


def download_images(images: list, product_url: str = "", category: str = "", fmt: str = "PNG") -> list:
    r2_paths = []
    uploaded = 0
    failed = 0

    if fmt.upper() == "JPG":
        ext = "jpg"
        content_type = "image/jpeg"
    else:
        ext = "png"
        content_type = "image/png"

    slug = product_url.rstrip("/").split("/")[-1] if product_url else "unknown"

    for idx, img_url in enumerate(images, start=1):
        filename = f"{slug}-{idx}.{ext}" 
        try:
            r = req.get(img_url, timeout=15)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                output_buffer = io.BytesIO()
                if fmt.upper() == "JPG":
                    img = img.convert("RGB")
                    img.save(output_buffer, format="JPEG", quality=90)
                else:
                    img.save(output_buffer, format="PNG")
                r2_key = upload_buffer(
                    output_buffer,
                    filename=filename,
                    category=category,
                    file_type="images",
                    content_type=content_type
                )
                if r2_key:
                    r2_paths.append(r2_key)
                    uploaded += 1
                else:
                    failed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    print(f"  Images: {uploaded} uploaded, {failed} failed out of {len(images)}")
    return r2_paths


def scrape_single(url: str, category: str = "") -> dict:
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=60000,
            wait_for_idle_network_timeout=10000
        )
        
        if "not-found" in str(page.url):
            print(f"  Redirected to not-found: {url}")
            return {}
        
        data = parse_product(page)
        if not data:
            return {}
        data["product_url"] = url
        data["images_local_paths"] = download_images(
            data.get("images", []),
            product_url=url,
            category=category
        )
        return data
    except Exception as e:
        print(f"  Error URL: {url} -> {e}")
        return {}
        
def run(links_csv: str, output_json: str, workers: int = 5, category: str = ""):
    print("\n" + "="*50)
    print(f"STEP 2: Scraping product pages ({workers} workers)...")
    print("="*50)

    if not os.path.exists(links_csv):
        print(f"ERROR: '{links_csv}' not found!")
        return {"success": 0, "failed": 0}

    urls = pd.read_csv(links_csv)["product_url"].tolist()
    print(f"Loaded {len(urls)} URLs")

    scraped_urls = set()
    if os.path.exists(output_json):
        with open(output_json, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    scraped_urls.add(row.get("product_url", ""))
                except Exception:
                    pass
        print(f"Skipping {len(scraped_urls)} already scraped")

    urls_to_scrape = [u for u in urls if u not in scraped_urls]
    print(f"Remaining: {len(urls_to_scrape)} URLs")

    if not urls_to_scrape:
        print("All URLs already scraped!")
        return {"success": 0, "failed": 0}

    counters = {"success": 0, "failed": 0}
    lock = threading.Lock()
    
    failed_urls = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scrape_single, url, category): url for url in urls_to_scrape}

        for future in as_completed(futures):
            url = futures[future]
            try:
                data = future.result(timeout=120)
            except Exception as e:
                print(f"  Timeout/Error: {url} -> {e}")
                data = {}
                future.cancel()

            if data:
                with lock:
                    with open(output_json, "a", encoding="utf-8") as f:
                        f.write(json.dumps(data, ensure_ascii=False) + "\n")
                    counters["success"] += 1
                print(f"  Saved: {data.get('title', 'OK')}")
            else:
                with lock:
                    counters["failed"] += 1
                    failed_urls.append(url)
                print(f"  Failed: {url}")
    
    # Retry failed URLs
    if failed_urls:
        print(f"\nRetrying {len(failed_urls)} failed URLs...")
        still_failed = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(scrape_single, url, category): url for url in failed_urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    data = future.result(timeout=120)
                except Exception as e:
                    print(f"  Timeout/Error: {url} -> {e}")
                    data = {}
                    future.cancel()
                if data:
                    with lock:
                        with open(output_json, "a", encoding="utf-8") as f:
                            f.write(json.dumps(data, ensure_ascii=False) + "\n")
                        counters["success"] += 1
                        counters["failed"] -= 1
                    print(f"  Saved: {data.get('title', 'OK')}")
                else:
                    still_failed.append(url)

        if still_failed:
            report_file = output_json.replace(".jsonl", "_failed.txt")
            with open(report_file, "w", encoding="utf-8") as f:
                for u in still_failed:
                    f.write(u + "\n")
            print(f"Saved {len(still_failed)} still-failed URLs to {report_file}")

    print(f"\nSTEP 2 DONE: {counters['success']} OK | {counters['failed']} failed")
    return counters