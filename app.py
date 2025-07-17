import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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