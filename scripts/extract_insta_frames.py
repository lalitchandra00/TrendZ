import os
import re
import shutil
import tempfile
import concurrent.futures

import pandas as pd
import requests
import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
EXCEL_PATH = os.path.join(DATASETS_DIR, "caap.xlsx")
OUTPUT_DIR = os.path.join(DATASETS_DIR, "insta_caption")
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
CAPTIONS_PATH = os.path.join(OUTPUT_DIR, "captions.txt")

MIN_LIKES = 5000
MAX_WORKERS = 4
TIMEOUT = 60
FRAME_INTERVAL_SECONDS = 2.0
MAX_FRAMES_PER_VIDEO = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Range": "bytes=0-",
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


def safe_name(username):
    return re.sub(r"[^\w]", "_", str(username))[:40] or "user"


def download_video(url, filepath):
    if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
        return True
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    return os.path.getsize(filepath) > 1000


def extract_frames(video_path, out_dir, base_name, caption_txt):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return []
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or fps != fps:
        fps = 25.0
    frame_step = max(1, int(round(fps * FRAME_INTERVAL_SECONDS)))

    current = 0
    kept = 0
    saved = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if current % frame_step == 0:
            if kept >= MAX_FRAMES_PER_VIDEO:
                break
            fname = f"{base_name}_f{kept:03d}.jpg"
            out_path = os.path.join(out_dir, fname)
            if not os.path.exists(out_path):
                cv2.imwrite(out_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            saved.append((fname, caption_txt))
            kept += 1
        current += 1
    cap.release()
    return saved


def process_video(job):
    idx, url, caption_txt, username, short_name = job
    first_frame = os.path.join(IMAGES_DIR, f"{short_name}_f000.jpg")
    if os.path.exists(first_frame):
        saved = []
        for k in range(MAX_FRAMES_PER_VIDEO):
            fname = f"{short_name}_f{k:03d}.jpg"
            if os.path.exists(os.path.join(IMAGES_DIR, fname)):
                saved.append((fname, caption_txt))
        return idx, saved, "done"
    tmp_dir = tempfile.mkdtemp(prefix="instavid_")
    video_path = os.path.join(tmp_dir, "video.mp4")
    try:
        if not download_video(url, video_path):
            return idx, [], f"bad video download {os.path.getsize(video_path)}"
        saved = extract_frames(video_path, IMAGES_DIR, short_name, caption_txt)
        return idx, saved, "ok"
    except Exception as e:
        return idx, [], str(e)[:120]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def load_existing_rows():
    if not os.path.exists(CAPTIONS_PATH):
        return set()
    existing = pd.read_csv(CAPTIONS_PATH)
    return set(zip(existing["image"], existing["caption"]))


def append_rows(rows):
    rows = [(i, c) for i, c in rows if c and i]
    if not rows:
        return
    new = pd.DataFrame(rows, columns=["image", "caption"])
    if not os.path.exists(CAPTIONS_PATH) or os.path.getsize(CAPTIONS_PATH) == 0:
        new.to_csv(CAPTIONS_PATH, index=False, encoding="utf-8")
        return
    existing = pd.read_csv(CAPTIONS_PATH)
    merged = pd.concat([existing, new], ignore_index=True).drop_duplicates(
        subset=["image"], keep="first"
    )
    merged.to_csv(CAPTIONS_PATH, index=False, encoding="utf-8")


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)

    df = pd.read_excel(EXCEL_PATH)
    df = df[df["likesCount"].notna() & (df["likesCount"] > MIN_LIKES)].copy()
    df = df[df["videoUrl"].notna() & (df["videoUrl"].str.strip() != "")]
    df = df[df["caption"].notna() & (df["caption"].str.strip() != "")]
    df = df.drop_duplicates(subset=["id"]).reset_index(drop=True)
    print(f"Videos in dataset: {len(df)}")

    existing = load_existing_rows()
    print(f"Existing caption rows: {len(existing)}")

    jobs = []
    for i, row in df.iterrows():
        username = safe_name(row.get("username", "user"))
        short_name = f"{username}_v{i:05d}"
        caption_txt = clean_caption(row["caption"])
        if not caption_txt:
            continue
        jobs.append((i, row["videoUrl"], caption_txt, username, short_name))

    failed = 0
    ok_jobs = 0
    frames_total = 0
    skipped_videos = 0

    print(f"Downloading + extracting frames (1 per {FRAME_INTERVAL_SECONDS}s, {MAX_WORKERS} workers)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(process_video, j) for j in jobs]
        for done in concurrent.futures.as_completed(futures):
            idx, saved, msg = done.result()
            if msg == "done":
                skipped_videos += 1
            elif msg == "ok" and saved:
                ok_jobs += 1
            else:
                failed += 1
                if failed <= 5:
                    print(f"  FAIL [{idx}]: {msg}")
            if saved:
                new_saved = [(i, c) for i, c in saved if (i, c) not in existing]
                append_rows(new_saved)
                existing.update((i, c) for i, c in new_saved)
                frames_total += len(saved)

            done_total = ok_jobs + failed + skipped_videos
            if done_total % 25 == 0 or done_total == len(jobs):
                print(f"  Progress: {done_total}/{len(jobs)} (ok={ok_jobs} fail={failed} skip={skipped_videos}) frames={frames_total}")

    actual_images = len([f for f in os.listdir(IMAGES_DIR) if f.endswith(".jpg")])
    print(f"\nDone!")
    print(f"  Videos OK: {ok_jobs}, Failed: {failed}, Skipped: {skipped_videos}")
    print(f"  Frame captions added this run: {frames_total}")
    print(f"  Total images on disk: {actual_images}")
    print(f"  Total captions.txt rows: {len(existing)}")
    print(f"  Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()