import telnyx
from typing import Dict
from .base import SMSProvider

class TelnyxProvider(SMSProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = telnyx.Client(api_key=self.api_key)

    def send_sms(self, to_number: str, from_number: str, message: str) -> Dict:
        try:
            resp = self.client.messages.send(
                from_=from_number,
                to=to_number,
                text=message
            )
            print(f"[DEBUG] SMS Response Type: {type(resp)}")
            print(f"[DEBUG] SMS Response Dir: {dir(resp)}")
            print(f"[DEBUG] SMS Response: {resp}")
            
            msg_id = getattr(resp, "id", None)
            # Fallback for nested data
            if not msg_id and hasattr(resp, "data"):
                 msg_id = getattr(resp.data, "id", None)
            
            return {"success": True, "message_id": msg_id, "error": None, "cost": 0.004}
        except Exception as e:
            return {"success": False, "message_id": None, "error": str(e), "cost": 0.0}

    def get_balance(self) -> float:
        try:
            resp = self.client.balance.retrieve()
            return float(resp.balance)
        except:
            return 0.0

    def make_call(self, to_number: str, from_number: str, connection_id: str, stream_url: str = None, stream_track: str = "both_tracks") -> dict:
        try:
            import requests
            import json
            # clean numbers
            to_number = to_number.strip()
            from_number = from_number.strip()
            
            payload = {
                "connection_id": connection_id,
                "to": to_number,
                "from": from_number,
            }
            if stream_url:
                payload["stream_url"] = stream_url
                payload["stream_track"] = stream_track
                payload["stream_bidirectional_mode"] = "rtp"

            print(f"[DEBUG] Direct API Dial Payload: {json.dumps(payload, indent=2)}")

            # Use Direct REST API to rule out SDK issues
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            resp = requests.post("https://api.telnyx.com/v2/calls", headers=headers, json=payload)
            print(f"[DEBUG] Direct API response: {resp.status_code} {resp.text}")
            
            if resp.status_code >= 400:
                return {"success": False, "error": resp.text}

            data = resp.json().get('data', {})
            call_control_id = data.get('call_control_id')
                
            return {
                "success": True, 
                "call_id": call_control_id,
                "full_response": str(data)
            }
        except Exception as e:
            print(f"Telnyx Dial Error: {e}")
            return {"success": False, "error": str(e)}

    def update_app(self, connection_id: str, webhook_url: str) -> Dict:
        try:
            app = self.client.call_control_applications.retrieve(connection_id)
            app.webhook_event_url = webhook_url
            app.save()
            return {"success": True, "data": app}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_outbound_voice_profiles(self) -> list:
        try:
            resp = self.client.outbound_voice_profiles.list()
            return resp.data
        except:
            return []

    def create_outbound_voice_profile(self, name: str) -> str:
        try:
            resp = self.client.outbound_voice_profiles.create(name=name)
            return resp.id
        except:
            return None

    def create_app(self, name: str, webhook_url: str) -> Dict:
        try:
            # 1. Resolve Profile
            profile_id = None
            profiles = self.get_outbound_voice_profiles()
            if profiles: 
                profile_id = profiles[0].id
            else:
                profile_id = self.create_outbound_voice_profile("LLM Gateway Outbound")

            params = {
                "application_name": name,
                "webhook_event_url": webhook_url,
                "webhook_event_failover_url": "",
                "active": True,
                "anchorsite_override": "Latency"
            }
            if profile_id:
                params["outbound"] = {"outbound_voice_profile_id": profile_id}
            
            resp = self.client.call_control_applications.create(**params)
            return {"success": True, "app_id": resp.id, "data": resp}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_media_stream(self, call_control_id: str, stream_url: str) -> Dict:
        try:
            # Inspection revealed start_streaming is on calls.actions
            # signature: start_streaming(call_control_id, stream_url=..., ...)
            resp = self.client.calls.actions.start_streaming(
                call_control_id,
                stream_url=stream_url,
                stream_track="both_tracks" 
            )
            return {"success": True, "data": resp}
        except Exception as e:
             return {"success": False, "error": str(e)}

    def hangup_call(self, call_control_id: str) -> Dict:
        try:
            # Using telnyx sdk
            # call = telnyx.Call.retrieve(call_control_id)
            # call.hangup()
            
            # Using direct REST for consistency/safety
            import requests
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "call_control_id": call_control_id,
                "command_id": "hangup_command"
            }
            # Telnyx Hangup Endpoint: https://api.telnyx.com/v2/calls/{call_control_id}/actions/hangup
            url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/hangup"
            resp = requests.post(url, headers=headers, json=payload)
            print(f"[DEBUG] Hangup Response: {resp.status_code} {resp.text}")
            
            if resp.status_code >= 400:
                return {"success": False, "error": resp.text}
                
            return {"success": True, "data": resp.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
