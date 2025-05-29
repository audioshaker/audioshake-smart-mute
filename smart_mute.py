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

def smart_mute(file_path: str, api_token: str, base_url: str = "https://groovy.audioshake.ai") -> str:
    """
    Detects music segments in the given WAV file, removes the music, and re‑assembles the audio.
    The processed file is written next to the original with ``_smart_mute`` appended to the stem.
    The function returns the path to the new file.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the input .wav file.
    api_token : str
        AudioShake API token.
    base_url : str, optional
        Alternate base URL for the AudioShake service.

    Raises
    ------
    FileNotFoundError
        If *file_path* does not exist.
    ValueError
        If the input is not a ``.wav`` file.
    Exception
        Propagates any exception raised by the AudioShake client.
    """
    import tempfile

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    if path.suffix.lower() != ".wav":
        raise ValueError("smart_mute only supports .wav input")

    # Initialise AudioShake client
    client = AudioShakeClient(api_token, base_url=base_url)

    music_detect_meta = {"name": "music_detection", "format": "json"}

    # Temporary workspace
    temp_dir = tempfile.mkdtemp(prefix="smart_mute_")
    try:
        # 1. Detect music regions
        detect_result = client.process_job(
            file_path=str(path),
            metadata=music_detect_meta,
            output_dir=temp_dir,
        )
        with open(detect_result["output_path"], "r") as fp:
            events = json.load(fp)

        # 2. Read original audio (read‑only copy)
        original_audio, sr = sf.read(str(path))
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

        # 4. Save the re‑assembled file next to original
        output_path = path.with_stem(f"{path.stem}_smart_mute")
        sf.write(str(output_path), processed_audio, sr)

        return str(output_path)

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


# CLI entry point
if __name__ == "__main__":
    """
    Quick CLI wrapper so you can run:
        python main.py /path/to/file.wav YOUR_API_TOKEN
    """
    import argparse

    parser = argparse.ArgumentParser(description="Remove music from a WAV file using AudioShake.")
    parser.add_argument("wav_path", help="Path to the input .wav file")
    parser.add_argument("api_token", help="AudioShake API token")
    parser.add_argument(
        "--base_url",
        default="https://groovy.audioshake.ai",
        help="Override the AudioShake base URL if needed",
    )
    args = parser.parse_args()

    try:
        output = smart_mute(args.wav_path, api_token=args.api_token, base_url=args.base_url)
        print(f"✅  Process complete. Output written to: {output}")
    except Exception as exc:
        print("❌  An error occurred while processing:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
