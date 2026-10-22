"""Create private local tokens and an editable firmware configuration."""

import argparse
import json
import secrets
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Select a local route without sending a packet.
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default=f"http://{lan_address()}:8765")
    args = parser.parse_args()
    path = ROOT / "config.local.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        print("Preserved existing local configuration and tokens.")
    else:
        config = {
            "admin_token": secrets.token_urlsafe(24),
            "server_url": args.server_url.rstrip("/"),
            "devices": {
                "lamp-a": {"token": secrets.token_urlsafe(24), "kind": "esp8266"},
                "sim-01": {"token": secrets.token_urlsafe(24), "kind": "simulator"},
            },
        }
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print(f"Created private configuration: {path}")
    firmware = ROOT / "firmware" / "include" / "config.h"
    if not firmware.exists():
        example = (firmware.parent / "config.example.h").read_text(encoding="utf-8")
        example = example.replace("http://192.168.1.100:8765", config["server_url"])
        example = example.replace("REPLACE_WITH_DEVICE_TOKEN", config["devices"]["lamp-a"]["token"])
        firmware.write_text(example, encoding="utf-8")
        print(f"Created firmware config; fill in your Wi-Fi locally: {firmware}")
    (ROOT / "data").mkdir(exist_ok=True)
    print(f"Phone URL: {config['server_url']}")
    print("Copy admin_token from config.local.json into the dashboard. Tokens were not printed.")


if __name__ == "__main__":
    main()

