import os
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import pickle

class YouTubeUploader:
    def __init__(self):
        self.youtube = self._authenticate()
        self.playlist_cache = {}  # Cache for playlist lookups
        self.video_cache = {}     # Cache for video checks
    
    def _authenticate(self):
        creds = None
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES,
                    redirect_uri='http://localhost:53477'
                )
                creds = flow.run_local_server(
                    port=53477,
                    authorization_prompt_message='Please visit this URL: {url}',
                    success_message='The auth flow is complete; you may close this window.',
                    open_browser=True
                )
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        return build("youtube", "v3", credentials=creds)

    def _find_existing_playlist(self, playlist_name):
        """Search for existing playlist by name"""
        if playlist_name in self.playlist_cache:
            return self.playlist_cache[playlist_name]
        
        try:
            request = self.youtube.playlists().list(
                part="snippet",
                mine=True,
                maxResults=50
            )
            response = request.execute()
            
            for item in response.get('items', []):
                if item['snippet']['title'].lower() == playlist_name.lower():
                    self.playlist_cache[playlist_name] = item['id']
                    return item['id']
        except HttpError as e:
            print(f"Error searching for playlists: {e}")
        return None

    def _create_or_get_playlist(self, playlist_name):
        """Get existing playlist or create new one"""
        playlist_id = self._find_existing_playlist(playlist_name)
        if playlist_id:
            print(f"Using existing playlist: {playlist_name}")
            return playlist_id
        
        try:
            request = self.youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": playlist_name,
                        "description": f"Automated playlist: {playlist_name}",
                    },
                    "status": {
                        "privacyStatus": "private"
                    }
                }
            )
            response = request.execute()
            print(f"Created new playlist: {playlist_name}")
            self.playlist_cache[playlist_name] = response['id']
            return response['id']
        except HttpError as e:
            print(f"Failed to create playlist: {e}")
            return None

    def _is_video_in_playlist(self, video_title, playlist_id):
        """Check if video already exists in playlist"""
        cache_key = f"{playlist_id}_{video_title}"
        if cache_key in self.video_cache:
            return self.video_cache[cache_key]
        
        try:
            request = self.youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50
            )
            response = request.execute()
            
            for item in response.get('items', []):
                if item['snippet']['title'].lower() == video_title.lower():
                    self.video_cache[cache_key] = True
                    return True
        except HttpError as e:
            print(f"Error checking playlist items: {e}")
        
        self.video_cache[cache_key] = False
        return False

    def _upload_video_with_retry(self, video_path, playlist_id, srt_path=None, max_retries=3):
        """Enhanced upload with retry logic and duplicate checking"""
        video_title = os.path.splitext(os.path.basename(video_path))[0]
        
        # First check if video already exists in playlist
        if self._is_video_in_playlist(video_title, playlist_id):
            print(f"Skipping already uploaded video: {video_title}")
            return True
        
        for attempt in range(max_retries):
            try:
                # Upload video
                request = self.youtube.videos().insert(
                    part="snippet,status",
                    body={
                        "snippet": {
                            "title": video_title,
                            "description": f"Automated upload from {os.path.basename(video_path)}",
                            "categoryId": "22"
                        },
                        "status": {
                            "privacyStatus": "private"
                        }
                    },
                    media_body=MediaFileUpload(video_path)
                )
                response = request.execute()
                video_id = response['id']
                
                # Add to playlist
                self.youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id
                            }
                        }
                    }
                ).execute()
                
                # Upload subtitles if available
                if srt_path:
                    try:
                        self.youtube.captions().insert(
                            part="snippet",
                            body={
                                "snippet": {
                                    "videoId": video_id,
                                    "language": "en",
                                    "name": "English"
                                }
                            },
                            media_body=MediaFileUpload(srt_path)
                        ).execute()
                    except HttpError as e:
                        print(f"Subtitle upload failed: {e}")
                
                print(f"Successfully uploaded: {video_title}")
                return True
                
            except HttpError as e:
                if 'uploadLimitExceeded' in str(e):
                    print("Daily upload limit reached. Please try again tomorrow.")
                    return False
                elif 'quotaExceeded' in str(e):
                    print("API quota exceeded. Please try again later.")
                    return False
                else:
                    wait_time = (attempt + 1) * 30  # Exponential backoff
                    print(f"Attempt {attempt + 1} failed. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
        
        print(f"Failed to upload after {max_retries} attempts: {video_title}")
        return False

    def process_folder(self, folder_path):
        """Process a folder of videos"""
        playlist_name = os.path.basename(folder_path)
        playlist_id = self._create_or_get_playlist(playlist_name)
        if not playlist_id:
            print(f"Failed to get/create playlist for {playlist_name}")
            return False
        
        videos = [f for f in os.listdir(folder_path) if f.lower().endswith('.mp4')]
        if not videos:
            print(f"No videos found in {folder_path}")
            return True
        
        print(f"Found {len(videos)} videos in {playlist_name}")
        
        for video_file in videos:
            video_path = os.path.join(folder_path, video_file)
            srt_path = self._find_matching_srt(video_path)
            
            if not self._upload_video_with_retry(video_path, playlist_id, srt_path):
                return False  # Stop if we hit limits
        
        return True

    def _find_matching_srt(self, video_file):
        """Find matching subtitle file"""
        base_name = os.path.splitext(video_file)[0]
        directory = os.path.dirname(video_file)
        
        # Check for exact match first
        exact_match = os.path.join(directory, f"{base_name}.srt")
        if os.path.exists(exact_match):
            return exact_match
        
        # Check for variations (e.g., with language codes)
        for file in os.listdir(directory):
            if file.startswith(base_name) and file.endswith('.srt'):
                return os.path.join(directory, file)
        
        return None

if __name__ == "__main__":
    # Configuration
    SCOPES = ["https://www.googleapis.com/auth/youtube"]
    TOKEN_FILE = "token.pickle"
    CREDENTIALS_FILE = "client_secret.json"
    MASTER_FOLDER = r"E:\khóa học\Backend web\[FEDU] Lập trình Backend với PHP- Mysql và Jquery"
    
    uploader = YouTubeUploader()
    
    try:
        # Check if master folder contains videos directly
        if any(f.lower().endswith('.mp4') for f in os.listdir(MASTER_FOLDER)):
            print(f"Processing master folder: {MASTER_FOLDER}")
            uploader.process_folder(MASTER_FOLDER)
        else:
            # Process subfolders
            for subfolder in os.listdir(MASTER_FOLDER):
                subfolder_path = os.path.join(MASTER_FOLDER, subfolder)
                if os.path.isdir(subfolder_path):
                    print(f"\nProcessing subfolder: {subfolder}")
                    uploader.process_folder(subfolder_path)
    
    except KeyboardInterrupt:
        print("\nUpload interrupted by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
    finally:
        input("\nPress Enter to exit...")