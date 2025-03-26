import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Define constants
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = "client_secrets.json"  # Replace with your OAuth 2.0 credentials file
MASTER_FOLDER = "path/to/your/master/folder"  # Replace with your master folder path

# Step 1: Authenticate
def get_authenticated_service():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=0)
    return build("youtube", "v3", credentials=credentials)

# Step 2: Check if playlist exists, create if not, and return its ID
def get_or_create_playlist(youtube, playlist_name):
    # Search for existing playlist
    playlists = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for playlist in playlists.get("items", []):
        if playlist["snippet"]["title"] == playlist_name:
            return playlist["id"]
    
    # Create new playlist if not found
    request_body = {
        "snippet": {
            "title": playlist_name,
            "description": f"Playlist for videos in {playlist_name}"
        },
        "status": {"privacyStatus": "private"}  # Adjust as needed
    }
    response = youtube.playlists().insert(part="snippet,status", body=request_body).execute()
    return response["id"]

# Step 3: Upload video and return its ID
def upload_video(youtube, file_path):
    request_body = {
        "snippet": {
            "title": os.path.basename(file_path),
            "description": "Uploaded automatically via script",
            "tags": ["auto-upload", "playlist"],
            "categoryId": "22"  # People & Blogs (adjust as needed)
        },
        "status": {"privacyStatus": "private"}  # Adjust as needed
    }
    media = MediaFileUpload(file_path)
    response = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    ).execute()
    return response["id"]

# Step 4: Upload SRT captions if available
def upload_captions(youtube, video_id, srt_path):
    media = MediaFileUpload(srt_path)
    youtube.captions().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "language": "en",  # Adjust language code as needed
                "name": "Subtitles",
                "isDraft": False
            }
        },
        media_body=media
    ).execute()

# Step 5: Add video to playlist
def add_video_to_playlist(youtube, video_id, playlist_id):
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

# Step 6: Process a folder (master or subfolder)
def process_folder(youtube, folder_path, playlist_id):
    mp4_files = [f for f in os.listdir(folder_path) if f.endswith(".mp4")]
    srt_files = [f for f in os.listdir(folder_path) if f.endswith(".srt")]

    for mp4_file in mp4_files:
        mp4_path = os.path.join(folder_path, mp4_file)
        mp4_basename = os.path.splitext(mp4_file)[0]

        print(f"Uploading {mp4_file}...")
        video_id = upload_video(youtube, mp4_path)
        print(f"Uploaded video with ID: {video_id}")

        # Look for matching SRT file
        matching_srt = None
        for srt_file in srt_files:
            if mp4_basename in srt_file:  # Match if MP4 basename is in SRT filename
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
        # Process each subfolder
        for subfolder in subfolders:
            subfolder_path = os.path.join(MASTER_FOLDER, subfolder)
            print(f"Processing subfolder: {subfolder}")
            process_folder(youtube, subfolder_path, playlist_id)
    else:
        # Process master folder directly
        print(f"No subfolders found. Processing master folder: {master_folder_name}")
        process_folder(youtube, MASTER_FOLDER, playlist_id)

if __name__ == "__main__":
    main()