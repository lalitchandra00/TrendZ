import os
import time
from itertools import islice

import pandas as pd
import requests
from dotenv import load_dotenv
from instaloader import Instaloader, Profile
from instaloader.exceptions import ConnectionException

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

L = Instaloader(max_connection_attempts=1)

PROFILES = ["cristiano"]
MIN_LIKES = 5000
MAX_POSTS = 50

media_folder = os.path.join(BASE_DIR, '..', 'datasets', 'general_caption', 'Media')
captions_path = os.path.join(BASE_DIR, '..', 'datasets', 'general_caption', 'captions.txt')
os.makedirs(media_folder, exist_ok=True)


def download_file(url, path):
    if os.path.exists(path):
        return
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    with open(path, 'wb') as f:
        f.write(response.content)


def get_post_type(typename):
    if typename == 'Image':
        return 'image'
    if typename == 'Carousel':
        return 'album'
    return 'video'


def post_files(post, username):
    filename_base = f"{username}_{post.shortcode}"
    if post.typename == 'Carousel':
        files = []
        for idx, node in enumerate(post.get_sidecar_nodes(), 1):
            is_video = bool(node.get("is_video"))
            url = node.get("video_url") if is_video else node.get("display_url")
            ext = '.mp4' if is_video else '.jpg'
            filepath = os.path.join(media_folder, f"{filename_base}_{idx}{ext}")
            download_file(url, filepath)
            files.append(os.path.basename(filepath))
        return files
    if post.typename == 'Video':
        filepath = os.path.join(media_folder, f"{filename_base}.mp4")
        download_file(post.video_url, filepath)
        return [os.path.basename(filepath)]
    filepath = os.path.join(media_folder, f"{filename_base}.jpg")
    download_file(post.url, filepath)
    return [os.path.basename(filepath)]


rows = []
try:
    for username in PROFILES:
        profile = Profile.from_username(L.context, username)
        for post in islice(profile.get_posts(), MAX_POSTS):
            if post.likes < MIN_LIKES:
                continue
            files = post_files(post, username)
            for f in files:
                rows.append({
                    'filename': f,
                    'caption': post.caption or '',
                    'hashtags': ' '.join(post.caption_hashtags),
                    'post_type': get_post_type(post.typename)
                })
            time.sleep(2)
except ConnectionException as exc:
    print(
        "Instagram rate-limited or blocked this connection. If the error mentions '429 Too Many Requests', "
        "your home IP is throttled: avoid Instagram from this network for a few hours, then retry."
    )
    raise

df = pd.DataFrame(rows)
if not df.empty:
    if os.path.exists(captions_path):
        df = pd.concat([pd.read_csv(captions_path), df], ignore_index=True)
    df.to_csv(captions_path, index=False)