from abc import ABC, abstractmethod
from typing import Optional, Dict

class SMSProvider(ABC):
    def __init__(self, api_key: str, api_url: Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url

    @abstractmethod
    def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None, media_base64: list[str] = None) -> Dict:
        """
        Sends an SMS.
        Returns a dict with: {'success': bool, 'message_id': str, 'error': str, 'cost': float}
        """
        pass
    
    @abstractmethod
    def get_balance(self) -> float:
        """
        Returns the current balance if supported.
        """
        pass
