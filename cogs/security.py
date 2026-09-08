"""
WAREHUS BOT — security cog (STRICT mode, Wick+ tier)

Layers:
  anti-spam       flood / duplicates / mention / attachment spam
  anti-invite     discord invite links auto-blocked
  anti-raid       account-age gate + join surge -> RAID MODE
  anti-nuke       mass channel/role delete, mass ban, mass kick,
                  mass channel create, mass channel rename
  anti-thread     mass thread creation / thread nuke
  anti-webhook    webhook spam -> delete webhooks + punish
  anti-escalation role create/update with dangerous perms -> revert + punish
  anti-bot-add    foreign bot invited -> kick + alarm
  anti-hijack     server name/vanity change alarm
  heat system     repeat offenders get harsher punishments
  backup/restore  structure snapshots + !restore after a nuke
  anti-crash      process-level exception guards (core.py)

Everything is configurable from config.json -> "security".
"""

from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import GOLD, GREEN, ORANGE, RED, WareBot

log = logging.getLogger("warehus")

INVITE_RE = re.compile(
    r"(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/[\w-]+", re.I)

# permissions that must never be handed out quietly
DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members",
)


class Security(commands.Cog):
    """The bouncer of the hood."""

    def __init__(self, bot: WareBot):
        self.bot = bot
        self.raid_watch.start()
        self.backup_loop.start()

    async def cog_load(self):
        return None

    def cog_unload(self):
        self.raid_watch.cancel()
        self.backup_loop.cancel()

    # ════════════════════════════════════════════════════════════
    #  helpers
    # ════════════════════════════════════════════════════════════
    def _trim(self, dq, window: float, now: float) -> None:
        while dq and now - dq[0] > window:
            dq.popleft()

    async def _punish(self, member: discord.Member, reason: str,
                      heat_amount: int = 25) -> None:
        """Timeout a member (strict mode) + alert the security channel.
        Heat system: repeat offenders inside the heat window get punished
        much harder (Wick-style escalation)."""
        heat = self.bot.add_heat(member.guild.id, member.id, heat_amount)
        heat_limit = int(self.bot.sec_cfg("heat_limit", 100))

        extra = ""
        if heat >= heat_limit:
            minutes = int(self.bot.sec_cfg("hard_timeout_minutes", 1440))
            minutes = max(30, min(minutes, 40320))
            extra = f"\n**heat:** {heat}/{heat_limit} — repeat offender, heavy timeout"
            self.bot.clear_heat(member.guild.id, member.id)
        else:
            minutes = int(self.bot.sec_cfg("auto_timeout_minutes", 60))
            minutes = max(1, min(minutes, 40320))  # discord hard cap = 28 days
            extra = f"\n**heat:** {heat}/{heat_limit}"

        try:
            await member.timeout(timedelta(minutes=minutes),
                                 reason=f"WAREHUS security: {reason}")
            action = f"timeout {minutes}m"
        except (discord.Forbidden, discord.HTTPException):
            action = "could not timeout (role too low)"

        now = time.time()
        if now - self.bot.spam_alert_cd.get(member.id, 0) > 60:
            self.bot.spam_alert_cd[member.id] = now
            e = self.bot.embed(
                "🚨 SECURITY ACTION",
                f"**member:** {member.mention} (`{member}`)\n"
                f"**reason:** {reason}\n**action:** {action}{extra}",
                color=RED)
            await self.bot.send_log(member.guild, "security_logs", e)

            try:
                await member.send(
                    "You got folded in the server for: "
                    f"**{reason}**\nChill out, read the rules, and come back.")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ════════════════════════════════════════════════════════════
    #  ANTI-SPAM  (flood / mention spam / duplicate spam)
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if self.bot.is_staff(message.author):
            return
        prefix = self.bot.config.get("prefix", "!")
        if message.content.startswith(prefix):
            return  # commands are not spam

        now = time.time()
        key = (message.guild.id, message.author.id)

        max_msgs = int(self.bot.sec_cfg("spam_messages", 7))
        window = float(self.bot.sec_cfg("spam_window_seconds", 5))
        max_mentions = int(self.bot.sec_cfg("max_mentions_per_message", 5))
        dup_count = int(self.bot.sec_cfg("duplicate_messages", 4))

        times = self.bot.msg_times[key]
        times.append(now)
        self._trim(times, window, now)

        hit = None

        # attachment-bomb (mass files = raid tool)
        if hit is None and message.attachments:
            max_att = int(self.bot.sec_cfg("max_attachments_per_message", 6))
            if len(message.attachments) > max_att:
                hit = f"attachment spam ({len(message.attachments)} files)"

        # invite links (raiders advertise / pull people out)
        if hit is None and message.content:
            if self.bot.sec_cfg("block_invites", True) and INVITE_RE.search(message.content):
                hit = "discord invite link"

        if hit is None and len(times) > max_msgs:
            hit = "flood spam (too fast)"

        if hit is None and message.mentions:
            users = len(message.mentions) + len(message.mention_roles)
            if users > max_mentions:
                hit = f"mention spam ({users} mentions)"

        if hit is None and message.content:
            cache = self.bot.msg_cache[key]
            content = message.content.strip().lower()
            cache.append(content)
            while len(cache) > dup_count + 2:
                cache.popleft()
            if len(cache) >= dup_count and all(
                    c == content for c in list(cache)[-dup_count:]):
                hit = "duplicate spam (same message x" + str(dup_count) + ")"

        if hit:
            times.clear()
            self.bot.msg_cache[key].clear()
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            await self._punish(message.author, hit)

    # ════════════════════════════════════════════════════════════
    #  ANTI-RAID  (account age gate + join surge detector)
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild is None:
            return
        now = time.time()

        # 0) FOREIGN BOT GUARD — bots are the #1 nuke tool of hacker kids.
        if member.bot:
            if member.id == self.bot.user.id:
                return  # that's me
            allowed = {int(x) for x in self.bot.config.get("allowed_bots", [])
                       if str(x).strip().isdigit()}
            bots_role = self.bot.find_role(guild, "Bots")
            if member.id in allowed or (bots_role and bots_role in member.roles):
                return  # configured / trusted bot — welcome
            executor = await self._executor_of(guild,
                                               discord.AuditLogAction.bot_add,
                                               member.id)
            adder = executor if executor is not None else None
            action_txt = "logged only"
            if not self.bot.sec_cfg("allow_foreign_bots", False):
                try:
                    await member.kick(reason="WAREHUS anti-bot-add: foreign bot")
                    action_txt = "bot KICKED"
                except (discord.Forbidden, discord.HTTPException):
                    action_txt = "could not kick (role too low)"
                if isinstance(adder, discord.Member) and not self.bot.is_staff(adder) \
                        and not self.bot.is_trusted(guild, adder):
                    try:
                        await adder.timeout(timedelta(days=7),
                                            reason="WAREHUS anti-bot-add")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            e = self.bot.embed(
                "🚨 FOREIGN BOT BLOCKED",
                f"**bot:** {member.mention} (`{member}`)\n"
                f"**invited by:** {adder.mention if adder else '*unknown*'}\n"
                f"**action:** {action_txt}\n"
                "Bots are the classic nuke tool. If this was legit, "
                "add the bot ID to `allowed_bots` in config.json.",
                color=RED)
            await self.bot.send_log(guild, "security_logs", e, ping=True)
            return

        # 1) strict account-age gate
        min_days = int(self.bot.sec_cfg("min_account_age_days", 7))
        age_days = (now - member.created_at.timestamp()) / 86400
        if age_days < min_days:
            try:
                await member.send(
                    f"Your Discord account is too fresh for **{guild.name}** "
                    f"(needs {min_days}+ days).\nCome back later, homie.")
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await member.kick(reason=f"WAREHUS anti-raid: account age {age_days:.1f}d < {min_days}d")
            except (discord.Forbidden, discord.HTTPException):
                pass
            e = self.bot.embed(
                "🚧 ACCOUNT AGE GATE",
                f"**blocked:** {member.mention} (`{member}`)\n"
                f"**account age:** {age_days:.1f} days (min {min_days})\n"
                f"**action:** kicked at the door",
                color=ORANGE)
            await self.bot.send_log(guild, "security_logs", e)

        # 2) join surge detector
        surge_n = int(self.bot.sec_cfg("join_surge_count", 6))
        surge_win = float(self.bot.sec_cfg("join_surge_window_seconds", 60))
        dq = self.bot.join_times[guild.id]
        dq.append(now)
        self._trim(dq, surge_win, now)

        if len(dq) >= surge_n:
            gs = self.bot.guild_settings(guild.id)
            if not gs.get("raid_mode"):
                self.bot.set_guild_setting(guild.id, "raid_mode", True)
                e = self.bot.embed(
                    "🚨 RAID MODE ARMED",
                    f"**{len(dq)} joins in {surge_win:.0f}s** — that's a raid pattern.\n"
                    "• verification level -> **HIGHEST**\n"
                    "• fresh accounts are being kicked at the door\n"
                    "• use `!lockdown on` for a full freeze\n"
                    "• raid mode auto-disarms 5 min after the last join",
                    color=RED)
                staff_role = None
                ids = gs.get("staff_roles", [])
                for rid in ids:
                    staff_role = guild.get_role(int(rid))
                    if staff_role:
                        break
                await self.bot.send_log(guild, "security_logs", e,
                                        content=(staff_role.mention if staff_role else "@here"),
                                        ping=True)
            try:
                if guild.verification_level != discord.VerificationLevel.highest:
                    await guild.edit(verification_level=discord.VerificationLevel.highest,
                                     reason="WAREHUS anti-raid: surge detected")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # raid watcher — disarm raid mode when it's calm again
    @tasks.loop(seconds=60)
    async def raid_watch(self):
        if not self.bot.is_ready():
            return  # gateway not up yet — nothing to check
        settings = self.bot.load_json("settings.json", {})
        now = time.time()
        for gid, gs in list(settings.items()):
            if not gs.get("raid_mode"):
                continue
            guild = self.bot.get_guild(int(gid))
            if guild is None:
                continue
            dq = self.bot.join_times.get(guild.id)
            last = dq[-1] if dq else 0
            if now - last > 300:
                self.bot.set_guild_setting(guild.id, "raid_mode", False)
                try:
                    await guild.edit(verification_level=discord.VerificationLevel.high,
                                     reason="WAREHUS anti-raid: raid over, disarming")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                e = self.bot.embed(
                    "✅ RAID MODE DISARMED",
                    "The streets are calm again.\nverification level -> **HIGH**",
                    color=discord.Colour(0x2ECC71))
                await self.bot.send_log(guild, "security_logs", e)

    # ════════════════════════════════════════════════════════════
    #  ANTI-NUKE  (mass deletes / mass bans / mass channel spam)
    # ════════════════════════════════════════════════════════════
    async def _executor_of(self, guild: discord.Guild, action, target_id: int):
        """Find who did it via audit log (last 10 seconds)."""
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                t_id = getattr(entry.target, "id", None)
                if t_id == target_id and \
                        (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                    return entry.user
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    def _register_nuke(self, guild: discord.Guild, kind: str, executor_id: int,
                       threshold: int | None = None,
                       window: float | None = None) -> bool:
        if threshold is None:
            threshold = int(self.bot.sec_cfg("nuke_threshold", 3))
        if window is None:
            window = float(self.bot.sec_cfg("nuke_window_seconds", 30))
        if kind == "channel_create":
            threshold += 1
        elif kind == "webhook_create":
            threshold = 2  # even 2 webhooks out of nowhere = raid tool
        now = time.time()
        dq = self.bot.nuke_track[(guild.id, kind)]
        dq.append((now, executor_id))
        while dq and now - dq[0][0] > window:  # entries are (time, uid) tuples
            dq.popleft()
        hits = [uid for _, uid in dq if uid == executor_id]
        return len(hits) >= threshold

    async def _nuke_response(self, guild: discord.Guild, kind: str, executor):
        if executor is None or executor.bot:
            return
        if self.bot.is_trusted(guild, executor):
            return  # owner doing legit cleanup — leave them alone

        # staff doing a fast ban-sweep during a raid must NOT be punished —
        # but the action still gets logged loudly so the owner can verify it.
        if isinstance(executor, discord.Member) and self.bot.is_staff(executor):
            e = self.bot.embed(
                "⚠️ MASS ACTION BY STAFF (LOGGED, NOT PUNISHED)",
                f"**executor:** {executor.mention} (`{executor}`)\n"
                f"**pattern:** mass `{kind}`\n"
                "If this wasn't a legit mod sweep — strip their roles NOW.",
                color=ORANGE)
            await self.bot.send_log(guild, "security_logs", e, ping=True)
            return

        desc = (
            f"**executor:** {executor.mention} (`{executor}`)\n"
            f"**pattern:** mass `{kind}` detected\n"
        )
        try:
            if isinstance(executor, discord.Member):
                await executor.timeout(timedelta(days=7),
                                       reason=f"WAREHUS anti-nuke: mass {kind}")
                desc += "**action:** timeout 7d + roles stripped\n"
                try:
                    roles = [r for r in executor.roles[1:] if r < guild.me.top_role]
                    if roles:
                        await executor.remove_roles(
                            *roles, reason="WAREHUS anti-nuke: quarantine")
                except (discord.Forbidden, discord.HTTPException):
                    desc += "⚠️ could not strip some roles\n"
            else:
                desc += "**action:** user left the server already\n"
        except (discord.Forbidden, discord.HTTPException):
            desc += "**⚠️ COULD NOT PUNISH — executor outranks the bot.**\n" \
                    "Move the bot role to the TOP of the role list!\n"

        e = self.bot.embed("🚨 NUKE ATTEMPT STOPPED", desc, color=RED)
        await self.bot.send_log(guild, "security_logs", e, ping=True)
        e2 = self.bot.embed(
            "💾 RECOVERY TIP",
            "Structure damage? Use `!restore` to rebuild deleted "
            "channels/roles from the last backup snapshot.",
            color=ORANGE)
        await self.bot.send_log(guild, "security_logs", e2)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        executor = await self._executor_of(guild, discord.AuditLogAction.channel_delete,
                                           channel.id)
        if executor is None:
            return
        if self._register_nuke(guild, "channel_delete", executor.id):
            await self._nuke_response(guild, "channel_delete", executor)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        guild = role.guild
        executor = await self._executor_of(guild, discord.AuditLogAction.role_delete,
                                           role.id)
        if executor is None:
            return
        if self._register_nuke(guild, "role_delete", executor.id):
            await self._nuke_response(guild, "role_delete", executor)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user):
        executor = await self._executor_of(guild, discord.AuditLogAction.ban, user.id)
        if executor is None:
            return
        if self._register_nuke(guild, "ban", executor.id):
            await self._nuke_response(guild, "ban", executor)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        executor = await self._executor_of(guild, discord.AuditLogAction.channel_create,
                                           channel.id)
        if executor is None:
            return
        if self._register_nuke(guild, "channel_create", executor.id):
            await self._nuke_response(guild, "channel_create", executor)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # someone just got an ADMIN role -> loud alert (classic hack move)
        before_ids = {r.id for r in before.roles}
        for role in after.roles:
            if role.id not in before_ids and role.permissions.administrator:
                if self.bot.is_trusted(after.guild, after):
                    continue
                e = self.bot.embed(
                    "🚨 ADMIN PERMISSION GRANTED",
                    f"**member:** {after.mention} (`{after}`)\n"
                    f"**role:** {role.mention}\n"
                    "If this wasn't you — check audit logs NOW and lock the server.",
                    color=RED)
                await self.bot.send_log(after.guild, "security_logs", e, ping=True)

    # ════════════════════════════════════════════════════════════
    #  MASS-KICK GUARD  (nukers kick instead of ban — we see both)
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild is None or member.bot:
            return
        executor = await self._executor_of(guild, discord.AuditLogAction.kick,
                                           member.id)
        if executor is None:
            return  # normal leave
        if self._register_nuke(guild, "kick", executor.id):
            await self._nuke_response(guild, "kick", executor)

    # ════════════════════════════════════════════════════════════
    #  ANTI-THREAD ATTACKS  (mass thread creation / thread nuke)
    #  Raiders spam-create threads to flood the server and ping
    #  everyone, or mass-delete threads to nuke conversations.
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        guild = thread.guild
        if guild is None:
            return
        creator_id = thread.owner_id
        if creator_id is None:
            return
        creator = guild.get_member(creator_id)
        if creator is None or creator.bot:
            return
        if self.bot.is_staff(creator) or self.bot.is_trusted(guild, creator):
            return

        limit = int(self.bot.sec_cfg("thread_nuke_threshold", 4))
        window = float(self.bot.sec_cfg("nuke_window_seconds", 30))
        if self._register_nuke(guild, "thread_create", creator_id,
                               threshold=limit, window=window):
            # delete the spam threads this person just made
            deleted = 0
            try:
                for t in guild.threads:
                    if t.owner_id == creator_id and not t.archived:
                        await t.delete(reason="WAREHUS anti-thread-spam")
                        deleted += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
            if isinstance(creator, discord.Member):
                await self._punish(
                    creator, f"mass thread creation ({deleted} deleted)",
                    heat_amount=40)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        guild = thread.guild
        if guild is None:
            return
        tcreate = getattr(discord.AuditLogAction, "thread_delete", None)
        if tcreate is None:
            return
        executor = await self._executor_of(guild, tcreate, thread.id)
        if executor is None:
            return
        if self._register_nuke(guild, "thread_delete", executor.id):
            await self._nuke_response(guild, "thread_delete", executor)

    # ════════════════════════════════════════════════════════════
    #  ANTI-ESCALATION  (role create/update with dangerous perms)
    #  A hacked admin silently edits a role to Administrator and
    #  the whole server falls. We revert it and punish instantly.
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        guild = role.guild
        gained = [p for p in DANGEROUS_PERMS if getattr(role.permissions, p)]
        if not gained:
            return
        executor = await self._executor_of(guild, discord.AuditLogAction.role_create,
                                           role.id)
        if executor is None or self.bot.is_trusted(guild, executor):
            return

        # try to delete the toxic role before it gets used
        deleted = False
        try:
            if not role.managed and role < guild.me.top_role:
                await role.delete(reason="WAREHUS anti-escalation")
                deleted = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        desc = (f"**executor:** {executor.mention} (`{executor}`)\n"
                f"**role:** `{role.name}`\n"
                f"**dangerous perms:** {', '.join('`' + p + '`' for p in gained)}\n"
                f"**action:** {'role DELETED' if deleted else '⚠️ could not delete (role too low)'}")
        await self._escalation_response(guild, executor, "dangerous role created", desc)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role,
                                   after: discord.Role):
        gained = [p for p in DANGEROUS_PERMS
                  if getattr(after.permissions, p)
                  and not getattr(before.permissions, p)]
        if not gained:
            return
        guild = after.guild
        executor = await self._executor_of(guild, discord.AuditLogAction.role_update,
                                           after.id)
        if executor is None or self.bot.is_trusted(guild, executor):
            return

        # revert the permissions back to what they were
        reverted = False
        try:
            if not after.managed and after < guild.me.top_role:
                await after.edit(permissions=before.permissions,
                                 reason="WAREHUS anti-escalation: revert")
                reverted = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        desc = (f"**executor:** {executor.mention} (`{executor}`)\n"
                f"**role:** {after.mention} (`{after.name}`)\n"
                f"**dangerous perms granted:** {', '.join('`' + p + '`' for p in gained)}\n"
                f"**action:** {'permissions REVERTED' if reverted else '⚠️ could not revert (role too low)'}")
        await self._escalation_response(guild, executor, "role permission escalation", desc)

    async def _escalation_response(self, guild: discord.Guild, executor,
                                   what: str, desc: str) -> None:
        """Escalation is NEVER forgiven for staff — a hacked admin account
        IS the attack. Only the owner / trust-list is exempt (checked above)."""
        punished = ""
        if isinstance(executor, discord.Member):
            try:
                await executor.timeout(timedelta(days=7),
                                       reason=f"WAREHUS anti-escalation: {what}")
                punished += "timeout 7d"
            except (discord.Forbidden, discord.HTTPException):
                punished += "⚠️ timeout failed (role too low)"
            try:
                roles = [r for r in executor.roles[1:] if r < guild.me.top_role]
                if roles:
                    await executor.remove_roles(
                        *roles, reason="WAREHUS anti-escalation: quarantine")
                punished += " + roles stripped"
            except (discord.Forbidden, discord.HTTPException):
                pass
        e = self.bot.embed("🚨 PERMISSION ESCALATION STOPPED",
                           f"**pattern:** {what}\n{desc}\n**punishment:** {punished}",
                           color=RED)
        await self.bot.send_log(guild, "security_logs", e, ping=True)

    # ════════════════════════════════════════════════════════════
    #  MASS-RENAME GUARD  (nukers rename every channel "beamed")
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.name == after.name:
            return
        guild = after.guild
        executor = await self._executor_of(guild, discord.AuditLogAction.channel_update,
                                           after.id)
        if executor is None:
            return
        if self._register_nuke(guild, "channel_update", executor.id):
            await self._nuke_response(guild, "channel_update", executor)

    # ════════════════════════════════════════════════════════════
    #  ANTI-WEBHOOK SPAM  (the classic "hacker kid" move)
    #  Raiders create webhooks and mass-ping @everyone. We nuke
    #  the webhooks and timeout the creator before it lands.
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        guild = channel.guild
        try:
            async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.webhook_create):
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > 15:
                    continue
                executor = entry.user
                if executor.bot or self.bot.is_trusted(guild, executor):
                    continue
                if self._register_nuke(guild, "webhook_create", executor.id):
                    await self._webhook_response(guild, executor)
                    return
        except (discord.Forbidden, discord.HTTPException):
            return

    async def _webhook_response(self, guild: discord.Guild, executor):
        staff = isinstance(executor, discord.Member) and self.bot.is_staff(executor)
        desc = f"**executor:** {executor.mention} (`{executor}`)\n"

        if staff:
            desc += "**action:** logged only (staff) — verify it was legit."
            e = self.bot.embed("⚠️ WEBHOOKS CREATED BY STAFF", desc, color=ORANGE)
        else:
            deleted = 0
            try:
                for wh in await guild.webhooks():
                    if wh.user and wh.user.id == executor.id:
                        await wh.delete(reason="WAREHUS anti-webhook-spam")
                        deleted += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
            desc += f"**webhooks deleted:** {deleted}\n"
            try:
                if isinstance(executor, discord.Member):
                    await executor.timeout(timedelta(days=7),
                                           reason="WAREHUS: webhook raid")
                    desc += "**action:** timeout 7d"
            except (discord.Forbidden, discord.HTTPException):
                desc += "**⚠️ timeout failed — move my role to the TOP**"
            e = self.bot.embed("🚨 WEBHOOK RAID STOPPED", desc, color=RED)

        await self.bot.send_log(guild, "security_logs", e, ping=True)

    # ════════════════════════════════════════════════════════════
    #  SERVER HIJACK ALERT  (name / vanity URL change)
    # ════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.name != after.name or \
                before.vanity_url_code != after.vanity_url_code:
            e = self.bot.embed(
                "🚨 SERVER SETTINGS CHANGED",
                f"**name:** `{before.name}` -> `{after.name}`\n"
                f"**vanity:** `{before.vanity_url_code or '—'}` -> "
                f"`{after.vanity_url_code or '—'}`\n"
                "If this wasn't you — the server may be hijacked. "
                "Check audit logs NOW and run `!lockdown on`.",
                color=RED)
            await self.bot.send_log(after, "security_logs", e, ping=True)

    # ════════════════════════════════════════════════════════════
    #  commands
    # ════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════
    #  AUTO-BACKUP LOOP  (structure snapshots so nukes are reversible)
    # ════════════════════════════════════════════════════════════
    @tasks.loop(minutes=20)
    async def backup_loop(self):
        if not self.bot.is_ready():
            return
        minutes = int(self.bot.sec_cfg("backup_interval_minutes", 20))
        if minutes != self.backup_loop.minutes:
            self.backup_loop.change_interval(minutes=max(5, minutes))
            return
        for guild in self.bot.guilds:
            if self.bot.guild_settings(guild.id).get("setup_done"):
                try:
                    self.bot.snapshot_guild(guild)
                except Exception as exc:
                    log.warning("backup failed for %s: %s", guild.id, exc)

    @backup_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    # ════════════════════════════════════════════════════════════
    #  TRUST LIST  (Wick-style whitelist)
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="trust", description="Whitelist a member — security never auto-punishes them")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to whitelist")
    async def trust(self, ctx: commands.Context, member: discord.Member):
        st = self.bot.guild_settings(ctx.guild.id)
        trusted = set(st.get("trusted_users", []))
        trusted.add(member.id)
        self.bot.set_guild_setting(ctx.guild.id, "trusted_users", sorted(trusted))
        await ctx.send(embed=self.bot.embed(
            "🤝 TRUSTED",
            f"{member.mention} is now on the whitelist.\n"
            "Security will never auto-punish them.\n"
            f"Use `!untrust {member.name}` to remove.", color=GREEN),
            ephemeral=True)

    @commands.hybrid_command(name="untrust", description="Remove a member from the security whitelist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to remove from the whitelist")
    async def untrust(self, ctx: commands.Context, member: discord.Member):
        st = self.bot.guild_settings(ctx.guild.id)
        trusted = set(st.get("trusted_users", []))
        trusted.discard(member.id)
        self.bot.set_guild_setting(ctx.guild.id, "trusted_users", sorted(trusted))
        await ctx.send(embed=self.bot.embed(
            "🚫 UNTRUSTED",
            f"{member.mention} was removed from the whitelist.",
            color=ORANGE), ephemeral=True)

    # ════════════════════════════════════════════════════════════
    #  BACKUP / RESTORE COMMANDS
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="backup", description="Save a structure snapshot NOW (roles + channels)")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def backup(self, ctx: commands.Context):
        snap = self.bot.snapshot_guild(ctx.guild)
        await ctx.send(embed=self.bot.embed(
            "💾 BACKUP SAVED",
            f"**roles:** {len(snap['roles'])}\n"
            f"**categories:** {len(snap['categories'])}\n"
            f"**text channels:** {len(snap['text'])}\n"
            f"**voice channels:** {len(snap['voice'])}\n\n"
            "If a nuke ever gets through, `!restore` rebuilds from this.",
            color=GREEN), ephemeral=True)

    @commands.hybrid_command(name="restore", description="Rebuild deleted channels/roles from the last backup")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def restore(self, ctx: commands.Context):
        snap = self.bot.last_backup(ctx.guild.id)
        if not snap:
            return await ctx.send(embed=self.bot.embed(
                "NO BACKUP YET", "Run `!backup` first so I have something "
                "to restore from.", color=ORANGE), ephemeral=True)

        guild = ctx.guild
        status = await ctx.send(embed=self.bot.embed(
            "🔧 RESTORING THE HOOD", "Rebuilding from the last snapshot...",
            color=GOLD))

        roles_restored = 0
        existing_roles = {r.name.lower() for r in guild.roles}
        for r in snap.get("roles", []):
            if r["name"].lower() in existing_roles:
                continue
            try:
                await guild.create_role(
                    name=r["name"], colour=discord.Colour(r.get("colour", 0)),
                    hoist=r.get("hoist", False),
                    permissions=discord.Permissions(r.get("permissions", 0)),
                    reason="WAREHUS restore")
                roles_restored += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        existing_cats = {c.name.lower() for c in guild.categories}
        cat_map = {}
        for c in snap.get("categories", []):
            found = self.bot.find_category(guild, c["name"])
            if found:
                cat_map[c["name"]] = found
                continue
            try:
                cat_map[c["name"]] = await guild.create_category(
                    c["name"], reason="WAREHUS restore")
            except (discord.Forbidden, discord.HTTPException):
                pass

        chans_restored = 0
        existing_txt = {c.name.lower() for c in guild.text_channels}
        for c in snap.get("text", []):
            if c["name"].lower() in existing_txt:
                continue
            cat = cat_map.get(c.get("category")) if c.get("category") else None
            try:
                await guild.create_text_channel(
                    c["name"], category=cat,
                    slowmode_delay=int(c.get("slowmode", 0)),
                    reason="WAREHUS restore")
                chans_restored += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        existing_vc = {c.name.lower() for c in guild.voice_channels}
        for c in snap.get("voice", []):
            if c["name"].lower() in existing_vc:
                continue
            cat = cat_map.get(c.get("category")) if c.get("category") else None
            try:
                await guild.create_voice_channel(c["name"], category=cat,
                                                 reason="WAREHUS restore")
                chans_restored += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        done = self.bot.embed(
            "✅ RESTORE COMPLETE",
            f"**roles rebuilt:** {roles_restored}\n"
            f"**channels rebuilt:** {chans_restored}\n\n"
            "Messages can't come back (Discord doesn't store them) — "
            "but the hood is standing again.\n"
            "Now re-run `!setup` to re-link log channels if any broke.",
            color=GREEN)
        await status.edit(embed=done)

    # ════════════════════════════════════════════════════════════
    #  SECURITY DASHBOARD
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="security", description="Show the security status of the hood")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def security(self, ctx: commands.Context):
        s = self.bot.guild_settings(ctx.guild.id)
        raid = "ARMED 🚨" if s.get("raid_mode") else "disarmed"
        sec = self.bot.sec
        backup = self.bot.last_backup(ctx.guild.id)
        btime = str(backup.get("time", "—"))[:16].replace("T", " ") if backup else "none yet"
        trusted_n = len(s.get("trusted_users", []))
        lines = (
            "**— GATES —**\n"
            f"**raid mode:** {raid}\n"
            f"**account age gate:** {sec.get('min_account_age_days', 7)}+ days\n"
            f"**join surge alarm:** {sec.get('join_surge_count', 6)} joins / "
            f"{sec.get('join_surge_window_seconds', 60)}s\n"
            "**— CHAT —**\n"
            f"**spam filter:** {sec.get('spam_messages', 7)} msgs / "
            f"{sec.get('spam_window_seconds', 5)}s\n"
            f"**mention cap:** {sec.get('max_mentions_per_message', 5)} · "
            f"**attachment cap:** {sec.get('max_attachments_per_message', 6)} · "
            f"**dup cap:** {sec.get('duplicate_messages', 4)}\n"
            f"**invites blocked:** {'YES' if sec.get('block_invites', True) else 'no'} · "
            f"**heat limit:** {sec.get('heat_limit', 100)}\n"
            "**— NUKE SHIELD —**\n"
            f"**mass delete/ban/kick:** {sec.get('nuke_threshold', 3)} actions / "
            f"{sec.get('nuke_window_seconds', 30)}s\n"
            f"**thread guard:** {sec.get('thread_nuke_threshold', 4)} threads / "
            f"{sec.get('nuke_window_seconds', 30)}s\n"
            "**webhooks:** 2 = punish · **escalation:** revert + punish · "
            "**foreign bots:** kicked\n"
            "**— RECOVERY —**\n"
            f"**auto-backup:** every {sec.get('backup_interval_minutes', 20)} min · "
            f"**last snapshot:** {btime}\n"
            f"**trusted users:** {trusted_n}\n"
            "**— LOGS —**\n"
            f"security={bool(s.get('security_logs'))} "
            f"mod={bool(s.get('mod_logs'))} server={bool(s.get('server_logs'))}"
        )
        await ctx.send(embed=self.bot.embed("🛡 SECURITY STATUS", lines,
                                            color=GREEN), ephemeral=True)

    @commands.hybrid_command(name="lockdown", description="Freeze / unfreeze the whole server (anti-raid)")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx: commands.Context, state: Literal["on", "off"]):
        guild = ctx.guild
        st = self.bot.guild_settings(guild.id)

        if state == "on":
            locked = []
            for ch in guild.text_channels:
                if ch.category and "STAFF" in (ch.category.name or "").upper():
                    continue
                if ch.category and "LOGS" in (ch.category.name or "").upper():
                    continue
                ows = dict(ch.overwrites)
                ow = ows.get(guild.default_role) or discord.PermissionOverwrite()
                if ow.send_messages is False:
                    continue  # already bot-only / muted channel
                ow.send_messages = False
                ows[guild.default_role] = ow
                try:
                    await ch.edit(overwrites=ows, reason="WAREHUS LOCKDOWN")
                    locked.append(ch.id)
                except (discord.Forbidden, discord.HTTPException):
                    pass
            self.bot.set_guild_setting(guild.id, "lockdown_channels", locked)
            self.bot.set_guild_setting(guild.id, "raid_mode", True)
            try:
                await guild.edit(verification_level=discord.VerificationLevel.highest,
                                 reason="LOCKDOWN")
            except (discord.Forbidden, discord.HTTPException):
                pass
            e = self.bot.embed(
                "🔒 LOCKDOWN ACTIVE",
                f"**{len(locked)} channels frozen.** @everyone can read, nobody can type.\n"
                "Verification -> HIGHEST. Raid mode armed.\n"
                "Use `!lockdown off` to unfreeze.",
                color=RED)
            await ctx.send(embed=e)
            await self.bot.send_log(guild, "security_logs", e)

        else:
            restored = 0
            for cid in st.get("lockdown_channels", []):
                ch = guild.get_channel(int(cid))
                if ch is None:
                    continue
                ows = dict(ch.overwrites)
                ow = ows.get(guild.default_role)
                if ow is None:
                    continue
                ow.send_messages = None  # back to default
                if ow.is_empty():
                    ows.pop(guild.default_role, None)
                else:
                    ows[guild.default_role] = ow
                try:
                    await ch.edit(overwrites=ows, reason="WAREHUS LOCKDOWN OFF")
                    restored += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
            self.bot.set_guild_setting(guild.id, "lockdown_channels", [])
            try:
                await guild.edit(verification_level=discord.VerificationLevel.high,
                                 reason="LOCKDOWN OFF")
            except (discord.Forbidden, discord.HTTPException):
                pass
            e = self.bot.embed(
                "🔓 LOCKDOWN LIFTED",
                f"**{restored} channels restored.** Verification -> HIGH.",
                color=discord.Colour(0x2ECC71))
            await ctx.send(embed=e)
            await self.bot.send_log(guild, "security_logs", e)


async def setup(bot: WareBot):
    await bot.add_cog(Security(bot))
