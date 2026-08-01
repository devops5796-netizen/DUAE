import os
import boto3
from botocore.client import Config
from dotenv import load_dotenv
load_dotenv()

CF_R2_ACCESS_KEY = os.getenv('CF_R2_ACCESS_KEY_ID')
CF_R2_SECRET_KEY = os.getenv('CF_R2_SECRET_ACCESS_KEY')
CF_R2_ENDPOINT_URL = os.getenv('CF_R2_ENDPOINT_URL')
BUCKET_NAME = os.getenv('CF_R2_BUCKET_NAME', '')

# Folder you want to delete

FOLDER = "DUAE"

client = boto3.client(
    's3',
    endpoint_url=CF_R2_ENDPOINT_URL,
    aws_access_key_id=CF_R2_ACCESS_KEY,
    aws_secret_access_key=CF_R2_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto',
)

# 1. Get all keys under this folder
keys = []
paginator = client.get_paginator('list_objects_v2')
for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=FOLDER):
    for obj in page.get('Contents', []):
        keys.append(obj['Key'])

print(f"Found {len(keys)} files to delete")

# 2. Delete them in batches of 1000
for i in range(0, len(keys), 1000):
    batch = keys[i:i + 1000]
    client.delete_objects(
        Bucket=BUCKET_NAME,
        Delete={'Objects': [{'Key': k} for k in batch]}
    )
    print(f"Deleted {i + len(batch)} / {len(keys)}")

print("Done")