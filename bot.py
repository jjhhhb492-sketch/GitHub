import asyncio
import os
import random
import time

import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()


def env_int(name: str) -> int:
    v = os.getenv(name, "")
    return int(v) if v.isdigit() else 0


TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME", "السيرفر")
WELCOME_CHANNEL_ID = env_int("WELCOME_CHANNEL_ID")
LEAVE_CHANNEL_ID = env_int("LEAVE_CHANNEL_ID") or WELCOME_CHANNEL_ID
AUTO_ROLE_ID = env_int("AUTO_ROLE_ID")
SUPPORT_ROLE_ID = env_int("SUPPORT_ROLE_ID")
TICKET_CATEGORY_ID = env_int("TICKET_CATEGORY_ID")
MONGO_URI = os.getenv("MONGO_URI")

# ---------- قاعدة البيانات (اختيارية: للفلات والمكافأة اليومية) ----------
users = None
if MONGO_URI:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo import ReturnDocument

    users = AsyncIOMotorClient(MONGO_URI)["discordbot"]["users"]

NO_DB_MSG = "❌ هذا النظام غير مفعّل لسه (ناقص MONGO_URI)"


def level_for(xp: int) -> int:
    return int((xp / 100) ** 0.5)


def xp_for_level(level: int) -> int:
    return 100 * level * level


intents = discord.Intents.default()
intents.members = True  # لازم تفعّل Server Members Intent من Developer Portal


# ---------- التذاكر (أزرار دائمة) ----------
class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        topic = getattr(ch, "topic", "") or ""
        if not topic.startswith("ticket:"):
            return await interaction.response.send_message("❌ هذي مش تذكرة", ephemeral=True)

        support = interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        is_owner = topic == f"ticket:{interaction.user.id}"
        is_staff = interaction.user.guild_permissions.manage_channels or (
            support is not None and support in interaction.user.roles
        )
        if not (is_owner or is_staff):
            return await interaction.response.send_message("❌ ما عندكش صلاحية", ephemeral=True)

        await interaction.response.send_message("🔒 التذكرة تتقفل بعد 5 ثواني...")
        await asyncio.sleep(5)
        await ch.delete(reason=f"Ticket closed by {interaction.user}")


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 فتح تذكرة", style=discord.ButtonStyle.green, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, user = interaction.guild, interaction.user
        await interaction.response.defer(ephemeral=True)

        for ch in guild.text_channels:
            if ch.topic == f"ticket:{user.id}":
                return await interaction.followup.send(f"عندك تذكرة مفتوحة: {ch.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        support = guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        if support:
            overwrites[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        channel = await guild.create_text_channel(
            f"ticket-{user.name}",
            overwrites=overwrites,
            category=category,
            topic=f"ticket:{user.id}",
        )
        embed = discord.Embed(
            title="🎫 تذكرة جديدة",
            description=f"أهلاً {user.mention}، اكتب مشكلتك وفريق الدعم يرد عليك قريب.",
            color=discord.Color.blurple(),
        )
        await channel.send(
            content=support.mention if support else None,
            embed=embed,
            view=CloseView(),
        )
        await interaction.followup.send(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(TicketPanel())
        self.add_view(CloseView())
        await self.tree.sync()

        # سيرفر صغير عشان Render يشوف بورت مفتوح + UptimeRobot يعمل ping
        async def health(_request):
            return web.Response(text="Bot is running ✅")

        app = web.Application()
        app.router.add_get("/", health)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        await web.TCPSite(runner, "0.0.0.0", port).start()


bot = Bot()


@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")


# ---------- الترحيب + الرتبة التلقائية + المغادرة ----------
@bot.event
async def on_member_join(member: discord.Member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"أهلاً بيك في {SERVER_NAME} 👋",
            description=f"نورتنا يا {member.mention}\nأنت العضو رقم {member.guild.member_count}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    try:
        await member.send(
            f"أهلاً بيك {member.name} في **{SERVER_NAME}** 🎉\n"
            "اقرا القوانين وتمتع معانا!"
        )
    except discord.Forbidden:
        pass

    if AUTO_ROLE_ID:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Auto role")
            except discord.Forbidden:
                print("⚠️ ما نقدرش نعطي الرتبة: ارفع رتبة البوت فوق الرتبة التلقائية")


@bot.event
async def on_member_remove(member: discord.Member):
    channel = member.guild.get_channel(LEAVE_CHANNEL_ID)
    if channel:
        await channel.send(f"👋 **{member.display_name}** غادر السيرفر. نشوفوك على خير!")


# ---------- اللفلات (XP على الرسائل) ----------
xp_cooldown: dict[int, float] = {}


@bot.event
async def on_message(message: discord.Message):
    if users is None or message.author.bot or message.guild is None:
        return
    now = time.time()
    if now - xp_cooldown.get(message.author.id, 0) < 60:
        return
    xp_cooldown[message.author.id] = now

    gain = random.randint(15, 25)
    doc = await users.find_one_and_update(
        {"_id": f"{message.guild.id}-{message.author.id}"},
        {
            "$inc": {"xp": gain},
            "$setOnInsert": {"guild_id": message.guild.id, "user_id": message.author.id},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if level_for(doc["xp"]) > level_for(doc["xp"] - gain):
        await message.channel.send(f"🎉 مبروك {message.author.mention}! وصلت لفل **{level_for(doc['xp'])}**")


# ================= أوامر المعلومات =================
@bot.tree.command(name="user", description="معلومات عن عضو")
@app_commands.guild_only()
async def user_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role][:10]
    embed = discord.Embed(title=str(member), color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="الآيدي", value=member.id)
    embed.add_field(name="فتح الحساب", value=discord.utils.format_dt(member.created_at, "R"))
    embed.add_field(name="دخل السيرفر", value=discord.utils.format_dt(member.joined_at, "R"))
    embed.add_field(name="الرتب", value=" ".join(roles) or "ما فيش", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="صورة عضو")
@app_commands.guild_only()
async def avatar_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"صورة {member.display_name}", color=member.color)
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="server", description="معلومات السيرفر")
@app_commands.guild_only()
async def server_cmd(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="المالك", value=g.owner.mention if g.owner else "؟")
    embed.add_field(name="الأعضاء", value=g.member_count)
    embed.add_field(name="الرومات", value=len(g.channels))
    embed.add_field(name="الرتب", value=len(g.roles))
    embed.add_field(name="البوستات", value=g.premium_subscription_count)
    embed.add_field(name="تم الإنشاء", value=discord.utils.format_dt(g.created_at, "R"))
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="profile", description="بطاقتك (لفل وXP وعملات)")
@app_commands.guild_only()
async def profile_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"بطاقة {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="دخل السيرفر", value=discord.utils.format_dt(member.joined_at, "R"))
    if users is not None:
        doc = await users.find_one({"_id": f"{interaction.guild.id}-{member.id}"}) or {}
        xp = doc.get("xp", 0)
        lvl = level_for(xp)
        embed.add_field(name="اللفل", value=lvl)
        embed.add_field(name="XP", value=f"{xp} / {xp_for_level(lvl + 1)}")
        embed.add_field(name="العملات 🪙", value=doc.get("coins", 0))
    await interaction.response.send_message(embed=embed)


# ================= اللفلات والمكافأة =================
@bot.tree.command(name="rank", description="لفلك وXP")
@app_commands.guild_only()
async def rank_cmd(interaction: discord.Interaction, member: discord.Member = None):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    member = member or interaction.user
    doc = await users.find_one({"_id": f"{interaction.guild.id}-{member.id}"}) or {}
    xp = doc.get("xp", 0)
    lvl = level_for(xp)
    await interaction.response.send_message(
        f"📊 **{member.display_name}** — لفل **{lvl}** — XP: **{xp}** / {xp_for_level(lvl + 1)}"
    )


@bot.tree.command(name="top", description="أعلى 10 أعضاء")
@app_commands.guild_only()
async def top_cmd(interaction: discord.Interaction):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    lines = []
    cursor = users.find({"guild_id": interaction.guild.id}).sort("xp", -1).limit(10)
    i = 1
    async for d in cursor:
        lines.append(f"**{i}.** <@{d['user_id']}> — لفل {level_for(d['xp'])} ({d['xp']} XP)")
        i += 1
    embed = discord.Embed(
        title="🏆 المتصدرين",
        description="\n".join(lines) or "ما فيش أحد لسه",
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description="خذ مكافأتك اليومية")
@app_commands.guild_only()
async def daily_cmd(interaction: discord.Interaction):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    key = f"{interaction.guild.id}-{interaction.user.id}"
    doc = await users.find_one({"_id": key}) or {}
    now = time.time()
    last = doc.get("last_daily", 0)
    if now - last < 86400:
        when = f"<t:{int(last + 86400)}:R>"
        return await interaction.response.send_message(f"⏳ خذتها قبل، ارجع {when}", ephemeral=True)

    reward = random.randint(100, 200)
    await users.update_one(
        {"_id": key},
        {
            "$inc": {"coins": reward},
            "$set": {"last_daily": now},
            "$setOnInsert": {"guild_id": interaction.guild.id, "user_id": interaction.user.id},
        },
        upsert=True,
    )
    await interaction.response.send_message(f"🎁 خذت **{reward}** عملة 🪙")


# ================= التذاكر =================
@bot.tree.command(name="ticket_panel", description="إرسال لوحة فتح التذاكر")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def ticket_panel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    embed = discord.Embed(
        title="🎫 الدعم الفني",
        description="محتاج مساعدة؟ دوس الزر تحت وتفتح تذكرة خاصة مع فريق الدعم.",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=embed, view=TicketPanel())
    await interaction.response.send_message("✅ تم", ephemeral=True)


# ================= أوامر الأدمن =================
@bot.tree.command(name="announce", description="إرسال إعلان في روم معين")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    channel="الروم اللي يتبعت فيه الإعلان",
    title="عنوان الإعلان",
    message="نص الإعلان",
    mention_everyone="منشن @everyone؟",
)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
    mention_everyone: bool = False,
):
    embed = discord.Embed(title=f"📢 {title}", description=message, color=discord.Color.gold())
    await channel.send(
        content="@everyone" if mention_everyone else None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=mention_everyone),
    )
    await interaction.response.send_message("✅ تم إرسال الإعلان", ephemeral=True)


@bot.tree.command(name="dm", description="إرسال رسالة في الخاص لعضو")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="العضو", text="الرسالة")
async def dm(interaction: discord.Interaction, member: discord.Member, text: str):
    try:
        await member.send(text)
        await interaction.response.send_message(f"✅ انبعتت لـ {member.mention}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ الخاص مقفول عند العضو", ephemeral=True)


@bot.tree.command(name="say", description="خلي البوت يكتب رسالة في روم")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="الروم (مثلاً الشات العام)", text="الكلام")
async def say(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message("✅ تم", ephemeral=True)


bot.run(TOKEN)
