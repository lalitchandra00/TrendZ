from googleapiclient.discovery import build
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
import os


load_dotenv()
api_key = os.getenv("YT_API")
youtube = build('youtube', 'v3', developerKey = api_key)
playlist_id ="PLKnIA16_RmvZo7fp5kkIth6nRTeQQsjfX"


def get_video_info(youtube, playlist_id):
    videos = []
    page_token = None
    while True:
        request = youtube.playlistItems().list(
            part = 'snippet',
            playlistId = playlist_id,
            pageToken = page_token
        )
        response = request.execute()
        videos.extend(response['items'])
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return videos

videos = get_video_info(youtube, playlist_id)

video_ids = []
snippet_map = {}
for item in videos:
    vid = item['snippet']['resourceId']['videoId']
    video_ids.append(vid)
    snippet_map[vid] = {
        'title': item['snippet']['title'],
        'description': item['snippet']['description']
    }

for i in range(0, len(video_ids), 50):
    stats = youtube.videos().list(
        part = 'statistics',
        id = ','.join(video_ids[i:i+50])
    ).execute()
    for stat in stats['items']:
        snippet_map[stat['id']]['likes'] = stat['statistics'].get('likeCount', '')

video_list = []
for vid in video_ids:
    video_list.append(snippet_map[vid])

df = pd.DataFrame(video_list)
file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'datasets', 'general_description.xlsx')

if os.path.exists(file_path):
    df = pd.concat([pd.read_excel(file_path), df], ignore_index=True)

df.to_excel(file_path, index=False)