# LLM Communications Gateway

> [!CAUTION]
> **SECURITY WARNING**: Please do **not** open this application to the public internet! Better security is planned but not yet implemented. Run this only on a trusted private network behind a secure tunnel (like ngrok or cloudflare WAF) or VPN.

A powerful, self-hosted gateway for building Voice AI applications with LLMs. Connects Telnyx telephony to your local or remote LLMs (Open WebUI, Ollama, OpenAI) with low-latency Speech-to-Text (Parakeet) and Text-to-Speech (Chatterbox).

**Primarily intended for use with Open WebUI** (See the companion tool here: [Communications Gateway Tool](https://openwebui.com/t/rezz/communications_gateway_tool))

## Features

- **Real-time Voice AI**: Bi-directional voice conversations with interruption handling.
- **Provider Agnostic**: Support for Open WebUI, Ollama, OpenAI and custom LLM endpoints.
- **Web Dashboard**: Manage providers, view call logs, and configure prompts via a modern UI.
- **Dockerized**: Easy deployment with Docker Compose.
- **Configurable**: extensive environment variable support for easy "infrastructure-as-code" setup.

## Prerequisites

- Docker Desktop / Docker Compose
- A Telnyx Account (API Key and Phone Number) - **Note:** Telnyx is the only provider currently tested and confirmed working for Voice/SMS.
- An LLM Provider (Ollama running locally, Open WebUI, or OpenAI Key)
- **STT & TTS Services**: This project was developed and **tested specifically** against the following forks:
    - **Parakeet (STT)**: [ther3zz/parakeet-tdt-0.6b-v2-fastapi](https://github.com/ther3zz/parakeet-tdt-0.6b-v2-fastapi)
    - **Chatterbox (TTS)**: [ther3zz/chatterbox-tts-api/tree/patch-1](https://github.com/ther3zz/chatterbox-tts-api/tree/patch-1)

## Fast Start

1.  **Extract the Zip**: Unzip the project folder.
2.  **Configure Environment**:
    *   Copy `.env.sample` to `.env`.
    *   Edit `.env` and fill in your details.
    *   **Crucial**: Set `BASE_URL` to your public server URL (e.g., ngrok) so Telnyx can reach you.
3.  **Run with Docker**:
    ```bash
    docker-compose up -d --build
    ```
4.  **Access the Dashboard**:
    *   Open `http://localhost:8000` in your browser.
    *   **API Documentation**: The FastAPI docs page can be found at `/docs` (e.g., `http://localhost:8000/docs`).
    *   Go to **Providers** and sync your Telnyx Application.

## Configuration (.env)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DEFAULT_LLM_PROVIDER` | `openai`, `ollama`, `openwebui`, or `custom` | `custom` |
| `OLLAMA_URL` | URL for Ollama (e.g. `http://host.docker.internal:11434`) | - |
| `OPEN_WEBUI_URL` | URL for Open WebUI | - |
| `BASE_URL` | Public URL for Telnyx Webhooks | - |
| `RTP_CODEC` | Audio Codec: `L16` (High Quality), `PCMU`, `PCMA` | `PCMU` |
| `DEFAULT_MAX_DURATION` | Global default max call duration (seconds) | `600` |
| `LLM_TIMEOUT` | Timeout for LLM generation (seconds) | `10` |
| `STT_TIMEOUT` | Timeout for STT transcriptions (seconds) | `10` |
| `TTS_TIMEOUT` | Timeout for TTS generation (seconds) | `10` |
| `TELNYX_API_KEY` | Your Telnyx API Key (seeds DB on start) | - |
| `DEBUG` | Set to `true` for verbose logging | `false` |

## Codec Support
- **L16 (Recommended)**: Uncompressed 16-bit 8kHz Linear PCM. Provides significantly clearer audio quality than standard PCMU/A.
- **PCMU/PCMA**: Standard G.711 codecs for legacy compatibility.

## New Features (v2.2)
### 🧩 Open WebUI Integration
- **User Assignment**: Assign specific Open WebUI users to different Providers. Inbound calls to that provider will automatically be logged under that user's ID.
- **Admin Token**: Configure an Open WebUI Admin Token to fetch and sync users directly from your Open WebUI instance.
- **Context Awareness**: Call logs invoke the LLM with user-specific context if assigned.

### � Messaging & Logs
- **Chat UI for Transcriptions**: View voice call transcriptions in a beautiful, interactive chat-bubble interface.
- **User Filtering**: SMS and Call logs are now strictly filtered by User ID. Use the dropdown selector to view logs for specific users.
- **Improved Metadata**: Call logs now capture `Direction`, `From`, `To`, and `Initial Greeting`.

### �📞 Inbound Call Handling
- **Full Support**: The gateway now fully supports inbound calls (Call-In).
- **Inbound Prompt**: Configure a specific system prompt for inbound callers (e.g., "You receive a call from a customer...") via the Provider settings.
- **Zero-Latency Greeting**: Uses `asyncio.Queue` streaming to begin speaking *immediately* when the call connects, even while the rest of the greeting is still generating.

### ⏱️ Call Duration Limits
- **Cost Control**: Set a hard limit (e.g., 5 minutes) on all calls to prevent runaway API costs.
- **Custom Message**: Configure a polite "Time's up" message that plays before the call is automatically terminated.
- **Configurable**: Set globally via `DEFAULT_MAX_DURATION` env var or per-provider in the Dashboard.

## ⚠️ Important Migration Note
If upgrading from v1.x, you **must delete your existing `database_v2.db` file** (or drop tables if using Postgres) to let the application regenerate the schema with new columns (`user_id`, `user_label`, `call_control_id`, `open_webui_admin_token`).

## Performance
- **Async TTS**: Includes a fully asynchronous, non-blocking TTS streaming engine (via `httpx`) for ultra-low latency response times.
- **Smart Hangup**: Uses wall-clock timing to calculate exact speech duration, ensuring the call ends immediately after the AI finishes speaking.

## Troubleshooting

-   **Logs**: Run `docker-compose logs -f llm-communications-gateway` to see what's happening.
-   **Audio Issues**: ensure `BASE_URL` is correct and accessible from the internet.
-   **LLM Connection**: If using `host.docker.internal` to reach local Ollama, ensure you started Ollama with `OLLAMA_HOST=0.0.0.0`.

## Architecture

-   **Gateway (FastAPI)**: Orchestrates calls, VAD, and LLM communication.
-   **Parakeet**: Fast non-streaming STT ([Tested Fork](https://github.com/ther3zz/parakeet-tdt-0.6b-v2-fastapi)).
-   **Chatterbox**: Fast streaming TTS ([Tested Fork](https://github.com/ther3zz/chatterbox-tts-api/tree/patch-1)).
-   **Postgres**: Persistent storage for logs and config (swappable with SQLite).
