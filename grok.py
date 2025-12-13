import os
import json
import time
import random
import pickle
import re
import argparse
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import google.auth.transport.requests
import requests

# Set retries for the requests library
requests.adapters.DEFAULT_RETRIES = 3
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Define constants
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]
CLIENT_SECRETS_FILE = r"client_secret.json"
# Default master folder (can be overridden via CLI)
MASTER_FOLDER = r""  # Change this to your master folder path
UPLOAD_LOG_FILE = r"upload_log.json"
TOKEN_FILE = r"token.pickle"
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5
CHUNK_SIZE = 1024 * 1024  # 1MB


# Helper function for natural sorting with numeric prefixes
def natural_sort_key(name):
    """
    Extract leading number for natural sorting.
    Handles formats like: "01 Title", "1. Title", "1 - Title", or "Title"
    Returns tuple for proper sorting: numbered items first (by number), then non-numbered (alphabetically)
    """
    match = re.match(r'^(\d+)', name)
    if match:
        return (0, int(match.group(1)), name)
    return (1, 0, name)


# Custom exception for quota exceeded
class QuotaExceededError(Exception):
    pass


# Step 1: Authenticate with token caching
def get_authenticated_service():
    credentials = None

    if os.path.exists(TOKEN_FILE):
        print("🔐 Loading cached credentials...")
        try:
            with open(TOKEN_FILE, "rb") as token:
                credentials = pickle.load(token)
            if credentials and credentials.valid:
                print("✅ Using cached credentials successfully!")
            elif credentials and credentials.expired and credentials.refresh_token:
                print("♻️ Credentials expired. Refreshing token...")
                credentials.refresh(google.auth.transport.requests.Request(session=session))
                with open(TOKEN_FILE, "wb") as token:
                    pickle.dump(credentials, token)
                print("💾 Refreshed token and saved for future use!")
            else:
                print("⚠️ Cached credentials are invalid or cannot be refreshed.")
                credentials = None
        except Exception as e:
            print(f"❌ Error loading token file: {e}")
            credentials = None

    if not credentials:
        print("🔑 No valid credentials found. Authenticating via browser...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        credentials = flow.run_local_server(port=8080)
        try:
            with open(TOKEN_FILE, "wb") as token:
                pickle.dump(credentials, token)
            print("✅ Credentials saved for future use!")
        except Exception as e:
            print(f"❌ Error saving token file: {e}")

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
        print(f"📃 Found existing playlist '{playlist_name}' with ID: {upload_log[playlist_name]['playlist_id']}")
        return upload_log[playlist_name]["playlist_id"]

    print(f"🔎 Searching for playlist '{playlist_name}'...")
    try:
        playlists = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for playlist in playlists.get("items", []):
            if playlist["snippet"]["title"] == playlist_name:
                upload_log[playlist_name] = upload_log.get(playlist_name, {})
                upload_log[playlist_name]["playlist_id"] = playlist["id"]
                save_upload_log(upload_log)
                print(f"✅ Found existing playlist '{playlist_name}' with ID: {playlist['id']}")
                return playlist["id"]
    except HttpError as e:
        print(f"❌ Error searching for playlist: {e}")
        raise

    print(f"🆕 Playlist '{playlist_name}' not found. Creating a new one...")
    request_body = {
        "snippet": {
            "title": playlist_name,
            "description": f"MERN Stack Front To Back Full Stack React, Redux & Node.js"
        },
        "status": {"privacyStatus": "private"}
    }
    try:
        response = youtube.playlists().insert(part="snippet,status", body=request_body).execute()
        upload_log[playlist_name] = upload_log.get(playlist_name, {})
        upload_log[playlist_name]["playlist_id"] = response["id"]
        save_upload_log(upload_log)
        print(f"🎉 Created new playlist '{playlist_name}' with ID: {response['id']}")
        return response["id"]
    except HttpError as e:
        print(f"❌ Error creating playlist: {e}")
        raise


# Step 4: Get videos in the playlist (in-memory cache)
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
                if title.endswith(".mp4"):
                    title = title[:-4]
                playlist_videos[title] = video_id
            request = youtube.playlistItems().list_next(request, response)
    except HttpError as e:
        print(f"❌ Error fetching playlist videos: {e}")
    return playlist_videos


# Step 5: Upload video with retry logic
def upload_video(youtube, file_path, subfolder_name=None):
    file_size = os.path.getsize(file_path)
    print(f"📦 File size: {file_size / (1024*1024):.2f} MB")

    base_title = os.path.splitext(os.path.basename(file_path))[0]
    # Prefix title with subfolder name for uniqueness
    video_title = f"{subfolder_name} - {base_title}" if subfolder_name else base_title

    request_body = {
        "snippet": {
            "title": video_title,
            "description": "section " + os.path.basename(os.path.dirname(file_path)),
            "tags": ["coding", "learning", "tutorial", "MERN Stack", "React", "Redux", "Node.js"],
            "categoryId": "28",  # Science & Technology.
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "embeddable": True,
            "license": "youtube",
            "madeForKids": False,
            "selfDeclaredMadeForKids": False
        }
    }

    for attempt in range(MAX_RETRIES):
        try:
            media = MediaFileUpload(
                file_path,
                chunksize=CHUNK_SIZE,
                resumable=True,
                mimetype="video/mp4"
            )

            print(f"🚀 Attempt {attempt + 1}/{MAX_RETRIES}: Uploading {file_path} "
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
                    print(f"🚄⏫ Uploaded {percent}%", end="\r")

            if response:
                video_id = response["id"]
                print(f"\n✅ Successfully uploaded! Video ID: {video_id}")
                return video_id

        except HttpError as e:
            reason = ""
            try:
                err = json.loads(e.content.decode("utf-8"))
                errors = err.get("error", {}).get("errors", [])
                if errors:
                    reason = errors[0].get("reason", "")
            except Exception:
                pass

            if e.resp.status in [403, 400] and reason in ["quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"]:
                print(f"⛔ Daily upload quota exceeded: {reason}")
                raise QuotaExceededError("Daily upload limit exceeded")
            else:
                print(f"🌐 HTTP error: {e}")

        except Exception as e:
            print(f"⚠️ Unexpected error: {e}")

        if attempt < MAX_RETRIES - 1:
            backoff = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1)
            print(f"🔄 Retrying in {backoff:.1f} seconds...")
            time.sleep(backoff)

    print(f"❌ Failed to upload {file_path} after {MAX_RETRIES} attempts.")
    return None


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
        print(f"📝 Successfully added captions to video ID: {video_id}")
        return True
    except HttpError as e:
        print(f"❌ Error uploading captions for video ID {video_id}: {e}")
        return False


# Step 7: Add video to playlist
def add_video_to_playlist(youtube, video_id, playlist_id):
    try:
        # print(f"Adding video ID {video_id} to playlist ID {playlist_id}...")
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
        print(f"📚 Successfully added video ID {video_id} to playlist {playlist_id}")
        return True
    except HttpError as e:
        print(f"❌ Error adding video {video_id} to playlist: {e}")
        return False


# Step 8: Process a folder
def process_folder(youtube, folder_path, playlist_id, subfolder_name=None, summary=None):
    mp4_files = sorted([f for f in os.listdir(folder_path) if f.endswith(".mp4")], key=natural_sort_key)
    srt_files = [f for f in os.listdir(folder_path) if f.endswith(".srt")]

    try:
        playlist_videos = get_playlist_videos(youtube, playlist_id)
    except Exception as e:
        print(f"Error fetching playlist videos: {e}")
        return False

    pending_videos = []
    for mp4_file in mp4_files:
        base_name = os.path.splitext(mp4_file)[0]
        # Create a prefixed name using subfolder for uniqueness
        prefixed_name = f"{subfolder_name} - {base_name}" if subfolder_name else base_name
        if prefixed_name not in playlist_videos:
            pending_videos.append(mp4_file)

    print(f"📝 Pending videos to upload:\n {pending_videos}")
    for mp4_file in pending_videos:
        mp4_path = os.path.join(folder_path, mp4_file)
        mp4_basename = os.path.splitext(mp4_file)[0]

        print(f"\n🎬 Processing video: {mp4_file}")
        try:
            video_id = upload_video(youtube, mp4_path, subfolder_name)
            if video_id is None:
                if summary is not None:
                    summary["upload_failures"].append(os.path.join(folder_path, mp4_file))
                continue
            # successful upload
            if summary is not None:
                summary["uploaded_count"] += 1
                try:
                    summary["uploaded_bytes"] += os.path.getsize(mp4_path)
                except Exception:
                    pass

            matching_srt = None
            for srt_file in srt_files:
                if mp4_basename in srt_file:
                    matching_srt = srt_file
                    break

            if matching_srt:
                srt_path = os.path.join(folder_path, matching_srt)
                if not upload_captions(youtube, video_id, srt_path):
                    if summary is not None:
                        summary["caption_failures"].append(srt_path)

            if add_video_to_playlist(youtube, video_id, playlist_id):
                print(f"✅ Successfully processed {mp4_file}")
            else:
                print(f"⚠️ Failed to add {mp4_file} to playlist. Will retry on next run.")
                if summary is not None:
                    summary["playlist_failures"].append(os.path.join(folder_path, mp4_file))
        except QuotaExceededError:
            print(f"⛔ Stopping due to upload limit.")
            return False
        except Exception as e:
            print(f"❌ Failed to process {mp4_file}: {e}")
            print("🔁 Will retry on next run...")

    print(f"📁 Finished processing folder: {folder_path}")
    return True


# Main function
def main():
    # Allow passing master folder via CLI to avoid editing code
    parser = argparse.ArgumentParser(description="YouTube uploader for local course videos")
    parser.add_argument("master", nargs="?", default=None, help="Path to MASTER_FOLDER (overrides default)")
    parser.add_argument("--master", dest="master_flag", default=None, help="Path to MASTER_FOLDER (overrides default)")
    args = parser.parse_args()

    effective_master_folder = args.master_flag or args.master or MASTER_FOLDER

    try:
        youtube = get_authenticated_service()
        master_folder_name = os.path.basename(os.path.normpath(effective_master_folder))
        playlist_id = get_or_create_playlist(youtube, master_folder_name)

        subfolders = sorted([d for d in os.listdir(effective_master_folder) if os.path.isdir(os.path.join(effective_master_folder, d))], key=natural_sort_key)

        # Initialize run summary
        summary = {
            "uploaded_count": 0,
            "uploaded_bytes": 0,
            "upload_failures": [],
            "caption_failures": [],
            "playlist_failures": []
        }

        if subfolders:
            for subfolder in subfolders:
                subfolder_path = os.path.join(effective_master_folder, subfolder)
                print(f"\n📌 Starting to process subfolder: {subfolder}")
                if not process_folder(youtube, subfolder_path, playlist_id, subfolder_name=subfolder, summary=summary):
                    break
        else:
            print(f"\n📂 No subfolders found. Processing master folder: {master_folder_name}")
            process_folder(youtube, effective_master_folder, playlist_id, subfolder_name=None, summary=summary)
        # Daily summary output
        uploaded_mb = summary["uploaded_bytes"] / (1024 * 1024)
        print("\n📊 === Daily Upload Summary ===")
        print(f"Uploaded videos: {summary['uploaded_count']} | Total size: {uploaded_mb:.2f} MB")
        if summary["upload_failures"]:
            print("\n❌ Videos failed to upload:")
            for p in summary["upload_failures"]:
                print(f" - {p}")
        if summary["caption_failures"]:
            print("\n❌ Captions failed to upload:")
            for p in summary["caption_failures"]:
                print(f" - {p}")
        if summary["playlist_failures"]:
            print("\n⚠️ Videos not added to playlist:")
            for p in summary["playlist_failures"]:
                print(f" - {p}")
        print("============================\n")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        print("Progress has been saved. You can run the script again to continue.")

    finally:
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()