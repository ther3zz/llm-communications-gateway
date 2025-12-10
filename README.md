# LLM Communications Gateway

> [!CAUTION]
> **SECURITY WARNING**: Please do **not** open this application to the public internet! Better security is planned but not yet implemented. Run this only on a trusted private network behind a secure tunnel (like ngrok) or VPN.

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
| `TELNYX_API_KEY` | Your Telnyx API Key (seeds DB on start) | - |
| `DEBUG` | Set to `true` for verbose logging | `false` |

## Troubleshooting

-   **Logs**: Run `docker-compose logs -f llm-communications-gateway` to see what's happening.
-   **Audio Issues**: ensure `BASE_URL` is correct and accessible from the internet.
-   **LLM Connection**: If using `host.docker.internal` to reach local Ollama, ensure you started Ollama with `OLLAMA_HOST=0.0.0.0`.

## Architecture

-   **Gateway (FastAPI)**: Orchestrates calls, VAD, and LLM communication.
-   **Parakeet**: Fast non-streaming STT.
-   **Chatterbox**: Fast streaming TTS.
-   **Postgres**: Persistent storage for logs and config (swappable with SQLite).
