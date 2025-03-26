import os
import json
import time
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta

# Define constants
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = "client_secret.json"  # Replace with your OAuth 2.0 credentials file
MASTER_FOLDER = r"E:\khóa học\Backend web\[FEDU] PHP MVC"  # Replace with your master folder path
UPLOAD_LOG_FILE = "upload_log.json"  # File to track uploaded videos
RETRY_WAIT_SECONDS = 3600  # Wait 1 hour before retrying after quota limit

# Step 1: Authenticate
def get_authenticated_service():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=8080)  # Fixed port
    return build("youtube", "v3", credentials=credentials)

# Step 2: Load or initialize upload log
def load_upload_log():
    if os.path.exists(UPLOAD_LOG_FILE):
        with open(UPLOAD_LOG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_upload_log(upload_log):
    with open(UPLOAD_LOG_FILE, "w") as f:
        json.dump(upload_log, f, indent=4)

# Step 3: Check if playlist exists, create if not, and return its ID
def get_or_create_playlist(youtube, playlist_name):
    upload_log = load_upload_log()
    if playlist_name in upload_log and "playlist_id" in upload_log[playlist_name]:
        return upload_log[playlist_name]["playlist_id"]

    # Search for existing playlist
    playlists = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for playlist in playlists.get("items", []):
        if playlist["snippet"]["title"] == playlist_name:
            upload_log[playlist_name] = upload_log.get(playlist_name, {})
            upload_log[playlist_name]["playlist_id"] = playlist["id"]
            save_upload_log(upload_log)
            return playlist["id"]

    # Create new playlist if not found
    request_body = {
        "snippet": {
            "title": playlist_name,
            "description": f"Playlist for videos in {playlist_name}"
        },
        "status": {"privacyStatus": "private"}
    }
    response = youtube.playlists().insert(part="snippet,status", body=request_body).execute()
    upload_log[playlist_name] = upload_log.get(playlist_name, {})
    upload_log[playlist_name]["playlist_id"] = response["id"]
    save_upload_log(upload_log)
    return response["id"]

# Step 4: Check if video is already uploaded
def is_video_uploaded(youtube, playlist_id, video_filename, upload_log, playlist_name):
    # Check local log first
    if playlist_name in upload_log and "uploaded_videos" in upload_log[playlist_name]:
        if video_filename in upload_log[playlist_name]["uploaded_videos"]:
            return True

    # Optionally, query the playlist to confirm (costs API quota)
    playlist_items = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    ).execute()
    for item in playlist_items.get("items", []):
        if item["snippet"]["title"] == video_filename:
            upload_log[playlist_name] = upload_log.get(playlist_name, {})
            upload_log[playlist_name]["uploaded_videos"] = upload_log[playlist_name].get("uploaded_videos", {})
            upload_log[playlist_name]["uploaded_videos"][video_filename] = item["snippet"]["resourceId"]["videoId"]
            save_upload_log(upload_log)
            return True
    return False

# Step 5: Upload video with retry logic
def upload_video(youtube, file_path, max_retries=3):
    request_body = {
        "snippet": {
            "title": os.path.basename(file_path),
            "description": "Uploaded automatically via script",
            "tags": ["auto-upload", "playlist"],
            "categoryId": "22"
        },
        "status": {"privacyStatus": "private"}
    }
    media = MediaFileUpload(file_path)

    for attempt in range(max_retries):
        try:
            response = youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            ).execute()
            return response["id"]
        except HttpError as e:
            if e.resp.status in [403, 429]:  # Quota exceeded or rate limit
                print(f"Quota or rate limit exceeded: {e}. Retrying in {RETRY_WAIT_SECONDS} seconds...")
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                print(f"Error uploading {file_path}: {e}")
                raise
    raise Exception(f"Failed to upload {file_path} after {max_retries} attempts")

# Step 6: Upload SRT captions if available
def upload_captions(youtube, video_id, srt_path):
    try:
        media = MediaFileUpload(srt_path)
        youtube.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "language": "en",
                    "name": "Subtitles",
                    "isDraft": False
                }
            },
            media_body=media
        ).execute()
    except HttpError as e:
        print(f"Error uploading captions for video ID {video_id}: {e}")

# Step 7: Add video to playlist
def add_video_to_playlist(youtube, video_id, playlist_id):
    try:
        request_body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
        youtube.playlistItems().insert(part="snippet", body=request_body).execute()
    except HttpError as e:
        print(f"Error adding video {video_id} to playlist: {e}")

# Step 8: Process a folder (master or subfolder)
def process_folder(youtube, folder_path, playlist_id, playlist_name):
    upload_log = load_upload_log()
    mp4_files = [f for f in os.listdir(folder_path) if f.endswith(".mp4")]
    srt_files = [f for f in os.listdir(folder_path) if f.endswith(".srt")]

    for mp4_file in mp4_files:
        mp4_path = os.path.join(folder_path, mp4_file)
        mp4_basename = os.path.splitext(mp4_file)[0]

        # Skip if already uploaded
        if is_video_uploaded(youtube, playlist_id, mp4_file, upload_log, playlist_name):
            print(f"Skipping {mp4_file} (already uploaded)")
            continue

        print(f"Uploading {mp4_file}...")
        try:
            video_id = upload_video(youtube, mp4_path)
            print(f"Uploaded video with ID: {video_id}")

            # Look for matching SRT file
            matching_srt = None
            for srt_file in srt_files:
                if mp4_basename in srt_file:
                    matching_srt = srt_file
                    break

            if matching_srt:
                srt_path = os.path.join(folder_path, matching_srt)
                print(f"Uploading captions from {matching_srt}...")
                upload_captions(youtube, video_id, srt_path)
                print(f"Captions added to video ID: {video_id}")

            # Add to playlist
            add_video_to_playlist(youtube, video_id, playlist_id)
            print(f"Added {mp4_file} to playlist")

            # Update upload log
            upload_log[playlist_name] = upload_log.get(playlist_name, {})
            upload_log[playlist_name]["uploaded_videos"] = upload_log[playlist_name].get("uploaded_videos", {})
            upload_log[playlist_name]["uploaded_videos"][mp4_file] = video_id
            save_upload_log(upload_log)

        except Exception as e:
            print(f"Failed to process {mp4_file}: {e}")
            continue

# Main function
def main():
    youtube = get_authenticated_service()
    
    # Get master folder name for playlist
    master_folder_name = os.path.basename(os.path.normpath(MASTER_FOLDER))
    playlist_id = get_or_create_playlist(youtube, master_folder_name)
    print(f"Using playlist '{master_folder_name}' with ID: {playlist_id}")

    # Check if master folder has subfolders
    subfolders = [d for d in os.listdir(MASTER_FOLDER) if os.path.isdir(os.path.join(MASTER_FOLDER, d))]
    
    if subfolders:
        for subfolder in subfolders:
            subfolder_path = os.path.join(MASTER_FOLDER, subfolder)
            print(f"Processing subfolder: {subfolder}")
            process_folder(youtube, subfolder_path, playlist_id, master_folder_name)
    else:
        print(f"No subfolders found. Processing master folder: {master_folder_name}")
        process_folder(youtube, MASTER_FOLDER, playlist_id, master_folder_name)

if __name__ == "__main__":
    main()