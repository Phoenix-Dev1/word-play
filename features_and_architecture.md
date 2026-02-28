# Word-Play Complete Architecture & Features

This document provides a comprehensive overview of the **Word-Play** desktop application, detailing its user-facing features, underlying architecture, and database schema.

---

## 🌟 Application Features

Word-Play is a non-intrusive, automated desktop lyrics overlay that synchronizes with any media playing on your Windows machine.

### Core Capabilities
1. **Universal Media Detection**
   - Automatically detects what song is playing across any Windows application (Spotify, Chrome, YouTube, Apple Music, etc.) using native Windows APIs.
   - Detects play, pause, and track change events instantly.

2. **Smart Lyrics Sourcing**
   - Automatically searches for lyrics using a multi-tiered fallback system.
   - Primarily relies on **LRCLIB** for time-synced lyrics.
   - Falls back to advanced fuzzy searching and transliteration matching for hard-to-find tracks.
   - Includes a custom **Genius Web Scraper** specifically built to handle Israeli/Hebrew tracks that aren't available on standard API endpoints.

3. **AI Forced Alignment (Karaoke Sync)**
   - If Word-Play finds lyrics online but they don't have time-stamps (plain text), it triggers a background AI engine (`stable-ts` / Whisper).
   - Word-Play downloads a tiny snippet of the song's audio from YouTube in the background, feeds it to the AI alongside the plain text lyrics, and generates perfect millisecond timestamps for every line.

4. **Dynamic Synchronized UI**
   - **Click-Through Overlay:** A beautiful, translucent overlay that floats on your screen. It is completely transparent to your mouse, meaning you can click "through" it to applications underneath.
   - **Interactive Mode:** By holding the `Ctrl` key, the window solidifies, allowing you to drag it around your screen or interact with its buttons.
   - **5-Line Karaoke View:** Displays the current line in bold white text, with the two previous and two upcoming lines faded in the background. It scrolls smoothly as the music plays.
   - **RTL Language Detection:** Automatically detects Hebrew/Arabic and shifts the UI alignment from Left-to-Right to Right-to-Left instantly.
   - **Loading States:** Displays "⚙️ AI Syncing Audio..." when the AI is processing plain lyrics in the background, preventing jarring UI jumps.

5. **Manual Scroll Fallback**
   - If a song completely fails to align via AI, the app gracefully falls back to a clean, scrollable text box containing the plain lyrics, which you can read at your own pace.

---

## 🗄️ Database Schema (MongoDB Atlas)

Word-Play uses a centralized remote MongoDB database to cache lyrics. This prevents the app from hammering external APIs or running the heavy AI alignment model twice for the same song.

**Database Name:** `word_play`
**Collection Name:** `lyrics`

### Document Structure

````json
{
  "_id": ObjectId("65dfa2..."),      // MongoDB native ID
  "track": "מי נהר",                 // The name of the song
  "artist": "עידן רייכל",              // The name of the artist
  "plainLyrics": "מי נהר...",         // Standard text lyrics (with \n breaks)
  "syncedLyrics": "[00:13.77]מי...", // LRC format timestamps string (or null)
  "last_sync_attempt": 1709214533.5, // Epoch timestamp of last AI sync attempt 
  
  // LRCLIB Extended Metadata (Optional fields usually pulled from the API)
  "albumName": "רבע לשש", 
  "duration": 224,
  "instrumental": false
}
````

### Key Database Mechanics
- **Unique Indexing:** The collection maintains a Unique Index on the combined `(artist, track)` fields. If a song is searched again, the database uses `$set` and `upsert=True` to update it or create it if missing.
- **Retry Cooldown Flow:** When a song is fetched from the database and it only has `plainLyrics` (meaning `syncedLyrics` is `null`), the app checks the `last_sync_attempt` timestamp. 
  - If the timestamp doesn't exist, or if it has been **over 24 hours**, the app will re-trigger the heavy AI Alignment process in the edge case that it failed the first time.

---

## 🧩 Project Layout & Architecture

The application is heavily multithreaded to keep the UI smooth (running at 100fps) while heavy network requests and AI inference happen in the background.

```text
c:\Projects\word-play\
├── core/                   # Shared non-UI logic
│   ├── audio_poller.py     # Background audio device monitoring
│   └── window_utils.py     # Lower-level Win32 API interactions
├── ui/                     # All visual components
│   ├── overlay_window.py   # The main lyrics display frame
│   ├── tray_manager.py     # System tray icon and menu logic
│   ├── styles.py           # Centralized QSS stylesheet provider
│   ├── icon_provider.py    # Dynamic QPainter-based tray icons
│   ├── components.py       # Custom scroll areas and UI widgets
│   └── constants.py        # Shared UI strings and sync phrases
├── dashboard/              # Flask Web Management Interface
│   ├── app.py              # Backend API and HTMX routes
│   └── templates/          # Bootstrap 5 Jinja2 templates
├── Tests/                  # (Ignored) Organized suite of debug and unit tests
├── lyrics_manager.py       # (PyMongo / Requests) The brain orchestrating the backend.
├── main.py                 # Minimal boot script binding all modules together.
├── requirements.txt        # Python package dependencies
├── .gitignore              # Ignored files (Tests/, build/, venv/, etc.)
└── venv/                   # Local Python environment
```

### Concurrency Model
1. **Main UI Thread (`main.py`)**: Draws the graphics, handles animations and mouse events.
2. **SMTC Polling Thread (`media_listener.py`)**: Runs an asyncio loop asking Windows what song is playing every half-second.
3. **Fetching Worker (`lyrics_manager.py`)**: QThread spawned every time a song changes to query MongoDB and the internet without freezing the UI.
4. **AI Alignment Worker (`lyrics_manager.py`)**: Heavy QThread constrained by a `Semaphore(1)` that locks GPU resources to transcribe and timestamp lyrics.
