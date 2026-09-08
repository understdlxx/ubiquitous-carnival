"""
WAREHUS BOT — moderation cog.
ban / unban / kick / mute(timeout) / warn / clear / lock / slowmode / serverinfo / ping
All commands work as BOTH prefix (!ban) and slash (/ban).
"""

from __future__ import annotations

from datetime import timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core import EMBED_COLOR, GREEN, ORANGE, RED, WareBot


def clip(text: str | None, n: int = 900) -> str:
    if not text:
        return "*—*"
    return text if len(text) <= n else text[:n] + "…"


class Moderation(commands.Cog):
    """Keep the streets clean."""

    def __init__(self, bot: WareBot):
        self.bot = bot

    # ── helpers ─────────────────────────────────────────────────
    def _can_act(self, ctx: commands.Context, target: discord.Member) -> bool:
        """Hierarchy checks: nobody is above the owner; bot must outrank target."""
        if target == ctx.guild.owner:
            return False
        if ctx.author == ctx.guild.owner:
            pass
        elif ctx.author.top_role <= target.top_role:
            return False
        return ctx.guild.me.top_role > target.top_role

    async def _mod_log(self, guild: discord.Guild, title: str, desc: str, color):
        e = self.bot.embed(title, desc, color=color)
        await self.bot.send_log(guild, "mod_logs", e)

    # ════════════════════════════════════════════════════════════
    #  BAN
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="ban", description="Ban a member from the hood")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="Who is getting banned", reason="Why?")
    async def ban(self, ctx: commands.Context, member: discord.Member,
                  *, reason: str = "No reason given"):
        if not self._can_act(ctx, member):
            return await ctx.send(embed=self.bot.embed(
                "CAN'T DO IT", "That member outranks you (or me). Deal with it in person.",
                color=ORANGE), ephemeral=True)
        try:
            await member.send(
                f"You got **BANNED** from **{ctx.guild.name}**\nReason: {reason}")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await member.ban(reason=f"by {ctx.author}: {reason}", delete_message_seconds=86400)
        e = self.bot.embed(
            "🔨 BANNED FROM THE HOOD",
            f"**member:** {member.mention} (`{member}`)\n"
            f"**by:** {ctx.author.mention}\n**reason:** {clip(reason)}",
            color=RED)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "🔨 BAN", f"{member} | by {ctx.author} | {clip(reason)}", RED)

    # ════════════════════════════════════════════════════════════
    #  UNBAN
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="unban", description="Unban a user by ID")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The ID of the banned user")
    async def unban(self, ctx: commands.Context, user_id: str,
                    *, reason: str = "No reason given"):
        try:
            user = await self.bot.fetch_user(int(user_id))
        except (ValueError, discord.NotFound):
            return await ctx.send(embed=self.bot.embed(
                "NOT FOUND", "That ID doesn't match any user.", color=ORANGE), ephemeral=True)
        try:
            await ctx.guild.unban(user, reason=f"by {ctx.author}: {reason}")
        except discord.NotFound:
            return await ctx.send(embed=self.bot.embed(
                "NOT BANNED", "That user is not banned.", color=ORANGE), ephemeral=True)
        e = self.bot.embed(
            "🕊 UNBANNED",
            f"**user:** {user.mention} (`{user}`)\n**by:** {ctx.author.mention}",
            color=GREEN)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "🕊 UNBAN", f"{user} | by {ctx.author}", GREEN)

    # ════════════════════════════════════════════════════════════
    #  KICK
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="kick", description="Kick a member from the hood")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="Who is getting kicked", reason="Why?")
    async def kick(self, ctx: commands.Context, member: discord.Member,
                   *, reason: str = "No reason given"):
        if not self._can_act(ctx, member):
            return await ctx.send(embed=self.bot.embed(
                "CAN'T DO IT", "That member outranks you (or me).", color=ORANGE), ephemeral=True)
        try:
            await member.send(
                f"You got **KICKED** from **{ctx.guild.name}**\nReason: {reason}")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await member.kick(reason=f"by {ctx.author}: {reason}")
        e = self.bot.embed(
            "👢 KICKED",
            f"**member:** {member.mention} (`{member}`)\n"
            f"**by:** {ctx.author.mention}\n**reason:** {clip(reason)}",
            color=ORANGE)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "👢 KICK", f"{member} | by {ctx.author} | {clip(reason)}", ORANGE)

    # ════════════════════════════════════════════════════════════
    #  MUTE / TIMEOUT
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="mute", description="Timeout a member (native mute)",
                             aliases=["timeout", "to"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="Who is getting muted", minutes="Minutes (max 40320 = 28d)",
                           reason="Why?")
    async def mute(self, ctx: commands.Context, member: discord.Member,
                   minutes: int = 60, *, reason: str = "No reason given"):
        if not self._can_act(ctx, member):
            return await ctx.send(embed=self.bot.embed(
                "CAN'T DO IT", "That member outranks you (or me).", color=ORANGE), ephemeral=True)
        minutes = max(1, min(minutes, 40320))
        try:
            await member.timeout(timedelta(minutes=minutes),
                                 reason=f"by {ctx.author}: {reason}")
        except (discord.Forbidden, discord.HTTPException):
            return await ctx.send(embed=self.bot.embed(
                "FAILED", "Timeout failed — check my role position.", color=RED), ephemeral=True)
        e = self.bot.embed(
            "🔇 MUTED",
            f"**member:** {member.mention} (`{member}`)\n"
            f"**duration:** {minutes} min\n"
            f"**by:** {ctx.author.mention}\n**reason:** {clip(reason)}",
            color=ORANGE)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "🔇 MUTE",
                            f"{member} | {minutes}m | by {ctx.author} | {clip(reason)}", ORANGE)

    @commands.hybrid_command(name="unmute", description="Remove a timeout from a member")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="Who is getting unmuted")
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        try:
            await member.timeout(None, reason=f"unmuted by {ctx.author}")
        except (discord.Forbidden, discord.HTTPException):
            return await ctx.send(embed=self.bot.embed(
                "FAILED", "Could not remove the timeout.", color=RED), ephemeral=True)
        e = self.bot.embed(
            "🔊 UNMUTED",
            f"**member:** {member.mention}\n**by:** {ctx.author.mention}", color=GREEN)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "🔊 UNMUTE", f"{member} | by {ctx.author}", GREEN)

    # ════════════════════════════════════════════════════════════
    #  WARN SYSTEM
    # ════════════════════════════════════════════════════════════
    def _warns(self, guild_id, user_id):
        data = self.bot.load_json("warnings.json", {})
        return data.setdefault(str(guild_id), {}).setdefault(str(user_id), [])

    def _save_warns(self, guild_id, user_id, entries):
        data = self.bot.load_json("warnings.json", {})
        data.setdefault(str(guild_id), {})[str(user_id)] = entries
        self.bot.save_json("warnings.json", data)

    @commands.hybrid_command(name="warn", description="Warn a member (3 warns = auto mute)")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="Who is getting warned", reason="Why?")
    async def warn(self, ctx: commands.Context, member: discord.Member,
                   *, reason: str = "No reason given"):
        if not self._can_act(ctx, member):
            return await ctx.send(embed=self.bot.embed(
                "CAN'T DO IT", "That member outranks you (or me).", color=ORANGE), ephemeral=True)
        entries = self._warns(ctx.guild.id, member.id)
        entries.append({
            "reason": reason,
            "mod": ctx.author.id,
            "time": discord.utils.utcnow().isoformat(),
        })
        self._save_warns(ctx.guild.id, member.id, entries)
        limit = int(self.bot.sec_cfg("warn_limit", 3))

        extra = ""
        if len(entries) >= limit:
            try:
                await member.timeout(timedelta(minutes=60), reason=f"{limit} warnings")
                extra = f"\n\n**{len(entries)} warns — auto muted for 60 min.**"
            except (discord.Forbidden, discord.HTTPException):
                extra = "\n\n**warn limit reached — mute failed (check my role).**"

        e = self.bot.embed(
            "⚠️ WARNED",
            f"**member:** {member.mention} (`{member}`)\n"
            f"**reason:** {clip(reason)}\n"
            f"**warns:** {len(entries)}/{limit}{extra}",
            color=ORANGE)
        await ctx.send(embed=e)
        await self._mod_log(ctx.guild, "⚠️ WARN",
                            f"{member} | by {ctx.author} | {clip(reason)} "
                            f"| total {len(entries)}", ORANGE)

    @commands.hybrid_command(name="warnings", description="Show a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        entries = self._warns(ctx.guild.id, member.id)
        if not entries:
            return await ctx.send(embed=self.bot.embed(
                "CLEAN RECORD", f"{member.mention} has no warnings. Good kid.", color=GREEN),
                ephemeral=True)
        lines = []
        for i, w in enumerate(entries[-10:], 1):
            lines.append(f"**{i}.** {clip(w.get('reason', '—'), 80)} "
                         f"— <@{w.get('mod', 0)}> · {str(w.get('time', ''))[:10]}")
        await ctx.send(embed=self.bot.embed(
            f"⚠️ WARNINGS — {member} ({len(entries)})", "\n".join(lines), color=ORANGE),
            ephemeral=True)

    @commands.hybrid_command(name="clearwarns", description="Wipe a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def clearwarns(self, ctx: commands.Context, member: discord.Member):
        self._save_warns(ctx.guild.id, member.id, [])
        await ctx.send(embed=self.bot.embed(
            "🧹 RECORD WIPED", f"All warnings cleared for {member.mention}.", color=GREEN),
            ephemeral=True)

    # ════════════════════════════════════════════════════════════
    #  CLEAR CHAT
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="clear", description="Delete the last N messages in this channel",
                             aliases=["purge"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @app_commands.describe(amount="How many messages (1-100)")
    async def clear(self, ctx: commands.Context, amount: int = 10):
        amount = max(1, min(amount, 100))
        deleted = await ctx.channel.purge(limit=amount + 1)
        e = self.bot.embed(
            "🧹 CHAT CLEARED",
            f"**{max(0, len(deleted) - 1)} messages** deleted by {ctx.author.mention}.",
            color=GREEN)
        await ctx.send(embed=e, ephemeral=True)

    # ════════════════════════════════════════════════════════════
    #  LOCK / UNLOCK a channel
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="lock", description="Lock a channel (stop @everyone from typing)")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to lock (default: this one)")
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        ows = dict(ch.overwrites)
        ow = ows.get(ctx.guild.default_role) or discord.PermissionOverwrite()
        ow.send_messages = False
        ows[ctx.guild.default_role] = ow
        await ch.edit(overwrites=ows, reason=f"locked by {ctx.author}")
        await ctx.send(embed=self.bot.embed("🔒 LOCKED", f"{ch.mention} is locked.",
                                            color=ORANGE))

    @commands.hybrid_command(name="unlock", description="Unlock a locked channel")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to unlock (default: this one)")
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        ows = dict(ch.overwrites)
        ow = ows.get(ctx.guild.default_role)
        if ow is not None:
            ow.send_messages = None
            if ow.is_empty():
                ows.pop(ctx.guild.default_role, None)
            else:
                ows[ctx.guild.default_role] = ow
        await ch.edit(overwrites=ows, reason=f"unlocked by {ctx.author}")
        await ctx.send(embed=self.bot.embed("🔓 UNLOCKED", f"{ch.mention} is open again.",
                                            color=GREEN))

    # ════════════════════════════════════════════════════════════
    #  SLOWMODE
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="slowmode", description="Set slowmode for a channel (seconds)")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="0-21600 seconds (0 = off)",
                           channel="Channel (default: this one)")
    async def slowmode(self, ctx: commands.Context, seconds: int,
                       channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        seconds = max(0, min(seconds, 21600))
        await ch.edit(slowmode_delay=seconds, reason=f"by {ctx.author}")
        txt = f"slowmode **{seconds}s**" if seconds else "slowmode **OFF**"
        await ctx.send(embed=self.bot.embed("⏱ SLOWMODE", f"{ch.mention} -> {txt}.",
                                            color=GREEN))

    # ════════════════════════════════════════════════════════════
    #  INFO
    # ════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="serverinfo", description="Server info, old-school style")
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        g = ctx.guild
        created = g.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        e = self.bot.embed(
            f"🏚 {g.name}",
            f"**owner:** <@{g.owner_id}>\n"
            f"**members:** {g.member_count}\n"
            f"**roles:** {len(g.roles)}\n"
            f"**channels:** {len(g.text_channels)} text / {len(g.voice_channels)} voice\n"
            f"**created:** {created}\n"
            f"**verification:** {g.verification_level.name}\n"
            f"**content filter:** {g.explicit_content_filter.name}",
            color=EMBED_COLOR)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="ping", description="Check if the bot is alive")
    async def ping(self, ctx: commands.Context):
        await ctx.send(embed=self.bot.embed(
            "🏓 PONG", f"latency: **{round(self.bot.latency * 1000)}ms** — still breathing.",
            color=GREEN))

    @commands.hybrid_command(name="help", description="The full command list")
    async def help(self, ctx: commands.Context):
        lines = (
            "**🛠 SETUP**\n"
            "• `!setup` — build the whole server (admin)\n"
            "**🔨 MODERATION**\n"
            "• `!ban / !kick / !unban` — remove or return folks\n"
            "• `!mute <member> <min>` / `!unmute` — timeout\n"
            "• `!warn / !warnings / !clearwarns` — warn system\n"
            "• `!clear <n>` — delete last N messages\n"
            "• `!lock / !unlock / !slowmode <s>` — channel control\n"
            "**🛡 SECURITY**\n"
            "• `!lockdown on/off` — freeze the whole server\n"
            "• `!security` — full security dashboard\n"
            "• `!trust / !untrust @member` — whitelist (never auto-punished)\n"
            "**💾 RECOVERY**\n"
            "• `!backup` — snapshot the server structure NOW\n"
            "• `!restore` — rebuild deleted channels/roles after a nuke\n"
            "**ℹ️ INFO**\n"
            "• `!serverinfo / !ping`\n\n"
            "**🤖 ALWAYS ON, NO COMMANDS NEEDED:**\n"
            "anti-spam · anti-invite · anti-raid · anti-nuke (delete/ban/"
            "kick/create/rename) · anti-thread spam · anti-webhook raid · "
            "anti-permission-escalation · foreign-bot blocker · heat system · "
            "auto-backup · anticrash\n\n"
            "*Every command also works as a slash command (/ban ...)*"
        )
        await ctx.send(embed=self.bot.embed("📖 THE COMMANDS", lines, color=EMBED_COLOR))


async def setup(bot: WareBot):
    await bot.add_cog(Moderation(bot))
