# Word-Play Management Dashboard Architecture

This document provides a technical overview of the **Word-Play Management Dashboard**, a lightweight local web interface designed to monitor, edit, and manage the lyrics stored in the MongoDB database.

---

## 🏗️ Dashboard Layout & Structure

The dashboard is built as a separate service from the main Word-Play desktop application. It runs locally on port `5000` and provides a graphical interface to the underlying data.

```text
c:\Projects\word-play\
├── db_config.py            # Shared MongoDB connection singleton
├── dashboard/
│   ├── app.py              # The Flask backend application (Entrypoint)
│   └── templates/
│       ├── index.html      # Home view: Stats and lyrics browser table
│       └── detail.html     # Editor view: Manual overrides and Force Sync
```

## 🛠️ Technical Stack

- **Backend:** Python with [Flask](https://flask.palletsprojects.com/) (v3.0+). Chosen for its simplicity and lightweight nature, ideal for a local utility dashboard.
- **Frontend:** HTML5 with [Bootstrap 5](https://getbootstrap.com/) via CDN. Provides a responsive, dark-themed UI without the need for complex JavaScript frameworks or build steps.
- **Database:** MongoDB Atlas (accessed via `pymongo`).

---

## 🔌 Database Integration (`db_config.py`)

To adhere to DRY (Don't Repeat Yourself) principles and prevent synchronization bugs, the database connection logic is separated into a root module (`db_config.py`). 

Both the main desktop application (`lyrics_manager.py`) and the web dashboard (`app.py`) import this module. It utilizes a **Singleton Pattern** to ensure that the `MongoClient` is initialized only once per process, reducing overhead and connection limits on the MongoDB Atlas cluster.

---

## 🚦 Backend Routing (`app.py`)

The Flask application defines several distinct routes to handle user interactions:

1. **`GET /` (Index)**
   - Fetches all documents from the `lyrics` collection, sorted alphabetically by artist and track.
   - Calculates high-level statistics: Total Songs, Number of AI Synced songs, and Number of Plain Text songs.
   - Renders `index.html`.

2. **`GET /edit/<doc_id>` (Detail View)**
   - Looks up a specific song by its MongoDB `ObjectId`.
   - Analyzes the `plainLyrics` and `syncedLyrics` strings using a heuristic `is_hebrew()` function. If Hebrew characters (`\u0590` to `\u05FF`) are detected, it flags the text areas to render in RTL (Right-to-Left) mode.
   - Renders `detail.html`.

3. **`POST /api/update/<doc_id>`**
   - Receives form data from the editor.
   - Performs an `update_one()` operation in MongoDB to explicitly overwrite the `plainLyrics` and `syncedLyrics` fields.
   - Converts empty HTML strings to `null` to maintain database consistency.

4. **`POST /api/force_sync/<doc_id>`**
   - This endpoint demonstrates a decoupled inter-process communication strategy. See the **"Safe AI Forcing"** section below.

5. **`POST /api/delete/<doc_id>`**
   - Performs a destructive `delete_one()` operation to remove bad or corrupted metadata entries from the database permanently.

---

## 🧠 Safe AI Forcing (Decoupled Sync Logic)

**The Problem:** The heavy AI forced-alignment model (`stable-ts` / Whisper) requires exclusive access to GPU VRAM and runs inside QThreads bound to the main PyQt6 desktop application. Attempting to trigger this heavy PyTorch inference directly from the Flask web server process could result in:
- Out of Memory (OOM) GPU crashes.
- Thread locks, as PyTorch expects to own the CUDA context.
- Duplicate processing if the song is currently playing.

**The Solution:** The dashboard utilizes a decoupled data-driven approach:
- When "Force AI Sync" is clicked, the Flask backend does **not** run the AI model. 
- Instead, it simply updates the MongoDB document: it sets `syncedLyrics` to `null` and resets the `last_sync_attempt` timestamp to `0`.
- The next time that specific song is played by the user, the Word-Play desktop application queries the database, notices the missing sync and the expired cooldown, and safely triggers the alignment process natively within its own protected thread and GPU context.

---

## 🎨 Frontend Design Patterns

- **`index.html`**: Utilizes Bootstrap cards for the top-level statistics display. The song list is rendered as a standard `table-dark` with conditional `badge` classes (Green: Synced, Yellow: Plain/Pending) to give the user immediate visual feedback on the state of their library.
- **`detail.html`**: A split-column layout. The left column contains the large text areas for editing lyrics. The right column contains the "Sync Controls" and the "Danger Zone" (Deletion) areas, visually separated by color semantics (Warning/Danger). Flash messages from the Flask backend bubble up to the top of both pages to confirm successful database operations.
