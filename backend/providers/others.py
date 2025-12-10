from .base import SMSProvider
from typing import Dict

class MockProvider(SMSProvider):
    def send_sms(self, to_number: str, from_number: str, message: str) -> Dict:
        print(f"DTO MOCK SEND: {to_number} -> {message}")
        return {"success": True, "message_id": "mock-id-12345", "error": None, "cost": 0.000}

    def get_balance(self) -> float:
        return 9999.99
    
class TwilioProvider(SMSProvider):
    # TODO: Implement Twilio
    def send_sms(self, to_number: str, from_number: str, message: str) -> Dict:
        return {"success": False, "message_id": None, "error": "Not implemented", "cost": 0.0}
    def get_balance(self) -> float:
        return 0.0

class VonageProvider(SMSProvider):
    # TODO: Implement Vonage
     def send_sms(self, to_number: str, from_number: str, message: str) -> Dict:
        return {"success": False, "message_id": None, "error": "Not implemented", "cost": 0.0}
     def get_balance(self) -> float:
        return 0.0
