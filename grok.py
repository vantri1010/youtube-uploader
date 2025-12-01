import os
import json
import time
import random
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import google.auth.transport.requests
import requests
import httplib2

# Set retries for the requests library
requests.adapters.DEFAULT_RETRIES = 3
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Define constants
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = r"client_secret.json"
MASTER_FOLDER = r"E:\khóa học\NodeJS\TypeScript-ES6(Javascript) qua dự án Shopping Cart- Nền tảng NodeJS và AngularJS2"
UPLOAD_LOG_FILE = r"upload_log.json"
TOKEN_FILE = r"token.pickle"
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5
HTTP_TIMEOUT = 60
CHUNK_SIZE = 256 * 1024  # 256KB

# Step 1: Authenticate with token caching
def get_authenticated_service():
    credentials = None
    # Create an HTTP client with a timeout
    http = httplib2.Http(timeout=HTTP_TIMEOUT)

    # Check if token file exists
    if os.path.exists(TOKEN_FILE):
        print("Loading cached credentials...")
        try:
            with open(TOKEN_FILE, "rb") as token:
                credentials = pickle.load(token)
            # Check if the token is valid and not expired
            if credentials and credentials.valid:
                print("Using cached credentials successfully!")
            elif credentials and credentials.expired and credentials.refresh_token:
                print("Credentials expired. Refreshing token...")
                credentials.refresh(google.auth.transport.requests.Request(session=session))
                with open(TOKEN_FILE, "wb") as token:
                    pickle.dump(credentials, token)
                print("Refreshed token and saved for future use!")
            else:
                print("Cached credentials are invalid or cannot be refreshed.")
                credentials = None
        except Exception as e:
            print(f"Error loading token file: {e}")
            credentials = None

    # If no valid credentials, authenticate via browser
    if not credentials:
        print("No valid credentials found. Authenticating via browser...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        credentials = flow.run_local_server(port=8080)
        # Save the credentials for future runs
        try:
            with open(TOKEN_FILE, "wb") as token:
                pickle.dump(credentials, token)
            print("Credentials saved for future use!")
        except Exception as e:
            print(f"Error saving token file: {e}")

    # Build the YouTube service with the custom HTTP client
    return build("youtube", "v3", credentials=credentials)

# Step 2: Load or initialize upload log
def load_upload_log():
    if os.path.exists(UPLOAD_LOG_FILE):
        try:
            with open(UPLOAD_LOG_FILE, "r") as f:
                content = f.read().strip()
                if not content:
                    print("upload_log.json is empty. Initializing with empty dictionary.")
                    return {}
                return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in upload_log.json: {e}. Initializing with empty dictionary.")
            return {}
        except Exception as e:
            print(f"Error loading upload_log.json: {e}. Initializing with empty dictionary.")
            return {}
    return {}

def save_upload_log(upload_log):
    try:
        with open(UPLOAD_LOG_FILE, "w") as f:
            json.dump(upload_log, f, indent=4)
    except Exception as e:
        print(f"Error saving upload_log.json: {e}")

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

# Step 4: Get videos in the playlist
def get_playlist_videos(youtube, playlist_id):
    playlist_videos = {}
    try:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50
        )
        while request:
            response = request.execute()
            for item in response.get("items", []):
                title = item["snippet"]["title"]
                video_id = item["snippet"]["resourceId"]["videoId"]
                # Normalize title by removing .mp4 if present
                if title.endswith(".mp4"):
                    title = title[:-4]
                playlist_videos[title] = video_id
            request = youtube.playlistItems().list_next(request, response)
    except HttpError as e:
        print(f"Error fetching playlist videos: {e}")
    return playlist_videos

# Step 5: Upload video with retry logic
def upload_video(youtube, file_path):
    file_size = os.path.getsize(file_path)
    print(f"File size: {file_size / (1024*1024):.2f} MB")

    request_body = {
        "snippet": {
            "title": os.path.splitext(os.path.basename(file_path))[0],
            "description": "Uploaded automatically via grok.py script",
            "tags": ["go", "microservices", "kubernetes", "golang"],
            "categoryId": "28"
        },
        "status": {
            "privacyStatus": "private",
            "embeddable": True,
            "license": "youtube"
        }
    }

    for attempt in range(MAX_RETRIES):
        try:
            # Recreate media per attempt to ensure a clean resumable stream
            media = MediaFileUpload(
                file_path,
                chunksize=CHUNK_SIZE,     # must be multiple of 256KB
                resumable=True,
                mimetype="video/mp4"
            )

            print(f"Attempt {attempt + 1}/{MAX_RETRIES}: Uploading {file_path} "
                  f"({file_size / (1024*1024):.2f} MB) with {CHUNK_SIZE//1024} KB chunks...")

            upload_request = youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = upload_request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    print(f"   Uploaded {percent}%", end="\r")

            if response:
                video_id = response["id"]
                print(f"\nSuccessfully uploaded! Video ID: {video_id}")
                return video_id

        except HttpError as e:
            # Robust quota detection by parsing error JSON
            reason = ""
            try:
                err = json.loads(e.content.decode("utf-8"))
                errors = err.get("error", {}).get("errors", [])
                if errors:
                    reason = errors[0].get("reason", "")
            except Exception:
                pass

            if e.resp.status in [403, 400] and reason in ["quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"]:
                print(f"Daily upload quota exceeded: {reason}")
                raise QuotaExceededError("Daily upload limit exceeded")
            else:
                print(f"HTTP error: {e}")

        except Exception as e:
            print(f"Unexpected error: {e}")

        if attempt < MAX_RETRIES - 1:
            backoff = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1)
            print(f"Retrying in {backoff:.1f} seconds...")
            time.sleep(backoff)

    print(f"Failed to upload {file_path} after {MAX_RETRIES} attempts.")
    return None

# Step 6: Upload SRT captions if available
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

# Step 7: Add video to playlist
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

# Step 8: Process a folder (master or subfolder)
def process_folder(youtube, folder_path, playlist_id, playlist_name):
    upload_log = load_upload_log()
    mp4_files = sorted([f for f in os.listdir(folder_path) if f.endswith(".mp4")])  # Sort alphabetically
    srt_files = [f for f in os.listdir(folder_path) if f.endswith(".srt")]

    # Step 1: Get playlist videos
    try:
        playlist_videos = get_playlist_videos(youtube, playlist_id)
    except Exception as e:
        print(f"Error fetching playlist videos: {e}")
        return False

    # Step 2: Create uploaded_videos mapping {mp4_file: video_id}
    uploaded_videos = {}
    for mp4_file in mp4_files:
        base_name = os.path.splitext(mp4_file)[0]
        if base_name in playlist_videos:
            uploaded_videos[mp4_file] = playlist_videos[base_name]

    # Step 3: Update upload_log
    upload_log[playlist_name] = upload_log.get(playlist_name, {})
    upload_log[playlist_name]["uploaded_videos"] = uploaded_videos

    # Step 4: Update pending_videos
    pending_videos = sorted([f for f in mp4_files if f not in uploaded_videos])
    upload_log[playlist_name]["pending_videos"] = pending_videos
    print(f"Updated pending_videos: {pending_videos}")
    save_upload_log(upload_log)

    # Step 5: Process pending videos
    while upload_log[playlist_name]["pending_videos"]:
        mp4_file = upload_log[playlist_name]["pending_videos"][0]
        mp4_path = os.path.join(folder_path, mp4_file)
        mp4_basename = os.path.splitext(mp4_file)[0]

        print(f"\nProcessing video: {mp4_file} ({len(upload_log[playlist_name]['pending_videos'])} remaining)")
        try:
            if mp4_basename in upload_log[playlist_name]["uploaded_videos"]:
                video_id = upload_log[playlist_name]["uploaded_videos"][mp4_basename]
                print(f"Video {mp4_file} already uploaded with ID: {video_id}")
            else:
                video_id = upload_video(youtube, mp4_path)
                if video_id is None:
                    continue

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
                upload_log[playlist_name]["uploaded_videos"][mp4_basename] = video_id
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