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
    Search for a channel by user ID and name (case-insensitive).
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
                # Case-insensitive comparison
                current_name = ch.get("name", "")
                if current_name.lower() == channel_name.lower():
                    # Check if user is a member
                    # Check 'user_ids' (list) OR 'user_id' (owner/creator singular)
                    user_ids = ch.get("user_ids") or []
                    if user_id in user_ids or ch.get("user_id") == user_id:
                        print(f"[DEBUG] OpenWebUI: Found channel '{current_name}' (ID: {ch.get('id')}). Matching user {user_id}.")
                        return ch.get("id")
                    
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
        
        # Ensure we only add the target user, NOT the admin (token bearer) implicitly if possible.
        # But usually 'user_ids' defines the members.
        
        payload = {
            "name": channel_name,
            "description": "Communications Alerts from LLM Communications Gateway",
            "is_private": True, # Keep it private
            "user_ids": [user_id], # Explicitly only the target user
            "access_control": {} # Default strict
        }
        
        # print(f"[DEBUG] OpenWebUI: Creating channel at {url} with payload {payload}")
        resp = requests.post(url, headers=get_headers(token), json=payload, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        else:
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
