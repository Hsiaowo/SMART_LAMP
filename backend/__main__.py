import argparse
import json
import os
from pathlib import Path

import uvicorn

from backend.main import ROOT, create_app


def main():
    parser = argparse.ArgumentParser(description="Run the local smart lamp MVP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    config_path = Path(os.getenv("SMART_LAMP_CONFIG", ROOT / "config.local.json"))
    if not config_path.exists():
        parser.error("Run python -m scripts.bootstrap first")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    app = create_app(
        Path(os.getenv("SMART_LAMP_DB", ROOT / "data" / "lamp.sqlite3")),
        config["admin_token"], config["devices"],
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
