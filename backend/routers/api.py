from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
import json

from ..database import get_session
from ..models import ProviderConfig, MessageLog, VoiceConfig, CallLog
from ..providers.telnyx import TelnyxProvider
from ..providers.others import MockProvider, TwilioProvider, VonageProvider
from ..utils.security import encrypt_value, decrypt_value

router = APIRouter()

@router.get("/proxies/llm/models")
def get_llm_models(session: Session = Depends(get_session)):
    import requests
    config = session.exec(select(VoiceConfig)).first()
    
    # Use defaults if not configured
    llm_url = (config.llm_url if config else None) or "http://open-webui:8080/v1"
    
    try:
        # OpenAI compatible: /models
        url = f"{llm_url.rstrip('/')}/models"
        headers = {}
        if config.llm_api_key:
            headers["Authorization"] = f"Bearer {decrypt_value(config.llm_api_key)}"
            
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching models: {e}")
        return {"data": []}

@router.get("/proxies/parakeet/status")
def get_parakeet_status(session: Session = Depends(get_session)):
    import requests
    config = session.exec(select(VoiceConfig)).first()
    if not config or not config.stt_url:
        raise HTTPException(status_code=400, detail="STT URL not configured")
    
    try:
        url = f"{config.stt_url.rstrip('/')}/healthz"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return {"status": "ok", "detail": "Connected to Parakeet"}
    except Exception as e:
        # Return 200 with error detail to prevent frontend try/catch block from masking details
        # Or better, return 503 so frontend sees it as error. Let's return 503 for clarity.
        raise HTTPException(status_code=503, detail=f"Failed to connect to Parakeet: {e}")

@router.get("/integrations/openwebui/users")
def get_open_webui_users(session: Session = Depends(get_session)):
    import requests
    config = session.exec(select(VoiceConfig)).first()
    if not config or not config.open_webui_admin_token:
        # If no token, return empty list (or 403, but empty is friendlier for UI probing)
        return []
    
    # Target URL: Use config.llm_url base but need /api/v1/users/
    # If llm_url defaults to .../api/v1, we can use that base.
    # User might set custom URL though.
    # Logic: Extract base from LLM URL or use default.
    
    base_url = "http://open-webui:8080"
    if config.llm_url:
        # naive parse: remove /api/v1 or /v1
        base_url = config.llm_url.split("/api/v1")[0].split("/v1")[0].rstrip('/')
    
    # Endpoint: /api/v1/users/all
    target = f"{base_url}/api/v1/users/all"
    
    token = decrypt_value(config.open_webui_admin_token)
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(target, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        # Expecting { "users": [...], "total": 7 } or list
        # Map to simple structure
        users = []
        # Check if data is list or wrapped
        raw_list = []
        if isinstance(data, list):
            raw_list = data
        elif data.get('users'):
             raw_list = data['users']
        elif data.get('data'):
             raw_list = data['data']
        
        for u in raw_list:
             users.append({
                 "id": u.get("id"),
                 "name": u.get("name"),
                 "email": u.get("email"),
                 "role": u.get("role")
             })
        return users
    except Exception as e:
        print(f"Error fetching Open WebUI users: {e}")
        return []

class SMSSendRequest(BaseModel):
    to_number: str
    message: str
    provider: Optional[str] = None # Optional override
    media_urls: Optional[List[str]] = None
    media_base64: Optional[List[str]] = None # List of Data URIs
    user_id: Optional[str] = None
    chat_id: Optional[str] = None

class ProviderConfigCreate(BaseModel):
    name: str
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    from_number: Optional[str] = None
    app_id: Optional[str] = None
    enabled: bool = True
    priority: int = 0
    webhook_secret: Optional[str] = None
    base_url: Optional[str] = None
    inbound_system_prompt: Optional[str] = None
    inbound_enabled: bool = True
    max_call_duration: Optional[int] = 600
    call_limit_message: Optional[str] = "This call has reached its time limit. Goodbye."
    assigned_user_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_label: Optional[str] = None
    messaging_profile_id: Optional[str] = None

def get_provider_instance(name: str, config: ProviderConfig):
    if name == 'telnyx':
        return TelnyxProvider(api_key=decrypt_value(config.api_key))
    elif name == 'mock':
        return MockProvider(api_key="mock", api_url="mock")
    # Add others
    return MockProvider(api_key="mock", api_url="mock")

@router.post("/sms/send")
def send_sms(request: SMSSendRequest, session: Session = Depends(get_session)):
    # 1. Determine provider
    if request.provider:
        provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.name == request.provider)).first()
    else:
        # Get highest priority enabled provider
        provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.enabled == True).order_by(ProviderConfig.priority)).first()
    
    if not provider_config:
        raise HTTPException(status_code=400, detail="No active provider found")

    # 2. Instantiate provider
    provider = get_provider_instance(provider_config.name, provider_config)
    
    # 3. Send
    # Use config from_number if not specified? For now assume config has it.
    from_num = provider_config.from_number    # Send via provider
    try:
        result = provider.send_sms(
            to_number=request.to_number,
            from_number=from_num,
            message=request.message,
            media_urls=request.media_urls,
            media_base64=request.media_base64
        )
    except Exception as e:
        # Handle potential errors during SMS sending
        result = {
            'success': False,
            'error': str(e),
            'cost': 0.0,
            'message_id': None
        }
    
    # 4. Log
    media_content = None
    if request.media_urls:
         media_content = json.dumps([str(u) for u in request.media_urls])
    # If base64 was used, the provider might have returned a URL (feature specific to Telnyx logic elsewhere),
    # but base64 itself isn't a URL so we don't save the HUGE string here.
    # FUTURE: If provider returns the uploaded URL (like Telnyx does internally), we might want to capture it.
    # Currently send_sms result doesn't return the media URL.
    
    log = MessageLog(
        provider_used=provider_config.name,
        destination=request.to_number,
        content=request.message,
        status="sent" if result['success'] else "failed",
        error_message=result['error'],
        cost=result['cost'],
        message_id=result['message_id'],
        user_id=request.user_id,
        chat_id=request.chat_id,
        media_url=media_content
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    
    return result

@router.get("/messages/{message_id}")
def get_message_status(message_id: str, user_id: str, session: Session = Depends(get_session)):
    """
    Retrieve message status by ID.
    Requires user_id to match the record for security.
    """
    # 1. Look up log by message_id (which is the provider's ID usually stored in message_id column)
    # The message_id in DB is the provider's ID.
    log = session.exec(select(MessageLog).where(MessageLog.message_id == message_id)).first()
    
    if not log:
        # Fallback: Check if message_id is actually our internal DB ID (if pure integer passed)?
        # But instructions verify "message_id" which usually implies the UUID returned by send.
        
        # Second try: Maybe user passed internal ID?
        if message_id.isdigit():
             log = session.get(MessageLog, int(message_id))

    if not log:
        raise HTTPException(status_code=404, detail="Message not found")

    # 2. Security Check
    # "must also pass the user id that sent the message and it must match"
    if log.user_id != user_id:
        # Return 404 to avoid leaking existence? Or 403.
        # "must match before returning any info" -> 404 is safer to prevent enumeration.
        raise HTTPException(status_code=404, detail="Message not found")

    return {
        "id": log.id,
        "message_id": log.message_id,
        "status": log.status,
        "cost": log.cost,
        "media_url": log.media_url,
        "error": log.error_message,
        "timestamp": log.timestamp
    }


@router.get("/calls/{call_id}")
def get_call_status(call_id: str, user_id: str, session: Session = Depends(get_session)):
    """
    Retrieve call status by call_control_id (or internal ID).
    Requires user_id match.
    """
    # 1. Lookup by Call Control ID
    log = session.exec(select(CallLog).where(CallLog.call_control_id == call_id)).first()
    
    if not log:
        # 2. Fallback: Internal ID
        if call_id.isdigit():
            log = session.get(CallLog, int(call_id))
            
    if not log:
        raise HTTPException(status_code=404, detail="Call not found")
        
    # 3. Security Check
    if log.user_id != user_id:
        raise HTTPException(status_code=404, detail="Call not found")
        
    return {
        "id": log.id,
        "call_id": log.call_control_id,
        "status": log.status,
        "duration": log.duration_seconds,
        "cost": log.cost,
        "recording_url": log.recording_url,
        "transcription": log.transcription,
        "timestamp": log.timestamp
    }

@router.get("/config/providers", response_model=List[ProviderConfig])
def get_providers(session: Session = Depends(get_session)):
    return session.exec(select(ProviderConfig)).all()

@router.post("/config/providers", response_model=ProviderConfig)
def create_provider(provider: ProviderConfigCreate, session: Session = Depends(get_session)):
    if not provider.api_key:
        raise HTTPException(status_code=400, detail="API Key is required for new providers")
    
    p_data = provider.dict()
    if p_data.get('api_key'):
        p_data['api_key'] = encrypt_value(p_data['api_key'])
    p_data = provider.dict()
    if p_data.get('api_key'):
        p_data['api_key'] = encrypt_value(p_data['api_key'])
    
    # Auto-generate webhook secret if not provided
    if not p_data.get('webhook_secret'):
        import uuid
        p_data['webhook_secret'] = uuid.uuid4().hex
        
    db_provider = ProviderConfig(**p_data)
    session.add(db_provider)
    session.commit()
    session.refresh(db_provider)
    return db_provider

@router.put("/config/providers/{provider_id}", response_model=ProviderConfig)
def update_provider(provider_id: int, provider: ProviderConfigCreate, session: Session = Depends(get_session)):
    db_provider = session.get(ProviderConfig, provider_id)
    if not db_provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider_data = provider.dict(exclude_unset=True)
    for key, value in provider_data.items():
        if key == 'api_key' and value:
            value = encrypt_value(value)
        setattr(db_provider, key, value)
    session.add(db_provider)
    session.commit()
    session.refresh(db_provider)
    return db_provider

@router.delete("/config/providers/{provider_id}")
def delete_provider(provider_id: int, session: Session = Depends(get_session)):
    provider = session.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    session.delete(provider)
    session.commit()
    return {"ok": True}

@router.get("/stats")
def get_stats(limit: int = 100, session: Session = Depends(get_session)):
    # SMS Stats
    sms_logs = session.exec(select(MessageLog).order_by(MessageLog.timestamp.desc()).limit(limit)).all()
    total_sms = session.query(MessageLog).count()
    
    # Voice Stats
    # We might need to import CallLog if not already imported at top, but let's assume I'll fix imports next or rely on previous context
    # actually I need to make sure CallLog is imported.
    from ..models import CallLog
    voice_logs = session.exec(select(CallLog).order_by(CallLog.timestamp.desc()).limit(limit)).all()
    total_calls = session.query(CallLog).count()
    
    return {
        "sms": {"logs": sms_logs, "total": total_sms},
        "voice": {"logs": voice_logs, "total": total_calls}
    }

@router.get("/logs")
def get_logs(skip: int = 0, limit: int = 20, session: Session = Depends(get_session)):
    logs = session.exec(select(MessageLog).order_by(MessageLog.timestamp.desc()).offset(skip).limit(limit)).all()
    total = session.query(MessageLog).count()
    return {"logs": logs, "total": total, "skip": skip, "limit": limit}

@router.get("/logs/calls")
def get_call_logs(user_id: str, skip: int = 0, limit: int = 20, session: Session = Depends(get_session)):
    # Filter by user_id
    query = select(CallLog).where(CallLog.user_id == user_id).order_by(CallLog.timestamp.desc()).offset(skip).limit(limit)
    logs = session.exec(query).all()
    
    # Count specific to user
    count_query = select(CallLog).where(CallLog.user_id == user_id)
    # total = session.exec(select(func.count()).select_from(count_query.subquery())).one() 
    # simpler count:
    total = len(session.exec(select(CallLog).where(CallLog.user_id == user_id)).all()) 
    
    return {"logs": logs, "total": total, "skip": skip, "limit": limit}

@router.get("/config/voice", response_model=VoiceConfig)
def get_voice_config(session: Session = Depends(get_session)):
    config = session.exec(select(VoiceConfig)).first()
    if not config:
        # Return default
        return VoiceConfig()
    
    # Decrypt for UI display
    if config.llm_api_key:
        config.llm_api_key = decrypt_value(config.llm_api_key)
    if config.open_webui_admin_token:
        config.open_webui_admin_token = decrypt_value(config.open_webui_admin_token)
    return config


@router.post("/config/voice", response_model=VoiceConfig)
def save_voice_config(config: VoiceConfig, session: Session = Depends(get_session)):
    existing = session.exec(select(VoiceConfig)).first()
    if existing:
        existing.stt_url = config.stt_url
        existing.tts_url = config.tts_url
        existing.llm_url = config.llm_url
        existing.llm_provider = config.llm_provider
        if config.llm_api_key:
             existing.llm_api_key = encrypt_value(config.llm_api_key)
        if config.open_webui_admin_token:
             existing.open_webui_admin_token = encrypt_value(config.open_webui_admin_token)
        existing.llm_model = config.llm_model
        existing.voice_id = config.voice_id
        existing.stt_timeout = config.stt_timeout
        existing.tts_timeout = config.tts_timeout
        existing.llm_timeout = config.llm_timeout
        existing.system_prompt = config.system_prompt
        existing.send_conversation_context = config.send_conversation_context
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    else:
        if config.llm_api_key:
            config.llm_api_key = encrypt_value(config.llm_api_key)
        if config.open_webui_admin_token:
            config.open_webui_admin_token = encrypt_value(config.open_webui_admin_token)
        session.add(config)
        session.commit()
        session.refresh(config)
        return config

@router.get("/proxies/chatterbox/voices")
def get_chatterbox_voices(session: Session = Depends(get_session)):
    config = session.exec(select(VoiceConfig)).first()
    
    # Use defaults
    tts_url = (config.tts_url if config else None) or "http://chatterbox:8000"
    
    import requests
    try:
        # User example: /v1/voices
        url = f"{tts_url.rstrip('/')}/v1/voices"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching voices: {e}")
        # Return empty or error structure so frontend doesn't crash
        return {"voices": []}




@router.post("/admin/migrate")
def migrate_db():
    from ..database import create_db_and_tables
    try:
        create_db_and_tables()
        return {"status": "success", "message": "Database tables created/migrated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/defaults")
def get_config_defaults():
    # Return Env Var defaults for UI pre-filling
    return {
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "openwebui_url": os.getenv("OPEN_WEBUI_URL", "http://open-webui:8080/v1"),
        "base_url": os.getenv("BASE_URL", ""),
        "system_prompt": os.getenv("SYSTEM_PROMPT", "")
    }
