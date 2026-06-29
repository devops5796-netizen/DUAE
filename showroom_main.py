import sys
import time
import pandas as pd

import showroom_links_scraper
import showroom_parser
import products_scraper
import flatten
import excel_writer
from products_scraper import download_images
from dotenv import load_dotenv
load_dotenv()


def process_showroom(url, jsonl_file, category_key: str):
    slug = url.split("/ar/showroom/")[-1].split("/")[0] if "/ar/showroom/" in url else "showroom"

    for attempt in range(3):
        try:
            details, product_links = showroom_parser.scrape_showroom(url)

            if not product_links:
                print(f"  [EMPTY] No products in {slug}")
                return None, "empty"

            tmp_csv = f"tmp_{slug}.csv"
            pd.DataFrame({"product_url": product_links}).to_csv(tmp_csv, index=False)

            products_scraper.run(
                links_csv=tmp_csv,
                output_json=jsonl_file,
                workers=6,
                category=f"showrooms_{category_key}"
            )

            df = flatten.run(jsonl_file)["df"]

            if details.get("cover_image"):
                r2 = download_images(
                    [details["cover_image"]],
                    product_url=url,
                    category=f"showrooms_{category_key}"
                )
                details["r2_image"] = r2[0] if r2 else ""

            for k, v in details.items():
                df[k] = v

            return df, "success"

        except Exception as e:
            print(f"  [Attempt {attempt+1}/3] failed: {e}")
            time.sleep(2)

    print(f"  [FAILED] Skipping: {url}")
    return None, "failed"


def run_single_showroom(url, category_key: str = "cars_for_sale"):
    slug = url.split("/ar/showroom/")[-1].split("/")[0] if "/ar/showroom/" in url else "showroom"
    jsonl_file = f"products_{slug}.jsonl"

    df, status = process_showroom(url, jsonl_file, category_key)

    if status == "success" and df is not None and not df.empty:
        sheets = {slug: df}
        excel_writer.write(sheets, f"showroom_{slug}.xlsx")
        print(f"  ✓ Saved: showroom_{slug}.xlsx")
        return True
    elif status == "empty":
        empty_df = pd.DataFrame({"status": ["empty - no products found"]})
        excel_writer.write({slug: empty_df}, f"showroom_{slug}.xlsx")
        print(f"  ⚠ Empty marker saved: showroom_{slug}.xlsx")

    else:
        print(f"  ✗ Failed: {slug}")
        return False


if __name__ == "__main__":
    # Usage:
    #   python showroom_main.py <url> <category_key>
    #   python showroom_main.py https://qatarsale.com/ar/showroom/xyz cars_for_rent
    if len(sys.argv) > 1:
        url = sys.argv[1]
        cat = sys.argv[2] if len(sys.argv) > 2 else "cars_for_sale"
        run_single_showroom(url, cat)

