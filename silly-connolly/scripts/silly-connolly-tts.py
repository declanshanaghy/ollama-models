#!/usr/bin/env python3
"""Generate Silly Connolly TTS audio via Open WebUI + Fish Audio.

Usage:
    # Generate a quip from a prompt, then TTS it
    ./silly-connolly/scripts/silly-connolly-tts.py -p "the washing machine is done"

    # Same but save to file instead of playing
    ./silly-connolly/scripts/silly-connolly-tts.py -p "monday mornings" -o quip.mp3

    # TTS raw text directly (skip LLM)
    ./silly-connolly/scripts/silly-connolly-tts.py -r "Yer dinner's ready ya numpty"

    # Pipe raw text via stdin (legacy behaviour)
    echo "Hello there" | ./silly-connolly/scripts/silly-connolly-tts.py

    # Voice management
    ./silly-connolly/scripts/silly-connolly-tts.py --voices
    ./silly-connolly/scripts/silly-connolly-tts.py --voice-info

Environment (.env):
    FISH_AUDIO_API_KEY   - Fish Audio API key
    FISH_AUDIO_VOICE_ID  - Voice model ID (auto-detected if only one voice exists)
    OPENWEBUI_URL        - Open WebUI base URL (default: http://hal-9005.lan:11080)
    OPENWEBUI_EMAIL      - Login email (default: admin@localhost)
    OPENWEBUI_PASS       - Login password (default: admin)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
ENV_FILE = REPO_DIR / ".env"
CACHE_DIR = REPO_DIR / "tmp" / "fish.audio"

OPENWEBUI_DEFAULT_URL = "http://hal-9005.lan:11080"
OPENWEBUI_MODEL = "silly-connolly"


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def openwebui_authenticate():
    """Authenticate with Open WebUI and return a bearer token."""
    base_url = os.environ.get("OPENWEBUI_URL", OPENWEBUI_DEFAULT_URL).rstrip("/")
    email = os.environ.get("OPENWEBUI_EMAIL", "admin@localhost")
    password = os.environ.get("OPENWEBUI_PASS", "admin")

    body = json.dumps({"email": email, "password": password}).encode()
    req = Request(f"{base_url}/api/v1/auths/signin", data=body, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())["token"]
    except HTTPError as e:
        err = e.read().decode()
        print(f"Open WebUI auth error {e.code}: {err}", file=sys.stderr)
        sys.exit(1)


def api_get(path, api_key):
    url = f"https://api.fish.audio{path}"
    req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err = e.read().decode()
        print(f"Fish Audio API error {e.code}: {err}", file=sys.stderr)
        sys.exit(1)


def cache_json(name, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"Cached: {path}", file=sys.stderr)
    return path


def fetch_voices(api_key):
    data = api_get("/model?self=true&page_size=50", api_key)
    cache_json("models", data)
    return data


def fetch_voice_info(api_key, voice_id):
    data = api_get(f"/model/{voice_id}", api_key)
    cache_json(f"model-{voice_id}", data)
    return data


def resolve_voice_id(api_key):
    voice_id = os.environ.get("FISH_AUDIO_VOICE_ID")
    if voice_id:
        return voice_id

    print("FISH_AUDIO_VOICE_ID not set, searching for voices...", file=sys.stderr)
    data = fetch_voices(api_key)
    items = data.get("items", [])
    if not items:
        print("No voices found on your Fish Audio account", file=sys.stderr)
        sys.exit(1)
    if len(items) == 1:
        voice_id = items[0]["_id"]
        print(f"Auto-detected voice: {items[0]['title']} ({voice_id})", file=sys.stderr)
        return voice_id

    print("Multiple voices found. Set FISH_AUDIO_VOICE_ID in .env:", file=sys.stderr)
    for v in items:
        print(f"  {v['_id']}  {v['title']}", file=sys.stderr)
    sys.exit(1)


def generate_quip(prompt):
    """Send a prompt to Open WebUI (silly-connolly model) and return the quip."""
    base_url = os.environ.get("OPENWEBUI_URL", OPENWEBUI_DEFAULT_URL).rstrip("/")
    token = openwebui_authenticate()

    body = json.dumps({
        "model": OPENWEBUI_MODEL,
        "messages": [
            {"role": "user", "content": f"Give me a quip about the {prompt}"},
        ],
    }).encode()

    req = Request(f"{base_url}/api/chat/completions", data=body, method="POST",
                  headers={
                      "Content-Type": "application/json",
                      "Authorization": f"Bearer {token}",
                  })

    print(f"Generating quip via {base_url} ({OPENWEBUI_MODEL})...", file=sys.stderr)
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        err = e.read().decode()
        print(f"Open WebUI API error {e.code}: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Open WebUI request failed: {e}", file=sys.stderr)
        sys.exit(1)

    content = data["choices"][0]["message"]["content"].strip()
    if not content:
        print("Open WebUI returned empty response", file=sys.stderr)
        sys.exit(1)

    return content


def tts(text, api_key, voice_id):
    url = "https://api.fish.audio/v1/tts"
    body = json.dumps({
        "text": text,
        "reference_id": voice_id,
        "format": "mp3",
        "model": "s2-pro",
        "temperature": 0.7,
        "top_p": 0.7,
    }).encode()

    req = Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "model": "s2-pro",
    })

    try:
        with urlopen(req, timeout=15) as resp:
            return resp.read()
    except HTTPError as e:
        err = e.read().decode()
        print(f"Fish Audio API error {e.code}: {err}", file=sys.stderr)
        sys.exit(1)


def play_audio(path):
    if sys.platform == "darwin":
        subprocess.run(["afplay", path], check=True)
    elif sys.platform == "linux":
        for player in ["mpv", "aplay", "paplay", "ffplay"]:
            if subprocess.run(["which", player], capture_output=True).returncode == 0:
                subprocess.run([player, path], check=True)
                return
        print(f"No audio player found. File saved at: {path}", file=sys.stderr)
    elif sys.platform == "win32":
        os.startfile(path)
    else:
        print(f"Cannot play audio on this platform. File saved at: {path}", file=sys.stderr)


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Silly Connolly TTS via Fish Audio")
    parser.add_argument("--voices", action="store_true", help="List and cache your voices")
    parser.add_argument("--voice-info", action="store_true", help="Show details for the configured voice")
    parser.add_argument("-o", "--output", help="Save MP3 to this path instead of playing")

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("-p", "--prompt", help="Generate a quip about this topic via Open WebUI, then TTS it")
    input_group.add_argument("-r", "--raw", help="TTS this text directly (skip LLM)")

    args = parser.parse_args()

    api_key = os.environ.get("FISH_AUDIO_API_KEY")
    if not api_key:
        print("FISH_AUDIO_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    if args.voices:
        data = fetch_voices(api_key)
        for v in data.get("items", []):
            state = v.get("state", "unknown")
            print(f"  {v['_id']}  {v['title']}  [{state}]")
        print(f"\n{data['total']} voice(s) found")
        return

    if args.voice_info:
        voice_id = resolve_voice_id(api_key)
        data = fetch_voice_info(api_key, voice_id)
        print(json.dumps(data, indent=2))
        return

    voice_id = resolve_voice_id(api_key)

    # Resolve text: -p (prompt via Open WebUI), -r (raw text), or stdin
    if args.prompt:
        text = generate_quip(args.prompt)
        print(f"Quip: {text}", file=sys.stderr)
    elif args.raw:
        text = args.raw
    else:
        text = sys.stdin.read().strip()
        if not text:
            print("No text provided. Use -p, -r, or pipe text via stdin.", file=sys.stderr)
            sys.exit(1)

    print(f"Generating speech for: {text}", file=sys.stderr)
    audio_data = tts(text, api_key, voice_id)

    if args.output:
        out_path = Path(args.output)
        out_path.write_bytes(audio_data)
        print(f"Saved {out_path} ({len(audio_data)} bytes)", file=sys.stderr)
    else:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            tmp_path = f.name

        print(f"Playing {tmp_path} ({len(audio_data)} bytes)", file=sys.stderr)
        play_audio(tmp_path)
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
