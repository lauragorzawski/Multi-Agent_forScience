#!/usr/bin/env python3
"""Check whether the local OpenAI API setup is ready without printing secrets."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def main() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    print(f".env path: {env_path}")
    print(f".env exists: {env_path.exists()}")

    key = ""
    model = ""
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "OPENAI_API_KEY":
                key = value.strip().strip('"').strip("'")
            if name.strip() == "OPENAI_MODEL":
                model = value.strip().strip('"').strip("'")

    key_ready = key.startswith("sk-") and len(key) > 40 and "your_" not in key and "paste_" not in key
    effective_key = os.environ.get("OPENAI_API_KEY", "")
    effective_key_is_placeholder = effective_key.startswith(("replace_", "paste_", "your_"))
    print(f"OPENAI_API_KEY ready: {key_ready}")
    print(f"Terminal OPENAI_API_KEY overrides .env: {bool(effective_key)}")
    print(f"Terminal OPENAI_API_KEY is placeholder: {effective_key_is_placeholder}")
    print(f"OPENAI_MODEL: {model or '(not set)'}")
    print(f"langchain-openai installed: {importlib.util.find_spec('langchain_openai') is not None}")
    print(f"openai installed: {importlib.util.find_spec('openai') is not None}")

    if not key_ready:
        print("")
        print("Fix: open .env and set the first line to OPENAI_API_KEY=sk-...")
        print("Do not leave OPENAI_API_KEY=your_real_key_here or OPENAI_API_KEY=paste_your_key_here.")
    elif effective_key_is_placeholder:
        print("")
        print("Note: your terminal has a placeholder OPENAI_API_KEY exported.")
        print("The app will now override placeholder terminal values with the real .env value.")


if __name__ == "__main__":
    main()
