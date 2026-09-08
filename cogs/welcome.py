"""
WAREHUS BOT — welcome & verification cog.
- persistent verify button (survives restarts)
- old-school welcome / goodbye embeds
- auto Unverified role on join, Member role on verify
"""

from __future__ import annotations

import discord
from discord.ext import commands

from core import GREEN, ORANGE, WareBot


class VerifyView(discord.ui.View):
    """Persistent verify button — registered in setup_hook, works after restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="I READ THE RULES — LET ME IN",
                       style=discord.ButtonStyle.success,
                       emoji="✅",
                       custom_id="warehus:verify:v1")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        guild = interaction.guild
        member = interaction.user

        if not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                "Something went sideways — try again.", ephemeral=True)

        st = bot.guild_settings(guild.id)
        member_role = guild.get_role(int(st["role_member"])) if st.get("role_member") \
            else bot.find_role(guild, "Member")

        if member_role is None:
            return await interaction.response.send_message(
                "The **Member** role doesn't exist yet. Run `!setup` first.", ephemeral=True)

        if member_role in member.roles:
            return await interaction.response.send_message(
                "You're already verified, homie. Pull up in #chat.", ephemeral=True)

        try:
            await member.add_roles(member_role, reason="Verified via button")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message(
                "Couldn't give you the role — tell an admin to check my permissions.",
                ephemeral=True)

        # drop the Unverified marker role if present
        unv = guild.get_role(int(st["role_unverified"])) if st.get("role_unverified") else None
        if unv and unv in member.roles:
            try:
                await member.remove_roles(unv, reason="Verified")
            except (discord.Forbidden, discord.HTTPException):
                pass

        e = bot.embed(
            "✅ NEW MEMBER VERIFIED",
            f"{member.mention} (`{member}`) hit the button and got in.",
            color=GREEN)
        await bot.send_log(guild, "server_logs", e)

        # point the newcomer at the intro channel
        intro_ch = guild.get_channel(int(st["introductions"])) if st.get("introductions") else None
        intro_mention = intro_ch.mention if intro_ch else "#introductions"
        await interaction.response.send_message(
            "You're in. Welcome to the hood, homie. 🚬\n"
            f"Pull up in {intro_mention} and introduce yourself.",
            ephemeral=True)


class Welcome(commands.Cog):
    """Doors & greetings of the hood."""

    def __init__(self, bot: WareBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        st = self.bot.guild_settings(guild.id)
        days = (discord.utils.utcnow() - member.created_at).days

        # auto Unverified marker role (if setup was done)
        if st.get("role_unverified"):
            unv = guild.get_role(int(st["role_unverified"]))
            if unv:
                try:
                    await member.add_roles(unv, reason="WAREHUS: new joiner marker")
                except (discord.Forbidden, discord.HTTPException):
                    pass

        gs = self.bot.guild_settings(guild.id)
        ch = guild.get_channel(int(gs["welcome"])) if gs.get("welcome") else None
        if isinstance(ch, discord.TextChannel):
            count = guild.member_count or 0
            e = self.bot.embed(
                "👋 WELCOME TO THE HOOD",
                f"{member.mention} just pulled up.\n"
                f"**member:** #{count}\n"
                f"**account age:** {days} days\n\n"
                "Read the rules, hit ✅#verify, and go chill in #chat.\n"
                "*Keep it real, homie.*",
                color=GREEN)
            e.set_thumbnail(url=member.display_avatar.url)
            try:
                await ch.send(embed=e)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if gs.get("raid_mode"):
            e = self.bot.embed(
                "🚨 RAID WATCH",
                f"{member.mention} (`{member}`, account {days}d) joined "
                "**while raid mode is ARMED** — keep an eye on the gate logs.",
                color=ORANGE)
            await self.bot.send_log(guild, "security_logs", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        gs = self.bot.guild_settings(guild.id)

        ch = guild.get_channel(int(gs["welcome"])) if gs.get("welcome") else None
        if isinstance(ch, discord.TextChannel):
            e = self.bot.embed(
                "🚪 LEFT THE HOOD",
                f"**{member}** just dipped. One less real one.",
                color=ORANGE)
            e.set_thumbnail(url=member.display_avatar.url)
            try:
                await ch.send(embed=e)
            except (discord.Forbidden, discord.HTTPException):
                pass

        logs = guild.get_channel(int(gs["server_logs"])) if gs.get("server_logs") else None
        if isinstance(logs, discord.TextChannel):
            joined = member.joined_at.strftime("%Y-%m-%d %H:%M UTC") if member.joined_at else "unknown"
            e2 = self.bot.embed(
                "🚪 MEMBER LEFT",
                f"**user:** {member} (`{member.id}`)\n**joined:** {joined}",
                color=ORANGE)
            try:
                await logs.send(embed=e2)
            except (discord.Forbidden, discord.HTTPException):
                pass


async def setup(bot: WareBot):
    await bot.add_cog(Welcome(bot))
