# Word-Play

**Word-Play** is a lightweight, frameless, and transparent Windows desktop overlay that listens to the music currently playing on your OS (via Spotify, Chrome, Apple Music, etc.) and displays synchronized lyrics right on your screen! 

The UI is entirely click-through, ensuring it never interferes with your workflow.

## Features
* **Auto-Sync:** Uses Windows System Media Transport Controls (SMTC) to detect song, artist, and playback position instantly.
* **Lyrics Integration:** Fetches timestamped lyrics from the open LRCLIB database.
* **Non-Intrusive Overlay:** A transparent, click-through, always-on-top window using PyQt6 and Win32 hooks.
* **System Tray Control:** Runs quietly in the background. Right click the system tray icon to exit.

## Running the App

### Option 1: Standalone Executable (Easy)
1. Go to the `dist` folder.
2. Double click `WordPlay.exe`. 
3. Play a song on Spotify or your browser, and watch the lyrics appear at the bottom of your screen!

### Option 2: From Source
1. Ensure you have Python 3.10+ installed.
2. Install the required dependencies: `pip install PyQt6 winrt-Windows.Media.Control winrt-Windows.Foundation requests`
3. Run the script: `python main.py`

## Portfolio Demo Video
For the portfolio showcase, simply run the executable while capturing your screen, open a Spotify window, play a popular English song (like "Shape of You" by Ed Sheeran), and demonstrate how the lyrics sync automatically and allow you to click on the Spotify window *through* the lyrics.

## Architecture & Tech Stack
* Language: Python 3
* UI: PyQt6
* OS API: `winrt` (Windows Runtime Projections)
* API: `lrclib.net`
