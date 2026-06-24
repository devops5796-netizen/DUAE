import pandas as pd
from urllib.parse import urljoin
from scrapling import StealthyFetcher

BASE_URL = "https://qatarsale.com"

SHOWROOM_CATEGORIES = {
    "cars_for_sale": "https://qatarsale.com/ar/showroom-list/cars_for_sale",
    "cars_for_rent": "https://qatarsale.com/ar/showroom-list/cars_for_rent",
}

def get_showroom_links(category: str = "cars_for_sale") -> list[str]:
    url = SHOWROOM_CATEGORIES.get(category)
    if not url:
        raise ValueError(f"Unknown category: {category}")

    print(f"Fetching showroom list for: {category}")

    page = StealthyFetcher.fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=60000,
        wait_for_idle_network_timeout=10000
    )

    all_links = []

    for i in page.css("[data-testid='at-showroom-item-link-title'] a"):
        href = i.attrib.get("href", "")
        if href:
            all_links.append(urljoin(BASE_URL, href))

    all_links = list(dict.fromkeys(all_links))
    print(f"Found {len(all_links)} showrooms")
    return all_links

