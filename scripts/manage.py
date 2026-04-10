#!/usr/bin/env python3
"""Manage custom models in Open WebUI.

Reads model definitions from <model-dir>/Modelfile files and syncs them
to an Open WebUI instance via its API. Tracks a SHA256 hash of each
Modelfile in Open WebUI metadata to detect when models are out of date.

Usage:
    ./manage.py status                # show sync status
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
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://hal-9005.lan:11080"
ENV_FILE = REPO_DIR / ".env"


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


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


def parse_modelfile(path):
    """Parse a Modelfile into a structured dict."""
    content = path.read_text()

    from_match = re.search(r'^FROM\s+(.+)$', content, re.MULTILINE)
    base_model_id = from_match.group(1).strip() if from_match else None

    params = {}
    for m in re.finditer(r'^PARAMETER\s+(\S+)\s+(.+)$', content, re.MULTILINE):
        key, val = m.group(1), m.group(2).strip()
        try:
            val = int(val)
        except ValueError:
            try:
                val = float(val)
            except ValueError:
                pass
        params[key] = val

    sys_match = re.search(r'SYSTEM\s+"""(.*?)"""', content, re.DOTALL)
    system = sys_match.group(1).strip() if sys_match else ""

    return {
        "base_model_id": base_model_id,
        "params": params,
        "system": system,
        "modelfile_hash": hashlib.sha256(content.encode()).hexdigest(),
    }


def discover_models():
    """Find all model directories (must contain a Modelfile)."""
    models = []
    for modelfile_path in sorted(REPO_DIR.glob("*/Modelfile")):
        model_dir = modelfile_path.parent
        dir_name = model_dir.name

        parsed = parse_modelfile(modelfile_path)

        # Load Open WebUI metadata from model.json if present
        meta_file = model_dir / "model.json"
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}

        models.append({
            "_dir": dir_name,
            "id": dir_name,
            "name": meta.get("name", dir_name.replace("-", " ").title()),
            "base_model_id": parsed["base_model_id"],
            "params": parsed["params"],
            "system": parsed["system"],
            "meta": {
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
            },
            "modelfile_hash": parsed["modelfile_hash"],
        })
    return models


def build_payload(model):
    """Convert parsed Modelfile dict into the Open WebUI ModelForm payload."""
    tags = model.get("meta", {}).get("tags", [])
    tag_objects = [{"name": t} if isinstance(t, str) else t for t in tags]

    params = dict(model.get("params", {}))
    if model.get("system"):
        params["system"] = model["system"]

    return {
        "id": model["id"],
        "name": model["name"],
        "base_model_id": model.get("base_model_id"),
        "meta": {
            "description": model.get("meta", {}).get("description", ""),
            "profile_image_url": model.get("meta", {}).get("profile_image_url", ""),
            "tags": tag_objects,
            "modelfile_hash": model.get("modelfile_hash", ""),
        },
        "params": params,
        "is_active": True,
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


def cmd_status(args):
    cfg = get_config()
    token = authenticate(cfg)
    local_models = discover_models()
    remote_models = list_remote_models(cfg, token)
    remote_by_id = {m["id"]: m for m in remote_models}

    print(f"{'ID':<30} {'Status':<15} {'Local':<10} {'Remote':<10}")
    print("-" * 70)
    for model in local_models:
        mid = model["id"]
        local_hash = model["modelfile_hash"][:8]
        remote = remote_by_id.get(mid)
        if not remote:
            print(f"{mid:<30} {'MISSING':<15} {local_hash:<10} {'-':<10}")
        else:
            remote_hash = (remote.get("meta", {}).get("modelfile_hash", "") or "")[:8]
            status = "UP TO DATE" if remote_hash == local_hash else "OUT OF DATE"
            print(f"{mid:<30} {status:<15} {local_hash:<10} {remote_hash or '-':<10}")


def get_nodered_config():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {
        "url": os.environ.get("NODERED_URL", "https://harry-os-2405:1880").rstrip("/"),
        "ssl_context": ctx,
    }


def nodered_api(cfg, method, path, data=None):
    url = f"{cfg['url']}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "Content-Type": "application/json",
        "Node-RED-API-Version": "v2",
    }
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, context=cfg["ssl_context"]) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err_body = e.read().decode()
        print(f"  Node-RED API error {e.code}: {err_body}", file=sys.stderr)
        raise


def cmd_deploy_nodered(args):
    cfg = get_nodered_config()
    ha_server_id = os.environ.get("NODERED_HA_SERVER_ID", "")
    flow_files = sorted(REPO_DIR.glob("*/silly-connolly-*.json"))
    if not flow_files:
        print("No flow files found", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching current flows from {cfg['url']}")
    current = nodered_api(cfg, "GET", "/flows")
    rev = current["rev"]
    flows = current["flows"]

    for flow_file in flow_files:
        with open(flow_file) as f:
            new_nodes = json.load(f)

        # Find top-level container nodes (tabs and subflow definitions)
        container_ids = {n["id"] for n in new_nodes if n.get("type") in ("tab", "subflow")}
        if not container_ids:
            print(f"  Skipping {flow_file.name} (no tab or subflow node found)")
            continue

        # Remember position of existing container (if any) to preserve ordering
        tab_positions = {}
        for i, n in enumerate(flows):
            if n.get("id") in container_ids:
                tab_positions[n["id"]] = i

        # Remove old nodes belonging to these containers
        # Only remove nodes whose z (parent) is one of our managed containers
        flows = [n for n in flows
                 if n.get("id") not in container_ids
                 and n.get("z") not in container_ids]

        # Inject HA server ID into any api-call-service nodes with empty server
        if ha_server_id:
            for node in new_nodes:
                if node.get("type") == "api-call-service" and not node.get("server"):
                    node["server"] = ha_server_id

        # Re-insert at original position to preserve flow order
        if tab_positions:
            insert_at = min(tab_positions.values())
            for node in reversed(new_nodes):
                flows.insert(insert_at, node)
        else:
            # New flow — prepend (put our flows first)
            flows = new_nodes + flows

        print(f"  Merged: {flow_file.name} ({len(new_nodes)} nodes, position {insert_at if tab_positions else 0})")

    result = nodered_api(cfg, "POST", "/flows", {"rev": rev, "flows": flows})
    print(f"Deployed! Rev: {result.get('rev', 'ok')}")


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

    sub.add_parser("status", help="Show sync status of local models vs remote")
    sub.add_parser("deploy-nodered", help="Deploy Node-RED flows")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    load_env()

    {"sync": cmd_sync, "list": cmd_list, "delete": cmd_delete, "chat": cmd_chat,
     "status": cmd_status, "deploy-nodered": cmd_deploy_nodered}[args.command](args)


if __name__ == "__main__":
    main()
