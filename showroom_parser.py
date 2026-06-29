from scrapling import StealthyFetcher

BASE_URL = "https://qatarsale.com"


# -------------------------
# DETAILS
# -------------------------


def parse_showroom_details(page, url: str) -> dict:
    name = ""
    cover_image = ""
    phones = []
    whatsapps = []
    posts_count = ""
    views_count = ""

    name_el = page.css("[data-testid='at-showroom-details-name-text'] h1")
    if name_el:
        name = name_el[0].text.strip()

    img_el = page.css("[data-testid='at-showroom-details-cover-image'] img")
    if img_el:
        cover_image = img_el[0].attrib.get("src", "")

    phone_blocks = page.css("[data-testid^='at-showroom-details-phone-link']")

    for p in phone_blocks:
        href = p.attrib.get("href", "")
        if href.startswith("tel:"):
            phones.append(href.replace("tel:", "").strip())

    whatsapp_blocks = page.css("[data-testid='at-showroom-details-whatsapp-link']")
    for w in whatsapp_blocks:
        href = w.attrib.get("href", "")
        if "phone=" in href:
            num = href.split("phone=")[-1].strip()
            whatsapps.append(num)

    posts_el = page.css("[data-testid='at-showroom-details-posts-count-text']")
    if posts_el:
        posts_count = posts_el[0].text.strip()

    views_el = page.css("[data-testid='at-showroom-details-posts-view-text']")
    if views_el:
        views_count = views_el[0].text.strip()

    return {
        "url": url,
        "name": name,
        "cover_image": cover_image,
        "phones": str(phones),
        "whatsapps": str(whatsapps),
        "posts_count": posts_count,
        "views_count": views_count
    }


# -------------------------
# PAGES COUNT (IMPORTANT FIX)
# -------------------------
def get_max_pages(page):
    pages = page.css("ul li.numbers a[href*='page=']")
    nums = []

    for p in pages:
        href = p.attrib.get("href", "")
        if "page=" in href:
            try:
                nums.append(int(href.split("page=")[-1]))
            except:
                pass

    return max(nums) if nums else 1


# -------------------------
# PRODUCT LINKS ONLY
# -------------------------
def extract_product_links(page):
    links = []
    
    items = page.css("qs-product-card-v2 a[href*='/product/']")
    
    for it in items:
        href = it.attrib.get("href", "")
        if href:
            if href.startswith("/"):
                href = BASE_URL + href
            links.append(href)
    
    return list(set(links))


# -------------------------
# MAIN SCRAPER
# -------------------------
def scrape_showroom(showroom_url):
    print(f"\nScraping: {showroom_url}")

    try:
        page = StealthyFetcher.fetch(
            showroom_url,
            headless=True,
            network_idle=True,
            timeout=60000,
            wait_for_idle_network_timeout=10000
        )
    except Exception as e:
        print(f"  [ERROR] Failed to fetch showroom page: {e}")
        return {}, []
    
    details = parse_showroom_details(page, showroom_url)
    max_pages = get_max_pages(page)
    print(f"Pages: {max_pages}")

    all_products = set(extract_product_links(page))
    print(f"  Page 1: {len(all_products)} products")

    for p in range(2, max_pages + 1):
        url = f"{showroom_url}?page={p}"
        try:
            pg = StealthyFetcher.fetch(
                url,
                headless=True,
                network_idle=True,
                timeout=60000,
                wait_for_idle_network_timeout=10000
            )
            links = extract_product_links(pg)
            print(f"  Page {p}: {len(links)} products")
            all_products.update(links)
        except Exception as e:
            print(f"  [ERROR] Page {p}: {e}")
            continue

    product_list = list(all_products)

    if not product_list:
        print(f"  [INFO] No products found in {showroom_url}")

    return details, product_list