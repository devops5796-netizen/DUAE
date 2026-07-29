import os
import random
import time

import pandas as pd
from camoufox.sync_api import Camoufox

BASE_URL = "https://uae.dubizzle.com/property-agencies/{slug}/"

BUTTON_SELECTORS = [
    '[data-testid="profile-call-button"]',
    'button:has-text("Call")',
    '[data-testid="call-cta-button"]',
    '[data-testid*="phone" i]',
    '[data-testid*="call" i]',
]

CHALLENGE_MARKERS = [
    "Pardon Our Interruption",
    "Additional security check is required",
    "I am human",
    "hCaptcha",
    "reeseSkipExpirationCheck",
]


def _is_challenge_page(html: str) -> bool:
    return any(marker in html for marker in CHALLENGE_MARKERS)




def _safe_content(page, retries=3, delay=1500):
    for attempt in range(retries):
        try:
            return page.content()
        except Exception:
            if attempt == retries - 1:
                raise
            page.wait_for_timeout(delay)
    return ""


def _reveal_agency_phone(page, timeout_ms=10000):
    captured = {"data": None}

    def handle_response(response):
        if "graphql" not in response.url:
            return
        try:
            post_data = response.request.post_data or ""
        except Exception:
            post_data = ""
        if "contactPhoneNumber" in post_data and response.status == 200:
            try:
                captured["data"] = response.json()
            except Exception:
                pass

    page.on("response", handle_response)

    button = None
    for selector in BUTTON_SELECTORS:
        loc = page.locator(selector).first
        try:
            if loc.is_visible(timeout=3500):
                button = loc
                break
        except Exception:
            continue

    if button is None:
        page.remove_listener("response", handle_response)
        return None, "button_not_found"

    try:
        button.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        try:
            button.click(timeout=6000)
        except Exception:
            button.click(force=True)

        waited = 0
        while captured["data"] is None and waited < timeout_ms:
            page.wait_for_timeout(400)
            waited += 400
    except Exception as e:
        page.remove_listener("response", handle_response)
        return None, f"click_error: {e}"
    finally:
        page.remove_listener("response", handle_response)

    if captured["data"] is None:
        return None, "no_response_captured"

    phone = (
        captured["data"]
        .get("data", {})
        .get("agency", {})
        .get("contactPhoneNumber")
    )
    return phone, "ok"


def enrich_agencies_with_phone(
    df: pd.DataFrame,
    slug_column: str = "slug",
    headless: bool = False,
    min_delay: float = 10,
    max_delay: float = 20,
    save_every: int = 25,
    checkpoint_path: str = "agencies_with_phone_checkpoint.xlsx",
    resume: bool = True,
    max_new: int = None,
) -> pd.DataFrame:
    df = df.copy()

    already_done = {}  # slug -> (phone, status)
    if resume and os.path.exists(checkpoint_path):
        try:
            prev_df = pd.read_excel(checkpoint_path)
            for _, prow in prev_df.iterrows():
                slug = prow.get(slug_column)
                status = prow.get("_scrape_status")
                if slug and pd.notna(status) and status not in ("imperva_challenge", "button_not_found"):
                    already_done[slug] = (prow.get("contact_phone_number"), status)
            print(f"Resuming: found {len(already_done)} already-processed agencies in checkpoint.")
        except Exception as e:
            print(f"Could not read checkpoint for resume ({e}), starting fresh.")

    phones = [None] * len(df)
    statuses = [None] * len(df)

    for pos, (idx, row) in enumerate(df.iterrows()):
        slug = row.get(slug_column)
        if slug in already_done:
            phones[pos], statuses[pos] = already_done[slug]

    def save_checkpoint():
        partial_df = df.copy()
        partial_df["contact_phone_number"] = phones
        partial_df["_scrape_status"] = statuses
        partial_df.to_excel(checkpoint_path, index=False)

    new_processed_count = 0
    consecutive_soft_fails = 0
    SOFT_FAIL_THRESHOLD = 3

    # Initializing Camoufox instead of standard Playwright + Stealth
    with Camoufox(
        headless=True,
        humanize=True,
        geoip=True,
        block_images=False
    ) as browser:
        page = browser.new_page()

        for pos, (idx, row) in enumerate(df.iterrows()):
            slug = row.get(slug_column)

            if slug in already_done:
                continue

            if max_new is not None and new_processed_count >= max_new:
                print(f"Reached max_new limit ({max_new}), stopping this run.")
                break

            if not slug:
                statuses[pos] = "no_slug"
                print(f"[{pos + 1}/{len(df)}] Skipped - no slug")
                continue

            url = BASE_URL.format(slug=slug)
            print(f"[{pos + 1}/{len(df)}] {slug}")

            attempt_result = None
            for attempt_num in range(2):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(random.uniform(10000, 15000))

                    html = _safe_content(page)
                    """if _is_challenge_page(html):
                        print("  -> Challenge page detected (Imperva/hCaptcha), stopping batch.")
                        statuses[pos] = "imperva_challenge"
                        save_checkpoint()
                        attempt_result = "imperva_break"
                        break"""
                    if _is_challenge_page(html):
                        print("Challenge detected")

                        page.screenshot(path="imperva.png", full_page=True)

                        with open("imperva.html", "w", encoding="utf-8") as f:
                            f.write(html)

                        print(page.url)
                        print(page.title())

                        input("Press Enter to close...")

                        statuses[pos] = "imperva_challenge"
                        save_checkpoint()
                        attempt_result = "imperva_break"
                        break

                    phone, status = _reveal_agency_phone(page)
                    phones[pos] = phone
                    statuses[pos] = status
                    print(f"  -> phone: {phone} (status: {status})")

                    if status == "button_not_found":
                        consecutive_soft_fails += 1
                        try:
                            safe_slug = slug.replace("/", "_")
                            page.screenshot(
                                path=f"debug_no_button_{safe_slug}.png", full_page=True
                            )
                            page_text = page.locator("body").inner_text()[:500]
                            print(f"     [DEBUG] Page title: {page.title()}")
                            print(f"     [DEBUG] Body text snippet: {page_text[:200]!r}")
                        except Exception as e:
                            print(f"     [DEBUG] Screenshot failed: {e}")
                    else:
                        consecutive_soft_fails = 0

                    attempt_result = "done"
                    break

                except Exception as e:
                    if attempt_num == 0:
                        print(f"  -> Transient error, retrying once: {e}")
                        page.wait_for_timeout(2000)
                        continue
                    statuses[pos] = f"error: {e}"
                    print(f"  -> FAILED after retry: {e}")
                    attempt_result = "failed"

            if attempt_result == "imperva_break":
                break

            if consecutive_soft_fails >= SOFT_FAIL_THRESHOLD:
                print(
                    f"\n⚠️  {consecutive_soft_fails} consecutive 'button_not_found' results - "
                    "this looks like a soft rate-limit/reputation warning from Imperva, "
                    "not real missing buttons. Stopping this run early to avoid a full block."
                )
                save_checkpoint()
                break

            new_processed_count += 1

            if new_processed_count % save_every == 0:
                save_checkpoint()
                print(f"  [Checkpoint saved - {new_processed_count} new rows this run]")

            if pos < len(df) - 1:
                time.sleep(random.uniform(min_delay, max_delay))

        page.close()

    save_checkpoint() 
    print(f"\nThis run processed {new_processed_count} new agencies.")

    df["contact_phone_number"] = phones
    df["_scrape_status"] = statuses
    return df


if __name__ == "__main__":
    start = 30
    end = 45
    agencies_df = pd.read_csv("property_agencies.csv")[start:end]

    result_df = enrich_agencies_with_phone(agencies_df, max_new=100, checkpoint_path="agencies_checkpoint.xlsx")

    result_df.to_excel(f"agencies_with_phone_{start}_{end}.xlsx", index=False)
    result_df.to_csv(f"agencies_with_phone_{start}_{end}.csv", index=False, encoding="utf-8-sig")

    total = len(result_df)
    with_phone = result_df["contact_phone_number"].notna().sum()
    attempted = result_df["_scrape_status"].notna().sum()
    print(f"\nProgress so far: {attempted}/{total} attempted, {with_phone} have a phone number")

