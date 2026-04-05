#!/usr/bin/env python3
"""Manage custom models in Open WebUI.

Reads model definitions from <model-dir>/model.yaml files and syncs them
to an Open WebUI instance via its API.

Usage:
    ./manage.py sync                  # sync all models
    ./manage.py sync silly-connolly   # sync one model
    ./manage.py list                  # list remote models
    ./manage.py delete silly-connolly # delete a model
    ./manage.py chat silly-connolly   # quick test chat

Environment:
    OPENWEBUI_URL   - Open WebUI base URL  (default: http://hal-9005.lan:11080)
    OPENWEBUI_EMAIL - Login email           (default: admin@localhost)
    OPENWEBUI_PASS  - Login password        (default: admin)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import yaml

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_URL = "http://hal-9005.lan:11080"


def get_config():
    return {
        "url": os.environ.get("OPENWEBUI_URL", DEFAULT_URL).rstrip("/"),
        "email": os.environ.get("OPENWEBUI_EMAIL", "admin@localhost"),
        "password": os.environ.get("OPENWEBUI_PASS", "admin"),
    }


def api(cfg, method, path, data=None, token=None):
    url = f"{cfg['url']}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err_body = e.read().decode()
        print(f"  API error {e.code}: {err_body}", file=sys.stderr)
        raise


def authenticate(cfg):
    resp = api(cfg, "POST", "/api/v1/auths/signin", {
        "email": cfg["email"],
        "password": cfg["password"],
    })
    return resp["token"]


def get_remote_model(cfg, token, model_id):
    try:
        return api(cfg, "GET", f"/api/v1/models/model?id={model_id}", token=token)
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def list_remote_models(cfg, token):
    resp = api(cfg, "GET", "/api/v1/models/list", token=token)
    return resp.get("items", resp) if isinstance(resp, dict) else resp


def discover_models():
    """Find all model.yaml files in subdirectories."""
    models = []
    for yaml_path in sorted(REPO_DIR.glob("*/model.yaml")):
        with open(yaml_path) as f:
            model = yaml.safe_load(f)
        model["_dir"] = yaml_path.parent.name
        models.append(model)
    return models


def build_payload(model):
    """Convert a model.yaml dict into the Open WebUI ModelForm payload."""
    tags = model.get("meta", {}).get("tags", [])
    tag_objects = [{"name": t} if isinstance(t, str) else t for t in tags]

    return {
        "id": model["id"],
        "name": model["name"],
        "base_model_id": model.get("base_model_id"),
        "meta": {
            "description": model.get("meta", {}).get("description", ""),
            "profile_image_url": model.get("meta", {}).get("profile_image_url", ""),
            "tags": tag_objects,
        },
        "params": model.get("params", {}),
        "is_active": model.get("is_active", True),
    }


def sync_model(cfg, token, model):
    model_id = model["id"]
    payload = build_payload(model)
    existing = get_remote_model(cfg, token, model_id)

    if existing:
        api(cfg, "POST", "/api/v1/models/model/update", data=payload, token=token)
        print(f"  Updated: {model_id}")
    else:
        api(cfg, "POST", "/api/v1/models/create", data=payload, token=token)
        print(f"  Created: {model_id}")


def delete_model(cfg, token, model_id):
    api(cfg, "POST", "/api/v1/models/model/delete", data={"id": model_id}, token=token)
    print(f"  Deleted: {model_id}")


def chat_test(cfg, token, model_id, message="Tell me a joke"):
    print(f"  Chatting with {model_id}...")
    resp = api(cfg, "POST", "/api/chat/completions", data={
        "model": model_id,
        "messages": [{"role": "user", "content": message}],
    }, token=token)
    content = resp["choices"][0]["message"]["content"]
    print(f"\n{content}\n")


def cmd_sync(args):
    cfg = get_config()
    token = authenticate(cfg)
    models = discover_models()

    if args.model:
        models = [m for m in models if m["id"] == args.model or m["_dir"] == args.model]
        if not models:
            print(f"Model '{args.model}' not found in repo", file=sys.stderr)
            sys.exit(1)

    print(f"Syncing {len(models)} model(s) to {cfg['url']}")
    for model in models:
        sync_model(cfg, token, model)
    print("Done.")


def cmd_list(args):
    cfg = get_config()
    token = authenticate(cfg)

    local_models = {m["id"]: m for m in discover_models()}
    remote_models = list_remote_models(cfg, token)

    print(f"{'ID':<30} {'Name':<25} {'Base Model':<20} {'Local'}")
    print("-" * 100)
    for m in remote_models:
        mid = m["id"]
        name = m.get("name", "")
        base = m.get("base_model_id", "")
        local = "yes" if mid in local_models else ""
        print(f"{mid:<30} {name:<25} {base:<20} {local}")


def cmd_delete(args):
    if not args.model:
        print("Usage: manage.py delete <model-id>", file=sys.stderr)
        sys.exit(1)
    cfg = get_config()
    token = authenticate(cfg)
    delete_model(cfg, token, args.model)
    print("Done.")


def cmd_chat(args):
    cfg = get_config()
    token = authenticate(cfg)
    message = " ".join(args.message) if args.message else "Tell me a joke"
    chat_test(cfg, token, args.model, message)


def main():
    parser = argparse.ArgumentParser(description="Manage Open WebUI custom models")
    sub = parser.add_subparsers(dest="command")

    p_sync = sub.add_parser("sync", help="Sync model(s) to Open WebUI")
    p_sync.add_argument("model", nargs="?", help="Model ID or directory name (default: all)")

    p_list = sub.add_parser("list", help="List remote custom models")

    p_del = sub.add_parser("delete", help="Delete a model from Open WebUI")
    p_del.add_argument("model", help="Model ID to delete")

    p_chat = sub.add_parser("chat", help="Test chat with a model")
    p_chat.add_argument("model", help="Model ID")
    p_chat.add_argument("message", nargs="*", help="Message (default: 'Tell me a joke')")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {"sync": cmd_sync, "list": cmd_list, "delete": cmd_delete, "chat": cmd_chat}[args.command](args)


if __name__ == "__main__":
    main()
