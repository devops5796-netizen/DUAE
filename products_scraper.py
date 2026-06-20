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
    title = price = currency = listing_type = posted_time = description = ""
    showroom_name = showroom_url = sold_date = ""
    seller_type = ""  
    condition = ""    
    view_count = fans_count = "0"
    images = []
    phones = []       
    whatsapps = []    
    specs = {}

    title_el = page.find("[data-testid='at-show-product-info-market-title-text']") or page.find("h1")
    if title_el:
        title = title_el.text.strip()

    price_el = page.find("[data-testid='at-show-product-info-startingPrice-text']")
    if price_el:
        price = price_el.text.strip()
        
    curr_el = page.find(".product-price p:not([data-testid])")
    if curr_el:
        currency = curr_el.text.strip()

    posted_el = page.find("[data-testid='at-show-product-info-productPosted-text']")
    if posted_el:
        posted_time = posted_el.text.strip()

    view_el = page.find("[data-testid='at-show-product-info-viewCount-text']")
    if view_el:
        view_count = view_el.text.strip()

    fans_el = page.find("[data-testid='at-show-product-info-fansCount-text']")
    if fans_el:
        fans_count = fans_el.text.strip()

    type_el = page.find("[data-testid='at-show-product-info-forSale-text']")
    if type_el:
        listing_type = type_el.attrib.get("title", "").strip() or type_el.text.strip()

    sold_el = page.find("[data-testid='at-show-product-info-soldDate-text']")
    if sold_el:
        sold_date = sold_el.text.strip()
    
    expired_el = page.find("[data-testid='at-show-product-info-expiredOn-text']")
    if expired_el:
        expired_on = expired_el.text.strip()
    else:
        expired_on = ""

    desc_el = page.find("[data-testid='at-show-product-description-text']")
    if desc_el:
        description = desc_el.text.strip()

    seller_type_el = page.css("[data-testid='at-show-product-info-personal-name-text']")
    seller_type = seller_type_el[0].get_all_text(strip=True) if seller_type_el else ""

    condition_el = page.css("[data-testid='at-show-product-info-conditionNew-text']")
    condition = condition_el[0].get_all_text(strip=True) if condition_el else ""

    showroom_el = page.css("[data-testid='at-show-product-info-showroom-name-text']")

    if showroom_el:
        showroom_name = showroom_el[0].get_all_text(strip=True)
        showroom_url = showroom_el[0].attrib.get("href", "")
    else:
        showroom_name = ""
        showroom_url = ""

    # Extract phone numbers and WhatsApp numbers from server-side state
    phones = []
    whatsapps = []

    state_script = page.find("script#serverApp-state")
    latitude = longitude = None

    if state_script:
        try:
            raw = (
                state_script.text
                .replace("&q;", '"')
                .replace("&l;", "<")
                .replace("&a;", "&")
                .replace("&s;", "'")
            )
            state_data = json.loads(raw)
            product = (
                state_data
                .get("product", {})
                .get("product", {})
            )
            owner = product.get("owner", {})

            # Phones & WhatsApp — contactBy: 0=phone, 1=whatsapp, 2=both
            for phone_data in owner.get("phones", []):
                phone_number = phone_data.get("phone", "").strip()
                if not phone_number:
                    continue
                contact_by = phone_data.get("contactBy", 0)
                if contact_by in (0, 2):
                    phones.append(phone_number)
                if contact_by in (1, 2):
                    whatsapps.append(phone_number)

            # Lat / Lng
            location = product.get("location", {})
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            
            # Images from state
            for img_url in product.get("images", []):
                if img_url and img_url not in images:
                    images.append(img_url)

        except Exception as e:
            print(f"Failed to parse state data: {e}")
            latitude = longitude = None

    labels = page.find_all("[data-testid^='at-show-product-parsedDefs-label-text-']")
    values = page.find_all("[data-testid^='at-show-product-parsedDefs-value-text-']")
    
    if labels and values:
        for lbl, val in zip(labels, values):
            key = lbl.text.strip()
            value = val.text.strip()
            if key:
                specs[key] = value

    return {
        "title": title,
        "price": price,
        "currency": currency,
        "listing_type": listing_type,
        "condition": condition,        
        "seller_type": seller_type,    
        "posted_time": posted_time,
        "sold_date": sold_date,
        "expired_on": expired_on,
        "view_count": view_count,
        "fans_count": fans_count,
        "showroom_name": showroom_name,
        "showroom_url": showroom_url,  
        "description": description,
        "latitude": latitude,
        "longitude": longitude,
        "images": images,
        "images_count": len(images),
        "phones": phones,        
        "whatsapps": whatsapps,  
        "specs": specs           
    }


def download_images(images: list, category: str = "", fmt: str = "PNG") -> list:
    r2_paths = []
    uploaded = 0
    failed = 0

    if fmt.upper() == "JPG":
        ext = "jpg"
        content_type = "image/jpeg"
    else:
        ext = "png"
        content_type = "image/png"

    for img_url in images:
        original_name = img_url.split("/")[-1].rsplit(".", 1)[0]
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
                    filename=f"{original_name}.{ext}",
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
        data = parse_product(page)
        data["images_local_paths"] = download_images(data.get("images", []), category=category)
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
                row = {
                    "product_url": url,
                    "title": data.get("title"),
                    "price": data.get("price"),
                    "currency": data.get("currency"),
                    "listing_type": data.get("listing_type"),
                    "condition": data.get("condition"),
                    "seller_type": data.get("seller_type"),
                    "showroom_name": data.get("showroom_name"),
                    "showroom_url": data.get("showroom_url"),
                    "posted_time": data.get("posted_time"),
                    "sold_date": data.get("sold_date"),
                    "expired_on": data.get("expired_on"),
                    "fans_count": data.get("fans_count"),
                    "view_count": data.get("view_count"),
                    "description": data.get("description"),
                    "phones": data.get("phones", []),
                    "whatsapps": data.get("whatsapps", []),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                    "images": data.get("images", []),
                    "images_count": data.get("images_count"),
                    "specifications": data.get("specs", {}),
                    "images_local_paths": data.get("images_local_paths", [])
                }
                with lock:
                    with open(output_json, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                with lock:
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
                    row = {
                        "product_url": url,
                        "title": data.get("title"),
                        "price": data.get("price"),
                        "currency": data.get("currency"),
                        "listing_type": data.get("listing_type"),
                        "condition": data.get("condition"),
                        "seller_type": data.get("seller_type"),
                        "showroom_name": data.get("showroom_name"),
                        "showroom_url": data.get("showroom_url"),
                        "posted_time": data.get("posted_time"),
                        "sold_date": data.get("sold_date"),
                        "fans_count": data.get("fans_count"),
                        "view_count": data.get("view_count"),
                        "description": data.get("description"),
                        "phones": data.get("phones", []),
                        "whatsapps": data.get("whatsapps", []),
                        "latitude": data.get("latitude"),
                        "longitude": data.get("longitude"),
                        "images": data.get("images", []),
                        "images_count": data.get("images_count"),
                        "specifications": data.get("specs", {}),
                        "images_local_paths": data.get("images_local_paths", [])
                    }
                    with lock:
                        with open(output_json, "a", encoding="utf-8") as f:
                            f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    with lock:
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