# AudioShake Smart Mute

A command-line tool that automatically detects and removes music from WAV audio files using the AudioShake API.

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

## Usage

The tool provides a simple command-line interface to process WAV files:

```bash
python smart_mute.py <wav_path> <api_token> [--base_url BASE_URL]
```

### Arguments

- `wav_path`: Path to the input WAV file
- `api_token`: Your AudioShake API token
- `--base_url`: (Optional) Override the AudioShake API base URL

### Example

```bash
python smart_mute.py input.wav YOUR_API_TOKEN
```

### Batch processing (recursive, 5 parallel jobs)

Process every `.wav` under a directory tree with up to five files handled concurrently:

```bash
API_TOKEN="YOUR_TOKEN"
ROOT="/path/to/wav/root"

find "$ROOT" -type f -iname '*.wav' -print0 \
  | xargs -0 -n1 -P 5 -I{} python smart_mute.py "{}" "$API_TOKEN"
```

The processed file will be saved in the same directory as the input file with `_smart_mute` appended to the filename. For example, if your input file is `input.wav`, the output will be `input_smart_mute.wav`.

### Requirements

- Python 3.6 or higher
- WAV audio files
- AudioShake API token

## How It Works

1. The tool first detects music segments in the input WAV file
2. For each detected music segment:
   - Extracts the segment
   - Processes it to remove music
   - Replaces the original segment with the processed version
3. Saves the final result as a new WAV file

## Error Handling

The tool will:
- Validate that the input file exists and is a WAV file
- Clean up temporary files even if an error occurs
- Provide detailed error messages if something goes wrong

## Notes

- Only WAV files are supported
- The API token must be valid and have sufficient permissions
- Processing time depends on the length of the audio file and the number of music segments 