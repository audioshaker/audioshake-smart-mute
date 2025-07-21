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
        print(f"    ✅ File is already WAV format: {input_path}")
        return str(input_path)
    
    # Convert to WAV using ffmpeg
    temp_wav_path = os.path.join(temp_dir, f"{input_path.stem}_temp.wav")
    print(f"    🔄 Converting {input_path.suffix} to WAV...")
    
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
        
        print(f"    ⚙️  Running ffmpeg command...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    ❌ ffmpeg conversion failed: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)
        
        print(f"    ✅ Conversion completed: {temp_wav_path}")
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

    print(f"🎵 Starting Smart Mute processing for: {file_path}")
    
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")

    # Check file size before processing
    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"📁 Input file size: {file_size_mb:0.2} MB")

    # Initialise AudioShake client
    print("🔧 Initializing AudioShake client...")
    client = AudioShakeClient(api_token, base_url=base_url)

    # Validate API connection before processing
    print("🔍 Validating AudioShake API connection...")
    try:
        client.validate_connection()
        print("✅ API connection validated successfully")
    except Exception as e:
        print(f"❌ API validation failed: {str(e)}")
        raise

    music_detect_meta = {"name": "music_detection", "format": "json"}

    # Temporary workspace
    print("📁 Creating temporary workspace...")
    temp_dir = tempfile.mkdtemp(prefix="smart_mute_")
    print(f"✅ Temporary directory created: {temp_dir}")
    
    try:
        # Convert input file to WAV if necessary
        print("🔄 Converting input file to WAV format...")
        wav_path = _convert_to_wav(str(path), temp_dir)
        print(f"✅ File converted to WAV: {wav_path}")

        # 1. Detect music regions
        print("\n🎼 STEP 1: Detecting music regions...")
        print(f"📤 Sending music detection job for: {wav_path}")
        detect_result = client.process_job(
            file_path=wav_path,
            metadata=music_detect_meta,
            output_dir=temp_dir,
        )
        print(f"✅ Music detection completed. Output: {detect_result['output_path']}")
        
        with open(detect_result["output_path"], "r") as fp:
            events = json.load(fp)
        print(f"📊 Found {len(events)} music segments to process")

        # 2. Read original audio (read‑only copy)
        print("\n📖 STEP 2: Loading original audio...")
        original_audio, sr = sf.read(wav_path)
        processed_audio = np.copy(original_audio)
        print(f"✅ Audio loaded: {len(original_audio)} samples at {sr}Hz ({len(original_audio)/sr:.2f}s duration)")

        # 3. For each detected region, remove music
        print(f"\n🎵 STEP 3: Processing {len(events)} music segments...")
        for i, ev in enumerate(events):
            start_time = ev["start_time"]
            end_time = ev["end_time"]
            duration = end_time - start_time
            
            print(f"\n  🎵 Processing segment {i+1}/{len(events)}: {start_time:.2f}s - {end_time:.2f}s (duration: {duration:.2f}s)")
            
            start_smp = int(start_time * sr)
            end_smp = int(end_time * sr)

            # Write slice to temp file
            slice_path = os.path.join(temp_dir, f"slice_{i:03d}.wav")
            print(f"    📁 Creating slice file: {slice_path}")
            sf.write(slice_path, processed_audio[start_smp:end_smp], sr)

            # Run music‑removal on slice
            print(f"    🎼 Removing music from segment {i+1}...")
            remove_result = client.process_job(
                file_path=slice_path,
                metadata={"name": "music_removal", "format": "wav"},
                output_dir=temp_dir,
            )
            print(f"    ✅ Music removal completed for segment {i+1}")
            
            stripped_audio, _ = sf.read(remove_result["output_path"])
            print(f"    📊 Stripped audio: {len(stripped_audio)} samples")

            # Replace region, padding/truncating if lengths differ
            target_len = end_smp - start_smp
            if stripped_audio.shape[0] != target_len:
                min_len = min(stripped_audio.shape[0], target_len)
                print(f"    ⚠️  Length mismatch: target={target_len}, actual={stripped_audio.shape[0]}, using {min_len}")
                processed_audio[start_smp:start_smp + min_len] = stripped_audio[:min_len]
                if min_len < target_len:
                    processed_audio[start_smp + min_len:end_smp] = 0
                    print(f"    🔇 Padding remaining {target_len - min_len} samples with silence")
            else:
                processed_audio[start_smp:end_smp] = stripped_audio
                print(f"    ✅ Segment {i+1} replaced successfully")

        # 4. Save the re‑assembled file next to original (always as WAV)
        print(f"\n💾 STEP 4: Saving final output...")
        output_path = path.with_stem(f"{path.stem}_smart_mute").with_suffix('.wav')
        print(f"📁 Writing output to: {output_path}")
        sf.write(str(output_path), processed_audio, sr)
        print(f"✅ Smart mute processing completed successfully!")
        print(f"🎉 Output saved to: {output_path}")

        return str(output_path)

    finally:
        # Clean up temporary directory
        print(f"\n🧹 Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"✅ Temporary files cleaned up")


# CLI entry point
if __name__ == "__main__":
    """
    Quick CLI wrapper so you can run:
        python smart_mute.py /path/to/file.wav [YOUR_API_TOKEN]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Remove music from audio/video files using AudioShake.")
    parser.add_argument("file_path", help="Path to the input file or directory (supports .wav, .mp3, .m4a, .mp4, .mov, or a directory containing them)")
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

    SUPPORTED_EXTS = {'.wav', '.mp3', '.m4a', '.mp4', '.mov'}

    input_path = Path(args.file_path).expanduser().resolve()
    if input_path.is_dir():
        # Directory mode: process all supported files in the directory (non-recursive)
        files = [f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS]
        if not files:
            print(f"❌  No supported audio/video files found in directory: {input_path}", file=sys.stderr)
            sys.exit(1)
        print(f"🔎 Found {len(files)} supported files in directory: {input_path}")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_file = {executor.submit(smart_mute, str(f), api_token, args.base_url): f for f in files}
            for future in as_completed(future_to_file):
                f = future_to_file[future]
                try:
                    output = future.result()
                    print(f"✅  Process complete. Output written to: {output}")
                    results.append((f, output))
                except Exception as exc:
                    print(f"❌  Error processing {f}: {exc}", file=sys.stderr)
                    errors.append((f, exc))
        print(f"\n🎉 Finished processing directory. {len(results)} succeeded, {len(errors)} failed.")
        if errors:
            print("Failed files:")
            for f, exc in errors:
                print(f"  {f}: {exc}")
        sys.exit(0 if not errors else 1)
    else:
        # Single file mode (existing behavior)
        try:
            output = smart_mute(str(input_path), api_token=api_token, base_url=args.base_url)
            print(f"✅  Process complete. Output written to: {output}")
        except Exception as exc:
            print("❌  An error occurred while processing:", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
