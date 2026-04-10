#!/usr/bin/env python3
"""Replace ChatBot Announcer instances with Silly Connolly Announce subflow.

Non-destructive: disables old ChatBot nodes, adds new Silly Connolly nodes.
Sets msg.areas directly on the existing change nodes that feed in.
"""

import json
import ssl
import uuid
from urllib.request import Request, urlopen

NODERED_URL = "https://harry-os-2405:1880"
SILLY_CONNOLLY_SUBFLOW_ID = "silly-connolly-subflow"
CHATBOT_SUBFLOW_ID = "5f310c062780a6bc"

# Area mapping: old ChatBot names → Silly Connolly friendly names
AREA_MAP = {
    "office": "Office",
    "living_room": "Living Room",
    "family_room": "Family Room",
    "guest_bedroom": "Guest Bedroom",
}

DEFAULT_AREAS = ["Living Room", "Family Room", "Office", "Guest Bedroom"]

REPLACEMENTS = [
    {
        "name": "WLED",
        "instance_id": "8a4f7880232cfef8",
        "input_ids": ["0db9ed427a651ea3"],
        "output_ids": [],
        "areas": None,
    },
    {
        "name": "Sprocket",
        "instance_id": "a263b31b2d23d052",
        "input_ids": ["ff7eaa032b3bc8c4"],
        "output_ids": ["a2d5fed4f8473e82"],
        "areas": None,
    },
    {
        "name": "Announcers Door",
        "instance_id": "f924e02dfecfef86",
        "input_ids": ["a8c77ccb.646a5"],
        "output_ids": [],
        "areas": None,
    },
    {
        "name": "Announcers Leak",
        "instance_id": "03c805338b40ed4e",
        "input_ids": ["a8bae373.d293"],
        "output_ids": ["96655a592305a32f", "89d572372d9d6cbd"],
        "areas": ["Living Room"],
    },
    {
        "name": "Laundry Room",
        "instance_id": "3d314bd7ee636804",
        "input_ids": ["bdb0d98ce9d88e78"],
        "output_ids": ["a94884fdf10675fc"],
        "areas": ["Living Room"],
    },
    {
        "name": "Prusa Mini",
        "instance_id": "1c3678415d464539",
        "input_ids": ["18ef3c3650f387ae", "0bc9b974e853d1bd"],
        "output_ids": [],
        "areas": ["Office"],
    },
    {
        "name": "BBQ",
        "instance_id": "1e4c5a9db197ce5d",
        "input_ids": ["b61f0535d3eea78d"],
        "output_ids": ["97b452b98d31eb5b"],
        "areas": None,
    },
]



def gen_id():
    return uuid.uuid4().hex[:16]


def map_areas(old_areas):
    if old_areas is None:
        return DEFAULT_AREAS
    if isinstance(old_areas, str):
        old_areas = [old_areas]
    result = []
    for a in old_areas:
        if a.startswith("x"):
            continue
        mapped = AREA_MAP.get(a, a)
        result.append(mapped)
    return result if result else DEFAULT_AREAS


def main():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    print("Downloading flows...")
    req = Request(f"{NODERED_URL}/flows", headers={"Node-RED-API-Version": "v2"})
    with urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read())

    rev = data["rev"]
    flows = data["flows"]
    nodes_by_id = {n["id"]: n for n in flows}

    # Remove any existing SC replacement nodes (idempotent re-run)
    sc_type = f"subflow:{SILLY_CONNOLLY_SUBFLOW_ID}"
    existing_sc = {n["id"] for n in flows
                   if n.get("type") == sc_type
                   and n.get("z") != "silly-connolly-flow"
                   and n.get("z") != "silly-connolly-test-flow"}
    if existing_sc:
        flows = [n for n in flows if n["id"] not in existing_sc]
        for n in flows:
            if "wires" in n:
                n["wires"] = [
                    [w for w in wg if w not in existing_sc] if isinstance(wg, list) else wg
                    for wg in n["wires"]
                ]
        nodes_by_id = {n["id"]: n for n in flows}
        print(f"  Cleaned up {len(existing_sc)} existing SC replacement nodes")

    # Process each replacement
    for rep in REPLACEMENTS:
        name = rep["name"]
        instance_id = rep["instance_id"]
        instance = nodes_by_id.get(instance_id)

        if not instance:
            print(f"  SKIP {name}: instance {instance_id} not found")
            continue

        tab_id = instance.get("z", "")
        x = instance.get("x", 400)
        y = instance.get("y", 200)

        # Disable the old ChatBot Announcer instance
        instance["d"] = True

        # Add msg.areas rule to each input change node
        areas = map_areas(rep["areas"])
        for input_id in rep["input_ids"]:
            input_node = nodes_by_id.get(input_id)
            if not input_node:
                print(f"    WARN: input node {input_id} not found")
                continue

            if input_node.get("type") == "change":
                # Check if areas rule already exists
                has_areas = any(
                    r.get("p") == "areas" for r in input_node.get("rules", [])
                )
                if not has_areas:
                    input_node.setdefault("rules", []).append({
                        "t": "set",
                        "p": "areas",
                        "pt": "msg",
                        "to": json.dumps(areas),
                        "tot": "json",
                    })
                    print(f"  [{name}] Added areas rule to {input_node.get('name', input_id)}: {areas}")
                else:
                    print(f"  [{name}] Areas rule already exists on {input_node.get('name', input_id)}")

        # Create new Silly Connolly subflow instance
        sc_instance_id = gen_id()
        sc_instance = {
            "id": sc_instance_id,
            "type": f"subflow:{SILLY_CONNOLLY_SUBFLOW_ID}",
            "z": tab_id,
            "name": f"Silly Connolly ({name})",
            "x": x,
            "y": y + 60,
            "wires": [
                rep["output_ids"],
            ],
        }

        # Wire input nodes directly to SC instance
        for input_id in rep["input_ids"]:
            input_node = nodes_by_id.get(input_id)
            if not input_node:
                continue
            if input_node.get("wires") and len(input_node["wires"]) > 0:
                if isinstance(input_node["wires"][0], list):
                    input_node["wires"][0].append(sc_instance_id)
                else:
                    input_node["wires"] = [[sc_instance_id]]
            else:
                input_node["wires"] = [[sc_instance_id]]

        flows.append(sc_instance)
        nodes_by_id[sc_instance_id] = sc_instance

        print(f"  [{name}] Disabled ChatBot, added Silly Connolly ({sc_instance_id})")

    # Deploy
    print("\nDeploying...")
    payload = json.dumps({"rev": rev, "flows": flows}).encode()
    req = Request(
        f"{NODERED_URL}/flows",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Node-RED-API-Version": "v2",
            "Node-RED-Deployment-Type": "full",
        },
    )
    with urlopen(req, context=ctx) as resp:
        result = json.loads(resp.read())
    print(f"Deployed! Rev: {result.get('rev', 'ok')}")


if __name__ == "__main__":
    main()
