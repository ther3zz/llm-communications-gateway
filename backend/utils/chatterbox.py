import httpx
import typing

class ChatterboxClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    async def speak_stream(self, text: str, voice_id: str = "default", timeout: int = 10) -> typing.AsyncGenerator[bytes, None]:
        """
        Stream audio from Chatterbox using the /v1/audio/speech/stream endpoint asynchronously.
        The input JSON is {"input": text} and we can expect a raw stream of WAV/audio.
        """
        url = f"{self.base_url}/v1/audio/speech/stream"
        payload = {
            "input": text,
            "voice": voice_id,
            "response_format": "wav"
        }
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        yield chunk
        except Exception as e:
            print(f"[Chatterbox] Error streaming speech: {e}")
            raise e

    def get_voices(self):
        # Sync version used at startup/UI, keep requests or use httpx.get inside async context if needed.
        # But this is rarely called in the hot path. Keep sync for now or use requests for safety if async not needed here.
        # Actually proper habit: use requests if called synchronously.
        import requests
        try:
            resp = requests.get(f"{self.base_url}/v1/voices", timeout=5)
            resp.raise_for_status()
            return resp.json().get('voices', [])
        except:
            return []
