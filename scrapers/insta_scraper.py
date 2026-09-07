import os
import random
import time
from itertools import islice

import pandas as pd
import requests
from dotenv import load_dotenv
from instaloader import Instaloader, Profile
from instaloader.exceptions import ConnectionException, InstaloaderException

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILES = [
    profile.strip()
    for profile in os.getenv("IG_PROFILES", "cristiano").split(",")
    if profile.strip()
]
MIN_LIKES = int(os.getenv("IG_MIN_LIKES", "5000"))
MAX_POSTS = int(os.getenv("IG_MAX_POSTS", "50"))

media_folder = os.path.join(BASE_DIR, '..', 'datasets', 'general_caption', 'Media')
captions_path = os.path.join(BASE_DIR, '..', 'datasets', 'general_caption', 'captions.txt')
os.makedirs(media_folder, exist_ok=True)

RATE_LIMIT_BACKOFF = [30, 60, 120, 300]


def _is_rate_limited(exc):
    msg = str(exc).lower()
    return (
        "401 unauthorized" in msg
        or "429" in msg
        or "please wait a few minutes" in msg
        or "too many request" in msg
    )


def with_retry(fn, retries=4, base_delay=30):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except (ConnectionException, requests.RequestException) as exc:
            if attempt == retries:
                raise
            if _is_rate_limited(exc):
                delay = RATE_LIMIT_BACKOFF[min(attempt - 1, len(RATE_LIMIT_BACKOFF) - 1)]
                delay += random.randint(0, 30)
                print(f"Rate-limited ({exc}); waiting {delay}s before retry {attempt + 1}/{retries}...")
            else:
                delay = base_delay * attempt + random.randint(0, 15)
                print(f"Request failed ({exc}); retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError("Retry operation did not complete")


def _random_delay(low=3, high=8):
    time.sleep(random.uniform(low, high))


def download_file(url, path):
    if os.path.exists(path):
        return
    if not url:
        raise ValueError(f"Instagram returned no media URL for {path}")
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


def login(loader):
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    if not username or not password:
        print("IG_USERNAME/IG_PASSWORD not set; trying public Instagram access.")
        return
    session_file = os.path.join(BASE_DIR, f"{username}.session")
    try:
        if os.path.exists(session_file):
            loader.load_session_from_file(username, session_file)
            print(f"Loaded saved session for @{username}.")
        else:
            with_retry(lambda: loader.login(username, password), retries=2, base_delay=10)
            loader.save_session_to_file(session_file)
            print(f"Logged in as @{username} and saved session.")
    except InstaloaderException as exc:
        reason = "Instagram requested a login checkpoint" if "checkpoint" in str(exc).lower() else "Instagram rejected the login"
        print(
            f"{reason}; continuing with public access. "
            "Check IG_USERNAME/IG_PASSWORD if public access is blocked."
        )


def scrape():
    loader = Instaloader(
        max_connection_attempts=3,
        request_timeout=60,
        sleep=False,
    )
    login(loader)
    rows = []
    for idx, username in enumerate(PROFILES):
        if idx > 0:
            delay = random.randint(30, 90)
            print(f"Throttling {delay}s before next profile...")
            time.sleep(delay)
        print(f"Scraping @{username}...")
        _random_delay(5, 15)
        profile = with_retry(lambda: Profile.from_username(loader.context, username))
        for post in islice(profile.get_posts(), MAX_POSTS):
            if (post.likes or 0) < MIN_LIKES:
                continue
            files = post_files(post, username)
            for filename in files:
                rows.append({
                    "filename": filename,
                    "caption": post.caption or "",
                    "hashtags": " ".join(post.caption_hashtags),
                    "post_type": get_post_type(post.typename),
                })
            _random_delay(2, 5)
    return rows


def save_rows(rows):
    if not rows:
        print("No posts matched the configured like threshold.")
        return
    new_rows = pd.DataFrame(rows)
    if os.path.exists(captions_path) and os.path.getsize(captions_path) > 0:
        old_rows = pd.read_csv(captions_path)
        new_rows = pd.concat([old_rows, new_rows], ignore_index=True).drop_duplicates(
            subset=["filename"]
        )
    new_rows.to_csv(captions_path, index=False)
    print(f"Saved {len(rows)} new media records to {captions_path}")


def main():
    try:
        save_rows(scrape())
    except (ConnectionException, requests.RequestException) as exc:
        if _is_rate_limited(exc):
            print("Instagram rate-limited this connection. Wait 10-15 minutes before retrying.")
        elif "getaddrinfo" in str(exc).lower() or "failed to resolve" in str(exc).lower():
            print("DNS failed for Instagram. Check your internet connection, VPN, or DNS settings.")
        else:
            print(f"Instagram connection error: {exc}")
        return 1
    except (InstaloaderException, RuntimeError, ValueError) as exc:
        print(f"Instagram scraper error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())