import os
import json
import time
import random
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import googleapiclient.http
import httplib2

# Define constants
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = r"client_secret.json"
MASTER_FOLDER = r"E:\khóa học\Backend web\[FEDU] PHP MVC"
UPLOAD_LOG_FILE = r"upload_log.json"
TOKEN_FILE = r"token.pickle"
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5

# Step 1: Authenticate with token caching and increased timeout
def get_authenticated_service():
    credentials = None
    if os.path.exists(TOKEN_FILE):
        print("Loading cached credentials...")
        with open(TOKEN_FILE, "rb") as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        print("No valid credentials found. Authenticating via browser...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        credentials = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(credentials, token)
        print("Credentials saved for future use!")
    else:
        print("Using cached credentials successfully!")

    http = httplib2.Http(timeout=60)
    return build("youtube", "v3", credentials=credentials, http=http)

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
        print(f"Found existing playlist '{playlist_name}' with ID: {upload_log[playlist_name]['playlist_id']}")
        return upload_log[playlist_name]["playlist_id"]

    print(f"Searching for playlist '{playlist_name}'...")
    try:
        playlists = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for playlist in playlists.get("items", []):
            if playlist["snippet"]["title"] == playlist_name:
                upload_log[playlist_name] = upload_log.get(playlist_name, {})
                upload_log[playlist_name]["playlist_id"] = playlist["id"]
                save_upload_log(upload_log)
                print(f"Found existing playlist '{playlist_name}' with ID: {playlist['id']}")
                return playlist["id"]
    except HttpError as e:
        print(f"Error searching for playlist: {e}")
        raise

    print(f"Playlist '{playlist_name}' not found. Creating a new one...")
    request_body = {
        "snippet": {
            "title": playlist_name,
            "description": f"Playlist for videos in {playlist_name}"
        },
        "status": {"privacyStatus": "private"}
    }
    try:
        response = youtube.playlists().insert(part="snippet,status", body=request_body).execute()
        upload_log[playlist_name] = upload_log.get(playlist_name, {})
        upload_log[playlist_name]["playlist_id"] = response["id"]
        save_upload_log(upload_log)
        print(f"Created new playlist '{playlist_name}' with ID: {response['id']}")
        return response["id"]
    except HttpError as e:
        print(f"Error creating playlist: {e}")
        raise

# Step 4: Get all videos uploaded by the user
def get_uploaded_videos(youtube):
    videos = {}
    try:
        request = youtube.videos().list(
            part="snippet",
            mine=True,
            maxResults=50
        )
        while request:
            response = request.execute()
            for video in response.get("items", []):
                videos[video["snippet"]["title"]] = video["id"]
            request = youtube.videos().list_next(request, response)
    except HttpError as e:
        print(f"Error fetching uploaded videos: {e}")
    return videos

# Step 5: Get videos in the playlist
def get_playlist_videos(youtube, playlist_id):
    playlist_videos = set()
    try:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50
        )
        while request:
            response = request.execute()
            for item in response.get("items", []):
                playlist_videos.add(item["snippet"]["title"])
            request = youtube.playlistItems().list_next(request, response)
    except HttpError as e:
        print(f"Error fetching playlist videos: {e}")
    return playlist_videos

# Step 6: Delete videos not in the playlist
def delete_unlisted_videos(youtube, uploaded_videos, playlist_videos, mp4_files):
    for video_title, video_id in uploaded_videos.items():
        if video_title in mp4_files and video_title not in playlist_videos:
            try:
                print(f"Deleting video '{video_title}' (ID: {video_id}) as it was not added to the playlist...")
                youtube.videos().delete(id=video_id).execute()
                print(f"Successfully deleted video '{video_title}'")
            except HttpError as e:
                print(f"Error deleting video '{video_title}': {e}")

# Step 7: Upload video with retry logic
def upload_video(youtube, file_path):
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

    for attempt in range(MAX_RETRIES):
        try:
            print(f"Attempt {attempt + 1}/{MAX_RETRIES}: Uploading {file_path}...")
            response = youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            ).execute()
            print(f"Successfully uploaded {file_path} with ID: {response['id']}")
            return response["id"]
        except HttpError as e:
            error_reason = e.error_details[0]["reason"] if e.error_details else "unknown"
            if e.resp.status in [403, 400] and error_reason in ["quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"]:
                print(f"Daily upload limit exceeded for {file_path}: {e}")
                print("YouTube typically allows 6-10 uploads per day for new/unverified accounts.")
                print("The script will save progress and exit.")
                print("Please run the script again after the quota resets (midnight Pacific Time).")
                raise QuotaExceededError("Daily upload limit exceeded")
            elif e.resp.status == 429:
                backoff_time = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1)
                print(f"Rate limit exceeded: {e}. Retrying in {backoff_time:.2f} seconds...")
                time.sleep(backoff_time)
            else:
                print(f"Temporary failure uploading {file_path}: {e}. Retrying in {BASE_BACKOFF_SECONDS * (2 ** attempt):.2f} seconds...")
                time.sleep(BASE_BACKOFF_SECONDS * (2 ** attempt))
        except Exception as e:
            print(f"Unexpected error uploading {file_path}: {e}. Retrying in {BASE_BACKOFF_SECONDS * (2 ** attempt):.2f} seconds...")
            time.sleep(BASE_BACKOFF_SECONDS * (2 ** attempt))
    print(f"Failed to upload {file_path} after {MAX_RETRIES} attempts. Keeping in pending list for next run.")
    return None

# Step 8: Upload SRT captions if available
def upload_captions(youtube, video_id, srt_path):
    try:
        print(f"Uploading captions from {srt_path} for video ID {video_id}...")
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
        print(f"Successfully added captions to video ID: {video_id}")
    except HttpError as e:
        print(f"Error uploading captions for video ID {video_id}: {e}")

# Step 9: Add video to playlist
def add_video_to_playlist(youtube, video_id, playlist_id):
    try:
        print(f"Adding video ID {video_id} to playlist ID {playlist_id}...")
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
        print(f"Successfully added video ID {video_id} to playlist")
        return True
    except HttpError as e:
        print(f"Error adding video {video_id} to playlist: {e}")
        return False

# Step 10: Process a folder (master or subfolder)
def process_folder(youtube, folder_path, playlist_id, playlist_name):
    upload_log = load_upload_log()
    mp4_files = [f for f in os.listdir(folder_path) if f.endswith(".mp4")]
    srt_files = [f for f in os.listdir(folder_path) if f.endswith(".srt")]

    # Step 10.1: Get uploaded videos and playlist videos
    print("Fetching uploaded videos and playlist videos...")
    uploaded_videos = get_uploaded_videos(youtube)
    playlist_videos = get_playlist_videos(youtube, playlist_id)

    # Step 10.2: Delete videos that were uploaded but not added to the playlist
    delete_unlisted_videos(youtube, uploaded_videos, playlist_videos, mp4_files)

    # Step 10.3: Initialize upload log for this playlist
    upload_log[playlist_name] = upload_log.get(playlist_name, {})
    upload_log[playlist_name]["uploaded_videos"] = upload_log[playlist_name].get("uploaded_videos", {})

    # Step 10.4: Update pending_videos based on local folder and uploaded videos
    pending_videos = []
    for mp4_file in mp4_files:
        if mp4_file not in upload_log[playlist_name]["uploaded_videos"]:
            pending_videos.append(mp4_file)
    upload_log[playlist_name]["pending_videos"] = pending_videos
    print(f"Updated pending_videos: {pending_videos}")
    save_upload_log(upload_log)

    # Step 10.5: Process pending videos
    while upload_log[playlist_name]["pending_videos"]:
        mp4_file = upload_log[playlist_name]["pending_videos"][0]
        mp4_path = os.path.join(folder_path, mp4_file)
        mp4_basename = os.path.splitext(mp4_file)[0]

        print(f"\nProcessing video: {mp4_file} ({len(upload_log[playlist_name]['pending_videos'])} remaining)")
        try:
            # Check if already uploaded (in case of partial failure in previous run)
            if mp4_file in uploaded_videos:
                video_id = uploaded_videos[mp4_file]
                print(f"Video {mp4_file} already uploaded with ID: {video_id}")
            else:
                video_id = upload_video(youtube, mp4_path)
                if video_id is None:
                    continue  # Keep in pending_videos if upload fails

            # Look for matching SRT file
            matching_srt = None
            for srt_file in srt_files:
                if mp4_basename in srt_file:
                    matching_srt = srt_file
                    break

            if matching_srt:
                srt_path = os.path.join(folder_path, matching_srt)
                upload_captions(youtube, video_id, srt_path)

            # Add to playlist
            if add_video_to_playlist(youtube, video_id, playlist_id):
                # Only mark as uploaded if successfully added to playlist
                upload_log[playlist_name]["uploaded_videos"][mp4_file] = video_id
                upload_log[playlist_name]["pending_videos"].remove(mp4_file)
                save_upload_log(upload_log)
            else:
                print(f"Failed to add {mp4_file} to playlist. Keeping in pending list for next run.")

        except QuotaExceededError:
            print(f"Stopping due to upload limit. Progress saved in {UPLOAD_LOG_FILE}.")
            return False
        except Exception as e:
            print(f"Failed to process {mp4_file}: {e}")
            print("Keeping in pending list for next run...")
            continue

    print(f"Finished processing folder: {folder_path}")
    return True

# Custom exception for quota exceeded
class QuotaExceededError(Exception):
    pass

# Main function
def main():
    try:
        youtube = get_authenticated_service()
        
        # Get master folder name for playlist
        master_folder_name = os.path.basename(os.path.normpath(MASTER_FOLDER))
        playlist_id = get_or_create_playlist(youtube, master_folder_name)

        # Check if master folder has subfolders
        subfolders = [d for d in os.listdir(MASTER_FOLDER) if os.path.isdir(os.path.join(MASTER_FOLDER, d))]
        
        if subfolders:
            for subfolder in subfolders:
                subfolder_path = os.path.join(MASTER_FOLDER, subfolder)
                print(f"\nStarting to process subfolder: {subfolder}")
                if not process_folder(youtube, subfolder_path, playlist_id, master_folder_name):
                    break
        else:
            print(f"\nNo subfolders found. Processing master folder: {master_folder_name}")
            process_folder(youtube, MASTER_FOLDER, playlist_id, master_folder_name)

        print("\nAll videos have been processed successfully!")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        print("Progress has been saved. You can run the script again to continue.")

    finally:
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()