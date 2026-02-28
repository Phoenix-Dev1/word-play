# Word-Play (v0.14) Technical Architecture

This document summarizes the core architecture, data flows, and state management of the Word-Play lyrics overlay application for Windows.

## 1. Global Architecture & Threading Model

Word-Play operates using three distinct threading/concurrency models to ensure a fluid, non-blocking UI:

-   **PyQt6 Main UI Thread**: Manages the `LyricsOverlay` window, the `SmoothScrollArea` (Unsynced Mode), the 5-line synced view, and all animations. A 100ms high-frequency timer drives the UI updates.
-   **WinRT SMTC Async Loop**: The `MediaListener` runs an `asyncio` event loop inside a dedicated daemon thread. It polls the Windows `GlobalSystemMediaTransportControlsSessionManager` every 500ms to update media state.
-   **LyricsManager Background Threads**: All HTTP requests (LRCLIB, Genius) and heavy AI alignment tasks (`stable-ts`) are spawned as independent `threading.Thread` instances. This prevents the UI from freezing during network latency or model inference.

## 2. Frontend & OS Hooks (`main.py`)

The UI is designed to be persistent but non-intrusive.

-   **Win32 Geofencing**: The window is initialized with `WS_EX_TRANSPARENT` and `WS_EX_LAYERED` flags. This makes the overlay click-through and "invisible" to the mouse by default.
-   **Ctrl-Key Hit-Testing**: The app uses `ctypes.windll.user32.GetAsyncKeyState(0x11)` to monitor the Ctrl key. When held, the `WS_EX_TRANSPARENT` flag is removed, instantly making the window interactive for dragging (moving the overlay) or manual scrolling.
-   **Dynamic RTL Shifting**: The app detects Hebrew characters in tracks or lyrics. If found, it dynamically sets `setLayoutDirection(Qt.LayoutDirection.RightToLeft)` and shifts text alignment to `AlignRight | AlignAbsolute`.
-   **UI State Switching**: The app seamlessly toggles between two modes:
    -   **Synced Mode**: A 5-line karaoke-style view with smoothed transitions for active lines.
    -   **Unsynced Mode**: A `SmoothScrollArea` that renders cleaned `plainLyrics`, allowing the user to manually scroll at their leisure.

## 3. Telemetry (`media_listener.py`)

To achieve millisecond-perfect lyric synchronization, Word-Play implements a position extrapolation engine:

1.  **SMTC Extraction**: Retrieves `base_position`, `last_updated_time`, and `is_playing` state from the WinRT session.
2.  **Extrapolation Logic**: Instead of relying solely on the 500ms poll, the `current_position` property calculates: `base_position + (now_utc - last_updated_time)`. This compensates for polling intervals and provides 0ms-latency visual synchronization.

## 4. The Data & Fallback Pipeline (`lyrics_manager.py`)

The application uses a robust, multi-tier pipeline to find lyrics for any song:

-   **JSON Filesystem Cache**: Data is cached in `lyrics_cache/`. Filenames are generated using an **MD5 hash** of `artist-track` to prevent filesystem encoding issues with Unicode/Hebrew titles.
-   **The Pipeine**: 
    1.  **LRCLIB (Exact)**: Standard API match.
    2.  **LRCLIB (Fuzzy/Root Search)**: Strips production credits/brackets and tries broader queries.
    3.  **Transliteration Search**: Extracts English parts from mixed-language titles.
    4.  **Tier 4 Genius AJAX Scraper**:
        -   Uses spoofed Chrome headers and Cloudflare headers to evade bot detection.
        -   Parses Genius `/api/search/multi` JSON, iterating through all sections (including `top_hit`).
        -   Extracts lyrics from multiple dynamic React `data-lyrics-container` elements.
        -   Stitches fragments and cleans headers/tags via a regex-based `clean_plain_lyrics` method.
    5.  **Tier 5 Local AI Alignment**: (See Section 5).

## 5. Local AI Forced Alignment Engine

When only `plainLyrics` are available, Word-Play activates its internal sync engine:

-   **Audio Fetching (`yt-dlp`)**: Searches YouTube (via `ytsearch1:`) and downloads the lowest-quality audio stream to a `temp_audio/` directory.
-   **Whisper Alignment (`stable-ts`)**:
    -   Initializes the `stable-whisper` (Whisper 'base') model.
    -   **GPU Routing**: Automatically detects CUDA support and routes PyTorch inference to the NVIDIA GPU if available.
    -   **Forced Alignment**: Maps the provided `plainLyrics` text directly onto the audio timeline using the model's `.align()` method.
-   **LRC Finalization**: 
    -   Translates the alignment segments into standard `[mm:ss.xx]` LRC tags.
    -   Updates the local JSON cache, promoting the song from "Unsynced" to "Synced".
    -   Signals the UI to snap back into Karaoke mode.
