import os
import logging
import pymongo
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env if present

logger = logging.getLogger(__name__)

# Cache the client at the module level so it's not recreated constantly
_mongo_client = None

def get_lyrics_collection():
    """
    Initializes and returns the MongoDB 'lyrics' collection.
    Reuses the client connection if it already exists.
    """
    global _mongo_client
    
    if _mongo_client is None:
        mongo_uri = os.environ.get("WORDPLAY_MONGO_URI")
        if not mongo_uri:
            raise ValueError("CRITICAL: WORDPLAY_MONGO_URI environment variable is not set. Please check your .env file.")
            
        try:
            _mongo_client = pymongo.MongoClient(mongo_uri)
            logger.info("MongoDB connected successfully via db_config.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB in db_config: {e}")
            raise

    db = _mongo_client["word_play"]
    lyrics_collection = db["lyrics"]
    
    # Ensure index exists on lookup fields
    try:
        lyrics_collection.create_index(
            [("artist", pymongo.ASCENDING), ("track", pymongo.ASCENDING)], 
            unique=True
        )
    except Exception as e:
        logger.warning(f"Could not ensure MongoDB index: {e}")
        
    return lyrics_collection
