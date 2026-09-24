"""
detect_pages.py

Fetches page 0 of the new_projects Algolia index to read nbHits/nbPages,
splits the page range into fixed-size chunks, and writes a GitHub Actions
matrix (list of {start_page, end_page}) to $GITHUB_OUTPUT so the scraping
job can fan out across parallel matrix runs instead of a hardcoded range.
"""

import json
import os
import sys

from main_nw_proj import get_page_with_retry


def build_matrix(nb_pages: int, chunk_size: int) -> dict:
    chunks = []
    for start in range(0, nb_pages, chunk_size):
        end = min(start + chunk_size - 1, nb_pages - 1)
        chunks.append({"start_page": start, "end_page": end})
    return {"include": chunks}


def main():
    chunk_size = int(os.environ.get("CHUNK_SIZE", "5"))

    data = get_page_with_retry(0)
    if data is None:
        print("Failed to fetch page 0 to detect nbPages", file=sys.stderr)
        sys.exit(1)

    try:
        result = data["results"][0]
        nb_pages = int(result["nbPages"])
        nb_hits = int(result["nbHits"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"Unexpected response shape, could not read nbPages: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Detected {nb_hits} hits across {nb_pages} pages (chunk_size={chunk_size})")

    matrix = build_matrix(nb_pages, chunk_size)
    print(f"Matrix: {json.dumps(matrix)}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        print("GITHUB_OUTPUT not set (not running in Actions?) — printing only.")
        return

    with open(github_output, "a", encoding="utf-8") as f:
        f.write(f"matrix={json.dumps(matrix)}\n")
        f.write(f"nb_pages={nb_pages}\n")


if __name__ == "__main__":
    main()