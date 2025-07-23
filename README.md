# Spotify to YouTube Web

A web application that transfers Spotify playlists to YouTube, supporting private and collaborative playlists. Built with Flask, it uses Spotify and Google OAuth for authentication and handles simultaneous user sessions securely.

## Features
- Authenticate with Spotify to access private and collaborative playlists.
- Transfer Spotify playlists to YouTube as private playlists.
- Resume interrupted transfers with progress tracking.
- Support for multiple users with isolated sessions.
- Logout functionality that clears all session data and redirects to the index page.

## Prerequisites
- Python 3.13
- Git
- pip (Python package manager)

## Installation

### Clone the Repository
```bash
git clone https://github.com/your-username/spotify-to-youtube-web.git
cd spotify-to-youtube-web
```

### Install Dependencies
Create and activate a virtual environment (recommended):
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
source venv/bin/activate  # On macOS/Linux
```

Install required packages:
```bash
pip install -r requirements.txt
```

### Environment Variables
Create a `.env` file in the project root with the following:
```
FLASK_SECRET_KEY=your_secure_secret_key
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/callback  # For local testing
GOOGLE_CLIENT_SECRETS={"web":{"client_id":"your_google_client_id","client_secret":"your_google_client_secret","redirect_uris":["http://127.0.0.1:5000/","http://127.0.0.1:5000/callback","http://127.0.0.1:5000/google-callback","http://localhost:5000/","http://localhost:5000/callback","http://localhost:5000/google-callback"],"auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs"}}
RENDER=true  # Set to true when deploying to Render
```

- Obtain `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
- Obtain `GOOGLE_CLIENT_SECRETS` by creating a project in the [Google Cloud Console](https://console.cloud.google.com/), enabling the YouTube Data API, and downloading the OAuth 2.0 credentials as a JSON file.

### Initialize Data Directory
Ensure the `data` directory exists:
```bash
mkdir data
```

## Running the Application

### Locally
Start the development server:
```bash
python app.py
```

Open your browser and navigate to `http://127.0.0.1:5000`.

### Deploying to Render
1. Push your code to a Git repository (e.g., GitHub).
2. Create a new Web Service on [Render](https://render.com/).
3. Connect your repository and set the following environment variables in the Render dashboard:
   - `FLASK_SECRET_KEY`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `SPOTIFY_REDIRECT_URI=https://your-render-url/callback`
   - `GOOGLE_CLIENT_SECRETS` (as a JSON string)
   - `RENDER=true`
4. Set the build command to `pip install -r requirements.txt` and the start command to `gunicorn --workers 4 --threads 4 app:app`.
5. Deploy the service and access it at the provided URL (e.g., `https://spotify-to-youtube-web.onrender.com`).

## Usage
1. **Login**:
   - Click "Log in with Spotify" on the index page.
   - You’ll be redirected to `https://accounts.spotify.com/en/login` to enter your credentials.
   - Authorize the app to access your playlists (required on first login or for different accounts).
2. **View Playlists**:
   - After successful login, you’ll be redirected to `/playlists`, listing your Spotify playlists.
3. **Transfer a Playlist**:
   - Click a playlist to initiate the transfer to YouTube.
   - Authorize with Google if not already done, then wait for the transfer to complete.
   - View the transfer status on the transfer page.
4. **Logout**:
   - Click "Log out" to clear all session data and return to the index page.
   - The next login will attempt to auto-authenticate with the same account if possible.

## Troubleshooting
- **State Mismatch Error**: If you encounter "Invalid or missing state parameter" errors, ensure the `session_id` and `state` are consistently passed between `/login`, `/authorize`, and `/callback`. Clear the `data` directory and retry.
- **TypeError with `show_dialog`**: Upgrade `spotipy` to version `>=2.19.0` in `requirements.txt` if you see this error.
- **Template Errors**: Verify `templates/index.html`, `templates/playlists.html`, `templates/transfer.html`, and `templates/error.html` exist and are syntactically correct.
- **Clear Cache**: Delete `data/.cache*` and `data/sessions` files if sessions behave unexpectedly.

## Development
- **Dependencies**: Managed in `requirements.txt`. Update with `pip freeze > requirements.txt` after adding packages.
- **Logging**: Check logs in the console or Render logs for debugging.
- **Testing**: Test locally with different browsers (e.g., Chrome, Firefox) to verify simultaneous logins.

## Contributing
Feel free to submit issues or pull requests on the GitHub repository. Ensure changes are tested locally before submission.

## License
[MIT License](LICENSE) - Feel free to modify and distribute, but include the original license.

## Acknowledgments
- [Spotipy](https://spotipy.readthedocs.io/) for Spotify API integration.
- [Google API Client Library](https://github.com/googleapis/google-api-python-client) for YouTube API access.
- [Flask](https://flask.palletsprojects.com/) for the web framework.