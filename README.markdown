# YouTube Uploader Script

## Overview

This Python script (`grok.py`) automates uploading videos to YouTube, organizing them into a playlist, and managing upload progress to avoid duplicates. It uses the YouTube Data API to authenticate, upload videos, add them to a playlist, and optionally upload captions (SRT files). The script tracks progress in a JSON log file (`upload_log.json`), ensuring it resumes from where it left off, even after interruptions like quota limits.

### Features

- Uploads videos from a specified folder to YouTube.
- Adds uploaded videos to a designated playlist.
- Supports uploading captions (SRT files) for videos.
- Avoids duplicate uploads by checking the playlist and local log.
- Uploads videos in alphabetical order for consistent sequencing.
- Handles YouTube API quota limits with retry logic and progress saving.
- Robust error handling for network issues, invalid JSON, and API errors.

## Prerequisites

- **Python 3.x**: Ensure Python is installed on your system.

- **Required Libraries**: Install the necessary Python packages using pip:

  ```
  pip install google-auth-oauthlib google-api-python-client requests httplib2
  ```

- **YouTube API Credentials**:

  - Create a project in the Google Cloud Console.
  - Enable the YouTube Data API v3.
  - Create OAuth 2.0 credentials and download the `client_secret.json` file.
  - Place `client_secret.json` in the same directory as `grok.py`.

- **Video Files**: Ensure your videos are in MP4 format, located in the folder specified by `MASTER_FOLDER`.

## Setup

1. **Clone or Download the Script**:

   - Download `grok.py` and place it in your working directory.

2. **Configure the Script**:

   - Open `grok.py` and update the following constants if needed:
     - `MASTER_FOLDER`: Path to your video folder (e.g., `r"E:\khóa học\NodeJS\Some Courses"`).
     - `CLIENT_SECRETS_FILE`: Path to your `client_secret.json` file (default: `r"client_secret.json"`).
     - `UPLOAD_LOG_FILE`: Path to the log file (default: `r"upload_log.json"`).
     - `TOKEN_FILE`: Path to the OAuth token file (default: `r"token.pickle"`).

3. **Prepare Your Video Folder**:

   - Ensure all videos are in MP4 format and named sequentially (e.g., "Bản sao của 01", "Bản sao của 02", etc.).
   - Optionally, include SRT files for captions with matching names (e.g., "Bản sao của 01.srt").

## Usage

1. **Run the Script**:

   - Open a terminal in the script’s directory and run:

     ```
     python grok.py
     ```

   - On the first run, the script will prompt you to authenticate via a browser. Follow the link, sign in with your Google account, and authorize the app. The token will be saved to `token.pickle` for future runs.

2. **What the Script Does**:

   - Authenticates with the YouTube API using your credentials.
   - Checks for an existing playlist named after the master folder or creates one if it doesn’t exist.
   - Scans the local folder for MP4 files and compares them with the playlist to avoid duplicates.
   - Uploads remaining videos in alphabetical order, adding them to the playlist.
   - Optionally uploads matching SRT captions.
   - Updates `upload_log.json` with uploaded and pending videos.

3. **Monitor Progress**:

   - The script prints progress messages, such as:

     ```
     Fetching uploaded videos and playlist videos...
     Updated pending_videos: ['Bản sao của 18.mp4', ...]
     Processing video: Bản sao của 18.mp4 (74 remaining)
     ```

   - Check `upload_log.json` to see the current state:

     - `uploaded_videos`: Videos already uploaded and in the playlist.
     - `pending_videos`: Videos remaining to be uploaded.

4. **Handle Interruptions**:

   - If the script stops (e.g., due to quota limits), progress is saved in `upload_log.json`. Rerun the script to resume from the last uploaded video.

## Example `upload_log.json`

```json
{
    "Full NodeJS Course": {
        "playlist_id": "PLZR5pKIruVjHaEde59o-Oc0kJXlWYF37c",
        "uploaded_videos": {
            "Bản sao của 01.mp4": "ifszWddKSuo",
            "Bản sao của 02.mp4": "7k4fVSiJodg",
            ...
            "Bản sao của 17.mp4": "NJx0p8daH-o"
        },
        "pending_videos": [
            "Bản sao của 18.mp4",
            "Bản sao của 19.mp4",
            ...
            "Bản sao của 91.mp4"
        ]
    }
}
```

## Troubleshooting

- **JSON Parsing Error**:

  - If you see `Invalid JSON in upload_log.json: Expecting value: line 1 column 1 (char 0)`, the log file might be empty or corrupted. The script now handles this by initializing an empty dictionary.
  - Delete `upload_log.json` and rerun to start fresh, but note that you’ll need to manually update it if videos were already uploaded.

- **Duplicate Uploads**:

  - If duplicates occur, ensure video titles in YouTube match local filenames (without ".mp4"). The script now uploads videos with titles excluding the ".mp4" extension for consistency.
  - Check `upload_log.json` to verify `uploaded_videos` matches your playlist.

- **Quota Limits**:

  - YouTube typically allows 6-10 uploads per day for new accounts. If you hit the limit, the script will save progress and exit. Rerun after the quota resets (midnight Pacific Time).

- **Authentication Issues**:

  - If authentication fails, delete `token.pickle` and rerun to re-authenticate.

- **Videos Not Added to Playlist**:

  - Ensure the playlist name matches the master folder name. If videos are uploaded but not in the playlist, they’ll be deleted on the next run to prevent duplicates.

## Notes

- The script assumes video filenames are unique and sequential (e.g., "Bản sao của 01.mp4"). If filenames don’t match playlist titles, you may need to manually edit `upload_log.json` or adjust the script.
- API quota usage includes fetching playlist videos (\~1 unit per 50 items). For large playlists, this may consume more quota.

## License

This script is provided as-is for personal use. Ensure compliance with YouTube’s Terms of Service and API usage policies.