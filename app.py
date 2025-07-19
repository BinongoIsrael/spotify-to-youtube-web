from flask import Flask, redirect, request, session, render_template, url_for, make_response
from flask_session import Session
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
import urllib.parse
import threading

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
load_dotenv()

# Configure Flask-Session
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join("data", "sessions")
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
Session(app)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths for progress file
PROGRESS_FILE = "data/transfer_progress.json"

# Ensure data directory and files exist
os.makedirs("data", exist_ok=True)
if not os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({}, f)

# Thread-safe OAuth state store
oauth_states = {}
oauth_states_lock = threading.Lock()

# Suppress Spotify deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Spotify OAuth setup with unique cache path per session
def get_spotify_oauth(session_id):
    cache_path = os.path.join("data", f".cache-{session_id}")
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope="playlist-read-private playlist-read-collaborative",
        cache_path=cache_path,  # Unique cache path per session
        state=session_id   # Use session_id as state for uniqueness
    )

def store_oauth_state(session_id, state):
    """Store OAuth state in thread-safe dictionary."""
    with oauth_states_lock:
        oauth_states[session_id] = state
        logger.info(f"Stored OAuth state for session_id {session_id}: {state}")

def get_oauth_state(session_id):
    """Retrieve OAuth state from thread-safe dictionary."""
    with oauth_states_lock:
        state = oauth_states.get(session_id)
        logger.info(f"Retrieved OAuth state for session_id {session_id}: {state}")
        return state

def remove_oauth_state(session_id):
    """Remove OAuth state from thread-safe dictionary."""
    with oauth_states_lock:
        oauth_states.pop(session_id, None)
        logger.info(f"Removed OAuth state for session_id {session_id}")

def refresh_spotify_token():
    """Refresh Spotify access token if expired."""
    try:
        token_info = session.get("token_info")
        if not token_info:
            raise ValueError("No token info in session")
        
        expires_at = token_info.get("expires_at")
        if not expires_at or datetime.now().timestamp() >= expires_at - 60:
            logger.info("Spotify token expired or about to expire, refreshing...")
            session_id = session.get("session_id")
            if not session_id:
                raise ValueError("No session_id in session")
            sp_oauth = get_spotify_oauth(session_id)
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
        # Ensure session is fresh for new requests
        session.pop("token_info", None)
        # Generate a unique session ID and cookie name if not present
        if "session_id" not in session:
            session["session_id"] = str(uuid.uuid4())
            app.config["SESSION_COOKIE_NAME"] = f"session_{session['session_id']}"  # Unique cookie name per session
            session.modified = True
        logger.info(f"Index accessed with session_id: {session['session_id']}, cookie: {app.config['SESSION_COOKIE_NAME']}")
        return render_template("index.html")
    except TemplateNotFound as e:
        logger.error(f"Template not found: {e}")
        return "Error: index.html template not found.", 500
    except TemplateSyntaxError as e:
        logger.error(f"Template syntax error in index.html: {e}")
        return f"Error: Invalid syntax in index.html: {str(e)}", 500

@app.route("/login")
def login():
    # Clear existing Spotify session, Flask session, and cache files
    session_id = session.get("session_id", "unknown")
    session.clear()  # Clear all session data
    for cache_file in os.listdir("data"):
        if cache_file.startswith(".cache"):
            try:
                os.remove(os.path.join("data", cache_file))
                logger.info(f"Removed cache file: {cache_file}")
            except Exception as e:
                logger.error(f"Error removing cache file {cache_file}: {e}")
    remove_oauth_state(session_id)
    
    # Generate new session ID and cookie name
    session["session_id"] = str(uuid.uuid4())
    app.config["SESSION_COOKIE_NAME"] = f"session_{session['session_id']}"
    session.modified = True
    logger.info(f"Session contents in /login: {session}, cookie: {app.config['SESSION_COOKIE_NAME']}")
    
    # Set up Spotify OAuth
    sp_oauth = get_spotify_oauth(session["session_id"])
    state = session["session_id"]
    store_oauth_state(session["session_id"], state)
    
    # Manually construct auth URL with show_dialog=true
    auth_url = sp_oauth.get_authorize_url(state=state)
    parsed_url = urllib.parse.urlparse(auth_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    query_params['show_dialog'] = ['true']
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    auth_url = urllib.parse.urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))
    logger.info(f"Redirecting to Spotify auth URL with state {state}: {auth_url}")
    
    # Clear all cookies (Flask and Spotify)
    response = make_response(redirect(auth_url))
    spotify_cookies = [
        "spotify-auth-session", "sp_t", "sp_key", "sp_dc", "__Host-auth.ext",
        "sp_landing", "sp_at", "sp_f", "sp_m", "sp_new", "sp_sso"
    ]
    for cookie in spotify_cookies:
        response.set_cookie(cookie, "", expires=0, domain=".spotify.com", path="/")
        response.set_cookie(cookie, "", expires=0, path="/")  # Clear for app domain too
    response.set_cookie(app.config["SESSION_COOKIE_NAME"], "", expires=0, path="/")
    
    return response

@app.route("/clear")
def clear_session():
    session_id = session.get("session_id", "unknown")
    session.clear()
    for cache_file in os.listdir("data"):
        if cache_file.startswith(".cache"):
            try:
                os.remove(os.path.join("data", cache_file))
                logger.info(f"Removed cache file: {cache_file}")
            except Exception as e:
                logger.error(f"Error removing cache file {cache_file}: {e}")
    remove_oauth_state(session_id)
    spotify_cookies = [
        "spotify-auth-session", "sp_t", "sp_key", "sp_dc", "__Host-auth.ext",
        "sp_landing", "sp_at", "sp_f", "sp_m", "sp_new", "sp_sso"
    ]
    response = make_response(redirect(url_for("login")))
    for cookie in spotify_cookies:
        response.set_cookie(cookie, "", expires=0, domain=".spotify.com", path="/")
        response.set_cookie(cookie, "", expires=0, path="/")
    logger.info(f"Cleared all cookies and session data for session_id {session_id}")
    return response

@app.route("/logout")
def logout():
    session_id = session.get("session_id", "unknown")
    for cache_file in os.listdir("data"):
        if cache_file.startswith(".cache"):
            try:
                os.remove(os.path.join("data", cache_file))
                logger.info(f"Removed cache file: {cache_file}")
            except Exception as e:
                logger.error(f"Error removing cache file {cache_file}: {e}")
    remove_oauth_state(session_id)
    logger.info(f"Cleared all Spotify and Flask cookies and redirected to index for session_id: {session_id}")
    return redirect(url_for("clear_session"))

@app.route("/callback")
def callback():
    try:
        session_id = session.get("session_id")
        if not session_id:
            raise ValueError("No session_id in session")
        sp_oauth = get_spotify_oauth(session_id)
        state = request.args.get("state")
        expected_state = get_oauth_state(session_id)
        if not state or state != expected_state:
            raise ValueError(f"Invalid or missing state parameter: got {state}, expected {expected_state}")
        token_info = sp_oauth.get_access_token(request.args["code"], as_dict=True)
        session["token_info"] = token_info
        remove_oauth_state(session_id)
        logger.info(f"Spotify token obtained for session_id {session_id}: {token_info['access_token'][:10]}...")
        logger.info(f"Token info in /callback: {token_info}")
        return redirect(url_for("playlists"))
    except Exception as e:
        logger.error(f"Spotify auth error: {e}")
        session.pop("token_info", None)
        remove_oauth_state(session_id)
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
        logger.info(f"Fetched playlists for Spotify user: {user['id']} ({user.get('display_name', 'Unknown')}) with session_id: {session.get('session_id')}")
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
        session_id = session.get("session_id", "unknown")
        state = get_oauth_state(session_id)
        if not state:
            raise ValueError("No OAuth state found for session")
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
        remove_oauth_state(session_id)
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
        logger.info(f"Resuming transfer from index {last_transferred} for session_id: {session.get('session_id')}")

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
                store_oauth_state(session.get("session_id", "unknown"), state)
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
        session.pop("google_credentials", None)
        session.pop("transfer_playlist_id", None)
        remove_oauth_state(session.get("session_id", "unknown"))
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True, threaded=True)