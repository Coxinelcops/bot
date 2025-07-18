import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import os
from datetime import datetime, UTC
import logging
from threading import Thread
from flask import Flask
import re
from bs4 import BeautifulSoup
import json

# === Flask (pour Render) ===
app = Flask('')

@app.route('/')
def home():
    return "Bot Discord LoL Monitor actif."

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# === Logger ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Bot Discord ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.ready_flag = False

# === Stockage des données ===
monitored_sites = {}
active_games = {}

class WebMonitor:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    async def check_site(self, url, selector=None):
        """Vérifie un site pour des parties LoL en cours"""
        try:
            session = await self.get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    return await self.detect_live_game(html, url)
                else:
                    logger.warning(f"Erreur HTTP {response.status} pour {url}")
                    return []
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {url}: {e}")
            return []

    async def detect_live_game(self, html, base_url):
        """Détection STRICTE - Ne détecte que les vraies parties en cours"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            logger.info(f"🔍 Analyse de la page pour détecter une partie LIVE...")

            # NOUVELLE APPROCHE : Chercher uniquement les indicateurs RÉELS de partie en cours
            # 1. D'abord, vérifier s'il y a des indicateurs concrets de jeu actif
            game_status_indicators = await self.find_active_game_indicators(soup)
            
            if not game_status_indicators:
                logger.info(f"❌ Aucun indicateur de jeu actif trouvé")
                return []

            logger.info(f"🎯 {len(game_status_indicators)} indicateur(s) de jeu actif trouvé(s)")

            # 2. Validation que ces indicateurs sont bien des parties LIVE
            for indicator in game_status_indicators:
                if await self.validate_active_game_indicator(indicator, soup):
                    game_info = await self.extract_game_info_from_validated_element(indicator, base_url, soup)
                    if game_info:
                        logger.info(f"🎮 Partie LIVE confirmée : {game_info['title']}")
                        games.append(game_info)
                        break  # Une seule partie détectée suffit

            if not games:
                logger.info(f"❌ Aucune partie LIVE authentique détectée")
                # MÉTHODE ALTERNATIVE : Recherche plus permissive pour les vraies parties
                logger.info(f"🔍 Recherche alternative pour parties live...")
                alternative_games = await self.find_live_games_alternative(soup, base_url)
                if alternative_games:
                    games.extend(alternative_games)

            return games

        except Exception as e:
            logger.error(f"Erreur lors de la détection live: {e}")
            return []

    async def find_live_games_alternative(self, soup, base_url):
        """Méthode alternative pour détecter les vraies parties live"""
        try:
            games = []

            # 🔒 Étape 1 : Vérifier qu'on est sur une page LoL
            if not soup or not soup.get_text():
                return []

            page_text = soup.get_text().lower()
            if "league of legends" not in page_text and "lol" not in page_text:
                logger.info("❌ Pas de contexte LoL détecté → abandon détection alternative")
                return []

            # 🔍 Étape 2 : Recherche plus stricte

            logger.info(f"🔍 Recherche de boutons spectate authentiques...")
            spectate_buttons = soup.find_all(['button', 'a'], string=re.compile(r'spectate|watch live', re.I))
            for button in spectate_buttons:
                button_text = button.get_text().strip().lower()
                if not any(bad in button_text for bad in ['demo', 'example', 'pro']):
                    if any(stat in button_text for stat in ['level', 'rank', 'kda', 'cs', 'champion']):
                        logger.info(f"🎯 Bouton spectate potentiellement valide: {button_text}")
                        player_name = await self.extract_player_name_from_url(base_url)
                        if player_name and player_name != "Joueur inconnu":
                            game_info = {
                                'title': f"🔴 Partie LIVE de {player_name}",
                                'url': base_url,
                                'player': player_name,
                                'rank': "Non classé",
                                'level': "?"
                            }
                            games.append(game_info)
                            return games

            logger.info("❌ Aucun indicateur de partie live authentique trouvé (alternative bloquée)")
            return games

        except Exception as e:
            logger.error(f"Erreur dans find_live_games_alternative: {e}")
            return []

    # Ajoutez ici les autres méthodes manquantes de la classe WebMonitor
    async def find_active_game_indicators(self, soup):
        """Trouve les indicateurs de jeu actif"""
        # Implémentation à compléter
        return []
    
    async def validate_active_game_indicator(self, indicator, soup):
        """Valide un indicateur de jeu actif"""
        # Implémentation à compléter
        return False
    
    async def extract_game_info_from_validated_element(self, indicator, base_url, soup):
        """Extrait les informations de jeu depuis un élément validé"""
        # Implémentation à compléter
        return None
    
    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL"""
        # Implémentation à compléter
        return "Joueur inconnu"
