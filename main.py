"""
WAREHUS BOT — main entry point.

Run:  python main.py

Token resolution order (nothing ever leaks into the repo):
  1. Environment variable DISCORD_TOKEN   -> used by GitHub Actions (Secrets)
  2. config.json "token"                  -> used when running on your own PC
"""

from __future__ import annotations

import json
import os
import sys

import discord

from core import WareBot

BANNER = r"""
=====================================================
   __          __  _      _   _  __        __
   \ \        / / | |    | | | | \ \      / /
    \ \  /\  / /__| |__ _| | | |__\ \ /\ / /
     \ \/  \/ / _ \ / _` | | | / / \ V  V /
      \  /\  / __/ | (_| | |/ /____\_/\_/
       \/  \/ \___|_|\__,_|_//_____|
   old school chill . new school security
=====================================================
"""


def load_config() -> dict:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "config.json")

    # GitHub Actions / secret-hosting path: config.json is gitignored on purpose.
    # The bot must still boot from environment variables alone.
    if not os.path.exists(path):
        example = os.path.join(base, "config.example.json")
        print("[OK] no config.json (normal on GitHub Actions) -> using defaults")
        src = example if os.path.exists(example) else None
        if src:
            try:
                with open(src, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if isinstance(cfg, dict):
                    return cfg
            except json.JSONDecodeError:
                pass
        return {"prefix": "!", "owner_ids": [], "security": {}}

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[X] config.json is not valid JSON: {exc}")
        print("    -> check for missing commas / quotes and try again")
        sys.exit(1)

    if not isinstance(cfg, dict):
        print("[X] config.json must contain a JSON object")
        sys.exit(1)
    return cfg


def resolve_token(cfg: dict) -> str:
    # 1) environment (GitHub Actions secret) — always wins
    env = os.getenv("DISCORD_TOKEN", "").strip()
    if env:
        print("[OK] token source: environment variable DISCORD_TOKEN (safe for GitHub)")
        return env

    # 2) local config.json
    tok = str(cfg.get("token", "")).strip()
    if not tok or "PUT_YOUR" in tok.upper():
        print("[X] NO BOT TOKEN FOUND")
        print("    Local run     : open config.json and paste your token")
        print("    GitHub Actions: add a repo secret named DISCORD_TOKEN")
        print("    (token comes from discord.com/developers/applications)")
        sys.exit(1)
    print("[OK] token source: config.json (local)")
    return tok


def apply_env_overrides(cfg: dict) -> dict:
    """Extra secrets (optional): OWNER_IDS=123,456  PREFIX=?"""
    raw = os.getenv("OWNER_IDS", "").strip()
    if raw:
        ids = [x.strip() for x in raw.split(",") if x.strip().isdigit()]
        if ids:
            cfg.setdefault("owner_ids", [])
            cfg["owner_ids"] = sorted(set(cfg["owner_ids"]) | set(ids))
            print(f"[OK] owner_ids from environment: {len(ids)} id(s)")
    pfx = os.getenv("PREFIX", "").strip()
    if pfx:
        cfg["prefix"] = pfx
    return cfg


def main() -> None:
    print(BANNER)
    cfg = apply_env_overrides(load_config())
    token = resolve_token(cfg)

    bot = WareBot(cfg)
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("[X] TOKEN IS INVALID OR RESET")
        print("    -> Developer Portal > Bot > Reset Token, paste the new one")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        print("[X] PRIVILEGED INTENTS ARE OFF")
        print("    -> Developer Portal > Bot > enable:")
        print("       SERVER MEMBERS INTENT  +  MESSAGE CONTENT INTENT")
        print("    -> then restart the bot")
        sys.exit(1)
    except KeyboardInterrupt:
        print("[OK] bot stopped by user")
    except OSError as exc:
        print(f"[X] network/system error: {exc}")
        print("    -> check your internet connection and try again")
        sys.exit(1)


if __name__ == "__main__":
    main()
