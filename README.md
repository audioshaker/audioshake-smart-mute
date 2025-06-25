# AudioShake Smart Mute

A command-line tool that automatically detects and removes music from audio and video files using the AudioShake API. Supports WAV, MP3, M4A, MP4, and MOV formats.

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd audioshake-smart-mute
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

**Note:** This tool requires `ffmpeg` to be installed on your system for audio/video format conversion. Install it:
- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt update && sudo apt install ffmpeg`
- **Windows**: Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)

## Usage

The tool provides a simple command-line interface to process audio and video files:

```bash
python smart_mute.py <file_path> [api_token] [--base_url BASE_URL]
```

### Arguments

- `file_path`: Path to the input file (supports .wav, .mp3, .m4a, .mp4, .mov)
- `api_token`: (Optional) Your AudioShake API token - if not provided, uses `AUDIOSHAKE_TOKEN` environment variable
- `--base_url`: (Optional) Override the AudioShake API base URL

### Examples

```bash
# Process a WAV file with API token as argument
python smart_mute.py input.wav YOUR_API_TOKEN

# Process an MP3 file using environment variable
export AUDIOSHAKE_TOKEN="YOUR_API_TOKEN"
python smart_mute.py song.mp3

# Process a video file (MP4/MOV)
python smart_mute.py video.mp4 YOUR_API_TOKEN
```

### Batch processing (recursive, 5 parallel jobs)

Process every supported audio/video file under a directory tree with up to five files handled concurrently:

```bash
# Option 1: Using environment variable (recommended for batch processing)
export AUDIOSHAKE_TOKEN="YOUR_TOKEN"
ROOT="/path/to/media/root"

find "$ROOT" -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.mp4' -o -iname '*.mov' \) -print0 \
  | xargs -0 -n1 -P 5 -I{} python smart_mute.py "{}"

# Option 2: Using command line argument
API_TOKEN="YOUR_TOKEN"
ROOT="/path/to/media/root"

find "$ROOT" -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.mp4' -o -iname '*.mov' \) -print0 \
  | xargs -0 -n1 -P 5 -I{} python smart_mute.py "{}" "$API_TOKEN"
```

The processed file will be saved in the same directory as the input file with `_smart_mute` appended to the filename and converted to WAV format. For example:
- `input.wav` → `input_smart_mute.wav`
- `song.mp3` → `song_smart_mute.wav`
- `video.mp4` → `video_smart_mute.wav`

### Requirements

- Python 3.6 or higher
- ffmpeg (for audio/video format conversion)
- Supported file formats: WAV, MP3, M4A, MP4, MOV
- AudioShake API token

## How It Works

1. If the input file is not WAV format, it's temporarily converted to WAV using ffmpeg
2. The tool detects music segments in the (converted) WAV file
3. For each detected music segment:
   - Extracts the segment
   - Processes it to remove music
   - Replaces the original segment with the processed version
4. Saves the final result as a new WAV file
5. Temporary files are automatically cleaned up

## Error Handling

The tool will:
- Validate that the input file exists and is in a supported format
- Clean up temporary files even if an error occurs
- Provide detailed error messages if something goes wrong
- Handle format conversion errors gracefully

## Notes

- Supported formats: WAV, MP3, M4A, MP4, MOV
- The API token must be valid and have sufficient permissions
- Processing time depends on the length of the audio file and the number of music segments
- All output files are saved in WAV format regardless of input format
- Requires ffmpeg to be installed for non-WAV input files 