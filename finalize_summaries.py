#!/usr/bin/env python3
"""
Finalize summaries: add workflow duration and upload to R2.
"""

import argparse
import json
import os
import glob
import io
from datetime import datetime, timedelta, timezone

from r2_uploader import upload_buffer


def load_summary(filepath: str) -> dict:
    """Load a summary JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_summary(filepath: str, data: dict) -> None:
    """Save a summary JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def finalize_summaries(summaries_dir: str, date_str: str, workflow_name: str = None):
    """
    Add workflow duration to all summary placeholders and upload to R2.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    workflow_duration = os.getenv("WORKFLOW_DURATION")
    if not workflow_duration:
        print("⚠️ WORKFLOW_DURATION not set. Using fallback.")
        workflow_duration = "0"

    try:
        duration_sec = float(workflow_duration)
    except ValueError:
        duration_sec = 0.0

    print(f"✅ Workflow duration: {duration_sec}s")

    pattern = os.path.join(summaries_dir, "summary_placeholder_*.json")
    summary_files = glob.glob(pattern)

    if not summary_files:
        print(f"No summary placeholder files found in {summaries_dir}")
        return

    print(f"Found {len(summary_files)} summary file(s)")

    for filepath in summary_files:
        basename = os.path.basename(filepath)
        category = basename.replace("summary_placeholder_", "").replace(".json", "")

        summary = load_summary(filepath)

        # Read category_path from summary if available, otherwise build fallback
        category_path = summary.get("category_path")
        if not category_path:
            # Fallback logic
            if category == "off_plan":
                category_path = "property/property-for-sale/off-plan"
            elif category.startswith("sale_"):
                category_path = f"property/property-for-sale/{category.replace('sale_', '')}"
            elif category.startswith("rent_"):
                category_path = f"property/property-for-rent/{category.replace('rent_', '')}"
            else:
                category_path = category.replace("_", "/")
            print(f"  Warning: category_path not found in summary, using fallback for {category}")

        print(f"  Processing: {category} -> {category_path}")

        if "request_metrics" not in summary:
            summary["request_metrics"] = {}

        summary["request_metrics"]["duration_sec"] = duration_sec

        if workflow_name:
            summary["workflow_name"] = workflow_name

        category_display = summary.get("category", {}).get("name_en", category)

        summary_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")
        summary_key = upload_buffer(
            io.BytesIO(summary_bytes),
            filename="summary.json",
            category_display=category_display,
            file_type="summary",
            content_type="application/json",
            dt=dt,
            category_path=category_path,
        )
        print(f"    Uploaded: {summary_key}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finalize summaries with workflow duration")
    parser.add_argument("--summaries-dir", default="summaries/", help="Directory with summary placeholders")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD data date")
    parser.add_argument("--workflow", default=None, help="Workflow name (dksa, motors, etc.)")
    args = parser.parse_args()

    finalize_summaries(args.summaries_dir, args.date, args.workflow)