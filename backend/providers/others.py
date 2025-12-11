from .base import SMSProvider
from typing import Dict

class MockProvider(SMSProvider):
    def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None, media_base64: list[str] = None) -> Dict:
        import uuid
        msg_id = f"mock_{uuid.uuid4().hex[:8]}"
        print(f"[MOCK] Sending SMS to {to_number} from {from_number}: {message} | Media: {media_urls} | Base64: {len(media_base64) if media_base64 else 0} items")
        return {"success": True, "cost": 0.00, "message_id": msg_id, "error": None}

    def get_balance(self) -> float:
        return 9999.99
    
class ConsoleProvider(SMSProvider):
    def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None, media_base64: list[str] = None) -> Dict:
        print(f"--- SMS SENT ---")
        print(f"From: {from_number}")
        print(f"To: {to_number}")
        print(f"Message: {message}")
        if media_urls:
            print(f"Media URLs: {media_urls}")
        if media_base64:
            print(f"Media Base64: {len(media_base64)} items provided")
        print("----------------")
        return {"success": True, "cost": 0.00, "message_id": "console_msg_id", "error": None}
    def get_balance(self) -> float:
        return 0.0

class TwilioProvider(SMSProvider):
    # TODO: Implement Twilio
    def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None) -> Dict:
        return {"success": False, "message_id": None, "error": "Not implemented", "cost": 0.0}
    def get_balance(self) -> float:
        return 0.0

class VonageProvider(SMSProvider):
    # TODO: Implement Vonage
     def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None) -> Dict:
        return {"success": False, "message_id": None, "error": "Not implemented", "cost": 0.0}
     def get_balance(self) -> float:
        return 0.0
