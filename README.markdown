# YouTube Uploader Script

## Overview

This Python script (`grok.py`) automates uploading videos to YouTube, organizing them into a playlist, and managing upload progress to avoid duplicates. It uses the YouTube Data API to authenticate, upload videos, add them to a playlist, and optionally upload captions (SRT files). The script tracks progress by pre-fetching all uploaded videos in current playlist, ensuring it resumes from where it left off, even after interruptions like quota limits.

### Features

- Uploads videos from a specified folder (and its subfolders) to YouTube.
- Adds uploaded videos to a designated playlist.
- Supports subfolder organization - processes videos in subfolders sequentially.
- Prefixes video titles with subfolder names for better organization and uniqueness.
- Supports uploading captions (SRT files) for videos.
- Avoids duplicate uploads by checking the playlist and local log.
- Uploads videos in numerical order for consistent sequencing.
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

   - You can pass the master folder via CLI (recommended) or edit constants:
     - CLI override examples:
       - Positional: `python grok.py "E:\\courses\\React"`
       - Flag: `python grok.py --master "E:\\courses\\React"`
       - Precedence: `--master` flag > positional argument > default `MASTER_FOLDER` in code.
     - If editing code, update:
       - `MASTER_FOLDER`: Path to your video folder (e.g., `r"E:\\khóa học\\NodeJS\\Some Courses"`).
       - `CLIENT_SECRETS_FILE`: Path to your `client_secret.json` file (default: `r"client_secret.json"`).
       - `TOKEN_FILE`: Path to the OAuth token file (default: `r"token.pickle"`).

3. **Prepare Your Video Folder**:

   - **Option 1 - With Subfolders**: Organize videos into subfolders within the master folder (e.g., "Section 1", "Section 2"). The script will process each subfolder sequentially, and video titles will be prefixed with "SubfolderName - VideoTitle".
   - **Option 2 - No Subfolders**: Place all videos directly in the master folder. Videos will be uploaded without subfolder prefixes.
   - Ensure all videos are in MP4 format and named sequentially (e.g., "01.mp4", "02.mp4", etc.).
   - Optionally, include SRT files for captions with matching names (e.g., "01.srt").

## Usage

1. **Run the Script**:

   - Open a terminal in the script's directory and run:

    ```
    # Use default path set in code
    python grok.py

    # Override master folder with positional arg
    python grok.py "E:\\courses\\React"

    # Override master folder with flag (takes precedence over positional)
    python grok.py --master "E:\\courses\\React"
    ```

   - On the first run, the script will prompt you to authenticate via a browser. Follow the link, sign in with your Google account, and authorize the app. The token will be saved to `token.pickle` for future runs.

2. **What the Script Does**:

   - Authenticates with the YouTube API using your credentials.
   - Checks for an existing playlist named after the master folder or creates one if it doesn't exist.
   - If subfolders exist, processes each subfolder in order:
     - Scans the subfolder for MP4 files and compares them with the playlist to avoid duplicates.
     - Uploads remaining videos in numerical order with titles prefixed by subfolder name.
     - Adds uploaded videos to the playlist.
   - If no subfolders exist, processes the master folder directly without title prefixes.
   - Optionally uploads matching SRT captions.

3. **Monitor Progress**:

   - The script prints progress messages, such as:

     ```
     Starting to process subfolder: Section 1
     Pending videos to upload: ['01.mp4', '02.mp4', ...]
     Processing video: 01.mp4
     File size: 45.32 MB
     Attempt 1/3: Uploading...
     ```

4. **Handle Interruptions**:

   - If the script stops (e.g., due to quota limits), rerun the script in the next 24h to resume from the last uploaded video. The script automatically skips videos already in the playlist.

## Troubleshooting


- **Quota Limits**:

  - YouTube typically allows 6-10 uploads per day for new accounts. If you hit the limit, the script will save progress and exit. Rerun after the quota resets (midnight Pacific Time).

- **Authentication Issues**:

  - If authentication fails, delete `token.pickle` and rerun to re-authenticate.

- **Videos Not Added to Playlist**:

   - Ensure the playlist name matches the master folder name. The main reason videos are uploaded but not in the playlist is the upload limit has been exceeded, causing the process of adding to the playlist to be interrupted. Manually delete the video or manually add it to a playlist.

## Notes

- The script processes subfolders sequentially in numerical order.
- When subfolders exist, video titles are automatically prefixed with the subfolder name (e.g., "Section 1 - 01.mp4" becomes "Section 1 - 01").
- Video descriptions include the parent directory (section) name for reference.
- API quota usage includes fetching playlist videos (\~1 unit per 50 items). For large playlists, this may consume more quota.
- Videos are uploaded with the "Science & Technology" category (ID: 28) and marked as private by default.

## License

This script is provided as-is for personal use. Ensure compliance with YouTube's Terms of Service and API usage policies.