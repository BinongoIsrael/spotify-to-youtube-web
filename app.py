from flask import Flask, render_template, request, redirect, url_for, session
import os
from dotenv import load_dotenv
from spotify_to_youtube import authenticate_spotify, authenticate_youtube, get_spotify_playlists, get_playlist_tracks, create_youtube_playlist, add_video_to_playlist, search_youtube_video, load_checkpoint, save_checkpoint, finalize_spotify_auth, finalize_youtube_auth
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging

app = Flask(__name__)
app.secret_key = os.urandom(24)
load_dotenv()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    logger.debug(f"Login - spotify_authenticated={session.get('spotify_authenticated')}, session_id={id(session)}")
    if not session.get('spotify_authenticated'):
        logger.debug("Redirecting to authenticate_spotify")
        return authenticate_spotify()
    logger.debug("Redirecting to select_playlist")
    return redirect(url_for('select_playlist'))

@app.route('/select_playlist')
def select_playlist():
    logger.debug(f"Select Playlist - spotify_authenticated={session.get('spotify_authenticated')}, youtube_authenticated={session.get('youtube_authenticated')}, spotify_token={session.get('spotify_token')}, session_id={id(session)}")
    if not session.get('spotify_authenticated'):
        logger.debug("Redirecting to login (spotify not authenticated)")
        return redirect(url_for('login'))
    if not session.get('youtube_authenticated'):
        logger.debug("Redirecting to login (youtube not authenticated)")
        return redirect(url_for('login'))
    if not session.get('spotify_token'):
        logger.debug("Redirecting to login (no spotify token)")
        return redirect(url_for('login'))
    sp = spotipy.Spotify(auth=session['spotify_token'])
    playlists = get_spotify_playlists(sp)
    logger.debug("Rendering select_playlist.html")
    return render_template('select_playlist.html', playlists=playlists)

@app.route('/select_playlist')
def select_playlist():
    logger.debug(f"Select Playlist - spotify_authenticated={session.get('spotify_authenticated')}, youtube_authenticated={session.get('youtube_authenticated')}, spotify_token={session.get('spotify_token')}, session_id={id(session)}")
    if not session.get('spotify_authenticated'):
        logger.debug("Redirecting to login (spotify not authenticated)")
        return redirect(url_for('login'))
    if not session.get('youtube_authenticated'):
        logger.debug("Redirecting to login (youtube not authenticated)")
        return redirect(url_for('login'))
    if not session.get('spotify_token'):
        logger.debug("Redirecting to login (no spotify token)")
        return redirect(url_for('login'))
    sp = spotipy.Spotify(auth=session['spotify_token'])
    playlists = get_spotify_playlists(sp)
    logger.debug("Rendering select_playlist.html")
    return render_template('select_playlist.html', playlists=playlists)

@app.route('/spotify_callback')
def spotify_callback():
    logger.debug(f"Spotify Callback - state={request.args.get('state')}, code={request.args.get('code')}, session_id={id(session)}")
    if 'spotify_oauth_state' not in session or session['spotify_oauth_state'] != request.args.get('state'):
        logger.debug("Invalid state parameter")
        return "Invalid state parameter", 400
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/spotify_callback"),
        scope="playlist-read-private"
    )
    if 'code' in request.args:
        token_info = sp_oauth.get_access_token(request.args['code'])
        session['spotify_token'] = token_info['access_token']
        logger.debug("Spotify token set")
    session['spotify_authenticated'] = True
    logger.debug("Spotify authenticated, redirecting to select_playlist")
    return redirect(url_for('select_playlist'))

@app.route('/youtube_callback')
def youtube_callback():
    logger.debug(f"YouTube Callback - state={request.args.get('state')}, code={request.args.get('code')}, session_id={id(session)}")
    if 'state' not in session or session['state'] != request.args.get('state'):
        logger.debug("Invalid state parameter")
        return "Invalid state parameter", 400
    try:
        youtube = finalize_youtube_auth(request)
        session['youtube_authenticated'] = True
        session['youtube_instance'] = str(youtube)
        logger.debug("YouTube authenticated, redirecting to select_playlist")
    except Exception as e:
        logger.error(f"YouTube auth failed: {e}")
        return "YouTube authentication failed", 500
    return redirect(url_for('select_playlist'))
    
@app.route('/transfer', methods=['POST'])
def transfer():
    if not session.get('youtube_authenticated') or not session.get('spotify_authenticated'):
        return redirect(url_for('login'))
    youtube = eval(session['youtube_instance'])  # Retrieve YouTube instance
    sp = spotipy.Spotify(auth=session['spotify_token'])
    playlist_id = request.form['playlist_id']
    checkpoint = load_checkpoint(playlist_id)
    youtube_playlist_id = checkpoint.get('youtube_playlist_id')

    if not youtube_playlist_id:
        tracks = get_playlist_tracks(sp, playlist_id)
        if not tracks:
            return render_template('transfer_status.html', message="No tracks found in the playlist.")
        playlist_name = next((p['name'] for p in get_spotify_playlists(sp) if p['id'] == playlist_id), 'New Playlist')
        youtube_playlist_id = create_youtube_playlist(youtube, playlist_name, f"Transferred from Spotify: {playlist_name}")
        save_checkpoint(playlist_id, youtube_playlist_id, -1)
    else:
        tracks = get_playlist_tracks(sp, playlist_id)
        if not tracks:
            return render_template('transfer_status.html', message="Failed to reload playlist tracks.")

    total_tracks = len(tracks)
    print(f"Total tracks: {total_tracks}, First track: {tracks[0]['track']['name'] if tracks else 'None'}")
    last_index = checkpoint.get('last_track_index', -1) + 1
    added_tracks = 0
    unmatched_tracks = []

    batch_size = 10
    for i in range(max(0, last_index), len(tracks), batch_size):
        batch = tracks[i:i + batch_size]
        for j, track in enumerate(batch):
            current_index = i + j
            if current_index <= last_index and current_index > 0:
                continue
            track_info = track.get('track', {})
            if not track_info or 'name' not in track_info or 'artists' not in track_info or not track_info['artists']:
                unmatched_tracks.append(f"Invalid track at index {current_index}")
                print(f"Skipping invalid track at index {current_index}")
                continue
            track_name = track_info['name']
            artist = track_info['artists'][0]['name']
            print(f"Searching for: {track_name} by {artist}")
            video_id = search_youtube_video(youtube, track_name, artist)
            if video_id:
                try:
                    add_video_to_playlist(youtube, youtube_playlist_id, video_id)
                    added_tracks += 1
                    save_checkpoint(playlist_id, youtube_playlist_id, current_index)
                    print(f"Added: {track_name}")
                except Exception as e:
                    print(f"Failed to add {track_name}: {e}")
                    if 'quotaExceeded' in str(e):
                        return render_template('transfer_status.html', message=f"Quota exceeded after {added_tracks}/{total_tracks} tracks. Resume after 12:00 AM PST (July 18, 2025).")
            else:
                unmatched_tracks.append(f"{track_name} by {artist}")
                print(f"Not found: {track_name}")
        time.sleep(60)  # Wait 1 minute between batches

    status = f"Transferred {added_tracks}/{total_tracks} tracks successfully!"
    if unmatched_tracks:
        status += "\nCould not find the following tracks on YouTube:"
        for track in unmatched_tracks:
            status += f"\n- {track}"
    session.clear()
    return render_template('transfer_status.html', message=status)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)