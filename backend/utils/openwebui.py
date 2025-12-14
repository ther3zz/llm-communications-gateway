import requests
import json
from typing import Optional

def get_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def find_channel_by_user(base_url: str, token: str, user_id: str, channel_name: str = "LLM-Communications-Gateway Alerts") -> Optional[str]:
    """
    Search for a channel by user ID and name.
    Returns channel_id if found, None otherwise.
    URL: /api/v1/channels/
    """
    try:
        url = f"{base_url.rstrip('/')}/api/v1/channels/"
        # print(f"[DEBUG] OpenWebUI: Searching channels at {url}")
        resp = requests.get(url, headers=get_headers(token), timeout=5)
        
        if resp.status_code == 200:
            channels = resp.json()
            # print(f"[DEBUG] OpenWebUI: Found {len(channels)} channels")
            for ch in channels:
                if ch.get("name") == channel_name:
                    # Check if user is a member
                    user_ids = ch.get("user_ids") or []
                    if user_id in user_ids:
                        print(f"[DEBUG] OpenWebUI: Found channel '{channel_name}' (ID: {ch.get('id')}). Type: {ch.get('type')}")
                        return ch.get("id")
                    
                    # Fallback: check "users" list of objects if user_ids is empty/missing?
                    # Schema says user_ids: [string] OR null.
                    
        else:
            print(f"[WARN] OpenWebUI: Failed to list channels ({resp.status_code}): {resp.text}")
            
    except Exception as e:
        print(f"[ERROR] OpenWebUI: Error finding channel: {e}")
        
    return None

def create_alert_channel(base_url: str, token: str, user_id: str, channel_name: str = "LLM-Communications-Gateway Alerts") -> Optional[str]:
    """
    Create a new channel for the user.
    URL: /api/v1/channels/create
    """
    try:
        url = f"{base_url.rstrip('/')}/api/v1/channels/create"
        # Append User ID to channel name to ensure uniqueness and privacy
        # Or should we trust the config? If we append, the user sees "Alerts - user-123"
        # clearer: "Inbound Alerts (Name)"
        
        # Actually, let's keep the name from config but rely on strict permissions?
        # If we use the same name, we might find someone else's channel if permissions are loose.
        # But we added logic to `find_channel_by_user` to check membership.
        # So if we are here, we didn't find a suitable channel.
        # So we are creating a NEW one. 
        # If we create a new one with the SAME name as an existing one, does it fail?
        # If strictly private, maybe duplicates are allowed?
        # Let's try to set explicit access control.
        
        payload = {
            "name": channel_name,
            "description": "Communications Alerts from LLM Communications Gateway",
            "is_private": True,
            "user_ids": [user_id],
            "access_control": {} # Try empty or explicit strict?
                                 # If we leave it empty, maybe it defaults to restricted?
                                 # The issue 'adding all users' implies default might be open.
                                 # Let's try passing explicit empty dict or user specific?
        }
        
        # print(f"[DEBUG] OpenWebUI: Creating channel at {url} with payload {payload}")
        resp = requests.post(url, headers=get_headers(token), json=payload, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        else:
            # If 409 conflict or similar, maybe it was created in race condition?
            print(f"[WARN] OpenWebUI: Failed to create channel ({resp.status_code}): {resp.text}")
            
    except Exception as e:
        print(f"[ERROR] OpenWebUI: Error creating channel: {e}")
        
    return None

def send_alert(base_url: str, token: str, channel_id: str, message: str) -> bool:
    """
    Post a message to the channel.
    URL: /api/v1/channels/{id}/messages/post
    """
    try:
        url = f"{base_url.rstrip('/')}/api/v1/channels/{channel_id}/messages/post"
        payload = {
            "content": message
        }
        
        # print(f"[DEBUG] OpenWebUI: Sending alert to {url}")
        resp = requests.post(url, headers=get_headers(token), json=payload, timeout=5)
        
        if resp.status_code == 200:
            return True
        else:
            print(f"[WARN] OpenWebUI: Failed to send alert ({resp.status_code}): {resp.text}")
            
    except Exception as e:
        print(f"[ERROR] OpenWebUI: Error sending alert: {e}")
        
    return False
