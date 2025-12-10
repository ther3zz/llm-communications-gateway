import requests
import typing

class ChatterboxClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def speak_stream(self, text: str, voice_id: str = "default", timeout: int = 10) -> typing.Generator[bytes, None, None]:
        """
        Stream audio from Chatterbox using the /v1/audio/speech/stream endpoint.
        The input JSON is {"input": text} and we can expect a raw stream of WAV/audio.
        """
        url = f"{self.base_url}/v1/audio/speech/stream"
        payload = {
            "input": text,
            "voice": voice_id,
            "response_format": "wav"
        }
        
        try:
            # stream=True is critical here
            with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"[Chatterbox] Error streaming speech: {e}")
            raise e

    def get_voices(self):
        try:
            resp = requests.get(f"{self.base_url}/v1/voices", timeout=5)
            resp.raise_for_status()
            return resp.json().get('voices', [])
        except:
            return []
