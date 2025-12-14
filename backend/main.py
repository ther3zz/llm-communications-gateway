from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from .database import create_db_and_tables, engine
from sqlmodel import Session, select, text
from .models import ProviderConfig, VoiceConfig
from .utils.security import encrypt_value
import os
import uuid

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Debug Mode
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    if debug_mode:
        print("[DEBUG] --- STARTING APP: VERSION v2.2 (LLM Provider Support) ---")
        print("[DEBUG] Starting lifespan...")
        print(f"[DEBUG] Environment Keys: {[k for k in os.environ.keys() if any(x in k for x in ['TELNYX', 'POSTGRES', 'LLM', 'TTS', 'WEBHOOK', 'OLLAMA', 'OPEN_WEBUI', 'BASE', 'SYSTEM_PROMPT', 'INBOUND'])]}")

    create_db_and_tables()
    
    # --- Migrations ---
    # We must ensure columns exist before querying models that expect them.
    with Session(engine) as session:
        # 1. VoiceConfig Columns (llm_model, voice_id)
        try:
            session.exec(text("SELECT llm_model FROM voiceconfig LIMIT 1"))
        except Exception:
            print("Migrating: Adding llm_model/voice_id to voiceconfig")
            try:
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN llm_model VARCHAR DEFAULT 'gpt-3.5-turbo'"))
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN voice_id VARCHAR DEFAULT 'default'"))
                session.commit()
            except Exception as e:
                print(f"Migration failed (voiceconfig): {e}")

        # 2. ProviderConfig (app_id, webhook_secret, priority, base_url)
        try:
             session.exec(text("SELECT app_id FROM providerconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding app_id/webhook_secret/priority to providerconfig")
             try:
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN app_id VARCHAR"))
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN webhook_secret VARCHAR"))
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN priority INTEGER DEFAULT 0"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (providerconfig cols): {e}")

        try:
             session.exec(text("SELECT base_url FROM providerconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding base_url to providerconfig")
             try:
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN base_url VARCHAR"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (base_url): {e}")

        # 2b. ProviderConfig (Inbound)
        try:
             session.exec(text("SELECT inbound_enabled FROM providerconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding inbound cols to providerconfig")
             try:
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN inbound_system_prompt VARCHAR"))
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN inbound_enabled BOOLEAN DEFAULT 1"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (provider_inbound): {e}")
                 
        # 3. VoiceConfig Timeouts - (Existing logic skipped for brevity if not modified)

        # 4. Context Logging (user_id, chat_id)
        for table in ["messagelog", "calllog"]:
             try:
                 session.exec(text(f"SELECT user_id FROM {table} LIMIT 1"))
             except Exception:
                 print(f"Migrating: Adding context columns to {table}")
                 try:
                     session.exec(text(f"ALTER TABLE {table} ADD COLUMN user_id VARCHAR"))
                     session.exec(text(f"ALTER TABLE {table} ADD COLUMN chat_id VARCHAR"))
                     session.commit()
                 except Exception as e:
                     print(f"Migration failed ({table} context): {e}")
        try:
            session.exec(text("SELECT stt_timeout FROM voiceconfig LIMIT 1"))
        except Exception:
            print("Migrating: Adding timeouts to voiceconfig")
            try:
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN stt_timeout INTEGER DEFAULT 10"))
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN tts_timeout INTEGER DEFAULT 10"))
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN llm_timeout INTEGER DEFAULT 10"))
                session.exec(text("ALTER TABLE voiceconfig ADD COLUMN llm_timeout INTEGER DEFAULT 10"))
                # session.exec(text("ALTER TABLE voiceconfig ADD COLUMN inbound_system_prompt VARCHAR")) # REMOVED in Refactor
                session.commit()
            except Exception as e:
                print(f"Migration failed (timeouts): {e}")

        # 4. System Prompt
        try:
             session.exec(text("SELECT system_prompt FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding system_prompt to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN system_prompt VARCHAR"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (system_prompt): {e}")

        # 5. LLM Provider
        try:
             session.exec(text("SELECT llm_provider FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding llm_provider to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN llm_provider VARCHAR DEFAULT 'custom'"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (llm_provider): {e}")

        # 6. Call Direction
        try:
             session.exec(text("SELECT direction FROM calllog LIMIT 1"))
        except Exception:
             print("Migrating: Adding direction to calllog")
             try:
                 session.exec(text("ALTER TABLE calllog ADD COLUMN direction VARCHAR DEFAULT 'outbound'"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (direction): {e}")

        # 7. Provider Call Duration Limits
        try:
             session.exec(text("SELECT max_call_duration FROM providerconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding duration limits to providerconfig")
             try:
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN max_call_duration INTEGER DEFAULT 600"))
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN call_limit_message VARCHAR DEFAULT 'This call has reached its time limit. Goodbye.'"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (duration limits): {e}")

        # 8. Send Conversation Context
        try:
             session.exec(text("SELECT send_conversation_context FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding send_conversation_context to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN send_conversation_context BOOLEAN DEFAULT 1"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (send_conversation_context): {e}")

             except Exception as e:
                 print(f"Migration failed (send_conversation_context): {e}")

        # 7. Call Control ID
        try:
             session.exec(text("SELECT call_control_id FROM calllog LIMIT 1"))
        except Exception:
             print("Migrating: Adding call_control_id to calllog")
             try:
                 session.exec(text("ALTER TABLE calllog ADD COLUMN call_control_id VARCHAR"))
                 session.commit()
             except Exception as e:
                 # This might fail if table doesn't exist yet (created by SQLModel on fresh run), which is fine.
                 print(f"Migration failed (call_control_id): {e}")

        # 8. MMS Media URL (MessageLog)
        try:
             session.exec(text("SELECT media_url FROM messagelog LIMIT 1"))
        except Exception:
             print("Migrating: Adding media_url to messagelog")
             try:
                 session.exec(text("ALTER TABLE messagelog ADD COLUMN media_url VARCHAR"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (media_url): {e}")

        # 9. RTP Codec (VoiceConfig)
        try:
             session.exec(text("SELECT rtp_codec FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding rtp_codec to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN rtp_codec VARCHAR DEFAULT 'PCMU'"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (rtp_codec): {e}")

        # 10. Open WebUI Integration
        try:
             session.exec(text("SELECT open_webui_admin_token FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding open_webui_admin_token to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN open_webui_admin_token VARCHAR"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (open_webui_admin_token): {e}")

        try:
             session.exec(text("SELECT assigned_user_id FROM providerconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding assigned_user fields to providerconfig")
             try:
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN assigned_user_id VARCHAR"))
                 session.exec(text("ALTER TABLE providerconfig ADD COLUMN assigned_user_label VARCHAR"))
                 session.commit()
             except Exception as e:
                print(f"Migration failed (assigned_user): {e}")

        # 11. Inbound Alert Channel Name
        try:
             session.exec(text("SELECT alert_channel_name FROM voiceconfig LIMIT 1"))
        except Exception:
             print("Migrating: Adding alert_channel_name to voiceconfig")
             try:
                 session.exec(text("ALTER TABLE voiceconfig ADD COLUMN alert_channel_name VARCHAR DEFAULT 'LLM-Communications-Gateway Alerts'"))
                 session.commit()
             except Exception as e:
                 print(f"Migration failed (alert_channel_name): {e}")

    # --- Seeding ---
    
    # Seed from Env (Telnyx)
    with Session(engine) as session:
        telnyx_key = os.getenv("TELNYX_API_KEY")
        if telnyx_key:
            if debug_mode: print("[DEBUG] Found TELNYX_API_KEY in environment.")
            
            provider = session.exec(select(ProviderConfig).where(ProviderConfig.name == "telnyx")).first()
            if not provider:
                print("Seeding Telnyx Provider from Env")
                provider = ProviderConfig(
                    name="telnyx",
                    api_key=encrypt_value(telnyx_key),
                    api_url="https://api.telnyx.com/v2",
                    from_number=os.getenv("TELNYX_FROM_NUMBER", "+15550000000"),
                    app_id=os.getenv("TELNYX_APP_ID", ""),
                    webhook_secret=uuid.uuid4().hex,
                    enabled=True,
                    priority=0
                )
                session.add(provider)
                session.commit()
                print("Telnyx Provider seeded successfully.")
            else:
                if debug_mode: print("[DEBUG] Telnyx provider already exists in DB. Checking for updates...")
                updates = False
                env_app_id = os.getenv("TELNYX_APP_ID")
                if env_app_id and provider.app_id != env_app_id:
                     print(f"Updating Telnyx App ID from Env: {env_app_id}")
                     provider.app_id = env_app_id
                     updates = True

                env_inbound_prompt = os.getenv("INBOUND_SYSTEM_PROMPT")
                if env_inbound_prompt and provider.inbound_system_prompt != env_inbound_prompt:
                     print(f"Updating Telnyx Inbound Prompt from Env")
                     provider.inbound_system_prompt = env_inbound_prompt
                     updates = True

                if updates:
                    session.add(provider)
                    session.commit()
        else:
            if debug_mode: print("[DEBUG] TELNYX_API_KEY not found in environment. Skipping Telnyx seeding.")

    # Ensure all providers have secrets
    with Session(engine) as session:
         providers = session.exec(select(ProviderConfig)).all()
         for p in providers:
             if not p.webhook_secret:
                 p.webhook_secret = uuid.uuid4().hex
                 session.add(p)
         session.commit()

    # Seed VoiceConfig
    with Session(engine) as session:
        v_config = session.exec(select(VoiceConfig)).first()
        updated = False
        
        # defaults
        stt_url_def = os.getenv("STT_URL", "http://parakeet:8000")
        tts_url_def = os.getenv("TTS_URL", "http://chatterbox:8000")
        llm_url_def = os.getenv("LLM_URL", "http://open-webui:8080/api/v1")
        
        if not v_config:
            if debug_mode: print("[DEBUG] Creating default VoiceConfig.")
            v_config = VoiceConfig(
                webhook_secret=uuid.uuid4().hex,
                stt_url=stt_url_def,
                tts_url=tts_url_def,
                llm_url=llm_url_def,
                llm_provider=os.getenv("DEFAULT_LLM_PROVIDER", "custom")
            )
            session.add(v_config)
            session.commit()
            session.refresh(v_config)
            # We don't mark 'updated = True' yet, we just continue to check specific Env overrides/extensions below
        
        # Apply Env Vars (Create or Update)
        
        # Base URL for Telnyx
        base_url_env = os.getenv("BASE_URL")
        if base_url_env:
            telnyx_main = session.exec(select(ProviderConfig).where(ProviderConfig.name == "telnyx")).first()
            if telnyx_main and telnyx_main.base_url != base_url_env:
                print(f"[DEBUG] Updating Telnyx Base URL from Env: {base_url_env}")
                telnyx_main.base_url = base_url_env
                session.add(telnyx_main)
                session.commit()

        # Voice Config Fields
        # 1. Webhook Secret
        env_secret = os.getenv("WEBHOOK_SECRET")
        if env_secret:
            if v_config.webhook_secret != env_secret:
                print(f"[DEBUG] Updating Webhook Secret from Env")
                v_config.webhook_secret = env_secret
                updated = True
            
            # Sync to Telnyx Provider
            telnyx_p = session.exec(select(ProviderConfig).where(ProviderConfig.name == "telnyx")).first()
            if telnyx_p and telnyx_p.webhook_secret != env_secret:
                telnyx_p.webhook_secret = env_secret
                session.add(telnyx_p)
                session.commit()
        elif not v_config.webhook_secret:
             v_config.webhook_secret = uuid.uuid4().hex
             updated = True

        # 2. URLs (if Env is present, enforce it)
        if os.getenv("STT_URL") and v_config.stt_url != os.getenv("STT_URL"):
             print(f"[DEBUG] Updating STT URL from Env: {os.getenv('STT_URL')}")
             v_config.stt_url = os.getenv("STT_URL")
             updated = True
        if os.getenv("TTS_URL") and v_config.tts_url != os.getenv("TTS_URL"):
             print(f"[DEBUG] Updating TTS URL from Env: {os.getenv('TTS_URL')}")
             v_config.tts_url = os.getenv("TTS_URL")
             updated = True
        
        # 4. LLM Provider (Default) - Resolve FIRST to guide URL selection
        env_provider = os.getenv("DEFAULT_LLM_PROVIDER")
        if env_provider and v_config.llm_provider != env_provider:
            print(f"[DEBUG] Updating LLM Provider from Env: {env_provider}")
            v_config.llm_provider = env_provider
            updated = True

        # 3. LLM URL Resolution (Provider-Aware)
        llm_url_source = None
        final_llm_url = None
        
        # Decide which Env Var to prioritize based on the active provider
        active_provider = v_config.llm_provider
        
        if active_provider == "ollama" and os.getenv("OLLAMA_URL"):
            final_llm_url = os.getenv("OLLAMA_URL")
            llm_url_source = "OLLAMA_URL"
            # Auto-fix Ollama URL if missing /v1
            if final_llm_url and not final_llm_url.endswith("/v1"):
                 final_llm_url = f"{final_llm_url.rstrip('/')}/v1"
                 
        elif active_provider == "openwebui" and os.getenv("OPEN_WEBUI_URL"):
            final_llm_url = os.getenv("OPEN_WEBUI_URL")
            llm_url_source = "OPEN_WEBUI_URL"
            # Open WebUI uses /api/v1
            if final_llm_url and not final_llm_url.endswith("/api/v1"):
                 final_llm_url = f"{final_llm_url.rstrip('/')}/api/v1"
        
        elif os.getenv("LLM_URL"):
            # Fallback or Custom
            final_llm_url = os.getenv("LLM_URL")
            llm_url_source = "LLM_URL"
            
        # If we didn't find specific ones but have the others present, maybe fallback?
        # But safest is to stick to the requested provider's var. 
        # If user selected 'ollama' but didn't set OLLAMA_URL, check LLM_URL.
        if not final_llm_url and os.getenv("LLM_URL"):
             final_llm_url = os.getenv("LLM_URL")
             llm_url_source = "LLM_URL"

        if final_llm_url and v_config.llm_url != final_llm_url:
             print(f"[DEBUG] Updating LLM URL from Env Var '{llm_url_source}': {final_llm_url}")
             v_config.llm_url = final_llm_url
             updated = True

        # 5. Models and Keys
        env_llm_model = os.getenv("LLM_MODEL")
        if env_llm_model and v_config.llm_model != env_llm_model:
            print(f"[DEBUG] Updating LLM Model from Env: {env_llm_model}")
            v_config.llm_model = env_llm_model
            updated = True
        
        env_voice_id = os.getenv("TTS_VOICE_ID")
        if env_voice_id and v_config.voice_id != env_voice_id:
            print(f"[DEBUG] Updating Voice ID from Env: {env_voice_id}")
            v_config.voice_id = env_voice_id
            updated = True

        env_llm_key = os.getenv("LLM_API_KEY")
        if env_llm_key:
            # Policy: If Env is present, does it overwrite? 
            # User said "set from env if none stored".
            # Check if stored is empty/None.
            if not v_config.llm_api_key:
                print(f"[DEBUG] Setting LLM API Key from Env (was empty)")
                v_config.llm_api_key = encrypt_value(env_llm_key)
                updated = True
             
        # 6. Timeouts & System Prompt
        env_llm_timeout = os.getenv("LLM_TIMEOUT")
        if env_llm_timeout:
             try:
                 val = int(env_llm_timeout)
                 if v_config.llm_timeout != val:
                     print(f"[DEBUG] Updating LLM Timeout from Env: {val}")
                     v_config.llm_timeout = val
                     updated = True
             except: pass

        env_stt_timeout = os.getenv("STT_TIMEOUT")
        if env_stt_timeout:
             try:
                 val = int(env_stt_timeout)
                 if v_config.stt_timeout != val:
                     print(f"[DEBUG] Updating STT Timeout from Env: {val}")
                     v_config.stt_timeout = val
                     updated = True
             except: pass

        env_tts_timeout = os.getenv("TTS_TIMEOUT")
        if env_tts_timeout:
             try:
                 val = int(env_tts_timeout)
                 if v_config.tts_timeout != val:
                     print(f"[DEBUG] Updating TTS Timeout from Env: {val}")
                     v_config.tts_timeout = val
                     updated = True
             except: pass

        env_system_prompt = os.getenv("SYSTEM_PROMPT")
        if env_system_prompt and v_config.system_prompt != env_system_prompt:
             print(f"[DEBUG] Updating System Prompt from Env")
             v_config.system_prompt = env_system_prompt
             updated = True
        
        env_send_context = os.getenv("SEND_CONVERSATION_CONTEXT")
        if env_send_context is not None:
             # handle booleans
             val = env_send_context.lower() == "true"
             if v_config.send_conversation_context != val:
                 print(f"[DEBUG] Updating Send Context from Env: {val}")
                 v_config.send_conversation_context = val
                 updated = True

        env_rtp_codec = os.getenv("RTP_CODEC")
        if env_rtp_codec and v_config.rtp_codec != env_rtp_codec:
             print(f"[DEBUG] Updating RTP Codec from Env: {env_rtp_codec}")
             v_config.rtp_codec = env_rtp_codec
             updated = True

        if updated:
            session.add(v_config)
            session.commit()
            if debug_mode: print("[DEBUG] VoiceConfig updated from Environment.")

        if debug_mode:
            print(f"[DEBUG] Final Active Config -> STT: {v_config.stt_url} | TTS: {v_config.tts_url}")
            print(f"[DEBUG] Final Active Config -> LLM Provider: {v_config.llm_provider}")
            print(f"[DEBUG] Final Active Config -> LLM URL: {v_config.llm_url} (Model: {v_config.llm_model})")
            print(f"[DEBUG] Final Active Config -> System Prompt Preview: {v_config.system_prompt[:50] if v_config.system_prompt else 'None'}...")

    yield

app = FastAPI(lifespan=lifespan)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

from .routers import api, voice_api
app.include_router(api.router, prefix="/api")
app.include_router(voice_api.router, prefix="/api")

# Mount frontend
import os
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
else:
    print("Warning: frontend/dist not found. Static files will not be served.")

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
