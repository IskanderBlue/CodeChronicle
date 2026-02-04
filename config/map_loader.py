"""
Singleton service for loading and caching building code maps from S3.
"""
import json
import os
import boto3
from django.conf import settings
from typing import Dict, Any, Optional


class MapCache:
    """
    Singleton that loads maps from S3/Local on demand and caches them in memory.
    """
    _instance = None
    _maps: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_map(self, code_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a map by its code name (e.g., 'OBC_2024').
        Loads from cache if available, otherwise fetches from S3 or local.
        """
        if code_name not in self._maps:
            map_data = self._load_map(code_name)
            if map_data:
                self._maps[code_name] = map_data
            else:
                return None
        return self._maps[code_name]
    
    def _load_map(self, code_name: str) -> Optional[Dict[str, Any]]:
        """
        Load map data from S3 or local file system for development.
        """
        # In development, try to load from a local directory first if specified
        local_maps_dir = os.environ.get('LOCAL_MAPS_DIR')
        if local_maps_dir:
            file_path = os.path.join(local_maps_dir, f"{code_name}.json")
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    print(f"Error loading local map {code_name}: {e}")
        
        # fallback to S3
        if not settings.AWS_ACCESS_KEY_ID:
            print("AWS credentials not configured, skipping S3 load.")
            return None
            
        try:
            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            response = s3.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=f"{code_name}.json"
            )
            return json.loads(response['Body'].read().decode('utf-8'))
        except Exception as e:
            print(f"Error loading map {code_name} from S3: {e}")
            return None

    def clear_cache(self):
        """Clear the in-memory map cache."""
        self._maps = {}


# Global instance
map_cache = MapCache()
