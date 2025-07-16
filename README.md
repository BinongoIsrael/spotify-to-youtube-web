# Spotify to YouTube Web Transfer

A web app to transfer Spotify playlists to YouTube with resume capability.

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Configure `.env` with Spotify credentials and place `client_secrets.json` in the root.
3. Run locally: `python app.py`
4. Deploy to Heroku or similar platform.

## Usage
- Visit the app URL, log in with Spotify, select a playlist, and transfer.
- If halted, restart to resume from the last added track.

## Notes
- Quota limit: 10,000 units/day, resets at midnight PST.
- Resume uses checkpoint files in the `checkpoints` directory.