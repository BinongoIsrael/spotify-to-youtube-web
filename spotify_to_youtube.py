import os
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import time

load_dotenv()

# Configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback")
SPOTIFY_SCOPE = "playlist-read-private"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]
YOUTUBE_CLIENT_SECRETS_FILE = "client_secrets.json"
CHECKPOINT_DIR = "checkpoints"

def authenticate_spotify():
    """Authenticate with Spotify API."""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        cache_path=".spotify_cache"
    ))

def authenticate_youtube():
    """Authenticate with YouTube API."""
    flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
    credentials = flow.run_local_server(port=0)
    return build("youtube", "v3", credentials=credentials)

def get_spotify_playlists(sp):
    """Fetch all user playlists from Spotify."""
    playlists = sp.current_user_playlists()
    return playlists["items"]

def get_playlist_tracks(sp, playlist_id):
    """Fetch tracks from a Spotify playlist."""
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    tracks.extend(results["items"])
    while results["next"]:
        results = sp.next(results)
        tracks.extend(results["items"])
    return tracks

def search_youtube_video(youtube, track_name, artist):
    """Search YouTube for a video matching the track and artist."""
    query = f"{track_name} {artist}"
    request = youtube.search().list(q=query, part="id", maxResults=1, type="video")
    response = request.execute()
    if response["items"]:
        return response["items"][0]["id"]["videoId"]
    return None

def create_youtube_playlist(youtube, title, description=""):
    """Create a YouTube playlist."""
    request = youtube.playlists().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": description, "defaultLanguage": "en"}, "status": {"privacyStatus": "private"}}
    )
    response = request.execute()
    return response["id"]

def load_checkpoint(playlist_id):
    """Load checkpoint data for a playlist."""
    checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{playlist_id}.json")
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r") as f:
            return json.load(f)
    return {"youtube_playlist_id": None, "last_track_index": -1}

def save_checkpoint(playlist_id, youtube_playlist_id, last_track_index):
    """Save checkpoint data for a playlist."""
    checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{playlist_id}.json")
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    with open(checkpoint_path, "w") as f:
        json.dump({"youtube_playlist_id": youtube_playlist_id, "last_track_index": last_track_index}, f)

def add_video_to_playlist(youtube, playlist_id, video_id):
    """Add a video to a YouTube playlist with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            request = youtube.playlistItems().insert(
                part="snippet",
                body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
            )
            request.execute()
            break
        except HttpError as e:
            if e.resp.status == 409 and attempt < max_retries - 1:
                print(f"Service unavailable, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(5)
            else:
                raise