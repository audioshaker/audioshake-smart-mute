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

    # ---------- Core API helpers ----------

    def upload_file(self, file_path: str) -> dict:
        url = f"{self.base_url}/upload/"
        with open(file_path, "rb") as f:
            files = {"file": f}
            resp = requests.post(url, headers=self.headers, files=files)
        resp.raise_for_status()
        return resp.json()

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
        timeout: int = 600,
        output_dir: str = "."
    ) -> dict:
        asset = self.upload_file(file_path)
        job = self.create_job(asset["id"], metadata, callback_url)
        job_id = job["id"]
        start = time.time()

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Get base name of input file
        input_base_name = Path(file_path).stem
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
        timeout: int = 600,
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