from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Request, Query
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
import json
import base64
import struct
import io
import requests
import httpx
import re
import audioop
import math
import uuid
import asyncio
from asyncio import Queue
import urllib.parse
import os

from ..database import get_session
from ..models import ProviderConfig, VoiceConfig, CallLog, UserChannel
from ..providers.telnyx import TelnyxProvider
from ..utils.parakeet import ParakeetClient
from ..utils.chatterbox import ChatterboxClient
from ..utils.security import decrypt_value
from ..utils import openwebui

router = APIRouter()

class CallRequest(BaseModel):
    to_number: str
    provider: str # Required now
    from_number: Optional[str] = None
    prompt: Optional[str] = None # Initial system prompt for the agent logic
    delay_ms: Optional[int] = 0 # Delay in BEFORE sending audio (to avoid overlap with "This is an automated call")
    user_id: Optional[str] = None
    chat_id: Optional[str] = None
    
class WebhookQuery(BaseModel):
    token: str

class SyncRequest(BaseModel):
    provider: str
    base_url: str # Base URL of the server (e.g. https://myapp.ngrok.io)

class CreateAppRequest(BaseModel):
    provider: str
    name: str # Name for the new app
    api_key: str # API key to use (might not be saved yet)
    base_url: str

# --- Audio Utilities ---
PRELOADED_STREAMS = {} # call_id -> asyncio.Queue of media chunks (or None for EOF)
STREAM_ID_MAP = {} # short_id -> call_id
CALL_CONTEXT = {} # call_id -> {user_id, chat_id}
DEBUG_AUDIO_DIR = "backend/debug_audio"
if not os.path.exists(DEBUG_AUDIO_DIR):
    os.makedirs(DEBUG_AUDIO_DIR, exist_ok=True)



def process_tts_stream(audio_stream, voice_id: str, codec: str = "PCMU"):
    """
    Consumes an ASYNC audio stream (PCM/WAV), resamples/transcodes it, and YIELDS encoded chunks as JSON strings.
    WARNING: Because this yields, it must be iterated with 'async for' by the caller if audio_stream is async.
    Actually, creating an 'async generator' requires 'async def'.
    """
    return _process_tts_stream_async(audio_stream, voice_id, codec)

async def _process_tts_stream_async(audio_stream, voice_id, codec):
    """
    Async implementation of audio processing
    """
    print(f"Processing TTS Stream for Voice: {voice_id} (Target Codec: {codec})")
    
    # State for resampling/transcoding
    state = None
    audio_buffer = bytearray()
    
    # WAV Header Parsing State
    header_parsed = False
    header_buffer = bytearray()
    HEADER_SIZE = 44
    
    in_rate = 24000 # Default fallback
    
    async for chunk in audio_stream:
        if not header_parsed:
            header_buffer.extend(chunk)
            if len(header_buffer) >= HEADER_SIZE:
                # Parse RIFF Header to find Sample Rate
                try:
                    # .. Check RIFF ...
                     rate_packed = header_buffer[24:28]
                     in_rate = struct.unpack('<I', rate_packed)[0]
                     print(f"Detected TTS Sample Rate: {in_rate}Hz")
                     header_parsed = True
                     
                     # Process remaining bytes in this chunk as audio
                     remaining = header_buffer[HEADER_SIZE:]
                     audio_buffer.extend(remaining)
                except Exception as e:
                    print(f"Error parsing WAV header: {e}. Defaulting to 24000.")
                    header_parsed = True # Skip parsing to avoid stuck loop
                    audio_buffer.extend(header_buffer)
            continue
            
        audio_buffer.extend(chunk)
        
        # This prevents 'not a whole number of frames' errors in audioop
        BLOCK_SIZE = 960
        
        while len(audio_buffer) >= BLOCK_SIZE:
             # Extract block
            raw_block = bytes(audio_buffer[:BLOCK_SIZE])
            del audio_buffer[:BLOCK_SIZE]
            
            # Target Rate: 8000 for L16 (Telnyx PSTN usually forces 8k even for L16), 8000 for PCMU/PCMA
            target_rate = 8000
            
            # Resample if needed
            processed_block = raw_block
            if in_rate != target_rate:
                try:
                    processed_block, state = audioop.ratecv(raw_block, 2, 1, in_rate, target_rate, state)
                except Exception as e:
                    print(f"Resampling error (block): {e}")
                    continue

            # Encode
            try:
               if codec == "L16":
                   encoded_data = processed_block
               elif codec == "PCMA":
                   encoded_data = audioop.lin2alaw(processed_block, 2)
               else:
                   encoded_data = audioop.lin2ulaw(processed_block, 2)

               b64_payload = base64.b64encode(encoded_data).decode('utf-8')
               yield json.dumps({
                   "event": "media", 
                   "media": {
                       "payload": b64_payload
                   }
               })
            except Exception as e:
                print(f"Encoding error: {e}")

    # Process remaining remainder (if even)
    if len(audio_buffer) > 0 and len(audio_buffer) % 2 == 0:
         target_rate = 8000
         try:
             processed_block = bytes(audio_buffer)
             if in_rate != target_rate:
                  processed_block, state = audioop.ratecv(bytes(audio_buffer), 2, 1, in_rate, target_rate, state)
             
             if codec == "L16":
                encoded_data = processed_block
             elif codec == "PCMA":
                encoded_data = audioop.lin2alaw(processed_block, 2)
             else:
                encoded_data = audioop.lin2ulaw(processed_block, 2)
                
             b64_payload = base64.b64encode(encoded_data).decode('utf-8')
             yield json.dumps({"event": "media", "media": {"payload": b64_payload}})
         except Exception as e:
             print(f"Remainder error: {e}")

async def generate_initial_audio(prompt: str, voice_config_data: dict, stream_queue: Optional[Queue] = None, call_id: Optional[str] = None) -> tuple:
    """
    Generate audio chunks for the prompt.
    If stream_queue is provided, pushes chunks to it asynchronously.
    Returns (audio_buffer, text).
    """
    print(f"Generating initial audio for prompt: {prompt}")
    audio_buffer = []
    try:
        # 1. LLM Generation
        llm_url = voice_config_data.get("llm_url")
        llm_api_key = voice_config_data.get("llm_api_key")
        llm_model = voice_config_data.get("llm_model")
        voice_id = voice_config_data.get("voice_id")
        llm_timeout = voice_config_data.get("llm_timeout", 10)
        tts_timeout = voice_config_data.get("tts_timeout", 10)
        tts_url = voice_config_data.get("tts_url", "http://chatterbox:8000")
        
        system_prompt = voice_config_data.get("system_prompt")
        
        # Combine global system prompt with specific call prompt
        if system_prompt:
             final_system_message = f"{system_prompt}\n\nCurrent Call Goal: {prompt}"
        else:
             final_system_message = prompt
             
        chat_payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": final_system_message},
                {"role": "user", "content": "Introduce yourself."}
            ],
            "stream": False 
        }
        print(f"[DEBUG] Initial Audio Context: {chat_payload['messages']}")
        headers = {"Authorization": f"Bearer {llm_api_key}"} if llm_api_key else {}
        
        reply = None
        try:
            llm_resp = requests.post(f"{llm_url.rstrip('/')}/chat/completions", json=chat_payload, headers=headers, timeout=llm_timeout)
            if llm_resp.status_code == 200:
                reply = llm_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"Agent Reply: {reply}")
            else:
                 print(f"LLM Error: {llm_resp.status_code} {llm_resp.text}")
        except Exception as e:
            print(f"LLM Exception: {e}")
            
        except Exception as e:
            print(f"LLM Exception: {e}")
            
        if reply:
            # IMMEDIATE CONTEXT UPDATE (Fix for Missing Greeting)
            if call_id:
                if call_id not in CALL_CONTEXT: CALL_CONTEXT[call_id] = {}
                CALL_CONTEXT[call_id]["initial_greeting"] = reply
                print(f"[DEBUG] Stored initial greeting for {call_id} immediately after LLM generation.")

            # 2. TTS Generation
            try:
                tts_client = ChatterboxClient(base_url=tts_url)
                tts_stream = tts_client.speak_stream(reply, voice_id=voice_id, timeout=tts_timeout)
                codec = voice_config_data.get("rtp_codec", "PCMU")
                
                async for msg_json in process_tts_stream(tts_stream, voice_id, codec=codec):
                    audio_buffer.append(msg_json)
                    if stream_queue:
                        await stream_queue.put(msg_json)
                    
                print(f"Audio generation complete. Buffered {len(audio_buffer)} chunks.")
                
            except Exception as e:
                print(f"TTS Error: {e}")
                
    except Exception as e:
        print(f"General Generation Error: {e}")
        
    # Signal EOF to queue
    if stream_queue:
        await stream_queue.put(None)
        
    return audio_buffer, reply if reply else ""

async def preload_inbound_audio(call_control_id: str, prompt: str, voice_config_data: dict):
    """
    Background task to generate and store initial audio for inbound calls.
    """
    print(f"[DEBUG] interactive_preload: Starting generation for {call_control_id} (Prompt: {prompt})")
    stream_queue = Queue()
    PRELOADED_STREAMS[call_control_id] = stream_queue
    
    # Generate will push to queue (streaming)
    _, text = await generate_initial_audio(prompt, voice_config_data, stream_queue=stream_queue, call_id=call_control_id)
    
    if text:
        print(f"[DEBUG] interactive_preload: Storing initial greeting for {call_control_id}: '{text}'")
        if call_control_id not in CALL_CONTEXT:
            CALL_CONTEXT[call_control_id] = {}
        CALL_CONTEXT[call_control_id]["initial_greeting"] = text

    print(f"[DEBUG] interactive_preload: Generation task finished for {call_control_id}")

def create_wav_header(pcm_data: bytes, sample_rate: int = 8000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    header = b'RIFF'
    header += struct.pack('<I', 36 + len(pcm_data))
    header += b'WAVEfmt '
    header += struct.pack('<I', 16) 
    header += struct.pack('<H', 1) 
    header += struct.pack('<H', channels)
    header += struct.pack('<I', sample_rate)
    header += struct.pack('<I', sample_rate * channels * (bits_per_sample // 8))
    header += struct.pack('<H', channels * (bits_per_sample // 8))
    header += struct.pack('<H', bits_per_sample)
    header += b'data'
    header += struct.pack('<I', len(pcm_data))
    return header + pcm_data

@router.websocket("/voice/stream/{short_id}")
async def websocket_endpoint(websocket: WebSocket, short_id: str, token: Optional[str] = None, delay_ms: int = 0):
    await websocket.accept()
    
    map_data = STREAM_ID_MAP.get(short_id)
    if not map_data:
        print(f"[ERROR] Unknown stream short_id: {short_id}. Closing.")
        await websocket.close()
        return

    call_id = map_data.get("call_id") if isinstance(map_data, dict) else map_data
    db_id = map_data.get("db_id") if isinstance(map_data, dict) else None
    initial_prompt = map_data.get("prompt") if isinstance(map_data, dict) else None

    print(f"WebSocket connected for short_id: {short_id} -> call_id: {call_id} (Token: {token})")
    print(f"WS ID: {call_id}. DB ID: {db_id}. Prompt Override: {bool(initial_prompt)}")
    
    stream_id = None

    # 1. Strict Handshake Loop: Wait for 'start' before doing ANYTHING media-related
    try:
        print("[DEBUG] Entering Handshake Loop...")
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get("event")
            print(f"[DEBUG] Handshake Event: {event}")

            if event == "connected":
                 print(f"[DEBUG] Received 'connected'. sending silence to wake up stream...")
                 # Send 1 second of silence to "wake up" the stream / satisfy Telnyx initial media requirement
                 silence_frame = b'\x00' * 160 # 20ms of silence (PCMU/8k)
                 # Send a burst of 50 frames (1 second)
                 for _ in range(50):
                      media_message = {
                          "event": "media",
                          "media": {
                              "payload": base64.b64encode(silence_frame).decode(),
                              "stream_id": short_id
                          }
                      }
                      await websocket.send_text(json.dumps(media_message))
                      await asyncio.sleep(0.02)
                 print("[DEBUG] Initial silence sent. Waiting for 'start'...")
                 continue
            elif event == "start":
                 stream_id = msg.get("stream_id")
                 print(f"[DEBUG] Received 'start' (ID: {stream_id}). Handshake complete.")
                 break
            elif event == "media":
                 # Fallback: If we receive media before 'start' (rare, but possible if timing off), assume started.
                 # Usually 'media' event has 'stream_id' inside it or in metadata.
                 # Telnyx Media Packet: { event: "media", stream_id: "...", media: ... }
                 stream_id = msg.get("stream_id")
                 if stream_id:
                     print(f"[DEBUG] Received 'media' (ID: {stream_id}) before 'start'. Assuming started.")
                     # Re-inject this media packet into the buffer so we don't lose it?
                     # Since we haven't entered the main loop, we can just consume it here or push it.
                     # But we are breaking out, and the main loop will run 'receive_text' again.
                     # So we WILL lose this packet unless we hack it.
                     # Actually, breaking here means the main loop starts RE-READING. 
                     # The main loop reads 'websocket.receive_text()'. 
                     # If we consumed it here, it's GONE.
                     # We must process it manually here or store it.
                     # Let's just break and accept the loss of 20ms of audio (silence usually).
                     break
            elif event == "stop":
                 print("[DEBUG] Received stop during handshake.")
                 return
    except Exception as e:
        print(f"Error during handshake: {e}")
        try:
             await websocket.close()
        except: pass
        return

    session_gen = get_session()
    session = next(session_gen)
    
    # Config default lookup
    stt_url = "http://parakeet:8000"
    tts_url = "http://chatterbox:8000"
    
    # Duration limit setup
    max_duration = map_data.get("max_duration", 600) if isinstance(map_data, dict) else 600
    limit_message = map_data.get("limit_message", "This call has reached its time limit. Goodbye.") if isinstance(map_data, dict) else "This call has reached its time limit. Goodbye."
    
    # Define monitor task
    async def monitor_call_duration():
        try:
            print(f"[DEBUG] Call Monitor: Watching for limit {max_duration}s for {call_id}")
            await asyncio.sleep(max_duration)
            print(f"[WARN] Call Monitor: Limit reached for {call_id}. Terminating...")
            
            # 1. Stop conversation tasks
            if sender_task: sender_task.cancel()
            if turn_tasks: 
                 for t in turn_tasks: t.cancel()
            
            # 2. Generate and Play Limit Message
            # 2. Generate and Play Limit Message
            print(f"[DEBUG] Call Monitor: Generating termination TTS via ChatterboxClient...")
            try:
                 # Use global Tts Client (already instantiated as tts_client)
                 # Cancel sender task to release socket if needed, though concurrency allows mixing.
                 # But we want to INTERRUPT.
                 
                 # Send interrupt silence first
                 interrupt_silence = json.dumps({
                     "event": "clear", # Hypothetical clear event or just silence
                     "stream_id": stream_id
                 })
                 # await websocket.send_text(interrupt_silence) 
                 
                 # Stream TTS
                 tts_stream = tts_client.speak_stream(limit_message, voice_id=voice_id, timeout=10)
                 
                 print(f"[DEBUG] Call Monitor: Streaming limit message...")
                 async for msg_json in process_tts_stream(tts_stream, voice_id, codec=rtp_codec):
                      # Inject stream_id
                      chunk_obj = json.loads(msg_json)
                      chunk_obj["stream_id"] = short_id
                      try:
                          await websocket.send_text(json.dumps(chunk_obj))
                      except RuntimeError as e:
                           if "close message has been sent" in str(e):
                               print("[DEBUG] Call Monitor: Socket closed during TTS. Stopping.")
                               return
                           raise e
                 
                 # Wait for playback (approx 2s buffer trail)
                 await asyncio.sleep(2.0)

            except Exception as e:
                 print(f"[ERROR] Call Monitor TTS Exception: {e}")
                 import traceback
                 traceback.print_exc()

            print(f"[DEBUG] Call Monitor: Initiating Hard Hangup for {call_id}...")
            
            # 3. Hard Hangup via Telnyx API
            try:
                # We need to find the provider config to get the API Key.
                # In this scope, we might not have 'provider_id'. 
                # But we can try to find the Telnyx provider or use env var.
                # Ideally, we should have passed provider config to this function, but let's look it up.
                # Fallback to env var if database lookup fails or is complex here.
                api_key = os.getenv("TELNYX_API_KEY")
                print(f"[DEBUG] Call Monitor: Hard Hangup API Key Present: {bool(api_key)}")
                
                # Try to get from DB if possible
                if not api_key:
                    # Quick separate session lookup if needed, or rely on Env.
                    pass

                if api_key:
                    from ..providers.telnyx import TelnyxProvider
                    provider = TelnyxProvider(api_key=api_key)
                    # Use 'call_id' which is the Telnyx Call Control ID mapped to 'short_id' in our loop?
                    # Wait, 'call_id' variable in this scope IS the call_control_id (v3:...) passed to websocket_endpoint
                    print(f"[DEBUG] Call Monitor: Sending Hangup Command for {call_id}...")
                    result = provider.hangup_call(call_id)
                    print(f"[DEBUG] Call Monitor: Hangup Result: {result}")
                else:
                    print(f"[WARN] Call Monitor: No API Key found for hard hangup.")

            except Exception as e:
                print(f"[ERROR] Call Monitor Hangup Failed: {e}")

            print(f"[DEBUG] Call Monitor: Closing connection.")
            await websocket.close(code=1000, reason="Duration Limit Reached")
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
             print(f"[ERROR] Call Monitor failed: {e}")

    monitor_task = asyncio.create_task(monitor_call_duration())

    try:
        voice_config = session.exec(select(VoiceConfig)).first()
        llm_url = (voice_config.llm_url if voice_config else None) or "http://open-webui:8080/v1"
        llm_api_key = decrypt_value(voice_config.llm_api_key) if voice_config and voice_config.llm_api_key else None
        llm_model = (voice_config.llm_model if voice_config else None) or "gpt-3.5-turbo"
        voice_id = (voice_config.voice_id if voice_config else None) or "default"
        db_system_prompt = voice_config.system_prompt if voice_config else None
        
        stt_timeout = voice_config.stt_timeout if voice_config and voice_config.stt_timeout else 10
        tts_timeout = voice_config.tts_timeout if voice_config and voice_config.tts_timeout else 10
        llm_timeout = voice_config.llm_timeout if voice_config and voice_config.llm_timeout else 10
        
        if voice_config and voice_config.stt_url: stt_url = voice_config.stt_url
        if voice_config and voice_config.tts_url: tts_url = voice_config.tts_url
        
        send_context = voice_config.send_conversation_context if voice_config else True
        rtp_codec = (voice_config.rtp_codec if voice_config else None) or "PCMU"
        
        print(f"[DEBUG] Loaded Timeouts from DB -> LLM: {llm_timeout}, TTS: {tts_timeout}, STT: {stt_timeout}")
        
        
    except Exception as e:
        print(f"Config Error: {e}")
        llm_url = "http://open-webui:8080/v1"
        llm_api_key = None
        llm_model = "gpt-3.5-turbo"
        voice_id = "default"
        db_system_prompt = None
        stt_timeout = 10
        tts_timeout = 10
        llm_timeout = 10
        # stt_url/tts_url remain defaults
    finally:
        session.close()

    stt_client = ParakeetClient(base_url=stt_url)
    tts_client = ChatterboxClient(base_url=tts_url)
    
    # Initialize VAD buffer early for access in inner functions
    inbound_buffer = bytearray()
    
    start_time = asyncio.get_event_loop().time()
    full_transcription = []
    conversation_history = []  # Maintain conversation state
    
    # Check for initial greeting (pre-generated)
    ctx = CALL_CONTEXT.get(call_id, {})
    if ctx.get("initial_greeting"):
        greeting = ctx["initial_greeting"]
        print(f"[DEBUG] Found initial greeting for {call_id}: {greeting}")
        full_transcription.append(f"Assistant: {greeting}")
        conversation_history.append({"role": "assistant", "content": greeting})

    # 2. Concurrency Setup
    # We spawn a background task to handle the "Sending" of initial audio (Silence -> Delay -> Preloaded).
    # This allows the Main Loop to immediately start "Receiving" (handling Pings, Stops, or Interruptions).
    
    is_bot_speaking = True

    async def send_initial_sequence():
        nonlocal is_bot_speaking
        try:
            # 2a. Send Silence Burst
            print(f"[DEBUG] [Sender] Sending silence to establish audio path...")
            for silence_chunk in generate_silence(duration_sec=0.5, codec=rtp_codec):
                await websocket.send_text(json.dumps({
                    "event": "media",
                    "stream_id": stream_id,
                    "media": {
                        "payload": silence_chunk
                    }
                }))
                await asyncio.sleep(0.02)

            # 2b. Delay
            if delay_ms > 0:
                 print(f"[DEBUG] [Sender] Applying audio delay of {delay_ms}ms with continuous silence...")
                 num_silence_chunks = int(delay_ms / 20)
                 for _ in range(num_silence_chunks):
                     for silence_chunk in generate_silence(duration_sec=0.02, codec=rtp_codec):
                         await websocket.send_text(json.dumps({
                             "event": "media",
                             "stream_id": stream_id,
                             "media": {
                                 "payload": silence_chunk
                             }
                         }))
                     await asyncio.sleep(0.02)

            # 2c. Preloaded Audio
            # Poll for preloaded audio if this is an inbound call (initial_prompt is set)
            # and it hasn't arrived yet.
            # Poll for the *Queue* if this is an inbound call (initial_prompt is set)
            if initial_prompt:
                 queue = None
                 # Use configured timeouts
                 total_wait_sec = (llm_timeout or 10) + (tts_timeout or 10)
                 polling_iter = int(total_wait_sec * 10)
                 
                 found_queue = False
                 for i in range(polling_iter):
                      if call_id in PRELOADED_STREAMS:
                          queue = PRELOADED_STREAMS[call_id]
                          found_queue = True
                          break
                      if i % 20 == 0:
                          print(f"[DEBUG] [Sender] Waiting for Stream Queue... {i/10}s")
                      await asyncio.sleep(0.1)
                 
                 if found_queue and queue:
                     print(f"[DEBUG] [Sender] Streaming from Queue for {call_id}...")
                     
                     # LATE BINDING: Check if greeting text is available now (race condition fix)
                     ctx = CALL_CONTEXT.get(call_id, {})
                     if ctx.get("initial_greeting") and not any(m['role'] == 'assistant' for m in conversation_history):
                         greeting = ctx["initial_greeting"]
                         print(f"[DEBUG] [Sender] Late-binding initial greeting: {greeting}")
                         full_transcription.append(f"Assistant: {greeting}")
                         conversation_history.append({"role": "assistant", "content": greeting})

                     chunks_sent = 0
                     while True:
                         try:
                             chunk = await queue.get()
                             if chunk is None:
                                 queue.task_done()
                                 break
                             
                             try:
                                 chunk_obj = json.loads(chunk)
                                 if stream_id and "stream_id" not in chunk_obj:
                                     chunk_obj["stream_id"] = stream_id
                                     chunk = json.dumps(chunk_obj)
                             except: pass

                             await websocket.send_text(chunk)
                             chunks_sent += 1
                             queue.task_done()
                         except Exception as e:
                             print(f"[ERROR] Stream consumption error: {e}")
                             break
                     print(f"[DEBUG] [Sender] Stream finished. Sent {chunks_sent} chunks.")
                 else:
                     print(f"[WARN] [Sender] Stream Queue never appeared for {call_id}. Skipping.")
            elif call_id in PRELOADED_STREAMS:
                 # Outbound case
                 queue = PRELOADED_STREAMS[call_id]
                 chunks_sent = 0
                 while True:
                     chunk = await queue.get()
                     if chunk is None:
                         queue.task_done()
                         break
                     
                     try:
                         chunk_obj = json.loads(chunk)
                         if stream_id and "stream_id" not in chunk_obj:
                             chunk_obj["stream_id"] = stream_id
                             chunk = json.dumps(chunk_obj)
                     except: pass
                     
                     await websocket.send_text(chunk)
                     chunks_sent += 1
                     queue.task_done()
                 print(f"[DEBUG] [Sender] Outbound/Ready stream finished. Sent {chunks_sent} chunks.")
            
            # Wait for echo tail (increased for inbound latency)
            await asyncio.sleep(2.0)
                 
        except asyncio.CancelledError:
            print("[DEBUG] [Sender] Task cancelled.")
            raise
        except WebSocketDisconnect:
            print("[WARN] [Sender] WebSocket disconnected.")
        except Exception as e:
            print(f"[ERROR] [Sender] Error: {e}")
        finally:
            print("[DEBUG] [Sender] Listening enabled (is_bot_speaking = False). Clearing Buffer.")
            is_bot_speaking = False
            inbound_buffer.clear()

    DEFAULT_SYSTEM_PROMPT = """
You are a helpful AI assistant.
"""
    
    # Construct final system prompt
    # Construct final system prompt
    # Merge Global System Prompt (Config) with Specific Call Prompt (API)
    if initial_prompt:
        if db_system_prompt and db_system_prompt.strip():
             base_prompt = f"{db_system_prompt}\n\nCurrent Call Goal: {initial_prompt}"
        else:
             base_prompt = initial_prompt
    else:
        base_prompt = db_system_prompt if db_system_prompt and db_system_prompt.strip() else DEFAULT_SYSTEM_PROMPT
    
    # Inject Context
    context = CALL_CONTEXT.get(call_id, {})
    user_id = context.get("user_id")
    chat_id = context.get("chat_id")
    if user_id or chat_id:
        base_prompt += f"\n\n[Context: user_id={user_id}, chat_id={chat_id}]"
    
    TOOL_INSTRUCTIONS = """
You can control the call by outputting a JSON block at the very end of your response.
Available Tools:
- hangup: Ends the call. Use this when the user says goodbye or wants to stop.

If you decide to hangup, you MUST generate a polite sign-off message (e.g., "Goodbye!", "Have a nice day!") before the JSON block in the "[Your spoken response here]" section.

Format:
[Your spoken response here]
```json
{
  "action": "hangup",
  "reason": "user said goodbye"
}
```
IMPORTANT: Do NOT output any text after the JSON block. Do NOT read the JSON block aloud.
"""
    final_system_prompt = base_prompt + "\n" + TOOL_INSTRUCTIONS

    async def process_conversation_turn(transcript):
         nonlocal is_bot_speaking
         is_bot_speaking = True
         print(f"[DEBUG] [Turn] Speaking Gate ENABLED (User: {transcript})")
         
         try:
             full_transcription.append(f"User: {transcript}")
             
             # Update History
             conversation_history.append({"role": "user", "content": transcript})
             
             # Construct Messages
             if send_context:
                 # History + Current (History includes the current user turn now)
                 messages_payload = [{"role": "system", "content": final_system_prompt}] + conversation_history
             else:
                 # Stateless: System + Current User
                 messages_payload = [
                     {"role": "system", "content": final_system_prompt},
                     {"role": "user", "content": transcript}
                 ]
             
             chat_payload = {
                 "model": llm_model,
                 "messages": messages_payload,
                 "stream": True 
             }
             print(f"[DEBUG] Turn Context: {chat_payload['messages']}")
             headers = {"Authorization": f"Bearer {llm_api_key}"} if llm_api_key else {}
             
             try:
                 llm_resp = requests.post(
                     f"{llm_url.rstrip('/')}/chat/completions",
                     json=chat_payload,
                     headers=headers,
                     timeout=llm_timeout,
                     stream=True, 
                 )
                 
                 if llm_resp.status_code == 200:
                     print("LLM Stream Started... Buffering for tool check...")
                     full_response_buffer = ""
                     
                     # 1. Accumulate FULL response first (to handle tools safely)
                     for line in llm_resp.iter_lines():
                         if line:
                             decoded = line.decode('utf-8')
                             if decoded.startswith("data: "):
                                 content = decoded[6:]
                                 if content == "[DONE]": break
                                 try:
                                     chunk_json = json.loads(content)
                                     delta = chunk_json.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                     if delta:
                                         full_response_buffer += delta
                                 except: pass
                                 
                     print(f"[DEBUG] [Turn] Full Buffer: {full_response_buffer[:100]}...")

                     # 2. Parse & Strip Command
                     should_hangup = False
                     final_text_to_speak = full_response_buffer
                     
                     # Simple parsing for JSON block at end
                     json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response_buffer, re.DOTALL)
                     if not json_match:
                          # Safer fallback: Look for JSON-like block at the END of string
                          json_match = re.search(r'(\{[\s\S]*?\})\s*$', full_response_buffer)

                     if json_match:
                         try:
                             command_str = json_match.group(1)
                             command = json.loads(command_str)
                             print(f"[DEBUG] [Turn] Parsed Command: {command}")
                             if command.get("action") == "hangup":
                                 should_hangup = True
                                 
                             # Remove the JSON from the spoken text (ALWAYS)
                             final_text_to_speak = full_response_buffer.replace(json_match.group(0), "").strip()
                             # Also try removing just the match group 1 if the fences were separate
                             final_text_to_speak = final_text_to_speak.replace(command_str, "").strip()
                         except Exception as e:
                             print(f"[WARN] Failed to parse detected JSON: {e}")

                     # 3. Speak Cleaned Text
                     total_sent_bytes = 0
                     speech_start_time = None
                     if final_text_to_speak.strip():
                          print(f"[DEBUG] [Turn] TTS Input (Cleaned): '{final_text_to_speak}'")
                          
                          # A. Send small silence padding to prevent cutoff (warmup)
                          # Reduced to 100ms to minimize latency perception
                          print(f"[DEBUG] [Turn] Sending pre-TTS silence padding...")
                          for padding_chunk in generate_silence(duration_sec=0.1, codec=rtp_codec):
                               await websocket.send_text(json.dumps({
                                   "event": "media",
                                   "stream_id": stream_id,
                                   "media": {
                                       "payload": padding_chunk
                                   }
                               }))
                               await asyncio.sleep(0.01)

                          tts_stream_gen = tts_client.speak_stream(final_text_to_speak, voice_id=voice_id, timeout=tts_timeout)
                          async for msg_json in process_tts_stream(tts_stream_gen, voice_id, codec=rtp_codec):
                              if speech_start_time is None:
                                  speech_start_time = asyncio.get_event_loop().time()
                              msg = json.loads(msg_json)
                              if stream_id: msg["stream_id"] = stream_id
                              
                              # Track audio duration for precise hangup
                              payload = msg.get("media", {}).get("payload")
                              if payload:
                                  try:
                                      # PCMU is 1 byte per sample, 8000Hz
                                      # Base64 string length -> approx bytes, or just decode
                                      total_sent_bytes += len(base64.b64decode(payload))
                                  except: pass

                              try:
                                  await websocket.send_text(json.dumps(msg))
                                  await asyncio.sleep(0.02)
                              except RuntimeError as e:
                                   if "WebSocket is not connected" in str(e):
                                       print("[WARN] [Turn] WebSocket disconnected during TTS flush.")
                                       return
                                   raise e
                     
                     print(f"[DEBUG] [Turn] Response finished.")
                     

                     # Update History with Assistant Reply (for context in next turn)
                     if final_text_to_speak.strip():
                        # Store only the CLEAN spoken text in history.
                        conversation_history.append({"role": "assistant", "content": final_text_to_speak})
                        # Add to full transcription for Call Log
                        full_transcription.append(f"Assistant: {final_text_to_speak}")
                     
                     if should_hangup:
                         # Calculate dynamic sleep time based on WALL CLOCK
                         # L16 (16-bit, 8kHz) = 16000 bytes/sec
                         # PCMU (8-bit, 8kHz) = 8000 bytes/sec
                         bytes_per_sec = 16000 if rtp_codec == "L16" else 8000
                         
                         wait_time = 0.1 # Default small buffer (was 0.5)
                         
                         if total_sent_bytes > 0:
                             speech_duration = total_sent_bytes / float(bytes_per_sec)
                             
                             if speech_start_time:
                                 # Time elapsed since we STARTED speaking
                                 elapsed = asyncio.get_event_loop().time() - speech_start_time
                                 # We want to wait until start + duration
                                 # Remaining wait = duration - elapsed
                                 remaining = speech_duration - elapsed
                                 
                                 if remaining > 0:
                                     wait_time = remaining + 0.1 # Small buffer
                                     print(f"[DEBUG] [Turn] Duration: {speech_duration:.2f}s. Elapsed: {elapsed:.2f}s. Waiting remaining: {wait_time:.2f}s")
                                 else:
                                     wait_time = 0.1 # Just buffer
                                     print(f"[DEBUG] [Turn] Duration: {speech_duration:.2f}s. Already elapsed: {elapsed:.2f}s. Just buffer.")
                             else:
                                  wait_time = speech_duration + 0.1
                         
                         await asyncio.sleep(wait_time)
                     else:
                         # Normal turn: Just wait a bit for echo tail / buffer drain
                         print(f"[DEBUG] [Turn] Turn finished. Waiting 1.0s for echo tail...")
                         await asyncio.sleep(1.0)

                     if should_hangup:
                         print("[DEBUG] [Turn] Executing Hangup Action.")
                         
                         # Execute Telnyx Hangup via REST API
                         try:
                             # We need the API key to hang up. 
                             # For now, we'll re-query the provider config or use a strict default since we know it's likely Telnyx.
                             # Optimization: In a real app, store api_key in STREAM_ID_MAP or pass it down.
                             # Here we will query it.
                             provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.name == "telnyx")).first()
                             if provider_config:
                                 telnyx_provider = TelnyxProvider(api_key=decrypt_value(provider_config.api_key))
                                 # We need the call_control_id. It's usually the same as call_id logic, 
                                 # but let's assume call_id passed to this function IS the call_control_id (which it is for Telnyx).
                                 telnyx_provider.hangup_call(call_id)
                         except Exception as hangup_e:
                             print(f"[ERROR] Failed to execute REST hangup: {hangup_e}")

                         await websocket.close()
                         return

                 else:
                     print(f"LLM Error {llm_resp.status_code}: {llm_resp.text}")
                         
             except Exception as llm_e:
                 print(f"LLM/TTS Error: {llm_e}")
                 
         except asyncio.CancelledError:
             print("[DEBUG] [Turn] Task cancelled.")
         except Exception as e:
             print(f"[ERROR] [Turn] Error: {e}")
         finally:
             print(f"[DEBUG] [Turn] Listening enabled (is_bot_speaking = False). Clearing Buffer.")
             is_bot_speaking = False
             inbound_buffer.clear()


    sender_task = None
    if stream_id:
        sender_task = asyncio.create_task(send_initial_sequence())
    
    # Store background tasks to prevent garbage collection
    turn_tasks = set()

    turn_tasks = set()

    # inbound_buffer = bytearray() # Moved to top scope
    silence_timer = 0.0 # RMS-based VAD timer
    has_speech_activity = False
    # BUFFER_THRESHOLD = 64000 # Deprecated in favor of VAD 
    
    # DEBUG_MODE check (module level or local?)
    # best to read from env here to save passing it down
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"

    # 3. Main Loop (Bidirectional Media)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get("event")
            
            if event == "media":
                if is_bot_speaking:
                    # print(".", end="", flush=True) # Optional: visual indicator
                    continue

                payload = msg.get("media", {}).get("payload") 
                if payload:
                    chunk_in = base64.b64decode(payload)
                    
                    if rtp_codec == "L16":
                        # L16 is 16k BE (usually), but Telnyx PSTN seems to force 8k.
                        # And we already found LE is preferred.
                        # So we assume 8k LE input. No Swap. No Resample.
                        chunk_pcm16 = chunk_in
                    elif rtp_codec == "PCMA":
                        chunk_pcm16 = audioop.ulaw2lin(chunk_in, 2) # Wait, this is alaw2lin!
                        chunk_pcm16 = audioop.alaw2lin(chunk_in, 2)
                    else:
                        # PCMU
                        chunk_pcm16 = audioop.ulaw2lin(chunk_in, 2)
                        
                    inbound_buffer.extend(chunk_pcm16)
                    
                    # VAD Logic
                    # 1. Calculate Energy
                    rms = audioop.rms(chunk_pcm16, 2)
                    chunk_duration = len(chunk_pcm16) / 16000.0
                    
                    # 2. Update Silence Timer
                    
                    # DEBUG VAD (Conditional)
                    if debug_mode and len(inbound_buffer) % 8000 < 200: 
                       print(f"[VAD DEBUG] Buffer: {len(inbound_buffer)} bytes. Current RMS: {rms}. Silence Timer: {silence_timer:.2f}")
                    
                    if rms < 500:
                        silence_timer += chunk_duration
                    else:
                        silence_timer = 0.0
                        has_speech_activity = True
                        
                    # Debug Print periodically
                    # if silence_timer > 0.1:
                    #    print(f"S({silence_timer:.1f})", end="", flush=True)

                    # 3. Trigger Conditions
                    # A. Max Duration Reached (15s) - Failsafe
                    # B. Silence Detected (> 1.2s) AND Minimum Speech Captured (> 0.5s)
                    
                    buffer_duration = len(inbound_buffer) / 16000.0
                    
                    should_process = False
                    reason = ""
                    
                    if buffer_duration > 15.0:
                         should_process = True
                         reason = "max_duration"
                    elif silence_timer > 1.2 and buffer_duration > 0.5:
                         should_process = True
                         reason = "silence_detected"
                         
                    if should_process:
                        if not has_speech_activity and reason == "silence_detected":
                             print(f"[DEBUG] Dropping silent buffer (Duration: {buffer_duration:.2f}s). RMS never exceeded threshold.")
                             inbound_buffer.clear()
                             silence_timer = 0.0
                             has_speech_activity = False
                        else:
                            print(f"[DEBUG] Processing Audio ({reason}). Duration: {buffer_duration:.2f}s. Silence: {silence_timer:.2f}s. Last RMS: {rms}")
                            wav_data = create_wav_header(bytes(inbound_buffer), sample_rate=8000)
                            try:
                                transcript = stt_client.transcribe(wav_data, timeout=stt_timeout)
                                print(f"[DEBUG] STT Raw Output: '{transcript}'") # Always log raw output
                                if transcript and transcript.strip():
                                    print(f"User: {transcript}")
                                    
                                    # Spawn background task for turn
                                    task = asyncio.create_task(process_conversation_turn(transcript))
                                    turn_tasks.add(task)
                                    task.add_done_callback(turn_tasks.discard)
                                else:
                                    print("[DEBUG] STT returned empty/silence.")
    
                                    
                            except Exception as e:
                                print(f"Pipeline Error: {e}")
                            
                            # Reset
                            inbound_buffer.clear()
                            silence_timer = 0.0
                            has_speech_activity = False
            elif event == "stop":
                print("Media stream stopped")
                break
            # Ignored events in main loop explicitly to clean up logic
            elif event in ["connected", "start"]:
                pass
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for {call_id}")
    except RuntimeError as e:
        if "WebSocket is not connected" in str(e):
             print(f"[WARN] WebSocket disconnected (RuntimeError) for {call_id}")
        else:
             print(f"[ERROR] WebSocket RuntimeError for {call_id}: {e}")
    except Exception as e:
        print(f"WebSocket error for {call_id}: {e}") # Log the error
        import traceback
        traceback.print_exc() # Print traceback for detailed error info
    finally:
        if sender_task:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[ERROR] Sender task error: {e}")

        if monitor_task:
             monitor_task.cancel()

        # Cancel any ongoing turn tasks (LLM generation/TTS)
        if turn_tasks:
            print(f"[DEBUG] Cancelling {len(turn_tasks)} background turn tasks...")
            for t in turn_tasks:
                t.cancel()

        try:
            await websocket.close()
        except:
            pass
            
        # Update Call Log in DB
        if db_id or call_id:
            print(f"[DEBUG] Attempting to update CallLog (DB: {db_id}, Control: {call_id})...")
            try:
                end_time = asyncio.get_event_loop().time()
                duration = int(end_time - start_time)
                
                session_gen = get_session()
                db_session = next(session_gen)
                try:
                    call_log = None
                    if db_id:
                        call_log = db_session.get(CallLog, db_id)
                    elif call_id:
                        # Fallback
                        statement = select(CallLog).where(CallLog.call_control_id == call_id).order_by(CallLog.id.desc())
                        call_log = db_session.exec(statement).first()
                    
                    if call_log:
                        call_log.status = "completed"
                        call_log.duration_seconds = duration
                        call_log.transcription = "\n".join(full_transcription)
                        call_log.cost = (duration / 60) * 0.005 
                        db_session.add(call_log)
                        db_session.commit()
                        print(f"[SUCCESS] Updated CallLog {call_log.id}: duration={duration}s, status=completed")
                    else:
                        print(f"[WARN] CallLog not found for DB ID {db_id} or Control ID {call_id}")
                finally:
                    db_session.close()
            except Exception as e:
                print(f"[ERROR] Failed to update CallLog: {e}")

            # --- Inbound Call Alerting ---
            if call_log and call_log.direction == "inbound" and call_log.user_id:
                try:
                    # 1. Get Configs
                    session_gen = get_session()
                    db_session = next(session_gen)
                    voice_conf = db_session.exec(select(VoiceConfig)).first()
                    
                    if voice_conf and voice_conf.open_webui_admin_token:
                        token = decrypt_value(voice_conf.open_webui_admin_token) if voice_conf.open_webui_admin_token else None
                        # Use LLM URL base if it looks like openwebui, or fallback to a guess?
                        # Actually we need the 'Base URL' of Open WebUI.
                        # If llm_url is 'http://open-webui:8080/v1', base is 'http://open-webui:8080'
                        # But more robustly, we might want a specific setting.
                        # For now, let's derive it from llm_url if llm_provider is openwebui, OR assume it matches if custom.
                        # Or checking 'open_webui_url' env default?
                        # Let's try to derive from llm_url first.
                        base_url = "http://open-webui:8080" # Default internal docker
                        if voice_conf.llm_url and "/v1" in voice_conf.llm_url:
                             possible_base = voice_conf.llm_url.split("/v1")[0].split("/api")[0]
                             if possible_base: base_url = possible_base
                        
                        # 2. Key: (user_id, channel_name)
                        channel_name = getattr(voice_conf, "alert_channel_name", "LLM-Communications-Gateway Alerts")
                        
                        # Check Cache
                        user_chan = db_session.exec(select(UserChannel).where(
                            UserChannel.user_id == call_log.user_id,
                            UserChannel.channel_name == channel_name
                        )).first()
                        
                        target_channel_id = None
                        if user_chan:
                            target_channel_id = user_chan.channel_id
                            # Verify existence? No, trust cache for speed. Fail soft.
                        else:
                            # 3. Lookup or Create
                            print(f"[DEBUG] Alerting: Searching/Creating channel '{channel_name}' for user {call_log.user_id}...")
                            found_id = openwebui.find_channel_by_user(base_url, token, call_log.user_id, channel_name)
                            if found_id:
                                target_channel_id = found_id
                            else:
                                created_id = openwebui.create_alert_channel(base_url, token, call_log.user_id, channel_name)
                                if created_id:
                                    target_channel_id = created_id
                            
                            # Cache it
                            if target_channel_id:
                                new_map = UserChannel(user_id=call_log.user_id, channel_name=channel_name, channel_id=target_channel_id)
                                db_session.add(new_map)
                                db_session.commit()
                        
                        # 4. Send Alert
                        if target_channel_id:
                            msg = f"**Inbound Call Alert**\n\n" \
                                  f"**From:** {call_log.from_number}\n" \
                                  f"**To:** {call_log.to_number}\n" \
                                  f"**Duration:** {call_log.duration_seconds}s\n" \
                                  f"**Status:** {call_log.status}\n\n" \
                                  f"**Transcription:**\n{call_log.transcription or '(No transcription available)'}"
                            
                            success = openwebui.send_alert(base_url, token, target_channel_id, msg)
                            if success:
                                print(f"[SUCCESS] Alert sent to OpenWebUI channel {target_channel_id}")
                            else:
                                print(f"[WARN] Failed to send alert to channel {target_channel_id}")
                        else:
                            print(f"[WARN] Could not find or create alert channel for user {call_log.user_id}")
                            
                    db_session.close()
                except Exception as e:
                     print(f"[ERROR] Alerting logic failed: {e}")


@router.post("/voice/call")
@router.post("/voice/call")
async def initiate_call(request: CallRequest, fastapi_req: Request, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.name == request.provider, ProviderConfig.enabled == True)).first()
    print(f"[DEBUG] Initiate Call Request: {request.json()}")
    if not provider_config:
        raise HTTPException(status_code=400, detail=f"Provider '{request.provider}' not configured or enabled")
    
    connection_id = provider_config.app_id
    if not connection_id:
        raise HTTPException(status_code=400, detail=f"Provider '{request.provider}' missing App ID (Connection ID)")

    # Use configured from_number from DB, ignore request payload if present
    from_number = provider_config.from_number
    if not from_number:
         raise HTTPException(status_code=400, detail=f"Provider '{request.provider}' missing configured 'From Number'")

    print(f"[DEBUG] Initiating call via {request.provider} (ID: {connection_id}) from {from_number} to {request.to_number}")
    # Resolve Base URL for Stream
    base_url = provider_config.base_url
    scheme = "http"
    if not base_url:
        host = fastapi_req.headers.get("host")
        scheme = fastapi_req.headers.get("x-forwarded-proto", fastapi_req.url.scheme)
        if host:
             base_url = f"{scheme}://{host}"

    # FORCE FALLBACK for local IPs
    # This prevents sending reachable LAN IPs to Telnyx, which causes silent failures
    if base_url and ("192.168" in base_url or "localhost" in base_url or "127.0.0.1" in base_url):
         print(f"Detected local base_url '{base_url}'. Forcing callback to public tunnel.")
         base_url = "https://telnyx-webhooks.sandoval.io"

    stream_url = None
    short_id = None
    webhook_secret = provider_config.webhook_secret
    
    if base_url and webhook_secret:
         import uuid
         short_id = uuid.uuid4().hex
         base_clean = base_url.replace("http://", "").replace("https://", "")
         
         # Robust WSS detection: Default to WSS if https in base_url, X-Forwarded-Proto is https, 
         # or if the domain looks like a public tunnel (typically HTTPS).
         is_secure = "https" in base_url or (scheme and "https" in str(scheme).lower())
         if "ngrok" in base_clean or "sandoval.io" in base_clean or "loca.lt" in base_clean:
             is_secure = True
             
         protocol = "wss" if is_secure else "ws"
         stream_url = f"{protocol}://{base_clean}/api/voice/stream/{short_id}?token={webhook_secret}"
         if request.delay_ms and request.delay_ms > 0:
             stream_url += f"&delay_ms={request.delay_ms}"
         print(f"Initiating Call with Stream: {stream_url} (Track: both_tracks)")
    
    # Pre-generate Audio (Blocking) to ensure no dead air
    if request.prompt:
         voice_config = session.exec(select(VoiceConfig)).first()
         vc_data = {
           "llm_url": (voice_config.llm_url if voice_config else None) or "http://open-webui:8080/v1",
           "llm_api_key": decrypt_value(voice_config.llm_api_key) if voice_config and voice_config.llm_api_key else None,
           "llm_model": (voice_config.llm_model if voice_config else None) or "gpt-3.5-turbo",
           "voice_id": (voice_config.voice_id if voice_config else None) or "default",
           "llm_timeout": getattr(voice_config, "llm_timeout", 10),
           "tts_timeout": getattr(voice_config, "tts_timeout", 10),
           "tts_url": (voice_config.tts_url if voice_config else None) or "http://chatterbox:8000",
           "system_prompt": getattr(voice_config, "system_prompt", None),
           "rtp_codec": getattr(voice_config, "rtp_codec", "PCMU") or "PCMU"
         }
         audio_buffer, init_text = await generate_initial_audio(request.prompt, vc_data)
         if init_text:
             # We don't have call_id yet (result comes after make_call), so we can't store in CALL_CONTEXT[call_id] instantly.
             # We have to wait until we get call_id.
             # But 'initiate_call' is blocking on this before 'make_call'.
             # Strategy: Store in a temporary variable and put in CALL_CONTEXT after 'make_call' succeeds.
             pass
    else:
        audio_buffer = []
        init_text = None

    provider = TelnyxProvider(api_key=decrypt_value(provider_config.api_key))
    from_num = request.from_number or provider_config.from_number or "+15555555555"

    # Pass stream_url to make_call
    rtp_codec = getattr(voice_config, "rtp_codec", "PCMU") or "PCMU"
    result = provider.make_call(request.to_number, from_num, connection_id, stream_url=stream_url, codec=rtp_codec)
    
    call_log = CallLog(
        to_number=request.to_number,
        from_number=from_num,
        status="initiated" if result['success'] else "failed",
        user_id=request.user_id,
        chat_id=request.chat_id,
        call_control_id=result.get('call_id'),
        direction="outbound"
    )
    session.add(call_log)
    session.commit()
    session.refresh(call_log)
    
    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error'))
       
    # Store mappings
    if result.get('call_id'):
        if short_id:
             STREAM_ID_MAP[short_id] = {
                 "call_id": result.get('call_id'),
                 "db_id": call_log.id,
                 "prompt": request.prompt,
                 "max_duration": provider_config.max_call_duration or 600,
                 "limit_message": provider_config.call_limit_message or "This call has reached its time limit. Goodbye."
             }
             print(f"Mapped {short_id} -> {result.get('call_id')} (DB: {call_log.id})")
             
             # Store Context
             # Store Context
             if request.user_id or request.chat_id or init_text:
                 if result.get('call_id') not in CALL_CONTEXT:
                      CALL_CONTEXT[result.get('call_id')] = {}
                 
                 if request.user_id: CALL_CONTEXT[result.get('call_id')]["user_id"] = request.user_id
                 if request.chat_id: CALL_CONTEXT[result.get('call_id')]["chat_id"] = request.chat_id
                 if init_text: CALL_CONTEXT[result.get('call_id')]["initial_greeting"] = init_text


        if audio_buffer:
            # Create a queue and pre-fill it for consistency with streaming logic
            # Since audio_buffer is already fully generated here (initiate_call is blocking on it)
            # We can just put them all in.
            q = Queue()
            for chunk in audio_buffer:
                q.put_nowait(chunk)
            q.put_nowait(None) # EOF
            
            PRELOADED_STREAMS[result.get('call_id')] = q
            print(f"Stored {len(audio_buffer)} preloaded chunks in Queue for {result.get('call_id')}")

    return {"status": "initiated", "call_id": result.get('call_id'), "db_id": call_log.id}

@router.post("/voice/webhook")
async def webhook_handler(request: dict, token: str, raw_request: Request, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Handle inbound webhooks from Telnyx.
    Requires 'token' query parameter matching a valid ProviderConfig.webhook_secret.
    """
    # Check if any provider has this token
    provider = session.exec(select(ProviderConfig).where(ProviderConfig.webhook_secret == token)).first()
    if not provider:
        print(f"Unauthorized webhook attempt. Token: {token}")
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    event_type = request.get("data", {}).get("event_type")
    payload = request.get("data", {}).get("payload", {})
    call_control_id = payload.get("call_control_id")
    direction = payload.get("direction", "inbound")
    
    print(f"[DEBUG] Webhook Event: {event_type} | ID: {call_control_id} | Dir: {direction}")

    if event_type == "call.initiated":
        if direction in ["inbound", "incoming"]:
             # CHECK ENABLED STATUS
             if not provider.inbound_enabled:
                 print(f"[DEBUG] Inbound call rejected: Provider {provider.name} inbound_enabled=False")
                 # Optional: Hangup or Reject. Telnyx usually expects action.
                 # Let's perform a hangup/reject action if possible, or just ignore (which leads to timeout).
                 # For now, just logging and doing nothing (soft reject).
                 return {"status": "rejected"}
                 
             print(f"[DEBUG] Inbound Call Initiated! Answering...")
             
             # Resolve Base URL
             base_url = provider.base_url
             scheme = "http"
             if not base_url:
                 host = raw_request.headers.get("host") or "localhost"
                 scheme = raw_request.headers.get("x-forwarded-proto", raw_request.url.scheme)
                 base_url = f"{scheme}://{host}"
             
             # FORCE FALLBACK for local IPs
             if base_url and ("192.168" in base_url or "localhost" in base_url or "127.0.0.1" in base_url):
                  base_url = "https://telnyx-webhooks.sandoval.io" 
             
             import uuid
             short_id = uuid.uuid4().hex
             base_clean = base_url.replace("http://", "").replace("https://", "")
             is_secure = "https" in base_url or (scheme and "https" in str(scheme).lower())
             if "ngrok" in base_clean or "sandoval.io" in base_clean or "loca.lt" in base_clean:
                 is_secure = True
             protocol = "wss" if is_secure else "ws"
             stream_url = f"{protocol}://{base_clean}/api/voice/stream/{short_id}?token={token}"
             
             print(f"[DEBUG] Generated Stream URL for Inbound: {stream_url}")

             # Inject Inbound System Prompt
             inbound_prompt = provider.inbound_system_prompt
             
             # Inject Inbound System Prompt
             inbound_prompt = provider.inbound_system_prompt
             
             # MOVED STREAM_ID_MAP population to after CallLog creation to capture DB ID
             
             # Fetch VoiceConfig for Codec AND for LLM Preloading
             codec = "PCMU"
             voice_config = None
             try:
                 voice_config = session.exec(select(VoiceConfig)).first()
                 if voice_config:
                     codec = getattr(voice_config, "rtp_codec", "PCMU") or "PCMU"
             except: pass

             # Trigger Background LLM Generation for Greeting
             if inbound_prompt:
                 print(f"[DEBUG] Scheduling Inbound Greeting Generation for {call_control_id}")
                 
                 # Construct Voice Config Data (copied from initiate_call logic)
                 vc_data = {
                   "llm_url": (voice_config.llm_url if voice_config else None) or "http://open-webui:8080/v1",
                   "llm_api_key": decrypt_value(voice_config.llm_api_key) if voice_config and voice_config.llm_api_key else None,
                   "llm_model": (voice_config.llm_model if voice_config else None) or "gpt-3.5-turbo",
                   "voice_id": (voice_config.voice_id if voice_config else None) or "default",
                   "llm_timeout": getattr(voice_config, "llm_timeout", 10),
                   "tts_timeout": getattr(voice_config, "tts_timeout", 10),
                   "tts_url": (voice_config.tts_url if voice_config else None) or "http://chatterbox:8000",
                   "system_prompt": inbound_prompt, # Use Provider Intent as System Prompt
                   "rtp_codec": codec
                 }
                 # Use "Introduce yourself" as the trigger for the bot to speak first
                 background_tasks.add_task(preload_inbound_audio, call_control_id, inbound_prompt, vc_data)

             from ..providers.telnyx import TelnyxProvider
             telnyx_provider = TelnyxProvider(api_key=decrypt_value(provider.api_key))
             # Answer WITH Stream Params (RTP + Codec + URL)
             resp = telnyx_provider.answer_call(
                 call_control_id, 
                 stream_url=stream_url,
                 mode="rtp",
                 codec=codec
             )
             
             # 2. Log it
             call_log = CallLog(
                to_number=payload.get("to", "unknown"),
                from_number=payload.get("from", "unknown"),
                status="ringing",
                call_control_id=call_control_id,
                direction="inbound",
                user_id=provider.assigned_user_id, # Auto-assign from Provider Config
                user_label=provider.assigned_user_label # Auto-assign label
             )
             session.add(call_log)
             session.commit()
             session.refresh(call_log)

             # Store Context Map (Before Answer)
             STREAM_ID_MAP[short_id] = {
                 "call_id": call_control_id,
                 "db_id": call_log.id,
                 "prompt": inbound_prompt,
                 "max_duration": provider.max_call_duration or 600,
                 "limit_message": provider.call_limit_message or "This call has reached its time limit. Goodbye."
             }

             # Store Context
             if provider.assigned_user_id:
                 CALL_CONTEXT[call_control_id] = {
                     "user_id": provider.assigned_user_id
                 }
             
             if not resp.get("success"):
                 print(f"[ERROR] Failed to answer inbound call: {resp.get('error')}")

    elif event_type == "call.answered":
        print(f"Call Answered! Control ID: {call_control_id}")
        if direction not in ["inbound", "incoming"]:
           print(f"[DEBUG] Outbound Call Answered. Stream assumed active.")
            
    elif event_type == "call.hangup":
         print(f"Call Hangup: {payload}")
    
    return {"status": "ok"}

@router.post("/voice/sync")
def sync_provider_app(request: SyncRequest, session: Session = Depends(get_session)):
    """
    Updates the provider's application with the correct webhook URL.
    Constructs the URL using the provided base_url and the stored/generated webhook_secret.
    """
    provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.name == request.provider)).first()
    if not provider_config or not provider_config.app_id:
        raise HTTPException(status_code=400, detail="Provider not found or missing App ID")
    
    if not provider_config.webhook_secret:
        # Should have been seeded, but generate if missing
        import uuid
        provider_config.webhook_secret = uuid.uuid4().hex
        session.add(provider_config)
        session.commit()
        session.refresh(provider_config)
        
    secret = provider_config.webhook_secret
    
    # Construct full URL
    base = request.base_url.rstrip('/')
    full_url = f"{base}/api/voice/webhook?token={secret}"
    
    # Save base_url
    provider_config.base_url = base
    session.add(provider_config)
    session.commit()
    
    if request.provider == 'telnyx':
        provider = TelnyxProvider(api_key=decrypt_value(provider_config.api_key))
        result = provider.update_app(provider_config.app_id, full_url)
        if not result['success']:
            raise HTTPException(status_code=500, detail=result.get('error'))
        return {"status": "synced", "url": full_url}
        
    raise HTTPException(status_code=400, detail="Provider does not support sync")

@router.post("/voice/create-app")
def create_provider_app(request: CreateAppRequest, session: Session = Depends(get_session)):
    """
    Creates a new Call Control Application on the provider (Telnyx only for now)
    and returns the new App ID.
    Does NOT save to DB; the frontend should use the returned ID to populate the form.
    But passing base_url allows us to construct the webhook URL accurately.
    """
    if request.provider != 'telnyx':
        raise HTTPException(status_code=400, detail="Only Telnyx is supported for app creation")
        
    if not request.api_key:
         raise HTTPException(status_code=400, detail="API Key is required")

    # Generate a temporary secret for the webhook URL
    import uuid
    temp_secret = uuid.uuid4().hex
    
    # Construct initial webhook URL
    base = request.base_url.rstrip('/')
    full_url = f"{base}/api/voice/webhook?token={temp_secret}"
    
    provider = TelnyxProvider(api_key=request.api_key)
    result = provider.create_app(request.name, full_url)
    
    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error'))
        
    return {
        "status": "created",
        "app_id": result.get("app_id"),
        "webhook_secret": temp_secret, # Return this so frontend can save it to the provider config
        "base_url": base, # Return base_url so frontend can save it too (although frontend sent it)
        "message": "App created. Please save the provider to persist the App ID and Webhook Secret."
    }

def generate_silence(duration_sec=1.0, codec="PCMU"):
   """Generate silent audio chunks."""
   if codec == "L16":
       sample_rate = 8000 # 16000 << Telnyx PSTN L16 is 8kHz
       bytes_per_sample = 2
       silence_byte = 0x00
   else: # PCMU / PCMA
       sample_rate = 8000
       bytes_per_sample = 1
       silence_byte = 0xFF if codec == "PCMU" else 0xD5 # PCMA silence is typically 0xD5 or 0x55, but 0xFF is often acceptable quiet. PCMU is 0xFF.

   # 20ms chunk size
   # PCMU: 8000 * 0.02 * 1 = 160 bytes
   # L16: 16000 * 0.02 * 2 = 640 bytes
   CHUNK_SIZE = int(sample_rate * 0.02 * bytes_per_sample)
   
   total_bytes = int(duration_sec * sample_rate * bytes_per_sample)
   silence = bytes([silence_byte] * CHUNK_SIZE)
   
   num_chunks = total_bytes // CHUNK_SIZE
   for _ in range(num_chunks):
       yield base64.b64encode(silence).decode('utf-8')
