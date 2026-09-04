from instagrapi import Client
import pandas as pd
from dotenv import load_dotenv
import os
import time


load_dotenv()
ig_username = os.getenv("IG_USERNAME")
ig_password = os.getenv("IG_PASSWORD")

client = Client()
session_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session.json')
if os.path.exists(session_path):
    client.load_settings(session_path)
client.login(ig_username, ig_password)
client.dump_settings(session_path)

PROFILES = []
MIN_LIKES = 5000
MAX_POSTS = 50

media_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'datasets', 'general_caption', 'Media')
captions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'datasets', 'general_caption', 'captions.txt')
os.makedirs(media_folder, exist_ok=True)


def get_post_type(media):
    if media.media_type == 1:
        return 'image'
    if media.media_type == 8:
        return 'album'
    if media.product_type == 'clips':
        return 'reel'
    return 'video'


rows = []
for username in PROFILES:
    user = client.user_id_from_username(username)
    medias = client.user_medias(user, amount=MAX_POSTS)
    for media in medias:
        if media.like_count < MIN_LIKES:
            continue
        filename = f"{username}_{media.pk}"
        if media.media_type == 1:
            path = client.photo_download(media.pk, media_folder, filename)
            files = [path.name]
        elif media.media_type == 8:
            paths = client.album_download(media.pk, media_folder, filename)
            files = [p.name for p in paths]
        else:
            path = client.video_download(media.pk, media_folder, filename)
            files = [path.name]
        for f in files:
            rows.append({
                'filename': f,
                'caption': media.caption_text,
                'hashtags': ' '.join(media.caption_hashtags),
                'post_type': get_post_type(media)
            })
        time.sleep(2)

df = pd.DataFrame(rows)
if not df.empty:
    if os.path.exists(captions_path):
        df = pd.concat([pd.read_csv(captions_path), df], ignore_index=True)
    df.to_csv(captions_path, index=False)