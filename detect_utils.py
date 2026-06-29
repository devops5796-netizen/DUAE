import json
from scrapling import StealthyFetcher

def get_last_page(url: str) -> int:
    page = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=90000)
    
    product_cards = page.find_all("qs-product-card-v2")
    if not product_cards:
        product_cards = page.find_all("qs-product-card-classic")
    if not product_cards:
        return 0

    numbers = []
    pagination_els = page.find_all("[data-testid^='at-paginator-page-']")
    for el in pagination_els:
        a = el.find("a")
        if not a:
            continue
        href = a.attrib.get("href", "")
        if "page=" in href:
            try:
                numbers.append(int(href.split("page=")[-1]))
            except ValueError:
                pass
    return max(numbers) if numbers else 1