import os
import re
import math
import shutil
from collections import defaultdict

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
INSTA_DIR = os.path.join(DATASETS_DIR, "insta_caption")
IMAGES_DIR = os.path.join(INSTA_DIR, "images")
CAPTIONS_PATH = os.path.join(INSTA_DIR, "captions.txt")
EXCEL_PATH = os.path.join(DATASETS_DIR, "caap.xlsx")

FRAME_INTERVAL_SECONDS = 2
MIN_WORDS = 3
MAX_WORDS = 80

DURATION_BUCKETS = [
    (10, 2),
    (15, 3),
    (20, 5),
    (30, 5),
    (40, 7),
    (9999, 10),
]


def frames_to_keep(n_frames):
    duration = n_frames * FRAME_INTERVAL_SECONDS
    for threshold, count in DURATION_BUCKETS:
        if duration < threshold:
            return min(count, n_frames)
    return min(10, n_frames)


def even_indices(n, k):
    if k >= n:
        return list(range(n))
    return [round(i * (n - 1) / (k - 1)) for i in range(k)] if k > 1 else [0]


JUNK_PATTERNS = [
    re.compile(r"link.{0,10}in.{0,10}bio", re.I),
    re.compile(r"photos?:.{0,5}(getty|wireimage|corbis|filmmagic|afp|splash|shutterstock)", re.I),
    re.compile(r"via.{0,5}/.{0,5}getty", re.I),
    re.compile(r"\bgetty\s*images?\b", re.I),
    re.compile(r"\bphoto.{0,3}(by|credit|line|producer|assistant)", re.I),
    re.compile(r"\bwireimage\b", re.I),
    re.compile(r"\bcorbis\b", re.I),
    re.compile(r"\bfilmmagic\b", re.I),
    re.compile(r"\bexecutive producer\b", re.I),
    re.compile(r"\bcamera.?person\b", re.I),
    re.compile(r"\|"),
    re.compile(r"📷|📸|🎥|🎬|🔗|👉|👇|✨|🔥|💯"),
]


def clean_caption(text):
    if not isinstance(text, str):
        return ""
    text = text.strip()
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"#\s+", "", text)
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(" :")
    return text


def caption_quality(text):
    if not text:
        return False, "empty"
    words = text.split()
    if len(words) < MIN_WORDS:
        return False, "too_short"
    if len(words) > MAX_WORDS:
        return False, "too_long"
    if text.endswith("...") or text.endswith(".."):
        return False, "truncated"
    if re.match(r"^.{0,10}\.\.\.\s*$", text):
        return False, "fragment"
    for pat in JUNK_PATTERNS:
        if pat.search(text):
            return False, "junk"
    if not re.search(r"[a-zA-Z]{3,}", text):
        return False, "no_words"
    return True, "ok"


def group_video_frames(all_files):
    groups = defaultdict(list)
    singles = []
    for f in all_files:
        m = re.match(r"^(.+)_f(\d{3})\.jpg$", f)
        if m:
            groups[m.group(1)].append((int(m.group(2)), f))
        else:
            singles.append(f)
    for key in groups:
        groups[key].sort(key=lambda x: x[0])
    return dict(groups), singles


def main():
    print("Loading captions.txt...")
    df = pd.read_csv(CAPTIONS_PATH, encoding="utf-8")
    print(f"  Rows: {len(df)}")

    all_files = set(os.listdir(IMAGES_DIR))
    caption_map = dict(zip(df["image"], df["caption"]))

    groups, singles = group_video_frames(all_files)
    print(f"  Single images: {len(singles)}")
    print(f"  Video groups: {len(groups)}")

    keep_images = {}
    deleted = 0

    for f in singles:
        cap = caption_map.get(f, "")
        if cap:
            keep_images[f] = cap

    print(f"  Single images kept: {len(keep_images)}")

    video_stats = defaultdict(int)
    for name, frame_list in groups.items():
        n = len(frame_list)
        k = frames_to_keep(n)
        indices = even_indices(n, k)
        keep = {frame_list[i][1] for i in indices}

        raw_cap = None
        for _, fname in frame_list:
            if fname in caption_map:
                raw_cap = caption_map[fname]
                break

        if not raw_cap:
            for _, fname in frame_list:
                deleted += 1
                p = os.path.join(IMAGES_DIR, fname)
                if os.path.exists(p):
                    os.remove(p)
            continue

        for _, fname in frame_list:
            if fname in keep:
                keep_images[fname] = raw_cap
            else:
                deleted += 1
                p = os.path.join(IMAGES_DIR, fname)
                if os.path.exists(p):
                    os.remove(p)

        video_stats[k] += 1

    print(f"  Video frames kept: {len(keep_images) - len(keep_images) + sum(len(g) for g in groups.values())}")
    print(f"  Frames deleted: {deleted}")
    print("  Frames kept per video:", dict(video_stats))

    clean_pairs = []
    drop_stats = defaultdict(int)
    for img, cap in keep_images.items():
        cleaned = clean_caption(cap)
        ok, reason = caption_quality(cleaned)
        if ok:
            clean_pairs.append((img, cleaned))
        else:
            drop_stats[reason] += 1
            p = os.path.join(IMAGES_DIR, img)
            if os.path.exists(p):
                os.remove(p)

    print(f"\nCaption filtering dropped {sum(drop_stats.values())} rows:")
    for reason, count in sorted(drop_stats.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print(f"  Kept: {len(clean_pairs)}")

    clean_pairs.sort(key=lambda x: x[0])

    with open(CAPTIONS_PATH, "w", encoding="utf-8") as f:
        f.write("image,caption\n")
        for img, cap in clean_pairs:
            safe_cap = cap.replace('"', '""')
            f.write(f'"{img}","{safe_cap}"\n')

    remaining = [f for f in os.listdir(IMAGES_DIR) if f.endswith(".jpg")]
    print(f"\nFinal captions.txt: {len(clean_pairs)} rows")
    print(f"Final images on disk: {len(remaining)}")

    print("\nSample retained captions:")
    for img, cap in clean_pairs[:5]:
        print(f"  {img}: {cap[:80]}{'...' if len(cap)>80 else ''}")


if __name__ == "__main__":
    main()
