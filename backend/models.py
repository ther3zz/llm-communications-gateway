from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

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

class VoiceConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stt_url: str = Field(default="http://parakeet:8000")
    tts_url: str = Field(default="http://chatterbox:8000")
    llm_url: str = Field(default="http://open-webui:8080/v1")
    llm_provider: str = Field(default="custom", description="Preferred LLM provider (openai, ollama, open_webui, custom)")
    llm_api_key: Optional[str] = Field(default=None, description="API Key if needed (e.g. for OpenAI)")
    llm_model: str = Field(default="gpt-3.5-turbo")
    voice_id: str = Field(default="default")
    webhook_secret: Optional[str] = Field(default=None, description="Secret token for securing webhooks")
    stt_timeout: int = Field(default=10, description="Timeout in seconds for STT requests")
    tts_timeout: int = Field(default=10, description="Timeout in seconds for TTS requests")
    llm_timeout: int = Field(default=10, description="Timeout in seconds for LLM requests")
    system_prompt: Optional[str] = Field(default=None, description="Custom System Prompt for the Voice Bot")
    send_conversation_context: bool = Field(default=True, description="Whether to send full conversation history to LLM")


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
