#!/usr/bin/env python3
"""Generate TTS audio using the silly-connolly voice on Fish Audio.

Reads text from stdin, converts to speech via Fish Audio API,
saves to a temp file, and plays it back locally.

Usage:
    echo "The washing machine is done, ya numpty" | ./scripts/silly-connolly-tts.py
    ./scripts/silly-connolly-tts.py --voices          # list & cache your voices
    ./scripts/silly-connolly-tts.py --voice-info       # show silly-connolly voice details

Environment (.env):
    FISH_AUDIO_API_KEY   - Fish Audio API key
    FISH_AUDIO_VOICE_ID  - Voice model ID (auto-detected if only one voice exists)
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
REPO_DIR = SCRIPT_DIR.parent
ENV_FILE = REPO_DIR / ".env"
CACHE_DIR = REPO_DIR / "tmp" / "fish.audio"


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


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
        with urlopen(req) as resp:
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

    text = sys.stdin.read().strip()
    if not text:
        print("No text provided on stdin", file=sys.stderr)
        sys.exit(1)

    print(f"Generating speech for: {text}", file=sys.stderr)
    audio_data = tts(text, api_key, voice_id)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_data)
        tmp_path = f.name

    print(f"Playing {tmp_path} ({len(audio_data)} bytes)", file=sys.stderr)
    play_audio(tmp_path)
    os.unlink(tmp_path)


if __name__ == "__main__":
    main()
