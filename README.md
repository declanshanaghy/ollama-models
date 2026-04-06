# ollama-models

Custom AI model definitions, voice cloning pipeline, and Home Assistant announcement system powered by Ollama, Fish Audio TTS, and Node-RED.

## Overview

This repo manages:

- **Custom LLM personas** deployed to [Open WebUI](http://hal-9005.lan:11080) via the Ollama backend
- **Voice cloning** using [Fish Audio](https://fish.audio) for text-to-speech with cloned voices
- **Node-RED flows** for Home Assistant that generate AI quips, convert them to speech, and announce them on media players throughout the house
- **Scripts** for managing models, deploying flows, and testing the pipeline

## Models

| Model | Base | Description |
|-------|------|-------------|
| [silly-connolly](silly-connolly/) | `gemma4:latest` | Comedy chatbot inspired by Billy Connolly. Generates quips with Scottish humour for TTS announcements. |

Models are defined in `<model-dir>/model.yaml` and synced to Open WebUI via the API.

## Architecture

See [docs/silly-connolly-architecture.md](docs/silly-connolly-architecture.md) for the full pipeline architecture.

```
[Trigger] --> [Ollama/gemma4] --> [Fish Audio TTS] --> [MP3 + silence] --> [HA media_player]
                  |                     |                                        |
           silly-connolly         Cloned voice                          zigbee2mqtt, octopi5,
           system prompt          from samples                          family-room-pi, etc.
```

## Quick Start

### Prerequisites

- Ollama running on `hal-9005.lan:11434`
- Open WebUI on `hal-9005.lan:11080`
- Fish Audio account with API key and cloned voice
- Node-RED (HA add-on) on `harry-os-2405:1880`
- Home Assistant on `homeassistant.lan:8123`

### Setup

1. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Sync model to Open WebUI**
   ```bash
   python3 scripts/manage.py sync
   ```

3. **Deploy Node-RED flows**
   ```bash
   python3 scripts/manage.py deploy-nodered
   ```

4. **Test locally**
   ```bash
   echo "the washing machine is done" | python3 scripts/silly-connolly-tts.py
   ```

## Scripts

| Script | Description |
|--------|-------------|
| [`scripts/manage.py`](docs/scripts.md#managepy) | Manage Open WebUI models and deploy Node-RED flows |
| [`scripts/silly-connolly-tts.py`](docs/scripts.md#silly-connolly-ttspy) | Local TTS testing — pipe text in, hear it spoken |
| [`scripts/replace-chatbot.py`](docs/scripts.md#replace-chatbotpy) | Migration script that replaced ChatBot Announcer with Silly Connolly |

## Node-RED Flows

| Flow | Description |
|------|-------------|
| [`silly-connolly-announce.json`](docs/node-red-flows.md#silly-connolly-announce) | Original standalone announce flow (manual trigger) |
| [`silly-connolly-subannounce.json`](docs/node-red-flows.md#silly-connolly-subflow) | Reusable subflow — the core pipeline |
| [`silly-connolly-test.json`](docs/node-red-flows.md#silly-connolly-test) | Test flow with triggers for each room |

## Documentation

See the [docs/](docs/) directory for detailed documentation:

- [Architecture](docs/silly-connolly-architecture.md) — Full pipeline design and data flow
- [Node-RED Flows](docs/node-red-flows.md) — Flow details, inputs/outputs, configuration
- [Scripts](docs/scripts.md) — CLI tool reference
- [Voice Cloning](docs/voice-cloning.md) — How the voice was created and how to update it
- [Infrastructure](docs/infrastructure.md) — Servers, services, and network topology

## Environment Variables

Stored in `.env` (gitignored):

| Variable | Description |
|----------|-------------|
| `FISH_AUDIO_API_KEY` | Fish Audio API key |
| `FISH_AUDIO_VOICE_ID` | Cloned voice model ID |
| `HA_API_TOKEN` | Home Assistant long-lived access token |
| `NODERED_URL` | Node-RED API URL |
| `NODERED_HA_SERVER_ID` | HA server config node ID in Node-RED |

## Repo Structure

```
ollama-models/
├── README.md
├── .env                              # API keys (gitignored)
├── .gitignore
├── docs/                             # Documentation
│   ├── README.md
│   ├── silly-connolly-architecture.md
│   ├── node-red-flows.md
│   ├── scripts.md
│   ├── voice-cloning.md
│   └── infrastructure.md
├── scripts/
│   ├── manage.py                     # Model + flow management CLI
│   ├── silly-connolly-tts.py         # Local TTS testing
│   └── replace-chatbot.py           # ChatBot → Silly Connolly migration
├── node-red/
│   ├── silly-connolly-announce.json  # Standalone announce flow
│   ├── silly-connolly-subannounce.json # Reusable subflow
│   └── silly-connolly-test.json      # Test flow
└── silly-connolly/
    ├── model.yaml                    # Open WebUI model definition
    ├── Modelfile                     # Ollama Modelfile reference
    └── voice-samples/               # Billy Connolly voice clips
        ├── raw/                      # Original MP3s from Archive.org
        ├── sample-*.wav              # Processed 2-min clips (24kHz/16-bit/mono)
        ├── silly-connolly-90s.mp3    # 90s clip for Fish Audio upload
        └── silly-connolly-combined*.mp3 # Combined clips
```
