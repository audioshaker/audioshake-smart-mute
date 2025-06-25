import json
import os
import soundfile as sf
import numpy as np
from api import AudioShakeClient
from pathlib import Path
import shutil
import argparse
import sys
import traceback
import tempfile
import subprocess

def _convert_to_wav(input_path: str, temp_dir: str) -> str:
    """
    Convert audio/video file to WAV format temporarily using ffmpeg.
    
    Parameters
    ----------
    input_path : str
        Path to the input file
    temp_dir : str
        Temporary directory to store the converted WAV file
        
    Returns
    -------
    str
        Path to the temporary WAV file
    """
    input_path = Path(input_path)
    supported_formats = {'.wav', '.mp3', '.m4a', '.mp4', '.mov'}
    
    if input_path.suffix.lower() not in supported_formats:
        raise ValueError(f"Unsupported file format: {input_path.suffix}. Supported formats: {', '.join(supported_formats)}")
    
    # If already WAV, just return the original path
    if input_path.suffix.lower() == '.wav':
        return str(input_path)
    
    # Convert to WAV using ffmpeg
    temp_wav_path = os.path.join(temp_dir, f"{input_path.stem}_temp.wav")
    
    try:
        # Use ffmpeg to convert to WAV
        cmd = [
            'ffmpeg', 
            '-i', str(input_path),
            '-acodec', 'pcm_s16le',  # 16-bit PCM
            '-ar', '44100',          # 44.1kHz sample rate
            '-ac', '2',              # Stereo
            '-y',                    # Overwrite output file
            temp_wav_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)
            
        return temp_wav_path
    except FileNotFoundError:
        raise ValueError("ffmpeg not found. Please install ffmpeg to convert audio/video files.")
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Failed to convert {input_path} to WAV using ffmpeg: {e.stderr}")
    except Exception as e:
        raise ValueError(f"Failed to convert {input_path} to WAV: {str(e)}")

def smart_mute(file_path: str, api_token: str, base_url: str = "https://groovy.audioshake.ai") -> str:
    """
    Detects music segments in the given audio/video file, removes the music, and re‑assembles the audio.
    The processed file is written next to the original with ``_smart_mute`` appended to the stem.
    The function returns the path to the new file.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the input file (supports .wav, .mp3, .m4a, .mp4, .mov).
    api_token : str
        AudioShake API token.
    base_url : str, optional
        Alternate base URL for the AudioShake service.

    Raises
    ------
    FileNotFoundError
        If *file_path* does not exist.
    ValueError
        If the input format is not supported.
    Exception
        Propagates any exception raised by the AudioShake client.
    """

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")

    # Initialise AudioShake client
    client = AudioShakeClient(api_token, base_url=base_url)

    music_detect_meta = {"name": "music_detection", "format": "json"}

    # Temporary workspace
    temp_dir = tempfile.mkdtemp(prefix="smart_mute_")
    try:
        # Convert input file to WAV if necessary
        wav_path = _convert_to_wav(str(path), temp_dir)

        # 1. Detect music regions
        detect_result = client.process_job(
            file_path=wav_path,
            metadata=music_detect_meta,
            output_dir=temp_dir,
        )
        with open(detect_result["output_path"], "r") as fp:
            events = json.load(fp)

        # 2. Read original audio (read‑only copy)
        original_audio, sr = sf.read(wav_path)
        processed_audio = np.copy(original_audio)

        # 3. For each detected region, remove music
        for i, ev in enumerate(events):
            start_smp = int(ev["start_time"] * sr)
            end_smp = int(ev["end_time"] * sr)

            # Write slice to temp file
            slice_path = os.path.join(temp_dir, f"slice_{i:03d}.wav")
            sf.write(slice_path, processed_audio[start_smp:end_smp], sr)

            # Run music‑removal on slice
            remove_result = client.process_job(
                file_path=slice_path,
                metadata={"name": "music_removal", "format": "wav"},
                output_dir=temp_dir,
            )
            stripped_audio, _ = sf.read(remove_result["output_path"])

            # Replace region, padding/truncating if lengths differ
            target_len = end_smp - start_smp
            if stripped_audio.shape[0] != target_len:
                min_len = min(stripped_audio.shape[0], target_len)
                processed_audio[start_smp:start_smp + min_len] = stripped_audio[:min_len]
                if min_len < target_len:
                    processed_audio[start_smp + min_len:end_smp] = 0
            else:
                processed_audio[start_smp:end_smp] = stripped_audio

        # 4. Save the re‑assembled file next to original (always as WAV)
        output_path = path.with_stem(f"{path.stem}_smart_mute").with_suffix('.wav')
        sf.write(str(output_path), processed_audio, sr)

        return str(output_path)

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


# CLI entry point
if __name__ == "__main__":
    """
    Quick CLI wrapper so you can run:
        python smart_mute.py /path/to/file.wav [YOUR_API_TOKEN]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Remove music from audio/video files using AudioShake.")
    parser.add_argument("file_path", help="Path to the input file (supports .wav, .mp3, .m4a, .mp4, .mov)")
    parser.add_argument("api_token", nargs="?", help="AudioShake API token (optional if AUDIOSHAKE_TOKEN env var is set)")
    parser.add_argument(
        "--base_url",
        default="https://groovy.audioshake.ai",
        help="Override the AudioShake base URL if needed",
    )
    args = parser.parse_args()

    # Get API token from command line argument or environment variable
    api_token = args.api_token or os.getenv('AUDIOSHAKE_TOKEN')
    if not api_token:
        print("❌  Error: API token is required. Provide it as an argument or set AUDIOSHAKE_TOKEN environment variable.", file=sys.stderr)
        sys.exit(1)

    try:
        output = smart_mute(args.file_path, api_token=api_token, base_url=args.base_url)
        print(f"✅  Process complete. Output written to: {output}")
    except Exception as exc:
        print("❌  An error occurred while processing:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
