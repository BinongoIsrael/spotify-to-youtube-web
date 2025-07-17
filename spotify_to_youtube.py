import os
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import urlencode, urlparse, parse_qs
import pickle
from pathlib import Path
from flask import redirect, session, request

# Configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/spotify_callback")
SPOTIFY_SCOPE = "playlist-read-private"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

# Handle credentials based on environment
if os.getenv("RENDER_EXTERNAL_URL"):  # Deployed on Render
    google_credentials = os.getenv("GOOGLE_CREDENTIALS")
    if not google_credentials:
        raise ValueError("GOOGLE_CREDENTIALS environment variable is not set. Please configure it in Render.")
    YOUTUBE_CLIENT_SECRETS = json.loads(google_credentials)
else:  # Local development
    YOUTUBE_CLIENT_SECRETS_FILE = "client_secrets.json"

def authenticate_spotify():
    """Initiate Spotify API authentication with web-based flow."""
    sp_oauth = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    auth_url = sp_oauth.get_authorize_url()
    session['spotify_oauth_state'] = sp_oauth.state
    return redirect(auth_url)

def finalize_spotify_auth(request):
    """Finalize Spotify authentication after callback."""
    sp_oauth = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    if 'code' not in request.args or session.get('spotify_oauth_state') != request.args.get('state'):
        return "Invalid authorization code or state", 400
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    return spotipy.Spotify(auth=token_info['access_token'])

def authenticate_youtube(request):
    if os.getenv("RENDER_EXTERNAL_URL"):
        flow = InstalledAppFlow.from_client_config(YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
    redirect_uri = f"{os.getenv('RENDER_EXTERNAL_URL', 'http://127.0.0.1:5000')}/youtube_callback"
    if not redirect_uri.startswith("https://") and not redirect_uri.startswith("http://127.0.0.1"):
        redirect_uri = "https://" + redirect_uri.split("://")[1]
    print(f"Using redirect URI: {redirect_uri}")  # Debug output
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        redirect_uri=redirect_uri
    )
    session['state'] = state
    return redirect(authorization_url)

def finalize_youtube_auth(request):
    if os.getenv("RENDER_EXTERNAL_URL"):
        flow = InstalledAppFlow.from_client_config(YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
    redirect_uri = f"{os.getenv('RENDER_EXTERNAL_URL', 'http://127.0.0.1:5000')}/youtube_callback"
    if not redirect_uri.startswith("https://") and not redirect_uri.startswith("http://127.0.0.1"):
        redirect_uri = "https://" + redirect_uri.split("://")[1]
    print(f"Debug: RENDER_EXTERNAL_URL={os.getenv('RENDER_EXTERNAL_URL')}")
    print(f"Debug: Initial redirect_uri={redirect_uri}")
    print(f"Debug: Request URL={request.url}")
    # Force HTTPS if deployed
    authorization_response = request.url
    if os.getenv("RENDER_EXTERNAL_URL") and not authorization_response.startswith("https://"):
        from urllib.parse import urlparse, urlunparse
        parsed_url = urlparse(authorization_response)
        authorization_response = urlunparse(("https",) + parsed_url[1:])
    print(f"Debug: Adjusted authorization_response={authorization_response}")
    flow.redirect_uri = redirect_uri
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    return build("youtube", "v3", credentials=credentials)
def get_spotify_playlists(sp):
    """Get user's Spotify playlists with track counts."""
    playlists = sp.current_user_playlists(limit=50)
    result = []
    for playlist in playlists["items"]:
        playlist_id = playlist["id"]
        detailed_playlist = sp.playlist(playlist_id, fields="id,name,tracks(total)")
        result.append({
            "id": detailed_playlist["id"],
            "name": detailed_playlist["name"],
            "tracks": {"total": detailed_playlist["tracks"]["total"]}
        })
    return result

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