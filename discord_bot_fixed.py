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

# === Flask (simulateur de port pour Render gratuit) ===
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

bot = commands.Bot(command_prefix='!', intents=intents)

# === Twitch API (identifiants à sécuriser via variable d'environnement idéalement) ===
TWITCH_CLIENT_ID = "tejcc6qy12vbclkl2qige9szpfoher"
TWITCH_CLIENT_SECRET = "18jywkay5xbbo5d2028f4fxwyf0txk"

# === Données temporairement en mémoire ===
streamers = {}
stream_messages = {}
ping_roles = {}
notification_channels = {}

# ... (Tout le reste de ton code existant reste inchangé)

# === TwitchAPI class (inchangée) ===
class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    # ... (toutes les méthodes comme get_token, get_streams, etc.)

# === Toutes tes commandes Discord restent inchangées ===

# === Lancement principal ===
if __name__ == "__main__":
    Thread(target=run_flask).start()  # ← Démarre le mini serveur web Flask pour Render

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant ! Définis la variable d'environnement DISCORD_BOT_TOKEN.")
    else:
        try:
            print(f"🚀 Connexion avec le token: {token[:10]}...")
            bot.run(token)
        except discord.errors.LoginFailure:
            print("❌ Token Discord invalide !")
        except Exception as e:
            logger.error(f"Erreur lors du lancement du bot: {e}")
