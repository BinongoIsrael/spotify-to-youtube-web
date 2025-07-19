from flask import Flask, redirect, request, session, render_template, url_for, make_response
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import os
import json
import logging
import os.path
from google.oauth2.credentials import Credentials
import warnings
from datetime import datetime, timedelta
from jinja2 import TemplateNotFound, TemplateSyntaxError
import tempfile
import uuid

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path for progress file
PROGRESS_FILE = "data/transfer_progress.json"

# Ensure data directory and progress file exist
os.makedirs("data", exist_ok=True)
if not os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({}, f)

# Suppress Spotify deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Spotify OAuth setup with no caching
def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope="playlist-read-private playlist-read-collaborative",
        cache_path=None  # Disable default caching
    )

def refresh_spotify_token():
    """Refresh Spotify access token if expired."""
    try:
        token_info = session.get("token_info")
        if not token_info:
            raise ValueError("No token info in session")
        
        expires_at = token_info.get("expires_at")
        if not expires_at or datetime.now().timestamp() >= expires_at - 60:
            logger.info("Spotify token expired or about to expire, refreshing...")
            sp_oauth = get_spotify_oauth()
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info
        logger.info(f"Using Spotify access token: {token_info['access_token'][:10]}...")
        return token_info["access_token"]
    except Exception as e:
        logger.error(f"Error refreshing Spotify token: {e}")
        session.pop("token_info", None)
        raise

def read_progress():
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading progress file: {e}")
        return {}

def write_progress(data):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error writing to progress file: {e}")

@app.route("/")
def index():
    try:
        return render_template("index.html")
    except TemplateNotFound as e:
        logger.error(f"Template not found: {e}")
        return "Error: index.html template not found.", 500
    except TemplateSyntaxError as e:
        logger.error(f"Template syntax error in index.html: {e}")
        return f"Error: Invalid syntax in index.html: {str(e)}", 500

@app.route("/login")
def login():
    # Clear existing Spotify session
    session.pop("token_info", None)
    sp_oauth = get_spotify_oauth()
    # Generate a unique state parameter to force fresh OAuth flow
    state = str(uuid.uuid4())
    session["spotify_oauth_state"] = state
    auth_url = sp_oauth.get_authorize_url(state=state)
    logger.info(f"Redirecting to Spotify auth URL with state {state}: {auth_url}")
    return redirect(auth_url)

@app.route("/logout")
def logout():
    # Clear all session data and cached tokens
    session.clear()
    # Remove any lingering Spotify cache files
    for cache_file in os.listdir("."):
        if cache_file.startswith(".cache"):
            try:
                os.remove(cache_file)
                logger.info(f"Removed cache file: {cache_file}")
            except Exception as e:
                logger.error(f"Error removing cache file {cache_file}: {e}")
    # Clear Spotify-related cookies and redirect to Spotify logout
    response = make_response(redirect("https://accounts.spotify.com/logout"))
    response.set_cookie("spotify-auth-session", "", expires=0, domain=".spotify.com")
    logger.info("Cleared Spotify session cookies and redirected to Spotify logout")
    return response

@app.route("/logout-callback")
def logout_callback():
    # After Spotify logout, redirect to index
    return redirect(url_for("index"))

@app.route("/callback")
def callback():
    try:
        sp_oauth = get_spotify_oauth()
        state = request.args.get("state")
        expected_state = session.get("spotify_oauth_state")
        if not state or state != expected_state:
            raise ValueError(f"Invalid or missing state parameter: got {state}, expected {expected_state}")
        token_info = sp_oauth.get_access_token(request.args["code"], as_dict=True)
        session["token_info"] = token_info
        session.pop("spotify_oauth_state", None)
        logger.info(f"Spotify token obtained for user: {token_info['access_token'][:10]}...")
        return redirect(url_for("playlists"))
    except Exception as e:
        logger.error(f"Spotify auth error: {e}")
        session.pop("token_info", None)
        session.pop("spotify_oauth_state", None)
        try:
            return render_template("error.html", message=f"Spotify login failed: {str(e)}")
        except TemplateNotFound as te:
            logger.error(f"Template not found: {te}")
            return f"Error: error.html template not found.", 500
        except TemplateSyntaxError as te:
            logger.error(f"Template syntax error in error.html: {te}")
            return f"Error: Invalid syntax in error.html: {str(te)}", 500

@app.route("/playlists")
def playlists():
    if "token_info" not in session:
        return redirect(url_for("login"))
    try:
        access_token = refresh_spotify_token()
        sp = spotipy.Spotify(auth=access_token)
        user = sp.current_user()
        logger.info(f"Fetched playlists for Spotify user: {user['id']} ({user.get('display_name', 'Unknown')})")
        playlists = sp.current_user_playlists(limit=50)["items"]
        logger.info(f"Fetched {len(playlists)} playlists for user with token: {access_token[:10]}...")
        return render_template("playlists.html", playlists=playlists)
    except Exception as e:
        logger.error(f"Error fetching playlists: {e}")
        session.pop("token_info", None)
        try:
            return render_template("error.html", message=f"Failed to fetch playlists: {str(e)}")
        except TemplateNotFound as te:
            logger.error(f"Template not found: {te}")
            return f"Error: error.html template not found.", 500
        except TemplateSyntaxError as te:
            logger.error(f"Template syntax error in error.html: {te}")
            return f"Error: Invalid syntax in error.html: {str(te)}", 500

@app.route("/google-callback")
def google_callback():
    try:
        state = session.get("google_oauth_state")
        if not state:
            raise ValueError("No OAuth state found in session")
        client_secrets_file = "client_secrets.json"
        temp_file = None
        if not os.path.exists(client_secrets_file) and os.getenv("GOOGLE_CLIENT_SECRETS"):
            try:
                client_secrets = json.loads(os.getenv("GOOGLE_CLIENT_SECRETS"))
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                    json.dump(client_secrets, temp_file)
                    temp_file.flush()
                    client_secrets_file = temp_file.name
                logger.info(f"Created temporary client_secrets file: {client_secrets_file}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid GOOGLE_CLIENT_SECRETS format: {e}")
                try:
                    return render_template("error.html", message=f"Invalid client secrets format: {str(e)}")
                except TemplateNotFound as te:
                    logger.error(f"Template not found: {te}")
                    return f"Error: error.html template not found.", 500
                except TemplateSyntaxError as te:
                    logger.error(f"Template syntax error in error.html: {te}")
                    return f"Error: Invalid syntax in error.html: {str(te)}", 500
        elif not os.path.exists(client_secrets_file):
            logger.error("client_secrets.json not found and GOOGLE_CLIENT_SECRETS not set")
            try:
                return render_template("error.html", message="Client secrets file not found.")
            except TemplateNotFound as te:
                logger.error(f"Template not found: {te}")
                return f"Error: error.html template not found.", 500
            except TemplateSyntaxError as te:
                logger.error(f"Template syntax error in error.html: {te}")
                return f"Error: Invalid syntax in error.html: {str(te)}", 500

        try:
            with open(client_secrets_file, "r", encoding="utf-8") as f:
                client_secrets = json.load(f)
            logger.info(f"Loaded client_secrets: {json.dumps(client_secrets, indent=2)}")
        except Exception as e:
            logger.error(f"Error loading client_secrets.json: {e}")
            try:
                return render_template("error.html", message=f"Error loading client secrets: {str(e)}")
            except TemplateNotFound as te:
                logger.error(f"Template not found: {te}")
                return f"Error: error.html template not found.", 500
            except TemplateSyntaxError as te:
                logger.error(f"Template syntax error in error.html: {te}")
                return f"Error: Invalid syntax in error.html: {str(te)}", 500

        flow = InstalledAppFlow.from_client_secrets_file(
            client_secrets_file,
            scopes=["https://www.googleapis.com/auth/youtube"],
            state=state,
            redirect_uri="https://spotify-to-youtube-web.onrender.com/google-callback" if os.getenv("RENDER") else "http://127.0.0.1:5000/google-callback"
        )
        logger.info(f"Google OAuth redirect URI in callback: {flow.redirect_uri}")
        flow.fetch_token(code=request.args.get("code"))
        credentials = flow.credentials
        session["google_credentials"] = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        playlist_id = session.get("transfer_playlist_id")
        if not playlist_id:
            raise ValueError("No playlist ID found in session")
        if temp_file:
            os.unlink(temp_file.name)
            logger.info(f"Deleted temporary client_secrets file: {temp_file.name}")
        return redirect(url_for("transfer", playlist_id=playlist_id))
    except Exception as e:
        logger.error(f"Google callback error: {e}")
        if temp_file:
            os.unlink(temp_file.name)
            logger.info(f"Deleted temporary client_secrets file: {temp_file.name}")
        try:
            return render_template("error.html", message=f"Google login failed: {str(e)}")
        except TemplateNotFound as te:
            logger.error(f"Template not found: {te}")
            return f"Error: error.html template not found.", 500
        except TemplateSyntaxError as te:
            logger.error(f"Template syntax error in error.html: {te}")
            return f"Error: Invalid syntax in error.html: {str(te)}", 500

@app.route("/transfer/<playlist_id>", methods=["GET", "POST"])
def transfer(playlist_id):
    if "token_info" not in session:
        return redirect(url_for("login"))

    try:
        # Check for resume state
        resume_key = f"transfer_{session['token_info']['access_token']}_{playlist_id}"
        progress = read_progress()
        last_transferred = progress.get(resume_key, {}).get("last_transferred", 0)
        logger.info(f"Resuming transfer from index {last_transferred}")

        # Spotify playlist data
        access_token = refresh_spotify_token()
        sp = spotipy.Spotify(auth=access_token)
        playlist = sp.playlist(playlist_id)
        tracks = sp.playlist_tracks(playlist_id)["items"]

        # Check if Google credentials are already in session
        if "google_credentials" in session:
            credentials = Credentials(**session["google_credentials"])
            youtube = build("youtube", "v3", credentials=credentials)
        else:
            # Load client secrets
            client_secrets_file = "client_secrets.json"
            temp_file = None
            if not os.path.exists(client_secrets_file) and os.getenv("GOOGLE_CLIENT_SECRETS"):
                try:
                    client_secrets = json.loads(os.getenv("GOOGLE_CLIENT_SECRETS"))
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                        json.dump(client_secrets, temp_file)
                        temp_file.flush()
                        client_secrets_file = temp_file.name
                    logger.info(f"Created temporary client_secrets file: {client_secrets_file}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid GOOGLE_CLIENT_SECRETS format: {e}")
                    try:
                        return render_template("error.html", message=f"Invalid client secrets format: {str(e)}")
                    except TemplateNotFound as te:
                        logger.error(f"Template not found: {te}")
                        return f"Error: error.html template not found.", 500
                    except TemplateSyntaxError as te:
                        logger.error(f"Template syntax error in error.html: {te}")
                        return f"Error: Invalid syntax in error.html: {str(te)}", 500
                except Exception as e:
                    logger.error(f"Error processing GOOGLE_CLIENT_SECRETS: {e}")
                    try:
                        return render_template("error.html", message=f"Error processing client secrets: {str(e)}")
                    except TemplateNotFound as te:
                        logger.error(f"Template not found: {te}")
                        return f"Error: error.html template not found.", 500
                    except TemplateSyntaxError as te:
                        logger.error(f"Template syntax error in error.html: {te}")
                        return f"Error: Invalid syntax in error.html: {str(te)}", 500
            elif not os.path.exists(client_secrets_file):
                logger.error("client_secrets.json not found and GOOGLE_CLIENT_SECRETS not set")
                try:
                    return render_template("error.html", message="Client secrets file not found.")
                except TemplateNotFound as te:
                    logger.error(f"Template not found: {te}")
                    return f"Error: error.html template not found.", 500
                except TemplateSyntaxError as te:
                    logger.error(f"Template syntax error in error.html: {te}")
                    return f"Error: Invalid syntax in error.html: {str(te)}", 500

            try:
                with open(client_secrets_file, "r", encoding="utf-8") as f:
                    client_secrets = json.load(f)
                logger.info(f"Loaded client_secrets: {json.dumps(client_secrets, indent=2)}")
            except Exception as e:
                logger.error(f"Error loading client_secrets.json: {e}")
                try:
                    return render_template("error.html", message=f"Error loading client secrets: {str(e)}")
                except TemplateNotFound as te:
                    logger.error(f"Template not found: {te}")
                    return f"Error: error.html template not found.", 500
                except TemplateSyntaxError as te:
                    logger.error(f"Template syntax error in error.html: {te}")
                    return f"Error: Invalid syntax in error.html: {str(te)}", 500

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secrets_file,
                    scopes=["https://www.googleapis.com/auth/youtube"],
                    redirect_uri="https://spotify-to-youtube-web.onrender.com/google-callback" if os.getenv("RENDER") else "http://127.0.0.1:5000/google-callback"
                )
                logger.info(f"Google OAuth redirect URI: {flow.redirect_uri}")
                auth_url, state = flow.authorization_url(prompt="consent")
                session["google_oauth_state"] = state
                session["transfer_playlist_id"] = playlist_id
                if temp_file:
                    os.unlink(temp_file.name)
                    logger.info(f"Deleted temporary client_secrets file: {temp_file.name}")
                return redirect(auth_url)
            except Exception as e:
                logger.error(f"Error initializing Google OAuth flow: {e}")
                if temp_file:
                    os.unlink(temp_file.name)
                    logger.info(f"Deleted temporary client_secrets file: {temp_file.name}")
                try:
                    return render_template("error.html", message=f"Failed to initialize Google OAuth: {str(e)}")
                except TemplateNotFound as te:
                    logger.error(f"Template not found: {te}")
                    return f"Error: error.html template not found.", 500
                except TemplateSyntaxError as te:
                    logger.error(f"Template syntax error in error.html: {te}")
                    return f"Error: Invalid syntax in error.html: {str(te)}", 500

        # Create YouTube playlist
        youtube_playlist = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": playlist["name"],
                    "description": playlist.get("description", "Transferred from Spotify")
                },
                "status": {"privacyStatus": "private"}
            }
        ).execute()

        # Transfer tracks and count successes
        total_tracks = len([item for item in tracks if item["track"]])
        successful_transfers = 0
        for i, item in enumerate(tracks[last_transferred:], start=last_transferred):
            track = item["track"]
            if not track:
                continue
            query = f"{track['name']} {track['artists'][0]['name']}"
            try:
                search_response = youtube.search().list(
                    q=query, part="id", maxResults=1, type="video"
                ).execute()
                if search_response["items"]:
                    video_id = search_response["items"][0]["id"]["videoId"]
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "playlistId": youtube_playlist["id"],
                                "resourceId": {"kind": "youtube#video", "videoId": video_id}
                            }
                        }
                    ).execute()
                    successful_transfers += 1
                # Save progress
                progress[resume_key] = {"last_transferred": i + 1}
                write_progress(progress)
            except HttpError as e:
                logger.error(f"Error transferring track {query}: {e}")
                continue

        # Clear progress and session data on completion
        progress.pop(resume_key, None)
        write_progress(progress)
        session.pop("google_oauth_state", None)
        session.pop("google_credentials", None)
        session.pop("transfer_playlist_id", None)
        try:
            return render_template(
                "transfer.html",
                message=f"Playlist '{playlist['name']}' transferred successfully!",
                successful_transfers=successful_transfers,
                total_tracks=total_tracks
            )
        except TemplateNotFound as e:
            logger.error(f"Template not found: {e}")
            return f"Error: transfer.html template not found.", 500
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in transfer.html: {e}")
            return f"Error: Invalid syntax in transfer.html: {str(e)}", 500
    except Exception as e:
        logger.error(f"Transfer error: {e}")
        try:
            return render_template("error.html", message=f"Transfer failed: {str(e)}")
        except TemplateNotFound as te:
            logger.error(f"Template not found: {te}")
            return f"Error: error.html template not found.", 500
        except TemplateSyntaxError as te:
            logger.error(f"Template syntax error in error.html: {te}")
            return f"Error: Invalid syntax in error.html: {str(te)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)