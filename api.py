import os
import time
import requests
import concurrent.futures
from typing import List, Dict
from pathlib import Path


class AudioShakeClient:
    def __init__(self, token: str, base_url: str = "https://groovy.audioshake.ai"):
        self.token = token
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }

    def validate_connection(self) -> bool:
        """Validate that the API token is valid and the service is accessible."""
        try:
            # Try to access a simple endpoint to validate the token
            url = f"{self.base_url}/job/"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 401:
                raise RuntimeError("Invalid API token - authentication failed")
            elif resp.status_code == 403:
                raise RuntimeError("API token lacks required permissions")
            elif resp.status_code >= 500:
                raise RuntimeError("AudioShake service is currently unavailable")
            return True
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot connect to AudioShake API at {self.base_url}")
        except requests.exceptions.Timeout:
            raise RuntimeError("Connection to AudioShake API timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to validate connection: {str(e)}")

    # ---------- Core API helpers ----------

    def upload_file(self, file_path: str) -> dict:
        # Validate file exists and is readable
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_size = os.path.getsize(file_path)
        print(f"📁 File size: {file_size / (1024*1024):.2f} MB")
        
        # Check if file is too large (AudioShake might have limits)
        if file_size > 500 * 1024 * 1024:  # 500MB limit
            print("⚠️  Warning: File is larger than 500MB, which might cause issues")
        
        url = f"{self.base_url}/upload/"
        try:
            with open(file_path, "rb") as f:
                files = {"file": f}
                print(f"📤 Uploading to: {url}")
                resp = requests.post(url, headers=self.headers, files=files, timeout=300)  # 5 minute timeout
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Upload timed out for file: {file_path}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Upload failed for file {file_path}: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error during upload: {str(e)}")

    def create_job(self, asset_id: str, metadata: dict, callback_url: str = None) -> dict:
        url = f"{self.base_url}/job/"
        payload = {"assetId": asset_id, "metadata": metadata}
        if callback_url:
            payload["callbackUrl"] = callback_url
        resp = requests.post(
            url,
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload
        )
        resp.raise_for_status()
        return resp.json()["job"]

    def get_job(self, job_id: str) -> dict:
        url = f"{self.base_url}/job/{job_id}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def download_asset(self, link: str, destination_path: str) -> None:
        resp = requests.get(link, stream=True)
        resp.raise_for_status()
        with open(destination_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

    # ---------- One-off job ----------

    def process_job(
        self,
        file_path: str,
        metadata: dict,
        callback_url: str = None,
        poll_interval: int = 5,
        timeout: int = 3600,
        output_dir: str = "."
    ) -> dict:
        print(f"📤 Uploading file: {file_path}")
        asset = self.upload_file(file_path)
        print(f"✅ File uploaded successfully. Asset ID: {asset['id']}")
        
        print(f"🚀 Creating job with metadata: {metadata}")
        job = self.create_job(asset["id"], metadata, callback_url)
        job_id = job["id"]
        print(f"✅ Job created successfully. Job ID: {job_id}")
        
        start = time.time()

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Get base name of input file
        input_base_name = Path(file_path).stem
        output_paths = []

        while True:
            job_info = self.get_job(job_id)["job"]
            status = job_info["status"]
            print(f"📊 Job {job_id} status: {status}")

            if status == "completed":
                print(f"✅ Job {job_id} completed successfully!")
                for a in job_info.get("outputAssets", []):
                    if a.get("link"):
                        # Get model name from metadata or use default
                        model_name = metadata.get("name", "output")
                        # Get format extension from asset name or default to wav
                        format_ext = Path(a.get("name", "output.wav")).suffix[1:] or "wav"
                        # Construct output filename
                        output_filename = f"{input_base_name}_{model_name}.{format_ext}"
                        output_path = os.path.join(output_dir, output_filename)
                        print(f"📥 Downloading output to: {output_path}")
                        self.download_asset(a["link"], output_path)
                        output_paths.append(output_path)
                # Add output path information to the return value
                if len(output_paths) == 1:
                    job_info["output_path"] = output_paths[0]
                else:
                    job_info["output_paths"] = output_paths
                return job_info

            if status in ("failed", "error"):
                # Get more detailed error information
                error_details = job_info.get("error", "No error details available")
                error_message = job_info.get("errorMessage", "No error message available")
                print(f"❌ Job {job_id} failed with status: {status}")
                print(f"❌ Error details: {error_details}")
                print(f"❌ Error message: {error_message}")
                raise RuntimeError(f"Job {job_id} failed: {status}. Details: {error_details}. Message: {error_message}")

            if time.time() - start > timeout:
                raise TimeoutError(f"Job {job_id} timed out after {timeout}s")

            time.sleep(poll_interval)

    # ---------- Multi-stem workflow (no post-processing) ----------

    def _process_single_job_no_upload(
        self,
        asset_id: str,
        metadata: dict,
        callback_url: str,
        poll_interval: int,
        timeout: int,
        output_dir: str,
        input_base_name: str
    ) -> dict:
        job = self.create_job(asset_id, metadata, callback_url)
        job_id = job["id"]
        start = time.time()
        output_paths = []

        while True:
            job_info = self.get_job(job_id)["job"]
            status = job_info["status"]

            if status == "completed":
                for a in job_info.get("outputAssets", []):
                    if a.get("link"):
                        # Get model name from metadata or use default
                        model_name = metadata.get("name", "output")
                        # Get format extension from asset name or default to wav
                        format_ext = Path(a.get("name", "output.wav")).suffix[1:] or "wav"
                        # Construct output filename
                        output_filename = f"{input_base_name}_{model_name}.{format_ext}"
                        output_path = os.path.join(output_dir, output_filename)
                        self.download_asset(a["link"], output_path)
                        output_paths.append(output_path)
                # Add output path information to the return value
                if len(output_paths) == 1:
                    job_info["output_path"] = output_paths[0]
                else:
                    job_info["output_paths"] = output_paths
                return job_info

            if status in ("failed", "error"):
                raise RuntimeError(f"Job {job_id} failed: {status}")

            if time.time() - start > timeout:
                raise TimeoutError(f"Job {job_id} timed out after {timeout}s")

            time.sleep(poll_interval)

    def process_jobs(
        self,
        file_path: str,
        metadata_list: List[Dict],
        callback_url: str = None,
        poll_interval: int = 5,
        timeout: int = 3600,
        output_dir: str = "."
    ) -> List[Dict]:
        asset_id = self.upload_file(file_path)["id"]
        input_base_name = Path(file_path).stem

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        results = []
        with concurrent.futures.ThreadPoolExecutor() as pool:
            futures = [
                pool.submit(
                    self._process_single_job_no_upload,
                    asset_id,
                    meta,
                    callback_url,
                    poll_interval,
                    timeout,
                    output_dir,
                    input_base_name
                )
                for meta in metadata_list
            ]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        return results