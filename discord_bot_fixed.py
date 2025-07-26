# discord_bot_merged.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import os
import json
import logging
from datetime import datetime, UTC, timedelta
from threading import Thread
from aiohttp import web
import pytz
from typing import Optional

# === CONFIG ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === TIMEZONE ===
TIMEZONE = pytz.timezone('Europe/Paris')
def get_current_time(): return datetime.now(TIMEZONE)
def parse_date(date_str):
    try:
        naive = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return TIMEZONE.localize(naive)
    except: return None

def format_date(date):
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"{days[date.weekday()]} {date.day} {months[date.month - 1]} {date.year} à {date.strftime('%H:%M')}"

# === FLASK (render) ===
async def start_web_server():
    async def health_check(request):
        return web.Response(text="Bot Discord actif ✅", status=200)
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()

# === TWITCH ===
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
streamers = {}
stream_messages = {}
currently_live_streamers = {}
ping_roles = {}
reaction_role_messages = {}

class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                data = await resp.json()
                self.token = data['access_token']
                self.token_expires_at = datetime.now(UTC).timestamp() + data['expires_in']
                self.headers = {
                    'Client-ID': TWITCH_CLIENT_ID,
                    'Authorization': f'Bearer {self.token}'
                }

    async def ensure_valid_token(self):
        if not self.token or datetime.now(UTC).timestamp() >= self.token_expires_at - 300:
            await self.get_token()

    async def get_streams(self, usernames):
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/streams"
        all_streams = []
        for i in range(0, len(usernames), 100):
            batch = usernames[i:i+100]
            params = {'user_login': batch}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        all_streams.extend(data['data'])
        return all_streams

twitch_api = TwitchAPI()

@tasks.loop(minutes=2)
async def check_streams():
    for channel_id, streamer_list in streamers.items():
        if not streamer_list:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        streams = await twitch_api.get_streams(streamer_list)
        live_now = {s['user_login']: s for s in streams}
        for username, stream in live_now.items():
            key = f"{channel_id}_{username}"
            if key in stream_messages:
                continue  # already live
            embed = discord.Embed(title=f"🔴 {stream['user_name']} est en live !", description=stream['title'], url=f"https://twitch.tv/{username}", color=0x9146ff)
            msg = await channel.send(embed=embed)
            stream_messages[key] = {'message_id': msg.id, 'last_update': datetime.now(UTC).timestamp()}

@check_streams.before_loop
async def before_check(): await bot.wait_until_ready()

# === EVENTS ===
events = {}
event_id_counter = 1
event_messages = {}
notifications_sent = {}
guild_role_configs = {}

class Event:
    def __init__(self, id, name, date, creator, guild_id, channel_id, role_id=None, category=None, stream=None, lieu=None, image=None, description=None):
        self.id = id
        self.name = name
        self.date = date
        self.creator = creator
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.role_id = role_id
        self.category = category
        self.stream = stream
        self.lieu = lieu
        self.image = image
        self.description = description
        self.created_at = get_current_time()

def create_event_embed(event):
    embed = discord.Embed(title=f"🎉 {event.name}", timestamp=event.created_at, color=0x00AE86)
    embed.add_field(name="📅 Date", value=format_date(event.date), inline=True)
    if event.lieu:
        embed.add_field(name="📍 Lieu", value=event.lieu, inline=True)
    if event.stream:
        embed.add_field(name="📺 Stream", value=event.stream, inline=False)
    if event.description:
        embed.add_field(name="📝 Description", value=event.description, inline=False)
    if event.image:
        embed.set_image(url=event.image)
    embed.set_footer(text=f"Créé par {event.creator}")
    return embed

@bot.tree.command(name="event-create", description="Créer un événement")
@app_commands.describe(nom="Nom", date="Date (DD/MM/YYYY HH:MM)", stream="Lien du stream", lieu="Lieu", image="Image", description="Description")
async def create_event(interaction: discord.Interaction, nom: str, date: str, stream: Optional[str] = None, lieu: Optional[str] = None, image: Optional[str] = None, description: Optional[str] = None):
    global event_id_counter
    dt = parse_date(date)
    if not dt:
        await interaction.response.send_message("❌ Date invalide.", ephemeral=True)
        return
    event = Event(event_id_counter, nom, dt, interaction.user.display_name, interaction.guild_id, interaction.channel_id, stream=stream, lieu=lieu, image=image, description=description)
    events[event_id_counter] = event
    embed = create_event_embed(event)
    await interaction.response.send_message(embed=embed)
    event_messages[event_id_counter] = await interaction.original_response()
    notifications_sent[event_id_counter] = {"15min": False, "live": False}
    event_id_counter += 1

@tasks.loop(minutes=1)
async def notification_system():
    now = get_current_time()
    for event_id, event in list(events.items()):
        if event_id not in notifications_sent:
            continue
        delta = event.date - now
        minutes = int(delta.total_seconds() / 60)
        if minutes <= 15 and not notifications_sent[event_id]["15min"]:
            await send_event_notification(event, 15)
            notifications_sent[event_id]["15min"] = True
        elif minutes <= 0 and not notifications_sent[event_id]["live"]:
            await send_event_notification(event, 0)
            notifications_sent[event_id]["live"] = True
        elif delta.total_seconds() < -1800:
            if event_id in event_messages:
                try: await event_messages[event_id].delete()
                except: pass
                del event_messages[event_id]
            del events[event_id]
            del notifications_sent[event_id]

async def send_event_notification(event, minutes_before):
    channel = bot.get_channel(event.channel_id)
    if not channel: return
    if minutes_before == 0:
        title = f"🔴 LIVE MAINTENANT - {event.name}"
        color = 0xFF0000
        msg = "L'événement commence maintenant !"
    else:
        title = f"⏰ {event.name} - dans {minutes_before} minutes"
        color = 0xFFA500
        msg = f"L'événement commence dans {minutes_before} minutes !"
    embed = discord.Embed(title=title, description=msg, color=color, timestamp=get_current_time())
    embed.add_field(name="📅 Heure", value=format_date(event.date), inline=True)
    if event.lieu:
        embed.add_field(name="📍 Lieu", value=event.lieu, inline=True)
    if event.stream:
        embed.add_field(name="📺 Stream", value=event.stream, inline=False)
    if event.image:
        embed.set_image(url=event.image)
    content = ""
    if event.role_id:
        role = channel.guild.get_role(event.role_id)
        if role:
            content = role.mention
    await channel.send(content=content, embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    await bot.tree.sync()
    await twitch_api.get_token()
    if not check_streams.is_running():
        check_streams.start()
    if not notification_system.is_running():
        notification_system.start()
    if os.getenv("PORT"):
        asyncio.create_task(start_web_server())

# === START ===
if __name__ == '__main__':
    token = os.getenv("DISCORD_TOKEN")
    if token:
        asyncio.run(bot.start(token))
    else:
        print("❌ DISCORD_TOKEN manquant !")
