import asyncio
import logging
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MediaListener:
    def __init__(self):
        self.current_title = ""
        self.current_artist = ""
        self.base_position = 0.0 # in seconds
        self.last_updated_time = None
        self.is_playing = False
        self.source_app_id = ""
        self.duration = 0.0 # total track duration in seconds
        
    @property
    def current_position(self):
        import datetime
        if self.is_playing and self.last_updated_time:
            # winrt datetimes come back as timezone-aware UTC objects.
            now = datetime.datetime.now(datetime.timezone.utc)
            
            try:
                # Calculate precise sub-second delta
                elapsed = max(0.0, (now - self.last_updated_time).total_seconds())
                return self.base_position + elapsed
            except Exception:
                pass
                
        return self.base_position

    async def get_current_media_session(self):
        sessions = await MediaManager.request_async()
        current_session = sessions.get_current_session()
        return current_session

    async def update_media_info(self):
        try:
            session = await self.get_current_media_session()
            if not session:
                logger.debug("No active media session found.")
                self.is_playing = False
                return

            info = await session.try_get_media_properties_async()
            timeline = session.get_timeline_properties()
            playback = session.get_playback_info()

            if info:
                self.current_title = info.title
                self.current_artist = info.artist
            
            if timeline:
                self.base_position = timeline.position.total_seconds()
                self.last_updated_time = timeline.last_updated_time
                self.duration = timeline.end_time.total_seconds()

            self.source_app_id = session.source_app_user_model_id

            if playback:
                # 4 corresponds to Playing in GlobalSystemMediaTransportControlsSessionPlaybackStatus
                self.is_playing = (playback.playback_status == 4) 

            logger.info(f"Updated Media: {self.current_artist} - {self.current_title} | "
                        f"Pos: {self.current_position:.2f}s | Playing: {self.is_playing}")
            return True
        except Exception as e:
            logger.error(f"Error fetching media info: {e}")
            return False

    def start_listening_in_background(self):
        """Starts a background daemon thread that continuously updates media info."""
        import threading
        
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def loop_task():
                while True:
                    await self.update_media_info()
                    await asyncio.sleep(0.5)
            
            loop.run_until_complete(loop_task())

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()

async def main():
    listener = MediaListener()
    while True:
        await listener.update_media_info()
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Listener stopped.")
