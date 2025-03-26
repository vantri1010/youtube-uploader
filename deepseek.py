import os
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import pickle

# OAuth scope
SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "client_secret.json"

class YouTubeUploader:
    def __init__(self):
        self.youtube = self._authenticate()
    
    def _authenticate(self):
        creds = None
        
        # Load existing credentials if available
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, run OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        
        return build("youtube", "v3", credentials=creds)
    
    def _create_playlist(self, playlist_name):
        request = self.youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": playlist_name,
                    "description": f"Automated playlist: {playlist_name}",
                },
                "status": {
                    "privacyStatus": "private"  # or "public", "unlisted"
                }
            }
        )
        response = request.execute()
        return response["id"]
    
    def _find_matching_srt(self, video_file):
        base_name = os.path.splitext(video_file)[0]
        
        # Look for exact match (video.mp4 -> video.srt)
        exact_match = f"{base_name}.srt"
        if os.path.exists(exact_match):
            return exact_match
        
        # Look for partial matches (useful for language codes)
        directory = os.path.dirname(video_file)
        for file in os.listdir(directory):
            if file.startswith(base_name) and file.endswith('.srt'):
                return os.path.join(directory, file)
        
        return None
    
    def _upload_video(self, video_path, playlist_id, srt_path=None):
        title = os.path.splitext(os.path.basename(video_path))[0]
        
        # Upload video
        request = self.youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": f"Automated upload from {os.path.basename(video_path)}",
                    "categoryId": "22"  # See YouTube category IDs
                },
                "status": {
                    "privacyStatus": "private"  # or "public", "unlisted"
                }
            },
            media_body=MediaFileUpload(video_path)
        )
        response = request.execute()
        video_id = response["id"]
        
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
                            "language": "en",  # Change as needed
                            "name": "English"    # Change as needed
                        }
                    },
                    media_body=MediaFileUpload(srt_path)
                ).execute()
            except HttpError as e:
                print(f"Failed to upload subtitles for {video_path}: {e}")
        
        return video_id
    
    def process_master_folder(self, master_folder_path):
        # Check if master folder contains videos directly
        direct_videos = [f for f in os.listdir(master_folder_path) 
                        if f.lower().endswith('.mp4')]
        
        if direct_videos:
            print(f"Processing master folder as playlist: {master_folder_path}")
            playlist_name = os.path.basename(master_folder_path)
            playlist_id = self._create_playlist(playlist_name)
            
            for video_file in direct_videos:
                video_path = os.path.join(master_folder_path, video_file)
                srt_path = self._find_matching_srt(video_path)
                
                print(f"Uploading {video_file}...")
                self._upload_video(video_path, playlist_id, srt_path)
                print(f"Uploaded {video_file} to playlist {playlist_name}")
        else:
            # Process subfolders
            for subfolder in os.listdir(master_folder_path):
                subfolder_path = os.path.join(master_folder_path, subfolder)
                if os.path.isdir(subfolder_path):
                    print(f"Processing subfolder as playlist: {subfolder}")
                    playlist_id = self._create_playlist(subfolder)
                    
                    for video_file in os.listdir(subfolder_path):
                        if video_file.lower().endswith('.mp4'):
                            video_path = os.path.join(subfolder_path, video_file)
                            srt_path = self._find_matching_srt(video_path)
                            
                            print(f"Uploading {video_file}...")
                            self._upload_video(video_path, playlist_id, srt_path)
                            print(f"Uploaded {video_file} to playlist {subfolder}")

if __name__ == "__main__":
    uploader = YouTubeUploader()
    
    # Example usage - process all master folders in a directory
    root_directory = "/path/to/your/master/folders"
    
    for item in os.listdir(root_directory):
        item_path = os.path.join(root_directory, item)
        if os.path.isdir(item_path):
            try:
                uploader.process_master_folder(item_path)
            except Exception as e:
                print(f"Error processing {item}: {e}")