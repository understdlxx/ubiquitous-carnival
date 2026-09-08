"""
WAREHUS BOT — core module
Old-school chill, new-school security.

This file holds the bot class, JSON storage, shared helpers and the
live security state (anti-raid / anti-spam / anti-nuke trackers).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

log = logging.getLogger("warehus")

# ── old-school palette ──────────────────────────────────────────────
EMBED_COLOR = 0x2F3136   # classic dark
GOLD = 0xF1C40F
RED = 0xE74C3C
GREEN = 0x2ECC71
ORANGE = 0xE67E22

EXTENSIONS = (
    "cogs.setup_server",
    "cogs.security",
    "cogs.moderation",
    "cogs.welcome",
    "cogs.logging_mod",
)


class WareBot(commands.Bot):
    """discord.py bot with config, JSON storage and security state."""

    def __init__(self, config: dict) -> None:
        intents = discord.Intents.default()
        intents.members = True           # privileged — enable in dev portal
        intents.message_content = True   # privileged — enable in dev portal

        prefix = str(config.get("prefix") or "!").strip() or "!"
        super().__init__(
            command_prefix=commands.when_mentioned_or(prefix),
            intents=intents,
            case_insensitive=True,
            strip_after_prefix=True,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=True
            ),
        )

        self.config = config
        self.sec = dict(config.get("security") or {})
        base = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(base, "data")
        os.makedirs(self.data_dir, exist_ok=True)

        # ── live security state (in-memory) ─────────────────────
        self.join_times: dict[int, deque] = defaultdict(deque)       # guild -> join timestamps
        self.msg_times: dict[tuple, deque] = defaultdict(deque)      # (guild, user) -> msg timestamps
        self.msg_cache: dict[tuple, deque] = defaultdict(deque)      # (guild, user) -> last contents
        self.nuke_track: dict[tuple, deque] = defaultdict(deque)     # (guild, type) -> (time, executor)
        self.spam_alert_cd: dict[int, float] = {}                    # user -> last alert time
        self.heat: dict[tuple, deque] = defaultdict(deque)           # (guild, user) -> (time, amount)

    # ── HEAT SYSTEM (Wick-style score, decays over time) ─────
    def add_heat(self, guild_id: int, user_id: int, amount: int,
                 window: float = 600.0) -> int:
        now = time.time()
        dq = self.heat[(guild_id, user_id)]
        dq.append((now, int(amount)))
        while dq and now - dq[0][0] > window:
            dq.popleft()
        return sum(a for _, a in dq)

    def clear_heat(self, guild_id: int, user_id: int) -> None:
        self.heat.pop((guild_id, user_id), None)

    # ────────────────────────────────────────────────────────────
    #  JSON storage
    # ────────────────────────────────────────────────────────────
    def _path(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    def load_json(self, name: str, default):
        p = self._path(name)
        if not os.path.exists(p):
            return default
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:  # corrupted file -> keep the bot alive
            log.error("could not read %s (%s) — using defaults", name, exc)
            return default

    def save_json(self, name: str, data) -> None:
        p = self._path(name)
        tmp = p + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)  # atomic write — no half-written files
        except Exception as exc:
            log.error("could not write %s (%s)", name, exc)

    # ── per-guild settings ──────────────────────────────────────
    def guild_settings(self, guild_id) -> dict:
        data = self.load_json("settings.json", {})
        return data.get(str(guild_id), {})

    def set_guild_setting(self, guild_id, key: str, value) -> None:
        data = self.load_json("settings.json", {})
        data.setdefault(str(guild_id), {})[key] = value
        self.save_json("settings.json", data)

    def sec_cfg(self, key: str, fallback):
        return self.sec.get(key, fallback)

    # ────────────────────────────────────────────────────────────
    #  shared helpers
    # ────────────────────────────────────────────────────────────
    def embed(self, title=None, description=None, color=EMBED_COLOR, footer=None) -> discord.Embed:
        e = discord.Embed(title=title, description=description, color=color)
        e.set_footer(text=footer or "WAREHUS SECURITY SYSTEM")
        e.timestamp = discord.utils.utcnow()
        return e

    def find_channel(self, guild: discord.Guild, name: str):
        name = name.lower()
        return discord.utils.find(lambda c: c.name.lower() == name, guild.text_channels)

    def find_category(self, guild: discord.Guild, name: str):
        name = name.lower()
        return discord.utils.find(lambda c: c.name.lower() == name, guild.categories)

    def find_role(self, guild: discord.Guild, name: str):
        name = name.lower()
        return discord.utils.find(lambda r: r.name.lower() == name, guild.roles)

    async def get_log_channel(self, guild: discord.Guild, kind: str):
        cid = self.guild_settings(guild.id).get(kind)
        if not cid:
            return None
        ch = guild.get_channel(int(cid))
        return ch if isinstance(ch, (discord.TextChannel, discord.Thread)) else None

    async def send_log(self, guild: discord.Guild, kind: str, embed: discord.Embed,
                       content: str | None = None, ping: bool = False):
        ch = await self.get_log_channel(guild, kind)
        if ch is None:
            return
        try:
            am = (discord.AllowedMentions(everyone=True, roles=True, users=True)
                  if ping else discord.AllowedMentions.none())
            await ch.send(content=content, embed=embed, allowed_mentions=am)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def is_staff(self, member: discord.Member) -> bool:
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator or member.id == member.guild.owner_id:
            return True
        staff = set(self.guild_settings(member.guild.id).get("staff_roles", []))
        return any(r.id in staff for r in member.roles)

    def is_trusted(self, guild: discord.Guild, user: discord.abc.User) -> bool:
        """Users security must NEVER auto-punish:
        server owner + owner_ids (config) + !trust whitelist."""
        if user.id == guild.owner_id:
            return True
        owners = {int(x) for x in self.config.get("owner_ids", []) if str(x).strip().isdigit()}
        if user.id in owners:
            return True
        trusted = set(self.guild_settings(guild.id).get("trusted_users", []))
        return user.id in trusted

    # ── HOME-GUILD LOCK (anti token-misuse: autoleave) ───────
    def home_guilds(self) -> set[int]:
        cfg_ids = {int(x) for x in self.config.get("allowed_guild_ids", [])
                   if str(x).strip().isdigit()}
        if cfg_ids:
            return cfg_ids
        saved = self.load_json("home_guilds.json", [])
        return {int(x) for x in saved if str(x).strip().isdigit()}

    def lock_home_guilds(self) -> set[int]:
        """First boot: lock the bot to the servers it is currently in."""
        cfg_ids = {int(x) for x in self.config.get("allowed_guild_ids", [])
                   if str(x).strip().isdigit()}
        if cfg_ids:
            self.save_json("home_guilds.json", sorted(cfg_ids))
            return cfg_ids
        saved = self.load_json("home_guilds.json", [])
        if saved:
            return {int(x) for x in saved}
        current = sorted(g.id for g in self.guilds)
        self.save_json("home_guilds.json", current)
        return {int(x) for x in current}

    # ────────────────────────────────────────────────────────────
    #  lifecycle
    # ────────────────────────────────────────────────────────────
    async def setup_hook(self) -> None:
        # ANTICRASH: nothing may kill the process silently (Wick-style)
        import asyncio
        import sys
        import threading
        import traceback

        def _loop_handler(_loop, context):
            exc = context.get("exception")
            if isinstance(exc, discord.ConnectionClosed):
                return  # discord.py reconnects on its own
            log.error("loop error: %s | context: %s", exc, context.get("message", "?"))

        def _sys_hook(et, ev, tb):
            if et in (KeyboardInterrupt, SystemExit):
                return
            log.error("unhandled exception:\n%s",
                      "".join(traceback.format_exception(et, ev, tb)))

        def _thread_hook(args):
            if args.exc_type in (SystemExit, KeyboardInterrupt):
                return
            log.error("thread crash in %s:\n%s", args.thread.name,
                      "".join(traceback.format_exception(
                          args.exc_type, args.exc_value, args.exc_traceback)))

        try:
            asyncio.get_running_loop().set_exception_handler(_loop_handler)
            sys.excepthook = _sys_hook
            threading.excepthook = _thread_hook
        except Exception as exc:
            log.warning("anticrash hooks not installed: %s", exc)

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("loaded extension: %s", ext)
            except Exception as exc:
                log.error("FAILED to load %s: %s", ext, exc)

        # persistent verify button — survives restarts
        from cogs.welcome import VerifyView
        self.add_view(VerifyView())

        # NOTE: slash commands are synced per-guild in on_ready
        # (instant availability, no duplicates from a global sync)

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, self.user and self.user.id)
        log.info("connected to %d guild(s)", len(self.guilds))

        # anti token-misuse: first boot locks the bot to its current servers
        try:
            home = self.lock_home_guilds()
            for g in list(self.guilds):
                if g.id not in home:
                    log.warning("FOREIGN GUILD detected: %s (%s) — leaving", g.name, g.id)
                    try:
                        if g.system_channel:
                            await g.system_channel.send(
                                "⛔ This bot is PRIVATE (WAREHUS). Leaving this server.")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    try:
                        await g.leave()
                    except (discord.Forbidden, discord.HTTPException):
                        pass
        except Exception as exc:
            log.warning("home-guild lock failed: %s", exc)

        try:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="the hood | !help",
                ),
                status=discord.Status.online,
            )
        except Exception as exc:
            log.warning("presence failed: %s", exc)

        # per-guild slash sync -> commands appear instantly on YOUR server
        if not getattr(self, "_synced", False):
            self._synced = True
            for g in self.guilds:
                try:
                    await self.tree.sync(guild=g)
                except Exception as exc:
                    log.warning("slash sync failed for guild %s: %s", g.id, exc)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        # ANTI-HIJACK: if the token leaks and someone invites the bot
        # somewhere else, it refuses to stay there.
        home = self.home_guilds()
        if guild.id not in home:
            log.warning("FOREIGN GUILD invite: %s (%s) — leaving immediately",
                        guild.name, guild.id)
            try:
                if guild.system_channel:
                    await guild.system_channel.send(
                        "⛔ This bot is PRIVATE (WAREHUS). It does not join other servers.")
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await guild.leave()
            except (discord.Forbidden, discord.HTTPException):
                pass
            return
        try:
            await self.tree.sync(guild=guild)
        except Exception:
            pass
        log.info("joined new guild: %s (%s)", guild.name, guild.id)

    # ── BACKUP / RESTORE (survive a nuke — rebuild the hood) ─
    def snapshot_guild(self, guild: discord.Guild) -> dict:
        """Save the server structure (roles + channels) to data/backup.json."""
        snap = {
            "time": discord.utils.utcnow().isoformat(),
            "roles": [
                {"name": r.name, "colour": r.colour.value, "hoist": r.hoist,
                 "permissions": r.permissions.value}
                for r in guild.roles if not r.managed and r != guild.default_role
            ],
            "categories": [{"name": c.name} for c in guild.categories],
            "text": [
                {"name": c.name, "category": c.category.name if c.category else None,
                 "slowmode": c.slowmode_delay}
                for c in guild.text_channels
            ],
            "voice": [
                {"name": c.name, "category": c.category.name if c.category else None}
                for c in guild.voice_channels
            ],
        }
        data = self.load_json("backup.json", {})
        data[str(guild.id)] = snap
        self.save_json("backup.json", data)
        return snap

    def last_backup(self, guild_id: int):
        return self.load_json("backup.json", {}).get(str(guild_id))

    # ────────────────────────────────────────────────────────────
    #  friendly error handling — the bot must never look broken
    # ────────────────────────────────────────────────────────────
    async def on_command_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions).replace("_", " ")
            await ctx.send(embed=self.embed(
                "ACCESS DENIED",
                f"You ain't got the clearance for that, homie.\nMissing: `{missing}`",
                color=RED), ephemeral=True)
            return
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions).replace("_", " ")
            await ctx.send(embed=self.embed(
                "I CAN'T DO THAT",
                f"I'm missing permissions: `{missing}`.\nMove my role to the top of the role list.",
                color=ORANGE), ephemeral=True)
            return
        if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument,
                             commands.BadBoolArgument, commands.ChannelNotFound,
                             commands.MemberNotFound, commands.RoleNotFound)):
            await ctx.send(embed=self.embed(
                "HOLD UP",
                f"Command used wrong: `{error}`\nTry `!help` style: `!ban @user reason`",
                color=ORANGE), ephemeral=True)
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=self.embed(
                "ACCESS DENIED", "This command is not for you, homie.", color=RED), ephemeral=True)
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=self.embed(
                "SLOW DOWN", f"Chill. Try again in {error.retry_after:.0f}s.", color=ORANGE),
                ephemeral=True)
            return
        log.error("command error in %s: %r", ctx.command, error)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        log.exception("error in event %s", event_method)
