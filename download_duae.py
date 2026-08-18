import os

import boto3
from dotenv import load_dotenv

load_dotenv()

CF_R2_ACCESS_KEY = os.getenv("CF_R2_ACCESS_KEY_ID")
CF_R2_SECRET_KEY = os.getenv("CF_R2_SECRET_ACCESS_KEY")
CF_R2_ENDPOINT_URL = os.getenv("CF_R2_ENDPOINT_URL")
BUCKET_NAME = os.getenv("CF_R2_BUCKET_NAME")

s3 = boto3.client(
    "s3",
    endpoint_url=CF_R2_ENDPOINT_URL,
    aws_access_key_id=CF_R2_ACCESS_KEY,
    aws_secret_access_key=CF_R2_SECRET_KEY,
    region_name="auto",
)

# ============================================================
# CONFIG
# ============================================================

r2_prefix = "DOMAN"

# Everything under DUAE will be downloaded
LOCAL_ROOT = f"{r2_prefix}"

PREFIXES = [
    f"{r2_prefix}/",
]


# ============================================================
# LIST OBJECTS
# ============================================================

def list_all_objects(prefix):
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=BUCKET_NAME,
        Prefix=prefix,
    ):
        for obj in page.get("Contents", []):
            yield obj["Key"]


# ============================================================
# CHECK IF IMAGE
# ============================================================

def is_image_path(key):
    """
    Skip anything inside an 'images' folder.
    Examples:
        DUAE/year=2026/month=08/day=16/images/...
        DUAE/year=2026/month=08/day=17/property/images/...
    """

    parts = key.split("/")

    return "images" in parts


# ============================================================
# DOWNLOAD FILE
# ============================================================

def download_file(key):
    if is_image_path(key):
        return False

    local_path = os.path.join(LOCAL_ROOT, key)

    os.makedirs(
        os.path.dirname(local_path),
        exist_ok=True,
    )

    print(f"⬇ {key}")

    s3.download_file(
        BUCKET_NAME,
        key,
        local_path,
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():
    downloaded = 0
    skipped = 0

    for prefix in PREFIXES:

        print("\n==============================")
        print(f"Searching under: {prefix}")
        print("==============================")

        for key in list_all_objects(prefix):

            # Skip folder placeholders
            if key.endswith("/"):
                continue

            # Skip images
            if is_image_path(key):
                skipped += 1
                print(f"⏭ Skipping image: {key}")
                continue

            try:
                if download_file(key):
                    downloaded += 1

            except Exception as e:
                print(f"❌ Failed: {key}")
                print(e)

    print("\n==============================")
    print("DOWNLOAD SUMMARY")
    print("==============================")
    print(f"Downloaded : {downloaded}")
    print(f"Skipped    : {skipped} (images)")
    print("==============================")


if __name__ == "__main__":
    main()