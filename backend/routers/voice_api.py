from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Request, Query
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
import json
import base64
import struct
import io
import requests
import re
import re
import audioop
import math
import uuid
import asyncio
import urllib.parse
import os

from ..database import get_session
from ..models import ProviderConfig, VoiceConfig, CallLog
from ..providers.telnyx import TelnyxProvider
from ..utils.parakeet import ParakeetClient
from ..utils.chatterbox import ChatterboxClient
from ..utils.security import decrypt_value

router = APIRouter()

class CallRequest(BaseModel):
    to_number: str
    provider: str # Required now
    from_number: Optional[str] = None
    from_number: Optional[str] = None
    prompt: Optional[str] = None # Initial system prompt for the agent logic
    delay_ms: Optional[int] = 0 # Delay in BEFORE sending audio (to avoid overlap with "This is an automated call")
    
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
PRELOADED_MESSAGES = {} # call_id -> list of base64 payloads
STREAM_ID_MAP = {} # short_id -> call_id
DEBUG_AUDIO_DIR = "backend/debug_audio"
if not os.path.exists(DEBUG_AUDIO_DIR):
    os.makedirs(DEBUG_AUDIO_DIR, exist_ok=True)



def process_tts_stream(tts_stream, voice_id: str):
    """
    Consumes a TTS stream, handles arbitrary chunking, detects WAV header,
    resamples to 8000Hz, encdodes to PCMU.
    """
    state = None
    in_rate = 24000 # Default fallback
    header_parsed = False
    
    # Buffer for accumulating raw bytes
    audio_buffer = bytearray()
    
    for chunk in tts_stream:
        if not header_parsed and b'RIFF' in chunk[:100]:
            # Simple header detection in first few chunks
            try:
                # Find start of RIFF
                idx = chunk.find(b'RIFF')
                if idx != -1 and len(chunk) >= idx + 28:
                    in_rate = struct.unpack('<I', chunk[idx+24:idx+28])[0]
                    print(f"Detected TTS Sample Rate: {in_rate}Hz")
                    # assume standard 44 byte header
                    chunk = chunk[idx+44:] 
                    header_parsed = True
            except Exception as e:
                print(f"Header parsing warning: {e}")
                
        audio_buffer.extend(chunk)
        
        # Process in smaller blocks for low latency (e.g. 960 bytes inputs ~ 20ms at 24kHz)
        # This prevents 'not a whole number of frames' errors in audioop
        BLOCK_SIZE = 960
        
        while len(audio_buffer) >= BLOCK_SIZE:
            # Extract block
            raw_block = bytes(audio_buffer[:BLOCK_SIZE])
            del audio_buffer[:BLOCK_SIZE]
            
            # Resample if needed
            processed_block = raw_block
            if in_rate != 8000:
                try:
                    # ratecv(fragment, width, nchannels, inrate, outrate, state)
                    processed_block, state = audioop.ratecv(raw_block, 2, 1, in_rate, 8000, state)
                except Exception as e:
                    print(f"Resampling error (block): {e}")
                    # If resampling fails, we drop this block to avoid noise
                    continue

            # Encode to u-law
            try:
               ulaw_data = audioop.lin2ulaw(processed_block, 2)
               
               # DEBUG: Save first few chunks of TTS
               try:
                   # Append mode to capture stream
                   if len(os.listdir(DEBUG_AUDIO_DIR)) < 10 or os.path.getsize(f"{DEBUG_AUDIO_DIR}/tts_stream_sample.ulaw") < 100000:
                        with open(f"{DEBUG_AUDIO_DIR}/tts_stream_sample.ulaw", "ab") as f:
                            f.write(ulaw_data)
               except: pass

               b64_payload = base64.b64encode(ulaw_data).decode('utf-8')
               # print(f"[STREAM] Processing chunk. Raw: {len(processed_block)} -> Encoded: {len(b64_payload)}")
               yield json.dumps({
                   "event": "media", 
                   "event": "media", 
                   "media": {
                       "payload": b64_payload
                   }
               })
            except Exception as e:
                print(f"Encoding error: {e}")

    # Process remaining remainder (if even)
    if len(audio_buffer) > 0:
        if len(audio_buffer) % 2 != 0:
            audio_buffer = audio_buffer[:-1] # Trim odd byte
            
        if len(audio_buffer) > 0:
             raw_block = bytes(audio_buffer)
             processed_block = raw_block
             if in_rate != 8000:
                 try:
                    processed_block, state = audioop.ratecv(raw_block, 2, 1, in_rate, 8000, state)
                 except: pass
             
             try:
                 ulaw_data = audioop.lin2ulaw(processed_block, 2)
                 b64 = base64.b64encode(ulaw_data).decode('utf-8')
                 yield json.dumps({
                     "event": "media", 
                     "event": "media", 
                     "media": {
                         "payload": b64
                     }
                 })
             except: pass

def generate_initial_audio(prompt: str, voice_config_data: dict) -> list:
    """
    Synchronously generate audio chunks for the prompt.
    Returns a list of JSON strings (media messages).
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
            
        if reply:
            # 2. TTS Generation
            try:
                tts_client = ChatterboxClient(base_url=tts_url)
                tts_stream = tts_client.speak_stream(reply, voice_id=voice_id, timeout=tts_timeout)
                
                for msg_json in process_tts_stream(tts_stream, voice_id):
                    audio_buffer.append(msg_json)
                    
                print(f"Audio generation complete. Buffered {len(audio_buffer)} chunks.")
                
            except Exception as e:
                print(f"TTS Error: {e}")
                
    except Exception as e:
        print(f"General Generation Error: {e}")
        
    return audio_buffer

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
                 print(f"[DEBUG] Received 'connected'. Waiting for 'start'...")
                 continue
            elif event == "start":
                 stream_id = msg.get("stream_id")
                 print(f"[DEBUG] Received 'start' (ID: {stream_id}). Handshake complete.")
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
    
    start_time = asyncio.get_event_loop().time()
    full_transcription = []
    conversation_history = []  # Maintain conversation state

    # 2. Concurrency Setup
    # We spawn a background task to handle the "Sending" of initial audio (Silence -> Delay -> Preloaded).
    # This allows the Main Loop to immediately start "Receiving" (handling Pings, Stops, or Interruptions).
    
    is_bot_speaking = True

    async def send_initial_sequence():
        nonlocal is_bot_speaking
        try:
            # 2a. Send Silence Burst
            print(f"[DEBUG] [Sender] Sending silence to establish audio path...")
            for silence_chunk in generate_silence(duration_sec=0.5):
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
                     for silence_chunk in generate_silence(duration_sec=0.02):
                         await websocket.send_text(json.dumps({
                             "event": "media",
                             "stream_id": stream_id,
                             "media": {
                                 "payload": silence_chunk
                             }
                         }))
                     await asyncio.sleep(0.02)

            # 2c. Preloaded Audio
            if call_id in PRELOADED_MESSAGES:
                 chunks = PRELOADED_MESSAGES.pop(call_id)
                 print(f"[DEBUG] [Sender] Streaming {len(chunks)} preloaded chunks...")
                 
                 for chunk_json in chunks:
                      chunk_obj = json.loads(chunk_json)
                      if stream_id:
                          chunk_obj["stream_id"] = stream_id
                      
                      await websocket.send_text(json.dumps(chunk_obj))
                      await asyncio.sleep(0.02)
                 print("[DEBUG] [Sender] Preloaded audio finished. Waiting 1.5s for echo tail...")
                 await asyncio.sleep(1.5) # Keep gate closed for echo return
                 
        except asyncio.CancelledError:
            print("[DEBUG] [Sender] Task cancelled.")
            raise
        except WebSocketDisconnect:
            print("[WARN] [Sender] WebSocket disconnected.")
        except Exception as e:
            print(f"[ERROR] [Sender] Error: {e}")
        finally:
            print("[DEBUG] [Sender] Listening enabled (is_bot_speaking = False).")
            is_bot_speaking = False

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
             full_transcription.append(transcript)
             
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
                     if final_text_to_speak.strip():
                          print(f"[DEBUG] [Turn] TTS Input (Cleaned): '{final_text_to_speak}'")
                          tts_stream_gen = tts_client.speak_stream(final_text_to_speak, voice_id=voice_id, timeout=tts_timeout)
                          for msg_json in process_tts_stream(tts_stream_gen, voice_id):
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
                     
                     if should_hangup:
                         # Calculate dynamic sleep time based on ACTUAL audio sent
                         # PCMU 8kHz = 8000 bytes/sec
                         if total_sent_bytes > 0:
                             speech_duration = total_sent_bytes / 8000.0
                             # Add small buffer for network/buffer draining (0.5s is usually enough for reliable packet arrival)
                             wait_time = speech_duration + 0.5 
                             print(f"[DEBUG] [Turn] Exact Audio Duration: {speech_duration:.2f}s. Hanging up in {wait_time:.2f}s...")
                         else:
                             # Fallback if no audio (shouldn't happen if text existed)
                             wait_time = 2.0
                             print(f"[DEBUG] [Turn] No audio bytes tracked. Fallback wait: {wait_time}s")
                             
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
             print(f"[DEBUG] [Turn] Listening enabled (is_bot_speaking = False).")
             is_bot_speaking = False


    sender_task = None
    if stream_id:
        sender_task = asyncio.create_task(send_initial_sequence())
    
    # Store background tasks to prevent garbage collection
    turn_tasks = set()

    inbound_buffer = bytearray()
    silence_timer = 0.0 # RMS-based VAD timer
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
                    chunk_pcmu = base64.b64decode(payload)
                    chunk_pcm16 = audioop.ulaw2lin(chunk_pcmu, 2)
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

        try:
            await websocket.close()
        except:
            pass
            
        # Update Call Log in DB
        if db_id:
            print(f"[DEBUG] Attempting to update CallLog {db_id}...")
            try:
                end_time = asyncio.get_event_loop().time()
                duration = int(end_time - start_time)
                session_gen = get_session()
                db_session = next(session_gen)
                call_log = db_session.get(CallLog, db_id)
                if call_log:
                    call_log.status = "completed"
                    call_log.duration_seconds = duration
                    call_log.transcription = " ".join(full_transcription)
                    # Cost calculation placeholder (e.g. $0.005/min)
                    call_log.cost = (duration / 60) * 0.005 
                    db_session.add(call_log)
                    db_session.commit()
                    print(f"[SUCCESS] Updated CallLog {db_id}: duration={duration}s, status=completed")
                else:
                    print(f"[ERROR] CallLog {db_id} not found in DB.")
                db_session.close()
            except Exception as e:
                print(f"[ERROR] Failed to update CallLog: {e}")

@router.post("/voice/call")
def initiate_call(request: CallRequest, fastapi_req: Request, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    provider_config = session.exec(select(ProviderConfig).where(ProviderConfig.name == request.provider, ProviderConfig.enabled == True)).first()
    print(f"[DEBUG] Initiate Call Request: {request.json()}")
    if not provider_config:
        raise HTTPException(status_code=400, detail=f"Provider '{request.provider}' not configured or enabled")
    
    connection_id = provider_config.app_id
    if not connection_id:
        raise HTTPException(status_code=400, detail="Provider missing App ID / Connection ID for voice") 
    
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
           "system_prompt": getattr(voice_config, "system_prompt", None)
         }
         audio_buffer = generate_initial_audio(request.prompt, vc_data)
    else:
        audio_buffer = []

    provider = TelnyxProvider(api_key=decrypt_value(provider_config.api_key))
    from_num = request.from_number or provider_config.from_number or "+15555555555"

    # Pass stream_url to make_call
    result = provider.make_call(request.to_number, from_num, connection_id, stream_url=stream_url)
    
    call_log = CallLog(
        to_number=request.to_number,
        from_number=from_num,
        status="initiated" if result['success'] else "failed",
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
                 "prompt": request.prompt
             }
             print(f"Mapped {short_id} -> {result.get('call_id')} (DB: {call_log.id})")


        if audio_buffer:
            PRELOADED_MESSAGES[result.get('call_id')] = audio_buffer
            print(f"Stored {len(audio_buffer)} preloaded chunks for {result.get('call_id')}")

    return {"status": "initiated", "call_id": result.get('call_id'), "db_id": call_log.id}

@router.post("/voice/webhook")
async def webhook_handler(request: dict, token: str, raw_request: Request, session: Session = Depends(get_session)):
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
    
    if event_type == "call.answered":
        # Start Media Stream
        payload_data = request.get("data", {}).get("payload", {})
        call_control_id = payload_data.get("call_control_id")
        
        print(f"Call Answered! Control ID: {call_control_id}")
        
        # Resolve Base URL
        base_url = provider.base_url
        scheme = "http" # Default
        if not base_url:
            # Fallback to request headers
            host = raw_request.headers.get("host")
            scheme = raw_request.headers.get("x-forwarded-proto", raw_request.url.scheme)
            if host:
                base_url = f"{scheme}://{host}"
                print(f"Warning: Provider base_url missing. Using fallback: {base_url}")
        
        if base_url and call_control_id:
            print(f"Call Answered. Stream should have been auto-started via Dial.")
            # Stream initiation moved to 'make_call' (Dial) to avoid 422 race conditions.
            # No manual start_streaming needed here.
            
    elif event_type == "call.hangup":
         print(f"Call Hangup: {request.get('data', {}).get('payload', {})}")
    
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

def generate_silence(duration_sec=1.0, sample_rate=8000):
   """Generate silent u-law audio chunks (0xFF)"""
   CHUNK_SIZE = 160 # 20ms
   total_bytes = int(duration_sec * sample_rate)
   # u-law silence is 0xFF
   silence = bytes([0xFF] * CHUNK_SIZE)
   
   num_chunks = total_bytes // CHUNK_SIZE
   for _ in range(num_chunks):
       yield base64.b64encode(silence).decode('utf-8')
