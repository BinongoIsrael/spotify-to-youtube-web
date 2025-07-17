import os
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import urlencode, urlparse, parse_qs
import pickle
from pathlib import Path

# Configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback")
SPOTIFY_SCOPE = "playlist-read-private"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

# Handle GOOGLE_CREDENTIALS
google_credentials = os.getenv("GOOGLE_CREDENTIALS")
if not google_credentials:
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not set. Please configure it in Render.")
YOUTUBE_CLIENT_SECRETS = json.loads(google_credentials)

def authenticate_spotify():
    """Authenticate with Spotify API."""
    sp_oauth = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    token_info = sp_oauth.get_access_token(as_dict=True)
    return spotipy.Spotify(auth=token_info['access_token'])

def authenticate_youtube(request):
    """Initiate YouTube API authentication with web-based flow."""
    flow = InstalledAppFlow.from_client_config(YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        redirect_uri=f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:5000')}/youtube_callback"
    )
    session['state'] = state
    return redirect(authorization_url)

def finalize_youtube_auth(request):
    """Finalize YouTube authentication after callback."""
    flow = InstalledAppFlow.from_client_config(YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
    flow.redirect_uri = f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:5000')}/youtube_callback"
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    return build("youtube", "v3", credentials=credentials)

def get_spotify_playlists(sp):
    """Get user's Spotify playlists."""
    playlists = sp.current_user_playlists(limit=50)
    return [{"id": p["id"], "name": p["name"]} for p in playlists["items"]]

def get_playlist_tracks(sp, playlist_id):
    """Get tracks from a Spotify playlist."""
    results = sp.playlist_tracks(playlist_id, fields="items(track(name,artists(name)))")
    return results["items"]

def create_youtube_playlist(youtube, title, description):
    """Create a new YouTube playlist."""
    request_body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": "private"}
    }
    response = youtube.playlists().insert(
        part="snippet,status",
        body=request_body
    ).execute()
    return response["id"]

def add_video_to_playlist(youtube, playlist_id, video_id):
    """Add a video to a YouTube playlist."""
    request_body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id}
        }
    }
    youtube.playlistItems().insert(
        part="snippet",
        body=request_body
    ).execute()

def search_youtube_video(youtube, query, artist):
    """Search for a YouTube video."""
    search_response = youtube.search().list(
        q=f"{query} {artist} official audio",
        part="id,snippet",
        maxResults=1,
        type="video"
    ).execute()
    videos = search_response.get("items", [])
    return videos[0]["id"]["videoId"] if videos else None

def load_checkpoint(playlist_id):
    """Load checkpoint data for a playlist."""
    checkpoint_path = Path("checkpoints") / f"{playlist_id}.pkl"
    if checkpoint_path.exists():
        with open(checkpoint_path, "rb") as f:
            return pickle.load(f)
    return {}

def save_checkpoint(playlist_id, youtube_playlist_id, last_track_index):
    """Save checkpoint data for a playlist."""
    checkpoint_path = Path("checkpoints") / f"{playlist_id}.pkl"
    checkpoint_path.parent.mkdir(exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump({"youtube_playlist_id": youtube_playlist_id, "last_track_index": last_track_index}, f)