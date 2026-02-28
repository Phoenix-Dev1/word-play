import sys
import os
import math
import time
import logging
import urllib.parse
from bson.objectid import ObjectId
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta

# Add parent directory to path to import db_config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import db_config

app = Flask(__name__)
app.secret_key = "wordplay_dashboard_secret_key" # Replace in production

# Use the shared MongoDB configuration
lyrics_collection = db_config.get_lyrics_collection()

def is_hebrew(text):
    """Simple heuristic to detect Hebrew characters for RTL layout."""
    if not text:
        return False
    return any("\u0590" <= char <= "\u05FF" for char in text)

def _build_search_query(search_query, artist_filter, needs_attention):
    query = {}
    if search_query:
        query["track"] = {"$regex": search_query, "$options": "i"}
    if artist_filter:
        query["artist"] = artist_filter
    if needs_attention:
        twenty_four_hours_ago = time.time() - 86400
        query["$and"] = [
            {"syncedLyrics": {"$in": [None, ""]}},
            {"plainLyrics": {"$nin": [None, ""]}},
            {"$or": [
                {"last_sync_attempt": {"$exists": False}},
                {"last_sync_attempt": None},
                {"last_sync_attempt": {"$lt": twenty_four_hours_ago}}
            ]}
        ]
    return query

@app.route("/")
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search_query = request.args.get('q', '').strip()
    artist_filter = request.args.get('artist', '').strip()
    needs_attention = request.args.get('needs_attention', 'false').lower() == 'true'

    query = _build_search_query(search_query, artist_filter, needs_attention)

    # Global stats
    total_docs = lyrics_collection.count_documents({})
    synced_count = lyrics_collection.count_documents({"syncedLyrics": {"$nin": [None, ""]}})
    plain_count = total_docs - synced_count
    
    pct_synced = round((synced_count / total_docs * 100)) if total_docs > 0 else 0
    pct_plain = round((plain_count / total_docs * 100)) if total_docs > 0 else 0

    filtered_count = lyrics_collection.count_documents(query)
    total_pages = math.ceil(filtered_count / per_page)
    
    skip = (page - 1) * per_page
    cursor = lyrics_collection.find(query).sort([("artist", 1), ("track", 1), ("_id", 1)]).skip(skip).limit(per_page)
    songs = list(cursor)
    
    unique_artists = [a for a in lyrics_collection.distinct("artist") if isinstance(a, str) and a]
    unique_artists.sort()

    # Calculate Chart Data: Last 7 Days Performance
    performance_labels = []
    performance_data = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        performance_labels.append(day.strftime("%a"))
        
        # Start and end of that day in Unix timestamp
        start_of_day = datetime(day.year, day.month, day.day).timestamp()
        end_of_day = start_of_day + 86400
        
        count = lyrics_collection.count_documents({
            "last_sync_attempt": {"$gte": start_of_day, "$lt": end_of_day},
            "syncedLyrics": {"$nin": [None, ""]}
        })
        performance_data.append(count)

    # Errors/Missing (Needs Attention query but simplified for count)
    twenty_four_hours_ago = time.time() - 86400
    error_count = lyrics_collection.count_documents({
        "syncedLyrics": {"$in": [None, ""]},
        "plainLyrics": {"$nin": [None, ""]},
        "$or": [
            {"last_sync_attempt": {"$exists": False}},
            {"last_sync_attempt": None},
            {"last_sync_attempt": {"$lt": twenty_four_hours_ago}}
        ]
    })

    return render_template(
        "index.html", 
        songs=songs, 
        total=total_docs,
        synced=synced_count, 
        plain=plain_count,
        pct_synced=pct_synced,
        pct_plain=pct_plain,
        unique_artists=unique_artists,
        current_page=page,
        total_pages=total_pages,
        filtered_count=filtered_count,
        search_query=search_query,
        artist_filter=artist_filter,
        needs_attention=needs_attention,
        performance_labels=performance_labels,
        performance_data=performance_data,
        error_count=error_count
    )

@app.route("/search")
def search():
    """HTMX endpoint returning only table rows."""
    search_query = request.args.get('q', '').strip()
    artist_filter = request.args.get('artist', '').strip()
    needs_attention = request.args.get('needs_attention', 'false').lower() == 'true'

    query = _build_search_query(search_query, artist_filter, needs_attention)
    cursor = lyrics_collection.find(query).sort([("artist", 1), ("track", 1), ("_id", 1)]).limit(50)
    songs = list(cursor)

    return render_template("partials/table_rows.html", songs=songs)


@app.route("/edit/<string:doc_id>")
def edit(doc_id):
    try:
        song = lyrics_collection.find_one({"_id": ObjectId(doc_id)})
        if not song:
            flash("Song not found!", "danger")
            return redirect(url_for("index"))
            
        plain_rtl = is_hebrew(song.get("plainLyrics", ""))
        synced_rtl = is_hebrew(song.get("syncedLyrics", ""))
        
        # Build Genius URL safely
        genius_query = urllib.parse.quote(f"{song.get('artist', '')} {song.get('track', '')}")
        genius_url = f"https://genius.com/search?q={genius_query}"
            
        return render_template(
            "detail.html", 
            song=song, 
            plain_rtl=plain_rtl, 
            synced_rtl=synced_rtl,
            genius_url=genius_url
        )
    except Exception as e:
        flash(f"Error loading song: {e}", "danger")
        return redirect(url_for("index"))

@app.route("/api/update/<string:doc_id>", methods=["POST"])
def update_song(doc_id):
    plain_lyrics = request.form.get("plainLyrics", "").strip()
    synced_lyrics = request.form.get("syncedLyrics", "").strip()
    
    plain_val = plain_lyrics if plain_lyrics else None
    synced_val = synced_lyrics if synced_lyrics else None
    
    try:
        lyrics_collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {
                "plainLyrics": plain_val,
                "syncedLyrics": synced_val
            }}
        )
        flash("Lyrics updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating lyrics: {e}", "danger")
        
    return redirect(url_for("edit", doc_id=doc_id))

@app.route("/api/force_sync/<string:doc_id>", methods=["POST"])
def force_sync(doc_id):
    try:
        lyrics_collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {
                "syncedLyrics": None,
                "last_sync_attempt": 0
            }}
        )
        if request.headers.get("Accept") == "application/json" or request.is_json:
            return jsonify({"success": True, "message": "Song queued for sync"})
        flash("Sync task queued! Play this song in the Word-Play app to trigger AI Alignment.", "info")
    except Exception as e:
        if request.headers.get("Accept") == "application/json" or request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Error forcing sync: {e}", "danger")
        
    return redirect(url_for("edit", doc_id=doc_id))

@app.route("/api/delete/<string:doc_id>", methods=["POST"])
def delete_song(doc_id):
    try:
        lyrics_collection.delete_one({"_id": ObjectId(doc_id)})
        if request.headers.get("Accept") == "application/json" or request.is_json:
            return jsonify({"success": True, "message": "Song deleted"})
        flash("Song deleted successfully.", "success")
    except Exception as e:
        if request.headers.get("Accept") == "application/json" or request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Error deleting song: {e}", "danger")
        
    return redirect(url_for("index"))

# --- BULK ACTIONS ---

@app.route("/api/bulk_delete", methods=["POST"])
def bulk_delete():
    data = request.get_json()
    doc_ids = data.get("ids", [])
    
    if not doc_ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
        
    try:
        object_ids = [ObjectId(i) for i in doc_ids]
        result = lyrics_collection.delete_many({"_id": {"$in": object_ids}})
        return jsonify({"success": True, "deleted_count": result.deleted_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/bulk_force_sync", methods=["POST"])
def bulk_force_sync():
    data = request.get_json()
    doc_ids = data.get("ids", [])
    
    if not doc_ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
        
    try:
        object_ids = [ObjectId(i) for i in doc_ids]
        result = lyrics_collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {
                "syncedLyrics": None,
                "last_sync_attempt": 0
            }}
        )
        return jsonify({"success": True, "modified_count": result.modified_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
