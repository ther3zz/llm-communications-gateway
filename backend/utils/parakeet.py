import requests
import typing

class ParakeetClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def transcribe(self, audio_data: bytes, filename: str = "audio.wav", timeout: int = 10) -> str:
        """
        Transcribe audio bytes to text using the /transcribe endpoint.
        """
        url = f"{self.base_url}/transcribe"
        files = {
            'file': (filename, audio_data, 'audio/wav')
        }
        # The /transcribe endpoint defaults to include_timestamps=False, should_chunk=True
        try:
            resp = requests.post(url, files=files, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("text", "")
        except Exception as e:
            print(f"[Parakeet] Error transcribing: {e}")
            raise e

    def health(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/healthz", timeout=2)
            return resp.status_code == 200
        except:
            return False
