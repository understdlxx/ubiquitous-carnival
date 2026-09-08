"""
WAREHUS BOT — full logging cog.
Logs to #server-logs: deleted/edited messages, role changes, nickname changes,
channel & role create/delete, voice activity, joins/leaves.
Logs to #mod-logs: bans & unbans.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from core import GREEN, ORANGE, RED, WareBot


def clip(text: str | None, n: int = 800) -> str:
    if not text:
        return "*—*"
    return text if len(text) <= n else text[:n] + "…"


class LoggingMod(commands.Cog):
    """The neighborhood watch. Everything gets written down."""

    def __init__(self, bot: WareBot):
        self.bot = bot

    # ── messages ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        desc = (f"**author:** {message.author.mention} (`{message.author}`)\n"
                f"**channel:** {message.channel.mention}\n"
                f"**content:** {clip(message.content)}")
        if message.attachments:
            names = ", ".join(a.filename for a in message.attachments[:5])
            desc += f"\n**attachments:** {names}"
        e = self.bot.embed("🗑 MESSAGE DELETED", desc, color=RED)
        await self.bot.send_log(message.guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        channel = messages[0].channel
        e = self.bot.embed(
            "🗑 BULK DELETE",
            f"**{len(messages)} messages** wiped in {channel.mention}.",
            color=RED)
        await self.bot.send_log(messages[0].guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        e = self.bot.embed(
            "✏️ MESSAGE EDITED",
            f"**author:** {before.author.mention} in {before.channel.mention}\n"
            f"**before:** {clip(before.content, 400)}\n"
            f"**after:** {clip(after.content, 400)}\n"
            f"[jump to message]({after.jump_url})",
            color=ORANGE)
        await self.bot.send_log(before.guild, "server_logs", e)

    # ── member changes ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        # nickname change
        if before.nick != after.nick:
            e = self.bot.embed(
                "📛 NICKNAME CHANGED",
                f"**member:** {after.mention}\n"
                f"**before:** {before.nick or '*none*'}\n"
                f"**after:** {after.nick or '*none*'}",
                color=ORANGE)
            await self.bot.send_log(guild, "server_logs", e)

        # role add / remove
        b_ids = {r.id for r in before.roles}
        a_ids = {r.id for r in after.roles}
        added = [guild.get_role(rid) for rid in (a_ids - b_ids)]
        removed = [guild.get_role(rid) for rid in (b_ids - a_ids)]
        added = [r for r in added if r]
        removed = [r for r in removed if r]
        if added:
            names = ", ".join(r.mention for r in added)
            e = self.bot.embed("➕ ROLES ADDED",
                               f"**member:** {after.mention}\n**roles:** {names}", color=GREEN)
            await self.bot.send_log(guild, "server_logs", e)
        if removed:
            names = ", ".join(r.mention for r in removed)
            e = self.bot.embed("➖ ROLES REMOVED",
                               f"**member:** {after.mention}\n**roles:** {names}", color=RED)
            await self.bot.send_log(guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.abc.User, after: discord.abc.User):
        if before.name != after.name or str(before) != str(after):
            settings = self.bot.load_json("settings.json", {})
            for gid in settings:
                guild = self.bot.get_guild(int(gid))
                if guild and guild.get_member(after.id):
                    e = self.bot.embed(
                        "👤 USERNAME CHANGED",
                        f"**before:** `{before}`\n**after:** `{after}`", color=ORANGE)
                    await self.bot.send_log(guild, "server_logs", e)
                    break

    # ── channels & roles ────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        e = self.bot.embed("📁 CHANNEL CREATED",
                           f"{channel.mention} (`{channel.name}`) in "
                           f"`{getattr(channel.category, 'name', '—')}`", color=GREEN)
        await self.bot.send_log(channel.guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        e = self.bot.embed("📁 CHANNEL DELETED",
                           f"`#{channel.name}` in "
                           f"`{getattr(channel.category, 'name', '—')}`", color=RED)
        await self.bot.send_log(channel.guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        e = self.bot.embed("🎭 ROLE CREATED", f"**role:** {role.mention}", color=GREEN)
        await self.bot.send_log(role.guild, "server_logs", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        e = self.bot.embed("🎭 ROLE DELETED", f"**role:** `{role.name}`", color=RED)
        await self.bot.send_log(role.guild, "server_logs", e)

    # ── bans ────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user):
        e = self.bot.embed("🔨 MEMBER BANNED",
                           f"**user:** {user} (`{user.id}`)", color=RED)
        await self.bot.send_log(guild, "mod_logs", e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user):
        e = self.bot.embed("🕊 MEMBER UNBANNED",
                           f"**user:** {user} (`{user.id}`)", color=GREEN)
        await self.bot.send_log(guild, "mod_logs", e)

    # ── voice ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState):
        if before.channel == after.channel:
            return
        if after.channel and not before.channel:
            desc = f"**{member.mention}** joined {after.channel.mention}"
            color = GREEN
        elif before.channel and not after.channel:
            desc = f"**{member.mention}** left {before.channel.mention}"
            color = ORANGE
        else:
            desc = (f"**{member.mention}** moved "
                    f"{before.channel.mention} -> {after.channel.mention}")
            color = ORANGE
        e = self.bot.embed("🔊 VOICE", desc, color=color)
        await self.bot.send_log(member.guild, "server_logs", e)


async def setup(bot: WareBot):
    await bot.add_cog(LoggingMod(bot))
