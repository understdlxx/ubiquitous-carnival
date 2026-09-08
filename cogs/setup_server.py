"""
WAREHUS BOT — server setup / template builder.

!setup  (or /setup)  builds the whole private-server template:

  📥 GETTING STARTED   welcome, rules, verify, announcements, introductions, staff-list
  🏠 PUBLIC            chat, images, fun, memes, off-topic, bot-commands
  🏭 WAREHUS           warehouse, media-vault, resources
  🎮 GTA SA            gta-chat, gta-clips, car-meet, server-status
  🔊 VOICE CHILL       chill lounge, gta sessions, car meet, afk
  🛡 STAFF ONLY        staff-chat, mod-logs, security-logs, server-logs

Roles: Owner / Admin / Moderator / Friend / Member / Unverified / Muted / Bots
Plus hard security settings (verification, content filter, slowmodes, lockdown perms).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from core import EMBED_COLOR, GOLD, GREEN, RED, WareBot

# ────────────────────────────────────────────────────────────────────
#  template definition
# ────────────────────────────────────────────────────────────────────

def ov(**kw) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(**kw)

# (channel_name, slowmode, @everyone overwrites, member-only perks)
PUBLIC_CATEGORIES = [
    ("📥 GETTING STARTED", [
        ("welcome", 0, {"send_messages": False, "add_reactions": True}, {}),
        ("rules", 0, {"send_messages": False}, {}),
        ("verify", 0, {"send_messages": False, "add_reactions": True}, {}),
        ("announcements", 0, {"send_messages": False, "add_reactions": True}, {}),
        ("introductions", 15, {}, {}),
        ("staff-list", 0, {"send_messages": False}, {}),
    ]),
    ("🏠 PUBLIC", [
        ("chat", 5, {}, {}),
        ("images", 8, {}, {"attach_files": True}),
        ("fun", 3, {}, {}),
        ("memes", 8, {}, {"attach_files": True}),
        ("off-topic", 5, {}, {}),
        ("bot-commands", 3, {}, {}),
    ]),
    ("🏭 WAREHUS", [
        ("warehouse", 10, {"attach_files": False}, {"attach_files": True}),
        ("media-vault", 10, {"attach_files": False}, {"attach_files": True}),
        ("resources", 0, {"send_messages": False}, {}),
    ]),
    ("🎮 GTA SA", [
        ("gta-chat", 5, {}, {}),
        ("gta-clips", 10, {}, {"attach_files": True}),
        ("car-meet", 8, {}, {}),
        ("server-status", 0, {"send_messages": False}, {}),
    ]),
]

VOICE_NAMES = ["🔊│Chill Lounge", "🔊│GTA Sessions", "🔊│Car Meet"]
AFK_CHANNEL = "💤│AFK"
STAFF_CATEGORY = "🛡 STAFF ONLY"
STAFF_CHANNELS = ["staff-chat", "mod-logs", "security-logs", "server-logs"]

ROLES = [
    # name, colour, permissions, hoist
    ("Owner", GOLD, discord.Permissions(administrator=True), True),
    ("Admin", RED, discord.Permissions(administrator=True), True),
    ("Moderator", 0x3498DB, discord.Permissions(
        manage_messages=True, manage_channels=True, manage_nicknames=True,
        kick_members=True, ban_members=True, moderate_members=True,
        view_audit_log=True, move_members=True, mute_members=True, deafen_members=True,
    ), True),
    ("Friend", 0x9B59B6, discord.Permissions(
        attach_files=True, use_external_emojis=True, priority_speaker=True,
        add_reactions=True, embed_links=True,
    ), True),
    ("Member", 0x95A5A6, discord.Permissions(
        send_messages=True, add_reactions=True, attach_files=True, embed_links=True,
        read_message_history=True, use_external_emojis=True, connect=True, speak=True,
        create_public_threads=False, create_private_threads=False, send_tts_messages=False,
    ), False),
    ("Unverified", 0x607D8B, discord.Permissions.none(), False),
    ("Muted", 0x2C2F33, discord.Permissions(
        send_messages=False, add_reactions=False, speak=False, connect=True,
        create_public_threads=False, create_private_threads=False,
    ), False),
    ("Bots", 0x5865F2, discord.Permissions.none(), True),
]

RULES_TEXT = (
    "**📜 THE RULES OF THE HOOD**\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "**1.** Respect each other. We're all grown here.\n"
    "**2.** No spam, no flooding, no self-bots. You will get folded.\n"
    "**3.** No raids, no invite links, no advertising. Instant ban, no paperwork.\n"
    "**4.** Keep it chill — NSFW stays out of public channels.\n"
    "**5.** No doxxing, no personal info. Privacy matters.\n"
    "**6.** Right channel for the right thing. Read the names.\n"
    "**7.** Staff word is final. Argue in DMs, not in the streets.\n"
    "**8.** GTA vibes only. Grab a controller, light one, relax. 🚬🕹\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "*Break the rules = gone. Keep it real, keep it chill.*"
)

WELCOME_TEXT = (
    "**WELCOME TO THE HOOD** 🏚\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "A private, old-school chill spot for real ones only.\n"
    "Here's the routine, homie:\n"
    "**1.** Read 📜#rules\n"
    "**2.** Hit the button in ✅#verify\n"
    "**3.** Introduce yourself in 👋#introductions\n"
    "**4.** Pull up in 💬#chat and chill\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "*No spam. No raids. No funny business. Security is watching.*"
)

VERIFY_TEXT = (
    "**ACCESS CHECKPOINT** 🚧\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "One step before you enter the streets.\n"
    "Read the rules, then hit the button below to get the **Member** role.\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
)

INTRO_TEXT = (
    "**👋 INTRODUCTIONS**\n"
    "Pull up and introduce yourself, old-school style:\n"
    "```Name / Age / Timezone / Fav GTA car / One line about you```"
)

STAFF_ACCESS = [
    ("👑 Owner", "Full control. Server + bot owner. Can do anything."),
    ("🛠 Admin", "Administrator. Manages server, roles, bans, bot settings."),
    ("🛡 Moderator", "Kicks, timeouts, clears chat, watches the streets."),
    ("🤝 Friend", "Trusted circle of the owners. Extra perks, extra trust."),
]


class SetupServer(commands.Cog):
    """Builds and hardens the whole server template."""

    def __init__(self, bot: WareBot):
        self.bot = bot

    # ────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="setup", description="Build the whole WAREHUS server template (admin only)")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True, manage_guild=True)
    async def setup(self, ctx: commands.Context):
        guild = ctx.guild
        me = guild.me

        status = await ctx.send(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD",
            "Give me a few seconds, homie...\n`step 1/6 — roles`", color=GOLD))

        st = self.bot.guild_settings(guild.id)
        created = {"roles": 0, "categories": 0, "channels": 0}
        failed = {"roles": 0, "channels": 0}

        # ── step 1: roles ───────────────────────────────────────
        role_map: dict[str, discord.Role] = {}
        for name, colour, perms, hoist in ROLES:
            role = self.bot.find_role(guild, name)
            if role is None:
                try:
                    role = await guild.create_role(
                        name=name, colour=discord.Colour(colour),
                        permissions=perms, hoist=hoist, mentionable=False,
                        reason="WAREHUS setup")
                    created["roles"] += 1
                except discord.Forbidden:
                    failed["roles"] += 1
                    continue
                except discord.HTTPException:
                    failed["roles"] += 1
                    continue
            role_map[name] = role

        await status.edit(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD", "`step 2/6 — role order`", color=GOLD))

        # best-effort: place roles right under the bot's top role
        order = ["Owner", "Admin", "Moderator", "Friend", "Bots", "Member", "Unverified", "Muted"]
        pos = max(1, me.top_role.position - 1)
        for name in order:
            role = role_map.get(name)
            if role and role.position != pos:
                try:
                    await role.edit(position=pos, reason="WAREHUS setup")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            pos -= 1

        # ── step 2: public categories & channels ────────────────
        await status.edit(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD", "`step 3/6 — categories & channels`", color=GOLD))

        muted = role_map.get("Muted")
        member = role_map.get("Member")

        for cat_name, channels in PUBLIC_CATEGORIES:
            cat = self.bot.find_category(guild, cat_name)
            if cat is None:
                try:
                    cat = await guild.create_category(cat_name, reason="WAREHUS setup")
                    created["categories"] += 1
                except (discord.Forbidden, discord.HTTPException):
                    continue

            for ch_name, slow, everyone_kw, member_kw in channels:
                overwrites = {}
                if everyone_kw:
                    overwrites[guild.default_role] = ov(**everyone_kw)
                if member_kw and member:
                    overwrites[member] = ov(**member_kw)
                if muted:
                    overwrites[muted] = ov(send_messages=False, add_reactions=False, speak=False)

                ch = self.bot.find_channel(guild, ch_name)
                if ch is None:
                    try:
                        ch = await guild.create_text_channel(
                            ch_name, category=cat, slowmode_delay=slow,
                            overwrites=overwrites or None, reason="WAREHUS setup")
                        created["channels"] += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed["channels"] += 1
                        continue
                # keep channel mapped even if it already existed
                self._map_channel(ch_name, ch, st)

        # ── step 3: voice + afk ─────────────────────────────────
        await status.edit(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD", "`step 4/6 — voice channels`", color=GOLD))

        voice_cat = self.bot.find_category(guild, "🔊 VOICE CHILL")
        if voice_cat is None:
            try:
                voice_cat = await guild.create_category("🔊 VOICE CHILL", reason="WAREHUS setup")
                created["categories"] += 1
            except (discord.Forbidden, discord.HTTPException):
                voice_cat = None

        afk_channel = None
        for vname in VOICE_NAMES + [AFK_CHANNEL]:
            vc = discord.utils.find(lambda c: c.name == vname, guild.voice_channels)
            if vc is None and voice_cat is not None:
                overwrites = {muted: ov(speak=False)} if muted else None
                try:
                    vc = await guild.create_voice_channel(
                        vname, category=voice_cat, overwrites=overwrites,
                        reason="WAREHUS setup")
                    created["channels"] += 1
                except (discord.Forbidden, discord.HTTPException):
                    continue
            if vname == AFK_CHANNEL:
                afk_channel = vc

        # ── step 4: staff-only category (locked) ────────────────
        await status.edit(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD", "`step 5/6 — staff area (locked)`", color=GOLD))

        staff_roles = [role_map[n] for n in ("Owner", "Admin", "Moderator") if n in role_map]
        staff_cat = self.bot.find_category(guild, STAFF_CATEGORY)
        if staff_cat is None:
            try:
                staff_cat = await guild.create_category(
                    STAFF_CATEGORY,
                    overwrites={
                        guild.default_role: ov(view_channel=False),
                        **{r: ov(view_channel=True, send_messages=True) for r in staff_roles},
                    },
                    reason="WAREHUS setup")
                created["categories"] += 1
            except (discord.Forbidden, discord.HTTPException):
                staff_cat = None

        for ch_name in STAFF_CHANNELS:
            ch = self.bot.find_channel(guild, ch_name)
            if ch is None and staff_cat is not None:
                try:
                    ch = await guild.create_text_channel(ch_name, category=staff_cat,
                                                         reason="WAREHUS setup")
                    created["channels"] += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed["channels"] += 1
                    continue
            if ch is not None:
                self._map_channel(ch_name, ch, st)

        # ── step 5: server hard settings ────────────────────────
        await status.edit(embed=self.bot.embed(
            "⚙️ BUILDING THE HOOD", "`step 6/6 — hardening server settings`", color=GOLD))

        hardened = []
        try:
            flags = discord.SystemChannelFlags()
            flags.suppress_join_notifications = True
            flags.suppress_premium_subscriptions = True
            welcome_ch = self.bot.find_channel(guild, "welcome")
            await guild.edit(
                verification_level=discord.VerificationLevel.high,
                explicit_content_filter=discord.ContentFilter.all_members,
                default_notifications=discord.NotificationLevel.only_mentions,
                system_channel=welcome_ch,
                system_channel_flags=flags,
                afk_channel=afk_channel,
                afk_timeout=300,
                reason="WAREHUS setup — hard security")
            hardened += ["verification: HIGH", "content filter: ALL MEMBERS",
                         "notifications: ONLY @mentions", "AFK channel: set (5 min)"]
        except (discord.Forbidden, discord.HTTPException):
            hardened += ["⚠️ some settings need the bot's role moved higher"]

        # lock down @everyone a bit
        try:
            dp = guild.default_role.permissions
            dp.mention_everyone = False
            dp.send_tts_messages = False
            dp.create_public_threads = False
            dp.create_private_threads = False
            dp.manage_messages = False
            await guild.default_role.edit(permissions=dp, reason="WAREHUS setup — lockdown")
            hardened += ["@everyone: no @-everyone / no TTS / no threads"]
        except (discord.Forbidden, discord.HTTPException):
            pass

        # give Owner role to the real owner
        owner_role = role_map.get("Owner")
        try:
            if owner_role and guild.owner and owner_role not in guild.owner.roles:
                await guild.owner.add_roles(owner_role, reason="WAREHUS setup — server owner")
        except (discord.Forbidden, discord.HTTPException):
            pass

        # ── save settings ───────────────────────────────────────
        settings = self.bot.load_json("settings.json", {})
        gs = settings.setdefault(str(guild.id), {})
        gs.update(st)  # merge channel id mappings collected during the build
        for rname in ("Owner", "Admin", "Moderator", "Friend", "Member",
                      "Unverified", "Muted", "Bots"):
            r = role_map.get(rname)
            if r:
                gs[f"role_{rname.lower()}"] = r.id
        gs["staff_roles"] = [r.id for r in staff_roles]
        gs["setup_done"] = True
        gs["raid_mode"] = gs.get("raid_mode", False)
        self.bot.save_json("settings.json", settings)

        # ── step 6: embeds ──────────────────────────────────────
        await self._post_embeds(guild, role_map)

        # ── step 7: first backup snapshot (nuke insurance) ──────
        try:
            self.bot.snapshot_guild(guild)
        except Exception:
            pass

        # ── done ────────────────────────────────────────────────
        summary = (
            f"**roles** — {created['roles']} created, {failed['roles']} failed\n"
            f"**categories** — {created['categories']} created\n"
            f"**channels** — {created['channels']} created, {failed['channels']} failed\n\n"
            "**server hardening:**\n" + "\n".join(f"• {h}" for h in hardened)
        )
        done = self.bot.embed("✅ THE HOOD IS READY", summary, color=GREEN,
                              footer="next: move the bot role to the TOP of the role list")
        await status.edit(embed=done)

    # ────────────────────────────────────────────────────────────
    def _map_channel(self, ch_name: str, ch, st: dict) -> None:
        kind = {
            "welcome": "welcome", "rules": "rules", "verify": "verify",
            "announcements": "announcements", "introductions": "introductions",
            "staff-list": "staff_list", "chat": "chat",
            "mod-logs": "mod_logs", "security-logs": "security_logs",
            "server-logs": "server_logs", "staff-chat": "staff_chat",
        }.get(ch_name)
        if kind:
            st[kind] = ch.id

    async def _post_embeds(self, guild: discord.Guild, role_map: dict) -> None:
        # clear old bot embeds in bot-only channels, then post fresh ones
        for ch_name in ("welcome", "rules", "verify", "staff-list",
                        "introductions", "announcements", "server-status"):
            ch = self.bot.find_channel(guild, ch_name)
            if ch is None:
                continue
            try:
                await ch.purge(limit=25, check=lambda m: m.author == guild.me)
            except (discord.Forbidden, discord.HTTPException):
                pass

        async def post(ch_name: str, embed: discord.Embed, view=None, content=None):
            ch = self.bot.find_channel(guild, ch_name)
            if ch is None:
                return
            try:
                await ch.send(content=content, embed=embed, view=view)
            except (discord.Forbidden, discord.HTTPException):
                pass

        await post("rules", self.bot.embed("RULES", RULES_TEXT, color=EMBED_COLOR))
        await post("welcome", self.bot.embed("THE HOOD", WELCOME_TEXT, color=EMBED_COLOR))

        from cogs.welcome import VerifyView
        await post("verify", self.bot.embed("VERIFY", VERIFY_TEXT, color=GREEN),
                   view=VerifyView())

        # staff list with access levels
        lines = []
        for rname, desc in STAFF_ACCESS:
            role = role_map.get(rname.split(" ", 1)[1])
            names = ", ".join(m.mention for m in role.members[:8]) if role else "—"
            lines.append(f"**{rname}** — {desc}\n└ {names or '*nobody yet*'}")
        staff_embed = self.bot.embed(
            "STAFF & OWNERS",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
            "\n".join(lines) +
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Access levels are managed by the Owner role. Don't ask for it.*",
            color=GOLD)
        await post("staff-list", staff_embed)

        await post("introductions", self.bot.embed("INTRODUCE YOURSELF", INTRO_TEXT,
                                                   color=EMBED_COLOR))
        await post("announcements", self.bot.embed(
            "📢 THE SERVER IS LIVE",
            "The hood is officially up.\nSecurity system: **ACTIVE** 🛡\n"
            "Anti-raid / anti-spam / anti-nuke / full logs — everything on.",
            color=GREEN))
        await post("server-status", self.bot.embed(
            "🎮 SERVER STATUS",
            "**Server:** `online and chill`\n**Security:** `armed`\n**Mode:** `old school`",
            color=GREEN))


async def setup(bot: WareBot):
    await bot.add_cog(SetupServer(bot))
