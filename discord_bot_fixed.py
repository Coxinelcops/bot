import discord
from discord.ext import commands, tasks
import aiohttp
import json
import asyncio
import os
from datetime import datetime, UTC
import logging
from threading import Thread
from flask import Flask

# === Flask (pour Render) ===
app = Flask('')

@app.route('/')
def home():
    return "Bot Discord actif."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# === Logger ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Bot Discord ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

# MODIFICATION: Désactiver la commande help par défaut
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# === Twitch credentials (variables d'environnement) ===
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

streamers = {}
stream_messages = {}  # Format: {channel_id_username: {'message_id': id, 'last_update': timestamp}}
currently_live_streamers = {}  # Pour suivre qui est actuellement en live
ping_roles = {}
notification_channels = {}
reaction_role_messages = {}

class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    async def get_token(self):
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            logger.error("❌ Variables d'environnement Twitch manquantes (TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)")
            return False
            
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.token = data['access_token']
                        self.headers = {
                            'Client-ID': TWITCH_CLIENT_ID,
                            'Authorization': f'Bearer {self.token}'
                        }
                        self.token_expires_at = datetime.now(UTC).timestamp() + data.get('expires_in', 3600)
                        logger.info("Token Twitch obtenu avec succès")
                        return True
                    else:
                        logger.error(f"Erreur lors de l'obtention du token Twitch: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Exception lors de l'obtention du token Twitch: {e}")
            return False

    async def ensure_valid_token(self):
        if not self.token or (self.token_expires_at and datetime.now(UTC).timestamp() >= self.token_expires_at - 300):
            await self.get_token()

    async def get_streams(self, usernames):
        if not usernames:
            return []

        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/streams"
        
        # L'API Twitch accepte jusqu'à 100 utilisateurs à la fois
        all_streams = []
        for i in range(0, len(usernames), 100):
            batch = usernames[i:i+100]
            params = {'user_login': batch}

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=self.headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            all_streams.extend(data['data'])
                        elif response.status == 401:
                            logger.warning("Token Twitch invalide, renouvellement...")
                            await self.get_token()
                            # Retry with new token
                            async with session.get(url, headers=self.headers, params=params) as retry_response:
                                if retry_response.status == 200:
                                    data = await retry_response.json()
                                    all_streams.extend(data['data'])
                        else:
                            logger.error(f"Erreur API Twitch streams: {response.status}")
                            
            except Exception as e:
                logger.error(f"Exception lors de la récupération des streams: {e}")
                
        return all_streams

    async def get_user_info(self, username):
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/users"
        params = {'login': username}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
        ...
