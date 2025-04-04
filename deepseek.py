import os
import time
import ssl
import socket
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed

class YouTubeUploader:
    def __init__(self):
        # Configure SSL context
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        socket.setdefaulttimeout(300)  # 5 minute timeout
        
        # Initialize YouTube service
        self.youtube = self._authenticate()
        self.playlist_cache = {}
        self.video_cache = {}
        self.executor = ThreadPoolExecutor(max_workers=2)  # Conservative concurrency

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
                    open_browser=True,
                    ssl_context=self.ssl_context
                )
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        
        # Build service with default HTTP client
        return build("youtube", "v3", credentials=creds)

    def _get_all_playlist_videos(self, playlist_id):
        """Retrieve all videos in a playlist with pagination"""
        videos = []
        next_page_token = None
        
        while True:
            try:
                request = self.youtube.playlistItems().list(
                    part="snippet",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                )
                response = request.execute()
                videos.extend(response.get('items', []))
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
                time.sleep(1)  # Brief pause between pages
            except (HttpError, socket.timeout) as e:
                print(f"Error retrieving playlist items: {e}")
                time.sleep(5)
                continue
            except ssl.SSLError as e:
                print(f"SSL error retrieving playlist: {e}")
                time.sleep(10)
                continue
        
        return videos

    def _cache_playlist_videos(self, playlist_id, playlist_name):
        """Cache all videos in a playlist"""
        if playlist_id in self.video_cache:
            return
        
        print(f"Caching videos for playlist: {playlist_name}")
        retries = 3
        for attempt in range(retries):
            try:
                videos = self._get_all_playlist_videos(playlist_id)
                self.video_cache[playlist_id] = {
                    v['snippet']['title'].lower(): True for v in videos
                }
                print(f"Cached {len(videos)} videos from playlist")
                return
            except Exception as e:
                if attempt == retries - 1:
                    print(f"Failed to cache playlist after {retries} attempts")
                    raise
                print(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(5 * (attempt + 1))

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
        except (HttpError, socket.timeout) as e:
            print(f"Error searching for playlists: {e}")
        return None

    def _create_or_get_playlist(self, playlist_name):
        """Get existing playlist or create new one"""
        playlist_id = self._find_existing_playlist(playlist_name)
        if playlist_id:
            print(f"Using existing playlist: {playlist_name}")
            self._cache_playlist_videos(playlist_id, playlist_name)
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
        except (HttpError, socket.timeout) as e:
            print(f"Failed to create playlist: {e}")
            return None

    def _is_video_in_playlist(self, video_title, playlist_id):
        """Check if video exists in playlist (using cache)"""
        if playlist_id in self.video_cache:
            return video_title.lower() in self.video_cache[playlist_id]
        return False

    def _find_matching_srt(self, video_file):
        """Find matching subtitle file"""
        base_name = os.path.splitext(video_file)[0]
        directory = os.path.dirname(video_file)
        
        # Check for exact match first
        exact_match = os.path.join(directory, f"{base_name}.srt")
        if os.path.exists(exact_match):
            return exact_match
        
        # Check for variations
        for file in os.listdir(directory):
            if file.startswith(base_name) and file.endswith('.srt'):
                return os.path.join(directory, file)
        
        return None

    def _upload_video(self, video_path, playlist_id, srt_path=None):
        """Upload video with retry logic"""
        video_title = os.path.splitext(os.path.basename(video_path))[0]
        
        for attempt in range(3):
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
                
                # Update cache
                if playlist_id in self.video_cache:
                    self.video_cache[playlist_id][video_title.lower()] = True
                
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
                    except (HttpError, socket.timeout, ssl.SSLError) as e:
                        print(f"Subtitle upload failed: {e}")
                
                return True
                
            except HttpError as e:
                if 'uploadLimitExceeded' in str(e):
                    print("Daily upload limit reached. Please try again tomorrow.")
                    return False
                elif 'quotaExceeded' in str(e):
                    print("API quota exceeded. Please try again later.")
                    return False
                else:
                    print(f"Upload failed (attempt {attempt + 1}): {e}")
                    if attempt == 2:
                        return False
                    time.sleep(10 * (attempt + 1))
            except (socket.timeout, ssl.SSLError) as e:
                print(f"Network error (attempt {attempt + 1}): {e}")
                if attempt == 2:
                    return False
                time.sleep(15 * (attempt + 1))
        
        return False

    def process_videos(self, video_files, folder_path, playlist_id):
        """Process videos with error handling"""
        results = []
        upload_queue = []
        
        # First check all videos to skip already uploaded ones
        for video_file in video_files:
            video_path = os.path.join(folder_path, video_file)
            video_title = os.path.splitext(video_file)[0]
            
            if self._is_video_in_playlist(video_title.lower(), playlist_id):
                print(f"Skipping already uploaded video: {video_title}")
                results.append(True)
            else:
                srt_path = self._find_matching_srt(video_path)
                upload_queue.append((video_path, srt_path, video_title))
        
        # Process upload queue with limited concurrency
        futures = {}
        for video_path, srt_path, video_title in upload_queue:
            future = self.executor.submit(
                self._upload_video,
                video_path,
                playlist_id,
                srt_path
            )
            futures[future] = video_title
        
        for future in as_completed(futures):
            video_title = futures[future]
            try:
                success = future.result()
                results.append(success)
                if not success:
                    break  # Stop on critical error
            except Exception as e:
                print(f"Fatal error uploading {video_title}: {e}")
                results.append(False)
                break
        
        return all(results)

    def process_folder(self, folder_path):
        """Process all videos in a folder"""
        playlist_name = os.path.basename(folder_path)
        playlist_id = self._create_or_get_playlist(playlist_name)
        if not playlist_id:
            return False
        
        video_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.mp4')]
        if not video_files:
            print(f"No videos found in {folder_path}")
            return True
        
        print(f"Processing {len(video_files)} videos in {playlist_name}")
        return self.process_videos(video_files, folder_path, playlist_id)

if __name__ == "__main__":
    # Configuration
    SCOPES = ["https://www.googleapis.com/auth/youtube"]
    TOKEN_FILE = "token.pickle"
    CREDENTIALS_FILE = "client_secret.json"
    MASTER_FOLDER = r"E:\khóa học\Backend web\[FEDU] Lập trình Backend với PHP- Mysql và Jquery"
    
    try:
        uploader = YouTubeUploader()
        
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
        if 'uploader' in locals():
            uploader.executor.shutdown(wait=True)
        input("\nPress Enter to exit...")