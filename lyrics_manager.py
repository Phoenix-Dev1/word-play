import requests
import re
import logging
import os
import json
import hashlib
import logging
import urllib.parse
import traceback
import threading
import time
from bs4 import BeautifulSoup
import yt_dlp
import stable_whisper
import torch
import static_ffmpeg
import pymongo
from PyQt6.QtCore import QObject, pyqtSignal, QThread

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class LyricsManager(QObject):
    # Signals for thread-safe UI updates
    lyrics_found = pyqtSignal(bool) # Success/Failure
    alignment_started = pyqtSignal()
    alignment_finished = pyqtSignal(bool, str) # Success/Failure, Song Key

    # Singleton/Persistent Whisper model
    _whisper_model = None
    _model_loading = False

    def __init__(self):
        super().__init__()
        self.api_url = "https://lrclib.net/api/get"
        self.temp_dir = "temp_audio"
        # Ensure directories exist
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # MongoDB Setup via structured db_config
        try:
            import db_config
            self.lyrics_collection = db_config.get_lyrics_collection()
        except Exception as e:
            logger.error(f"Failed to load MongoDB collection from db_config: {e}")
        
        # Ensure ffmpeg is in path
        try:
            static_ffmpeg.add_paths()
        except Exception as e:
            logger.warning(f"Failed to add static-ffmpeg paths: {e}")
        
        self.synced_lyrics = []
        self.plain_lyrics = ""
        self.album_art_url = ""
        self.is_synced = False
        self.is_aligning = False
        self.current_song_key = "" # Add tracking
        self.last_sync_time = 0
        self.sync_cooldown = 86400  # 24 hours in seconds
        self.alignment_lock = threading.Semaphore(1) # Ensure only one stable-ts runs at a time

    def fetch_lyrics(self, track_name, artist_name):
        """
        Starts a FetchWorker QThread to retrieve lyrics.
        """
        logger.info(f"Fetching lyrics for: {artist_name} - {track_name}")
        self.synced_lyrics = []
        self.plain_lyrics = ""
        self.album_art_url = ""
        self.is_synced = False
        self.is_aligning = False
        
        self.fetch_worker = FetchWorker(self, track_name, artist_name)
        self.fetch_worker.finished_signal.connect(self._on_fetch_worker_finished)
        self.fetch_worker.start()

    def _on_fetch_worker_finished(self, success, image_data=None):
        """Handles completion of fetching."""
        self.lyrics_found.emit(success)
        if hasattr(self, '_main_ui_ref'): # Callback if needed
            if image_data:
                self._main_ui_ref.pending_image_data = image_data

    def _execute_fetch_logic(self, track_name, artist_name):
        """
        INTERNAL: Synchronous fetching logic to be called by FetchWorker.
        Returns (success, image_data)
        """

        # Fetch album art independently 
        self.fetch_album_art(track_name, artist_name)

        # 1. Try to load from MongoDB
        try:
            doc = self.lyrics_collection.find_one({"artist": artist_name, "track": track_name})
            
            if doc:
                synced_raw = doc.get("syncedLyrics")
                self.plain_lyrics = doc.get("plainLyrics", "")

                if synced_raw:
                    logger.info("Found synced lyrics in MongoDB.")
                    self.parse_synced_lyrics(synced_raw)
                    self.is_synced = True
                    return True
                elif self.plain_lyrics:
                    logger.info("Found plain lyrics in MongoDB.")
                    self.is_synced = False
                    
                    # RETRY LOGIC
                    last_attempt = doc.get("last_sync_attempt")
                    if last_attempt is None:
                        last_attempt = 0

                    now = time.time()
                    if now - last_attempt > 86400:
                        logger.info(f"Retrying AI alignment. Last attempt was >24h ago.")
                        song_key = f"{artist_name} - {track_name}"
                        # Trigger locally, worker will update DB
                        self.trigger_ai_alignment(track_name, artist_name, song_key)
                    else:
                        hours_left = round((86400 - (now - last_attempt))/3600, 1)
                        logger.info(f"AI alignment cooldown active. Try again in {hours_left} hours.")
                        
                    return True
                else:
                    logger.info("Found 'Missing' record in MongoDB. Stop trying.")
                    return False
        except Exception as e:
            logger.error(f"MongoDB read error: {e}")

        # Clean the title of junk like "(Cover)", "[Remastered]", etc.
        clean_track_name = self._clean_title(track_name)
        clean_track_name = self.clean_hebrew_metadata(clean_track_name)
        
        # 2. Cache miss or corrupt, hit the LRCLIB network API
        try:
            params = {
                "track_name": clean_track_name,
                "artist_name": artist_name
            }
            # Provide a proper User-Agent as requested by LRCLIB API docs
            headers = {"User-Agent": "WordPlay/0.2 (https://github.com/yourusername/word-play)"}

            response = requests.get(self.api_url, params=params, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                synced_raw = data.get("syncedLyrics")
                plain_raw = data.get("plainLyrics", "")
                
                # Strip structural tags from plain lyrics to save vertical density
                if plain_raw:
                    plain_raw = self.clean_plain_lyrics(plain_raw)
                    
                self.plain_lyrics = plain_raw

                if synced_raw or plain_raw:
                    if synced_raw:
                        self.parse_synced_lyrics(synced_raw)
                        self.is_synced = True
                    else:
                        self.is_synced = False
                        logger.info("Song found, but only plain text lyrics available.")
                    
                    # Successfully parsed from network, save to MongoDB
                    try:
                        self.save_to_db({
                            "track": track_name,
                            "artist": artist_name,
                            "plainLyrics": plain_raw,
                            "syncedLyrics": synced_raw,
                            **data  # Merge whatever else LRCLIB sent
                        })
                        logger.info(f"Saved lyrics to MongoDB: {artist_name} - {track_name}")
                    except Exception as e:
                        logger.error(f"Failed to write lyrics to MongoDB: {e}")
                        
                    # Trigger local AI alignment if only plain lyrics found
                    if self.plain_lyrics and not self.is_synced:
                        song_key = f"{artist_name} - {track_name}"
                        # Trigger locally, worker will update DB
                        self.trigger_ai_alignment(track_name, artist_name, song_key)

                    return True
                else:
                    logger.info("Song found, but no lyrics available. Trying fallback pipeline...")
            else:
                logger.warning(f"LRCLIB exact match failed (Status: {response.status_code}). Trying fallback pipeline...")
                
            # --- TIER 1 FALLBACK: Fuzzy Search on the mildly cleaned title ---
            if self._fallback_fuzzy_search(clean_track_name, artist_name):
                return True
                
            # --- TIER 2 FALLBACK: Nuclear Option. Split at first ( or [ or - or | and take just the root word ---
            # E.g. "תהום (Prod. by Guy Dan)" -> "תהום"
            # E.g. "תהום - Tehom" -> "תהום "
            super_clean_title = re.split(r'[\(\[\-\|]', track_name)[0].strip()
            if super_clean_title and super_clean_title != clean_track_name:
                logger.info(f"Tier 1 fuzzy failed. Executing Tier 2 nuclear split root search: '{super_clean_title}'")
                if self._fallback_fuzzy_search(super_clean_title, artist_name):
                    return True
                    
            # --- TIER 3 FALLBACK: Transliteration Extraction. If it's a mixed language title, try the English part alone ---
            # E.g. "תהום Tehom" -> Extract "Tehom"
            english_parts = re.findall(r'[a-zA-Z]+', track_name)
            if english_parts:
                english_title = " ".join(english_parts).strip()
                if english_title and english_title != super_clean_title and english_title.lower() not in ['prod', 'by', 'remix', 'cover', 'live']:
                    logger.info(f"Tier 2 nuclear failed. Executing Tier 3 transliteration search: '{english_title}'")
                    if self._fallback_fuzzy_search(english_title, artist_name):
                        return True
            
            # --- TIER 4 FALLBACK: Genius AJAX/BS4 Scraper for Hebrew Tracks ---
            if self.is_hebrew(track_name) or self.is_hebrew(artist_name):
                logger.info(f"Tier 3 transliteration failed for Hebrew track. Executing Tier 4 Genius Scraper...")
                if self._fallback_genius_scrape(clean_track_name, artist_name):
                    # Trigger local AI alignment if only plain lyrics found
                    if self.plain_lyrics and not self.is_synced:
                        song_key = f"{artist_name} - {track_name}"
                        # DB save handled inside scrape, trigger updates last_attempt
                        self.trigger_ai_alignment(track_name, artist_name, song_key)
                    
                    self.lyrics_found.emit(True)
                    return True

            # All fallbacks exhausted
            logger.warning("All LRCLIB exact and fallback search tiers exhausted. No lyrics found.")
            
            # Save a 'Missing' record to track this failure in the dashboard
            try:
                self.save_to_db({
                    "track": track_name,
                    "artist": artist_name,
                    "plainLyrics": None,
                    "syncedLyrics": None,
                    "status": "Missing",
                    "last_attempt": time.time()
                })
                logger.info(f"Saved 'Missing' record to MongoDB: {artist_name} - {track_name}")
            except Exception as e:
                logger.error(f"Failed to write Missing record to MongoDB: {e}")
                
            self.lyrics_found.emit(False)
            return False
            
        except Exception as e:
            logger.error(f"Error fetching lyrics: {e}")
            return False

    def _clean_title(self, title):
        """Strips out common suffixes that break exact API matches."""
        # Remove (Official Video), [Remastered], - Radio Edit, (feat. X) etc.
        cleaned = re.sub(r'(?i)(\(|\[).*?(official|video|remastered|remix|cover|feat\.?|ft\.?|קאבר|לייב).*?(\)|\])', '', title)
        cleaned = re.sub(r'(?i)-\s*(radio edit|remaster|remix|stereo version).*$', '', cleaned)
        return cleaned.strip()

    def clean_hebrew_metadata(self, title):
        """Aggressively strips structural production credits and labels specific to Israeli music."""
        # Remove (Prod. by...) or [Prod...]
        cleaned = re.sub(r'(?i)(\(|\[)\s*prod\..*?(\)|\])', '', title)
        # Remove anything after a pipe that looks like a label e.g., | מנורה 2024
        cleaned = re.sub(r'\|.*$', '', cleaned)
        return cleaned.strip()

    def clean_plain_lyrics(self, text):
        """Robustly cleans plaintext lyrics from headers, bracketed tags, and excessive spacing."""
        if not text:
            return ""
            
        # Step 1: Strip Genius-style "Contributors... Lyrics" header (handles multiline)
        text = re.sub(r'(?i)^.*?Lyrics\s*', '', text, flags=re.DOTALL)
        
        # Step 2: Strip bracketed tags [Chorus], [Verse], etc.
        text = re.sub(r'\[.*?\]', '', text)
        
        # Step 3: Normalize spacing - collapse 3+ newlines into 2
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Step 4: Final trim
        return text.strip()

    def is_hebrew(self, text):
        """Returns True if the text contains any Hebrew characters."""
        if not text:
            return False
        return bool(re.search(r'[\u0590-\u05FF]', text))

    def _fallback_fuzzy_search(self, track_name, artist_name):
        """Performs a broader search if the exact match fails."""
        try:
            search_url = "https://lrclib.net/api/search"
            # Provide a proper User-Agent as requested by LRCLIB API docs
            headers = {"User-Agent": "WordPlay/0.2 (https://github.com/yourusername/word-play)"}
            
            # Use both artist and track for a robust query
            query = f"{artist_name} {track_name}"
            params = {"q": query}
            
            logger.info(f"Performing fallback fuzzy search for: '{query}'")
            response = requests.get(search_url, params=params, headers=headers, timeout=5)
            
            if response.status_code == 200:
                results = response.json()
                if not results:
                    logger.info("Fallback search yielded no results.")
                    return False
                    
                # Find the best match that has synced lyrics or plain lyrics
                best_match = None
                for res in results:
                    if res.get("syncedLyrics") or res.get("plainLyrics"):
                        # Basic fuzzy check: does the result title contain our clean title?
                        res_title = res.get("trackName", "").lower()
                        if track_name.lower() in res_title or res_title in track_name.lower():
                            best_match = res
                            break
                            
                # If no perfect fuzzy match, just take the first one with lyrics
                if not best_match:
                    for res in results:
                        if res.get("syncedLyrics") or res.get("plainLyrics"):
                            best_match = res
                            break
                            
                if best_match:
                    logger.info(f"Fallback search found a match: {best_match.get('artistName')} - {best_match.get('trackName')}")
                    synced_raw = best_match.get("syncedLyrics")
                    plain_raw = best_match.get("plainLyrics", "")
                    if plain_raw:
                        plain_raw = self.clean_plain_lyrics(plain_raw)
                        best_match["plainLyrics"] = plain_raw

                    self.plain_lyrics = plain_raw
                    
                    if synced_raw:
                        self.parse_synced_lyrics(synced_raw)
                        self.is_synced = True
                    else:
                        self.is_synced = False
                    
                    # Save the dictionary as if it were an exact match
                    try:
                        self.save_to_db({
                            "track": track_name,
                            "artist": artist_name,
                            "plainLyrics": plain_raw,
                            "syncedLyrics": synced_raw,
                            **best_match
                        })
                        logger.info(f"Saved fallback lyrics to MongoDB: {artist_name} - {track_name}")
                    except Exception as e:
                        logger.error(f"Failed to write lyrics to MongoDB: {e}")
                    
                    # Trigger local AI alignment if only plain lyrics found
                    if self.plain_lyrics and not self.is_synced:
                        song_key = f"{artist_name} - {track_name}"
                        # Trigger locally, worker will update DB
                        self.trigger_ai_alignment(track_name, artist_name, song_key)

                    return True
                else:
                    logger.info("Fallback search found results, but none possessed lyrics.")
                    return False
            else:
                logger.warning(f"Fallback search failed. Status: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error during fallback search: {e}")
            return False

    def _fallback_genius_scrape(self, track_name, artist_name):
        """Scrapes plain text lyrics via Genius public AJAX search to bypass bot blockers."""
        try:
            query = f"{artist_name} {track_name}"
            # Genius public AJAX search endpoint
            url = f"https://genius.com/api/search/multi?per_page=5&q={urllib.parse.quote(query)}"
            
            # Browser-like headers to evade detection
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://genius.com/"
            }
            
            response = requests.get(url, headers={"User-Agent": headers["User-Agent"], "Accept": "application/json"}, timeout=5)
            if response.status_code != 200:
                logger.warning(f"Genius search failed: {response.status_code}")
                return False
                
            data = response.json()
            song_url = None
            
            try:
                sections = data.get("response", {}).get("sections", [])
                for section in sections:
                    # Look for hits in any section, especially 'top_hit' and 'song'
                    hits = section.get("hits", [])
                    for hit in hits:
                        # Extract the result and check if it's actually a song
                        result = hit.get("result", {})
                        # Genius API uses hit['type'] and result['_type'] to identify songs
                        if hit.get("type") == "song" or result.get("_type") == "song":
                            logger.info(f"Genius match found in section '{section.get('type')}': {result.get('full_title')}")
                            # Extract the native URL or path from the API response
                            song_url = result.get("url")
                            if not song_url and result.get("path"):
                                song_url = f"https://genius.com{result.get('path')}"
                            break
                    if song_url:
                        break
            except Exception as e:
                logger.error(f"Error parsing Genius search JSON: {e}")

            if not song_url:
                # Debug dump for manual inspection
                try:
                    with open("genius_debug_payload.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                    logger.error("Genius URL extraction failed. Raw JSON payload dumped to genius_debug_payload.json for inspection.")
                except Exception as dump_err:
                    logger.error(f"Failed to dump Genius debug payload: {dump_err}")
                return False
                
            # Fetch the actual Genius song page with spoofed browser headers
            song_response = requests.get(song_url, headers=headers, timeout=5)
            if song_response.status_code != 200:
                logger.warning(f"Failed to load Genius page: {song_response.status_code} at {song_url}")
                return False
                
            song_soup = BeautifulSoup(song_response.text, 'html.parser')
            # Target the specific React container data attribute
            lyrics_containers = song_soup.find_all("div", attrs={"data-lyrics-container": "true"})
            
            if lyrics_containers:
                lyrics_fragments = []
                for container in lyrics_containers:
                    # Genius sometimes includes track info/bios within lyrics containers.
                    # We extract the HTML robustly, stripping script and style tags.
                    for elem in container(["script", "style"]):
                        elem.decompose()
                        
                    # Use natural newline separator for the React DOM structure
                    text = container.get_text(separator="\n")
                    
                    # Heuristic 1: If it contains exactly "Read More" or starts with "השיר החמישי" 
                    # and has no line breaks, it's a bio paragraph.
                    if "Read More" in text:
                        # Split by "Read More" and only take what comes after (or heavily filter)
                        # Often the bio is BEFORE "Read More", but sometimes the lyrics start right after.
                        parts = text.split("Read More")
                        if len(parts) > 1:
                            # Usually the actual lyrics are in a completely different container, 
                            # but if they are stitched, take the second half and strip.
                            text = parts[-1].strip()
                        else:
                            text = ""

                    # Heuristic 2: Strip heavy biographical paragraphs (long unbroken strings of text)
                    lines = text.split('\n')
                    clean_lines = []
                    for line in lines:
                        clean_line = line.strip()
                        # Allow lines with timecodes or section headers [] 
                        # But drop lines that are purely massive blocks of text without typical lyric punctuation
                        if len(clean_line) > 150 and "[" not in clean_line and "]" not in clean_line:
                            if not re.search(r'\d{2}:\d{2}', clean_line):
                                logger.info(f"Stripped likely bio paragraph: {clean_line[:30]}...")
                                continue
                        
                        # Also drop lines that look exactly like the "Read More" bio chunk from Muki
                        if "השיר החמישי מתוך אלבום הסולו" in clean_line or "התנהגות שלה כלפיו מותנית במצב הרוח" in clean_line:
                            continue
                            
                        clean_lines.append(line)
                        
                    filtered_text = "\n".join(clean_lines).strip()
                    
                    if filtered_text:
                        lyrics_fragments.append(filtered_text)
                
                # Join with newline to stitch fragments together
                raw_lyrics = "\n".join(lyrics_fragments).strip()
                
                # Final pass: Remove trailing 'Read More' artifacts and fix spacing
                raw_lyrics = re.sub(r'(?i)read\s+more', '', raw_lyrics)
                
                if not raw_lyrics:
                    logger.warning("Genius scrape extracted text, but it was empty after filtering.")
                    return False
                
                # Apply robust header cleaning
                clean_text = self.clean_plain_lyrics(raw_lyrics)
                
                # Assign explicitly to the Lyric manager state variables
                self.plain_lyrics = clean_text
                self.is_synced = False
                self.synced_lyrics = []
                
                logger.info(f"Successfully scraped lyrics from Genius: {song_url}")
                
                # Cache the scraped result as a mock LRCLIB JSON payload
                mock_payload = {
                    "track": track_name,
                    "artist": artist_name,
                    "plainLyrics": clean_text,
                    "syncedLyrics": None
                }
                
                try:
                    self.save_to_db(mock_payload)
                except Exception as e:
                    logger.error(f"Failed to write Genius scrape to MongoDB: {e}")
                    
                return True
            else:
                logger.warning(f"Failed to extract lyrics containers from Genius DOM: {song_url}")
                return False
                
        except Exception as e:
            logger.error(f"Error during Genius scrape: {e}")
            
        return False

    def save_to_db(self, data_dict):
        """Helper to upsert a dictionary into MongoDB based on artist and track."""
        try:
            # Ensure artist and track are standardized keys
            artist = data_dict.get("artistName") or data_dict.get("artist")
            track = data_dict.get("trackName") or data_dict.get("track")
            
            if not artist or not track:
                logger.error("Cannot save to DB: missing artist or track")
                return

            # Skip write if it's completely empty AND not flagged as Missing
            if not data_dict.get("plainLyrics") and not data_dict.get("syncedLyrics") and data_dict.get("status") != "Missing":
                logger.warning("No lyrics to save and not flagged as Missing. Skipping DB write.")
                return

            # Clear out the "_id" key if it somehow got carried over to avoid ImmutableField errors
            if "_id" in data_dict:
                del data_dict["_id"]

            self.lyrics_collection.update_one(
                {"artist": artist, "track": track},
                {"$set": data_dict},
                upsert=True
            )
        except Exception as e:
            logger.error(f"MongoDB save_to_db error: {e}")

    def parse_synced_lyrics(self, lrc_text):
        """
        Parses the raw .lrc format text into a list of dictionaries.
        """
        # Example LRC line: [00:15.22] Hello world
        # Some lines might have multiple timestamps, but we'll assume the simple case for now
        pattern = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)")
        
        parsed = []
        for line in lrc_text.splitlines():
            match = pattern.search(line)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                milliseconds = int(match.group(3))
                # Normalize milliseconds (could be 2 or 3 digits)
                if len(match.group(3)) == 2:
                    milliseconds *= 10
                    
                total_seconds = (minutes * 60) + seconds + (milliseconds / 1000.0)
                text = match.group(4).strip()
                
                parsed.append({"time": total_seconds, "text": text})

        # Ensure lyrics are sorted by time
        self.synced_lyrics = sorted(parsed, key=lambda x: x["time"])
        logger.info(f"Parsed {len(self.synced_lyrics)} synced lyric lines.")

    def get_current_line(self, current_position_sec):
        """
        Given the current playback position in seconds, returns the active lyric line.
        """
        if not self.synced_lyrics:
            return ""

        # Find the last line whose timestamp is less than or equal to current_position_sec
        active_line = ""
        for line in self.synced_lyrics:
            if current_position_sec >= line["time"]:
                active_line = line["text"]
            else:
                break
                
        return active_line

    def get_lyrics_context(self, current_position_sec, past_lines_count=2, future_lines_count=2):
        """
        Returns a tuple: (past_lines list, current_line string, future_lines list, is_rtl boolean)
        """
        if not self.synced_lyrics:
            return ([], "", [], False)

        active_idx = -1
        # Find the index of the active line
        for i, line in enumerate(self.synced_lyrics):
            if current_position_sec >= line["time"]:
                active_idx = i
            else:
                break

        if active_idx == -1:
            # We are before the first lyric line
            future = [l["text"] for l in self.synced_lyrics[:future_lines_count]]
            # If future lines are hebrew, text will be RTL even before the first line
            is_rtl = self.is_hebrew(" ".join(future))
            return ([], "", future, is_rtl)

        current_line = self.synced_lyrics[active_idx]["text"]
        
        start_past = max(0, active_idx - past_lines_count)
        past_lines = [l["text"] for l in self.synced_lyrics[start_past:active_idx]]
        
        start_future = active_idx + 1
        future_lines = [l["text"] for l in self.synced_lyrics[start_future:start_future + future_lines_count]]

        is_rtl = self.is_hebrew(current_line)

        return (past_lines, current_line, future_lines, is_rtl)

    def trigger_ai_alignment(self, track_name, artist_name, song_key):
        """Starts the AI alignment process in a background QThread."""
        logger.info(f"Triggering Local AI Forced Alignment for: {artist_name} - {track_name}")
        
        self.is_aligning = True
        
        # Update last_sync_attempt to prevent spamming
        try:
            self.lyrics_collection.update_one(
                {"artist": artist_name, "track": track_name},
                {"$set": {"last_sync_attempt": time.time()}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to update last_sync_attempt: {e}")

        self.alignment_started.emit()
        self.alignment_worker = AlignmentWorker(self, track_name, artist_name, song_key)
        self.alignment_worker.finished_signal.connect(self._on_alignment_worker_finished)
        self.alignment_worker.start()

    def _on_alignment_worker_finished(self, success, lrc_content, song_key):
        """Handles completion of alignment worker."""
        self.is_aligning = False
        
        if success and lrc_content:
            logger.info("AI Alignment successful. Updating local manager state.")
            self.parse_synced_lyrics(lrc_content)
            self.is_synced = True
            self.alignment_finished.emit(True, song_key)
        else:
            self.alignment_finished.emit(False, song_key)

    def _download_temp_audio(self, track_name, artist_name):
        """Fetches lowest quality audio stream from YouTube via yt-dlp (Quiet Mode)."""
        query = f"ytsearch1:{artist_name} {track_name} audio"
        output_tmpl = os.path.join(self.temp_dir, "%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=opus]/bestaudio',
            'outtmpl': output_tmpl,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'extract_audio': True,
            'max_filesize': 5 * 1024 * 1024, # 5MB limit
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=True)
                if 'entries' in info and info['entries']:
                    filename = ydl.prepare_filename(info['entries'][0])
                    # Ensure path uses forward slashes to prevent \n escape sequences breaking FFmpeg
                    filename = os.path.abspath(filename).replace("\\", "/")
                    logger.info(f"Downloaded temp audio: {filename}")
                    return filename
        except Exception as e:
            logger.error(f"yt-dlp download failed: {e}")
        return None

    def _align_lyrics_to_audio(self, audio_path, plain_text):
        """Performs forced alignment using stable-ts (Whisper) with Singleton loading."""
        if not plain_text:
            return None

        # Singleton/Persistent Model Loading
        if LyricsManager._whisper_model is None:
            if LyricsManager._model_loading: 
                logger.warning("Whisper model is currently loading in another request. Skipping.")
                return None
            
            LyricsManager._model_loading = True
            try:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"Initializing Persistent Whisper 'base' model on {device}...")
                LyricsManager._whisper_model = stable_whisper.load_model('base', device=device)
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                return None
            finally:
                LyricsManager._model_loading = False

        try:
            logger.info("Starting Whisper forced alignment...")
            result = LyricsManager._whisper_model.align(audio_path, plain_text, language='he')
            
            # Extract all words with their timestamps into a flat list
            all_words = []
            for segment in result.segments:
                for word in segment.words:
                    word_text = word.word.strip()
                    if word_text:
                        all_words.append({
                            "text": word_text,
                            "start": word.start
                        })
            
            # Split original plain text into lines
            original_lines = [line.strip() for line in plain_text.split('\n')]
            
            lrc_lines = []
            word_idx = 0
            total_words = len(all_words)
            
            for line in original_lines:
                if not line:
                    continue
                    
                # We need to find the start time of the first word in this line.
                # Since stable-ts might split words differently (punctuation, etc),
                # we do a loose comparison by consuming words until we've matched 
                # the approximate length of the original line.
                
                if word_idx >= total_words:
                    logger.warning("Ran out of timestamped words before finishing original lines.")
                    break
                    
                # The start time of this line is the start time of our current word pointer
                line_start_time = all_words[word_idx]["start"]
                
                minutes = int(line_start_time // 60)
                seconds = int(line_start_time % 60)
                hundredths = int((line_start_time % 1) * 100)
                lrc_time = f"[{minutes:02d}:{seconds:02d}.{hundredths:02d}]"
                
                # Reconstruct the line EXACTLY as it appeared in the plain text
                lrc_lines.append(f"{lrc_time}{line}")
                
                # Consume words until we roughly match the character length of the original line.
                # We remove spaces and punctuation for a robust length comparison.
                clean_orig_line = re.sub(r'[^\w\s]', '', line).replace(" ", "")
                char_count = 0
                target_len = len(clean_orig_line)
                
                while word_idx < total_words and char_count < target_len:
                    clean_word = re.sub(r'[^\w\s]', '', all_words[word_idx]["text"])
                    char_count += len(clean_word)
                    word_idx += 1
            
            return "\n".join(lrc_lines)
            
        except Exception as e:
            logger.error(f"Stable-ts alignment error: {e}")
            logger.error(traceback.format_exc())
            return None

    def fetch_album_art(self, track_name, artist_name):
        """
        Fetches album art URL via the iTunes Search API.
        """
        try:
            itunes_url = "https://itunes.apple.com/search"
            params = {
                "term": f"{artist_name} {track_name}",
                "entity": "song",
                "limit": 1
            }
            response = requests.get(itunes_url, params=params, timeout=3)
            if response.status_code == 200:
                results = response.json().get("results", [])
                if results and len(results) > 0:
                    # Get 100x100 or higher resolution image
                    art_url = results[0].get("artworkUrl100", "")
                    if art_url:
                        # Request a higher resolution image by replacing 100x100 with 600x600
                        self.album_art_url = art_url.replace("100x100bb", "600x600bb")
                        logger.info(f"Found album art: {self.album_art_url}")
                        return
            logger.info("No album art found on iTunes.")
        except Exception as e:
            logger.error(f"Error fetching album art: {e}")

class FetchWorker(QThread):
    finished_signal = pyqtSignal(bool, bytes) # success, image_data

    def __init__(self, manager, track_name, artist_name):
        super().__init__()
        self.manager = manager
        self.track_name = track_name
        self.artist_name = artist_name

    def run(self):
        try:
            success = self.manager._execute_fetch_logic(self.track_name, self.artist_name)
            image_data = None
            if success and self.manager.album_art_url:
                try:
                    image_data = requests.get(self.manager.album_art_url, timeout=3).content
                except: pass
            self.finished_signal.emit(success, image_data if image_data else b"")
        except Exception as e:
            logger.error(f"FetchWorker error: {e}")
            self.finished_signal.emit(False, b"")


class AlignmentWorker(QThread):
    finished_signal = pyqtSignal(bool, str, str) # success, lrc_content, song_key

    def __init__(self, manager, track_name, artist_name, song_key):
        super().__init__()
        self.manager = manager
        self.track_name = track_name
        self.artist_name = artist_name
        self.song_key = song_key
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True
        logger.info(f"AlignmentWorker for {self.song_key} received cancellation signal.")

    def run(self):
        audio_path = None
        acquired = False
        try:
            # Quick check before doing anything
            if self.is_cancelled or self.song_key != self.manager.current_song_key:
                logger.info(f"AI Alignment aborted early: {self.song_key} is no longer active.")
                self.finished_signal.emit(False, "", self.song_key)
                return

            # Wait for GPU resources
            logger.debug(f"AI Alignment waiting for semaphore: {self.song_key}")
            self.manager.alignment_lock.acquire()
            acquired = True
            
            # Check after acquiring lock - someone else might have played next
            if self.is_cancelled or self.song_key != self.manager.current_song_key:
                logger.info(f"AI Alignment aborted after lock: {self.song_key} is no longer active.")
                self.finished_signal.emit(False, "", self.song_key)
                return

            # 1. Download
            audio_path = self.manager._download_temp_audio(self.track_name, self.artist_name)
            if not audio_path:
                self.finished_signal.emit(False, "", self.song_key)
                return
                
            # Check again before massive inference
            if self.is_cancelled or self.song_key != self.manager.current_song_key:
                logger.info(f"AI Alignment aborted before inference: {self.song_key} is no longer active.")
                self.finished_signal.emit(False, "", self.song_key)
                return

            # 2. Align
            lrc_content = self.manager._align_lyrics_to_audio(audio_path, self.manager.plain_lyrics)
            if not lrc_content:
                self.finished_signal.emit(False, "", self.song_key)
                return

            # 3. Update Cache (Sync check before parsing in main thread)
            try:
                self.manager.lyrics_collection.update_one(
                    {"artist": self.artist_name, "track": self.track_name},
                    {"$set": {
                        "syncedLyrics": lrc_content,
                        "last_sync_attempt": time.time()
                    }},
                    upsert=True
                )
                logger.debug(f"AI sync cached successfully to MongoDB")
            except Exception as cache_err:
                logger.warning(f"Failed to update MongoDB with AI alignment: {cache_err}")

            self.finished_signal.emit(True, lrc_content, self.song_key)

        except Exception as e:
            logger.error(f"AlignmentWorker error: {e}")
            self.finished_signal.emit(False, "", self.song_key)
        finally:
            if acquired:
                self.manager.alignment_lock.release()
                
            # 4. Cleanup
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    logger.debug(f"Cleaned up temp audio: {audio_path}")
                except: pass

# Basic manual test
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    lm = LyricsManager()
    found = lm.fetch_lyrics("Shape of You", "Ed Sheeran") 
    # This won't run properly because of QThread loop, but enough for basic check
    print("Fetch triggered...")

