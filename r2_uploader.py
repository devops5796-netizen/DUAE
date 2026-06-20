import os
import mimetypes
from pathlib import Path
from datetime import datetime
import boto3
import io

CF_R2_ACCESS_KEY = os.getenv('CF_R2_ACCESS_KEY_ID')
CF_R2_SECRET_KEY = os.getenv('CF_R2_SECRET_ACCESS_KEY')
CF_R2_ENDPOINT_URL = os.getenv('CF_R2_ENDPOINT_URL')
BUCKET_NAME = os.getenv('CF_R2_BUCKET_NAME', '')

CLEAN_ENDPOINT = ""
if CF_R2_ENDPOINT_URL:
    CLEAN_ENDPOINT = CF_R2_ENDPOINT_URL.rstrip("/").removesuffix("/" + BUCKET_NAME)


def get_r2_client():
    if CF_R2_ACCESS_KEY and CF_R2_SECRET_KEY and CLEAN_ENDPOINT:
        try:
            return boto3.client(
                's3',
                endpoint_url=CLEAN_ENDPOINT,
                aws_access_key_id=CF_R2_ACCESS_KEY,
                aws_secret_access_key=CF_R2_SECRET_KEY,
                region_name='auto'
            )
        except Exception as e:
            print(f"Failed to initialize R2 Client: {e}")
            return None
    print("Warning: R2 Environment variables are missing.")
    return None

R2_CLIENT_INSTANCE = get_r2_client()


def build_r2_key(folder_name: str, category: str, file_type: str, filename: str, dt: datetime = None) -> str:
    if dt is None:
        dt = datetime.now()
    
    year  = f"year={dt.year}"
    month = f"month={dt.strftime('%m')}"
    day   = f"day={dt.strftime('%d')}"
    
    if file_type:
        return f"{folder_name}/{year}/{month}/{day}/{category}/{file_type}/{filename}"
    else:
        return f"{folder_name}/{year}/{month}/{day}/{category}/{filename}"


def upload_single_file(
    local_path: str,
    folder_name: str = "qatarsale",
    category: str = "",
    file_type: str = "images",
    dt: datetime = None
) -> bool:
    client = R2_CLIENT_INSTANCE if R2_CLIENT_INSTANCE else get_r2_client()
    if not client or not BUCKET_NAME:
        return False

    filename = Path(local_path).name
    r2_key = build_r2_key(folder_name, category, file_type, filename, dt)

    try:
        content_type, _ = mimetypes.guess_type(local_path)
        if not content_type:
            content_type = 'image/jpeg' if file_type == "images" else 'application/octet-stream'

        client.upload_file(
            local_path, BUCKET_NAME, r2_key,
            ExtraArgs={"ContentType": content_type}
        )
        #print(f"  [OK] Uploaded to R2: {r2_key}")
        return True
    except Exception as e:
        print(f"  [ERROR] R2 upload failed for {filename}: {e}")
        return False

def upload_buffer(
    buffer: io.BytesIO,
    filename: str,
    folder_name: str = "qatarsale",
    category: str = "",
    file_type: str = "images",
    content_type: str = "image/webp",
    dt: datetime = None
) -> str | None:
    client = R2_CLIENT_INSTANCE if R2_CLIENT_INSTANCE else get_r2_client()
    if not client or not BUCKET_NAME:
        return None

    r2_key = build_r2_key(folder_name, category, file_type, filename, dt)

    try:
        buffer.seek(0)
        client.upload_fileobj(
            buffer, BUCKET_NAME, r2_key,
            ExtraArgs={"ContentType": content_type}
        )
        return r2_key
    except Exception as e:
        print(f"  [ERROR] R2 upload failed for {filename}: {e}")
        return None

def upload_final_batch_assets(images_folder: str, final_excel: str, folder_name: str = "qatarsale", category: str = "") -> dict:
    print("\n" + "="*50)
    print("STEP 4: Uploading final Excel artifact to Cloudflare R2...")
    print("="*50)

    uploaded = 0
    failed = 0
    dt = datetime.now()

    if os.path.exists(final_excel):
        print(f"Found final Excel file '{final_excel}', starting upload...")
        success = upload_single_file(final_excel, folder_name=folder_name, category=category, file_type="excel", dt=dt)
        if success:
            uploaded += 1
            print("-> Final Excel Artifact Uploaded successfully to R2!")
        else:
            failed += 1
            print("-> [ERROR] Failed to upload final Excel to R2.")
    else:
        print(f"-> [WARNING] Excel Artifact NOT found at: {final_excel}")
        failed += 1

    return {"uploaded": uploaded, "failed": failed}