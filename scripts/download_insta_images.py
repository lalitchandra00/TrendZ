import os
import re
import sys
import time
import random
import concurrent.futures

import pandas as pd
import requests
from PIL import Image
from io import BytesIO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
EXCEL_PATH = os.path.join(DATASETS_DIR, "caap.xlsx")
OUTPUT_DIR = os.path.join(DATASETS_DIR, "insta_caption")
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
CAPTIONS_PATH = os.path.join(OUTPUT_DIR, "captions.txt")

MIN_LIKES = 5000
MAX_WORKERS = 8
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}


def clean_caption(text):
    if not isinstance(text, str):
        return ""
    text = text.strip()
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_filename(index, username):
    safe = re.sub(r"[^\w]", "_", str(username))
    return f"{safe}_{index:05d}.jpg"


def download_image(row):
    index, url, out_path = row
    if os.path.exists(out_path):
        return index, True, "exists"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        img = img.convert("RGB")
        img.save(out_path, "JPEG", quality=95)
        return index, True, "ok"
    except Exception as e:
        return index, False, str(e)


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)

    print(f"Reading {EXCEL_PATH}...")
    df = pd.read_excel(EXCEL_PATH)
    print(f"Total rows: {len(df)}")

    df = df[df["likesCount"].notna() & (df["likesCount"] > MIN_LIKES)].copy()
    df = df[df["displayUrl"].notna() & (df["displayUrl"].str.strip() != "")]
    df = df[df["caption"].notna() & (df["caption"].str.strip() != "")]
    df = df[df["videoUrl"].isna()]
    df = df.drop_duplicates(subset=["id"])
    df = df.reset_index(drop=True)

    print(f"After filtering (> {MIN_LIKES} likes, image only, has caption): {len(df)}")

    rows = []
    for i, row in df.iterrows():
        fname = make_filename(i, row.get("username", "user"))
        out_path = os.path.join(IMAGES_DIR, fname)
        rows.append((i, row["displayUrl"], out_path))

    downloaded = 0
    skipped = 0
    failed = 0
    captions = []

    print(f"Downloading {len(rows)} images with {MAX_WORKERS} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(download_image, r): r for r in rows}
        for fut in concurrent.futures.as_completed(futures):
            idx, success, msg = fut.result()
            if msg == "exists":
                skipped += 1
            elif success:
                downloaded += 1
            else:
                failed += 1
                if failed <= 5:
                    print(f"  FAIL [{idx}]: {msg[:100]}")

            total_done = downloaded + skipped + failed
            if total_done % 50 == 0 or total_done == len(rows):
                print(f"  Progress: {total_done}/{len(rows)} (ok={downloaded} skip={skipped} fail={failed})")

    for i, row in df.iterrows():
        fname = make_filename(i, row.get("username", "user"))
        out_path = os.path.join(IMAGES_DIR, fname)
        if os.path.exists(out_path):
            cap = clean_caption(row["caption"])
            if cap:
                captions.append((fname, cap))

    with open(CAPTIONS_PATH, "w", encoding="utf-8") as f:
        f.write("image,caption\n")
        for fname, cap in captions:
            safe_cap = cap.replace('"', '""')
            f.write(f'"{fname}","{safe_cap}"\n')

    print(f"\nDone!")
    print(f"  Images downloaded: {downloaded}")
    print(f"  Images skipped (already existed): {skipped}")
    print(f"  Downloads failed: {failed}")
    print(f"  Captions written: {len(captions)}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  captions.txt: {CAPTIONS_PATH}")


if __name__ == "__main__":
    main()
