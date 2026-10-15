import os

import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
SERVER_NAME = os.getenv("SERVER_NAME", "السيرفر")

intents = discord.Intents.default()
intents.members = True  # لازم تفعّل Server Members Intent من Developer Portal


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
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


# ---------- 1) الترحيب ----------
@bot.event
async def on_member_join(member: discord.Member):
    # رسالة ترحيب في الروم
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"أهلاً بيك في {SERVER_NAME} 👋",
            description=f"نورتنا يا {member.mention}\nأنت العضو رقم {member.guild.member_count}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    # رسالة في الخاص
    try:
        await member.send(
            f"أهلاً بيك {member.name} في **{SERVER_NAME}** 🎉\n"
            "اقرا القوانين وتمتع معانا!"
        )
    except discord.Forbidden:
        pass  # الخاص مقفول عند العضو


# ---------- 2) إعلان في السيرفر ----------
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
    embed = discord.Embed(
        title=f"📢 {title}",
        description=message,
        color=discord.Color.gold(),
    )
    await channel.send(
        content="@everyone" if mention_everyone else None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=mention_everyone),
    )
    await interaction.response.send_message("✅ تم إرسال الإعلان", ephemeral=True)


# ---------- 3) رسالة في الخاص ----------
@bot.tree.command(name="dm", description="إرسال رسالة في الخاص لعضو")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="العضو", text="الرسالة")
async def dm(interaction: discord.Interaction, member: discord.Member, text: str):
    try:
        await member.send(text)
        await interaction.response.send_message(f"✅ انبعتت لـ {member.mention}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ الخاص مقفول عند العضو", ephemeral=True)


# ---------- 4) خلي البوت يتكلم في الشات العام ----------
@bot.tree.command(name="say", description="خلي البوت يكتب رسالة في روم")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="الروم (مثلاً الشات العام)", text="الكلام")
async def say(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message("✅ تم", ephemeral=True)


bot.run(TOKEN)
