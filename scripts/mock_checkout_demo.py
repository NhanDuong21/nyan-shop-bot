"""Start loopback mock checkout with an ignored local access key."""

from __future__ import annotations

import os
import secrets
import socket
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
KEY_FILE = ROOT / ".nyan-demo" / "access-token"


def access_token() -> str:
    KEY_FILE.parent.mkdir(exist_ok=True)
    if KEY_FILE.exists():
        value = KEY_FILE.read_text(encoding="ascii").strip()
        if len(value) < 32:
            raise SystemExit("Ignored demo key is invalid; remove it and restart the demo.")
        return value
    value = secrets.token_urlsafe(32)
    with KEY_FILE.open("x", encoding="ascii") as output:
        output.write(value + "\n")
    return value


def main() -> None:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            raise SystemExit("Port 8000 is in use. Stop the current local API, then retry.")
    os.environ.update(
        APP_ENV="local",
        APP_HOST="127.0.0.1",
        SUPPLIER_MODE="mock",
        PAYMENT_MODE="disabled",
        ALLOW_REAL_PURCHASES="false",
        MOCK_CHECKOUT_ACCESS_TOKEN=access_token(),
    )
    print(f"Mock checkout access key is stored only at: {KEY_FILE}", flush=True)
    print("API: http://127.0.0.1:8000 · keep this terminal open.", flush=True)
    uvicorn.run("nyan_shop_bot.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
