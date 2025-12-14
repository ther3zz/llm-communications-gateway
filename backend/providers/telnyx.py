import telnyx
from typing import Dict
import requests
import json
import base64
import os
from .base import SMSProvider

class TelnyxProvider(SMSProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = telnyx.Client(api_key=self.api_key)

    def upload_media(self, url: str) -> str:
        """
        Downloads media from a URL and uploads it to Telnyx Media Storage.
        Returns the public URL provided by Telnyx.
        """
        try:
            print(f"[DEBUG] Downloading media from: {url}")
            # 1. Download Content
            r_get = requests.get(url, stream=True)
            r_get.raise_for_status()
            
            filename = url.split('/')[-1].split('?')[0] or "media_file"
            
            # 2. Upload to Telnyx
            # Endpoint: POST https://api.telnyx.com/v2/media
            print(f"[DEBUG] Uploading {filename} to Telnyx Storage...")
            files = {
                'media_url': (None, url), # Telnyx supports direct URL fetch too!
            }
            # Wait, docs say "media_url" OR "file". 
            # If we use media_url, Telnyx fetches it. This is SAFER/FASTER if the URL is public.
            # But the user said "users dont have to expose anything else". 
            # If the user's URL is INTERNAL/LOCAL, Telnyx can't fetch it.
            # So we MUST download and upload.
            
            files = {'media': (filename, r_get.content, r_get.headers.get('content-type'))}
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            r_post = requests.post("https://api.telnyx.com/v2/media", files=files, headers=headers)
            print(f"[DEBUG] Upload Response: {r_post.status_code} {r_post.text}")
            
            if r_post.status_code >= 400:
                print(f"[WARN] Failed to upload media: {r_post.text}")
                return url # Fallback to original URL?
                
            data = r_post.json().get('data', {})
            return data.get('media_url') # The hosted URL
            
        except Exception as e:
            print(f"[ERROR] Media Upload Failed: {e}")
            return url # Fallback

    def upload_base64(self, data_uri: str) -> str:
        """
        Decodes a Data URI and uploads it to Telnyx Media Storage.
        Format: data:image/jpeg;base64,.....
        """
        try:
            print(f"[DEBUG] Processing Base64 Data URI...")
            
            # 1. Parse Data URI
            if ',' not in data_uri:
                raise ValueError("Invalid Data URI format")
                
            header, encoded = data_uri.split(',', 1)
            # data:image/jpeg;base64
            mime_type = header.split(':')[1].split(';')[0]
            extension = mime_type.split('/')[-1]
            filename = f"upload_{base64.urlsafe_b64encode(os.urandom(6)).decode()}.{extension}"
            
            file_content = base64.b64decode(encoded)
            
            # 2. Upload to Telnyx
            print(f"[DEBUG] Uploading {filename} ({len(file_content)} bytes) to Telnyx Storage...")
            files = {'media': (filename, file_content, mime_type)}
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            r_post = requests.post("https://api.telnyx.com/v2/media", files=files, headers=headers)
            
            if r_post.status_code >= 400:
                print(f"[WARN] Failed to upload base64 media: {r_post.text}")
                return None
                
            data = r_post.json().get('data', {})
            return data.get('media_url')
            
        except Exception as e:
            print(f"[ERROR] Base64 Upload Failed: {e}")
            return None
        super().__init__(api_key)
        self.client = telnyx.Client(api_key=self.api_key)

    def upload_media(self, url: str) -> str:
        """
        Downloads media from a URL and uploads it to Telnyx Media Storage.
        Returns the public URL provided by Telnyx.
        """
        try:
            print(f"[DEBUG] Downloading media from: {url}")
            # 1. Download Content
            r_get = requests.get(url, stream=True)
            r_get.raise_for_status()
            
            filename = url.split('/')[-1].split('?')[0] or "media_file"
            
            # 2. Upload to Telnyx
            # Endpoint: POST https://api.telnyx.com/v2/media
            print(f"[DEBUG] Uploading {filename} to Telnyx Storage...")
            files = {
                'media_url': (None, url), # Telnyx supports direct URL fetch too!
            }
            # Wait, docs say "media_url" OR "file". 
            # If we use media_url, Telnyx fetches it. This is SAFER/FASTER if the URL is public.
            # But the user said "users dont have to expose anything else". 
            # If the user's URL is INTERNAL/LOCAL, Telnyx can't fetch it.
            # So we MUST download and upload.
            
            files = {'media': (filename, r_get.content, r_get.headers.get('content-type'))}
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            r_post = requests.post("https://api.telnyx.com/v2/media", files=files, headers=headers)
            print(f"[DEBUG] Upload Response: {r_post.status_code} {r_post.text}")
            
            if r_post.status_code >= 400:
                print(f"[WARN] Failed to upload media: {r_post.text}")
                return url # Fallback to original URL?
                
            data = r_post.json().get('data', {})
            return data.get('media_url') # The hosted URL
            
        except Exception as e:
            print(f"[ERROR] Media Upload Failed: {e}")
            return url # Fallback

    def send_sms(self, to_number: str, from_number: str, message: str, media_urls: list[str] = None, media_base64: list[str] = None) -> Dict:
        try:
            processed_media_urls = []
            
            # Process URLs
            if media_urls:
                print(f"[DEBUG] Processing {len(media_urls)} media URL attachments...")
                for url in media_urls:
                    hosted_url = self.upload_media(url)
                    processed_media_urls.append(hosted_url)
            
            # Process Base64
            if media_base64:
                print(f"[DEBUG] Processing {len(media_base64)} media Base64 attachments...")
                for data_uri in media_base64:
                    hosted_url = self.upload_base64(data_uri)
                    if hosted_url:
                        processed_media_urls.append(hosted_url)

            params = {
                "from_": from_number,
                "to": to_number,
                "text": message
            }
            if processed_media_urls:
                params["media_urls"] = processed_media_urls

            resp = self.client.messages.send(**params)
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

    def make_call(self, to_number: str, from_number: str, connection_id: str, stream_url: str = None, stream_track: str = "both_tracks", codec: str = "PCMU") -> dict:
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
                # Signal the codec to Telnyx!
                # Note: Telnyx uses "L16" but might want "L16" strictly. Codec config is usually PCMU/PCMA/L16.
                payload["stream_bidirectional_codec"] = codec

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
            
            resource_id = getattr(resp, 'id', None)
            if not resource_id and hasattr(resp, 'data'):
                  resource_id = getattr(resp.data, 'id', None)

            return {"success": True, "app_id": resource_id, "data": resp}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_messaging_profile(self, name: str, webhook_url: str) -> Dict:
        try:
             # Check if exists? Telnyx allows duplicates, so we just create.
             payload = {
                 "name": name,
                 "webhook_url": webhook_url,
                 "whitelisted_destinations": ["US", "CA"] # Default to reasonable defaults or empty list if allowed? Documentation says required.
             }
             resp = self.client.messaging_profiles.create(**payload)
             # Telnyx SDK v2 often wraps response in a structure where the resource is in .data
             # or the object itself acts like the resource but 'id' access might be tricky if it's a validataproperty.
             # Based on user error 'MessagingProfileCreateResponse object has no attribute id', we should try .data.id
             # But let's be safe and try getattr or dictionary access if possible, or assume .data.id based on typical pattern.
             resource_id = getattr(resp, 'id', None)
             if not resource_id and hasattr(resp, 'data'):
                 resource_id = getattr(resp.data, 'id', None)
             
             return {"success": True, "id": resource_id, "data": resp}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def assign_messaging_profile_to_number(self, phone_number: str, profile_id: str) -> Dict:
        try:
            # 1. Search for the number to get its ID
            # Telnyx API numbers list takes 'filter[phone_number]'
            # phone_number should be E.164
            clean_number = phone_number.strip()
            if not clean_number.startswith('+'):
                clean_number = '+' + clean_number

            numbers = self.client.phone_numbers.list(filter={'phone_number': clean_number})
            
            # Fix: Telnyx ListResponse is not a list, it has a .data property which is the list
            # We must check if .data exists and has items
            numbers_list = getattr(numbers, 'data', [])
            if not numbers_list or len(numbers_list) == 0:
                 return {"success": False, "error": "Phone number not found in Telnyx account"}
            
            number_obj = numbers_list[0]
            
            # 2. Update the number with the messaging_profile_id
            # Use explicit client update method which we confirmed exists via introspection
            
            try:
                # Update directly via the client resource
                # number_obj is a simple object or dict from the list response .data
                # We need its ID.
                resource_id = getattr(number_obj, 'id', None)
                if not resource_id:
                     # fallback if it's a dict
                     resource_id = number_obj.get('id')
                
                # Fix: Use the specific messaging sub-resource update method
                # This aligns with the "updatePhoneNumberWithMessagingSettings" error hint
                updated_obj = self.client.phone_numbers.messaging.update(resource_id, messaging_profile_id=profile_id)
                
                return {"success": True, "data": updated_obj}
            except Exception as e:
                print(f"[ERROR] Assignment failed: {e}")
                return {"success": False, "error": str(e)}
        except Exception as e:
             return {"success": False, "error": str(e)}

    def start_media_stream(self, call_control_id: str, stream_url: str, stream_track: str = "both_tracks", mode: str = None, codec: str = None) -> Dict:
        try:
            # Use Direct REST API for full control
            import requests
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "stream_url": stream_url,
                "stream_track": stream_track
            }
            if mode:
                payload["stream_bidirectional_mode"] = mode
            if codec:
                payload["stream_bidirectional_codec"] = codec
            
            print(f"[DEBUG] Start Streaming Payload: {json.dumps(payload, indent=2)}")
            
            url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/streaming_start"
            resp = requests.post(url, headers=headers, json=payload)
            print(f"[DEBUG] Start Streaming Response: {resp.status_code} {resp.text}")
            
            if resp.status_code >= 400:
                 return {"success": False, "error": resp.text}
                 
            return {"success": True, "data": resp.json()}
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

    def answer_call(self, call_control_id: str, stream_url: str = None, stream_track: str = "both_tracks", mode: str = None, codec: str = None) -> Dict:
        """
        Answers an inbound call. Optionally starts streaming immediately if stream_url is provided.
        """
        try:
             import requests
             headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
             }
             payload = {
                 "call_control_id": call_control_id,
                 "command_id": "answer_command"
             }
             if stream_url:
                 # Support Streaming on Answer!
                 payload["stream_url"] = stream_url
                 payload["stream_track"] = stream_track
                 if mode:
                    payload["stream_bidirectional_mode"] = mode
                 if codec:
                    payload["stream_bidirectional_codec"] = codec
                 
                 # Note: client_state is NOT supported in answer command usually, or at least not needed for stream setup here.
                 # We keep it simple.

             print(f"[DEBUG] Answering Call {call_control_id} (Stream: {bool(stream_url)})... Payload: {json.dumps(payload, indent=2)}")
             url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/answer"
             resp = requests.post(url, headers=headers, json=payload)
             print(f"[DEBUG] Answer Response: {resp.status_code} {resp.text}")
             
             if resp.status_code >= 400:
                 return {"success": False, "error": resp.text}
                 
             return {"success": True, "data": resp.json()}
        except Exception as e:
             return {"success": False, "error": str(e)}
