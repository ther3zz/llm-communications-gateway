from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
import os

class ProviderConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # e.g., 'telnyx', 'twilio'
    api_key: str
    api_url: Optional[str] = None
    from_number: Optional[str] = None # Default sender number
    app_id: Optional[str] = None # e.g. Telnyx Call Control App ID
    enabled: bool = Field(default=False)
    priority: int = Field(default=0) # 0 = highest priority
    webhook_secret: Optional[str] = Field(default=None, description="Secret token for securing webhooks specific to this provider")
    base_url: Optional[str] = Field(default=None, description="Public Base URL for WebSocket connections")
    inbound_system_prompt: Optional[str] = Field(default=None, description="System prompt for inbound calls using this provider")
    inbound_enabled: bool = Field(default=True) # Whether to accept inbound calls
    max_call_duration: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_MAX_DURATION", 600))) # Max duration in seconds
    call_limit_message: Optional[str] = Field(default="This call has reached its time limit. Goodbye.")
    assigned_user_id: Optional[str] = Field(default=None, description="Open WebUI User ID to route calls/messages to")
    assigned_user_label: Optional[str] = Field(default=None, description="Human readable label for the assigned user")

class VoiceConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stt_url: str = Field(default="http://parakeet:8000")
    tts_url: str = Field(default="http://chatterbox:8000")
    llm_url: str = Field(default="http://open-webui:8080/api/v1")
    llm_provider: str = Field(default="custom", description="Preferred LLM provider (openai, ollama, open_webui, custom)")
    llm_api_key: Optional[str] = Field(default=None, description="API Key if needed (e.g. for OpenAI)")
    open_webui_admin_token: Optional[str] = Field(default=None, description="Admin Token for fetching users from Open WebUI")
    llm_model: str = Field(default="gpt-3.5-turbo")
    voice_id: str = Field(default="default")
    webhook_secret: Optional[str] = Field(default=None, description="Secret token for securing webhooks")
    stt_timeout: int = Field(default=10, description="Timeout in seconds for STT requests")
    tts_timeout: int = Field(default=10, description="Timeout in seconds for TTS requests")
    llm_timeout: int = Field(default=10, description="Timeout in seconds for LLM requests")
    system_prompt: Optional[str] = Field(default=None, description="Custom System Prompt for the Voice Bot")
    send_conversation_context: bool = Field(default=True, description="Whether to send full conversation history to LLM")
    rtp_codec: str = Field(default="PCMU", description="RTP Codec for audio streaming (PCMU, PCMA)")


class MessageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    provider_used: str
    destination: str
    content: str
    status: str # 'sent', 'failed', 'delivered'
    error_message: Optional[str] = None
    cost: Optional[float] = Field(default=0.0)
    message_id: Optional[str] = None # External ID from provider
    user_id: Optional[str] = None
    user_label: Optional[str] = None # Human readable label (Name/Email)
    chat_id: Optional[str] = None
    media_url: Optional[str] = None # JSON list or single URL

class CallLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    to_number: str
    from_number: Optional[str] = None
    duration_seconds: int = Field(default=0)
    status: str = Field(default="completed") # completed, busy, failed, no-answer
    cost: Optional[float] = Field(default=0.0)
    recording_url: Optional[str] = None
    transcription: Optional[str] = None
    user_id: Optional[str] = None
    user_label: Optional[str] = None # Human readable label (Name/Email)
    chat_id: Optional[str] = None
    call_control_id: Optional[str] = None
    direction: str = Field(default="outbound") # inbound, outbound
