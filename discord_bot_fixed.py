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

app = Flask('')

@app.route('/')
def home():
    return "Bot Discord LoL Monitor actif."

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.ready_flag = False

monitored_sites = {}
active_games = {}

debug_logs = {}

class WebMonitor:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    async def validate_active_game_indicator    async def find_active_game_indicators(self, soup):
        """Renforcée : recherche uniquement d'éléments très probables d'une partie en cours"""
        active_indicators = []

        # 🔍 1. Classes courantes signalant une partie en cours
        classes_indicatives = [
            'in-game', 'live-game', 'currently-playing', 'match-live', 'game-active', 'spectate-active'
        ]
        for class_name in classes_indicatives:
            elements = soup.find_all(attrs={'class': re.compile(rf"\b{re.escape(class_name)}\b", re.I)})
            for el in elements:
                if el not in active_indicators:
                    active_indicators.append(el)

        # 🔍 2. Boutons ou liens contenant "Spectate", "Observer" (mais éviter les exemples ou faux matchs)
        spectate_keywords = re.compile(r'\b(spectate|observer|watch live|regarder)\b', re.I)
        spectate_elements = soup.find_all(['a', 'button'], string=spectate_keywords)
        for el in spectate_elements:
            if el.get_text(strip=True).lower() not in ['demo', 'example', 'test']:
                active_indicators.append(el)

        # 🔍 3. Élément avec stats de jeu précises (KDA, CS, niveau)
        stats_patterns = re.compile(r'(\d+/\d+/\d+|\d+\s*CS|level\s*\d+|\d+\s*KDA)', re.I)
        stat_matches = soup.find_all(string=stats_patterns)
        for s in stat_matches:
            if s.parent not in active_indicators:
                active_indicators.append(s.parent)

        # 🔍 4. Sections contenant "live" et "game" dans le même bloc
        combined_texts = soup.find_all(string=re.compile(r'live', re.I))
        for t in combined_texts:
            context = t.parent.get_text().lower() if t.parent else ""
            if 'game' in context or 'match' in context or 'partie' in context:
                if t.parent not in active_indicators:
                    active_indicators.append(t.parent)

        logger.info(f"🔍 {len(active_indicators)} indicateurs potentiels détectés")
        return active_indicators
(self element, soup, debug=False):
        logs = []
        try:
            element_text = element.get_text().strip().lower()
            logs.append(f"🔍 Analyse: '{element_text[:80]}...'")

            hard_exclusions = [
                'self.__next_f', 'push([', '__next_f', 'javascript', 'json',
                'script', 'function', 'var ', 'let ', 'const ', 'return',
                'props:', 'children:', 'module_', 'null,', 'undefined',
                'document.', 'window.', 'console.', 'error:', 'debug',
                'history', 'historique', 'previous', 'ancienne partie', 'match terminé', 'partie précédente'
            ]
            for exclusion in hard_exclusions:
                if exclusion in element_text:
                    logs.append(f"❌ Exclusion technique: {exclusion}")
                    return False, logs if debug else False

            strong_lol_indicators = [
                'live_game', 'partie en cours', 'currently playing',
                'in game', 'ingame', 'en partie', 'match en cours',
                'spectate', 'observer', 'regarder'
            ]
            if any(indicator in element_text for indicator in strong_lol_indicators):
                logs.append("✅ Indicateur fort détecté")
                return True, logs if debug else True

            other_games = ['overwatch', 'valorant', 'apex', 'csgo', 'fortnite', 'pubg', 'minecraft', 'wow', 'hearthstone']
            has_other_games = any(game in element_text for game in other_games)
            has_lol_context = any(lol_word in element_text for lol_word in ['league of legends', 'lol', 'summoner', 'champion'])
            if has_other_games and not has_lol_context:
                logs.append("❌ Autre jeu détecté sans LoL")
                return False, logs if debug else False

            has_game_stats = (
                re.search(r'\d+/\d+/\d+', element_text) or
                re.search(r'\d+\s*cs', element_text, re.I) or
                re.search(r'level\s*\d+', element_text, re.I) or
                re.search(r'\d+\s*kda', element_text, re.I) or
                re.search(r'(iron|bronze|silver|gold|platinum|diamond|master|grandmaster|challenger)', element_text, re.I)
            )
            if has_game_stats:
                if await self.has_live_game_context(element):
                    logs.append("✅ Statistiques valides dans contexte live")
                    return True, logs if debug else True
                else:
                    logs.append("❌ Stats détectées mais contexte live manquant")
                    return False, logs if debug else False

            live_indicators = ['live', 'en cours', 'currently', 'playing']
            if any(indicator in element_text for indicator in live_indicators):
                if await self.has_game_context_nearby(element):
                    logs.append("✅ LIVE + Contexte jeu")
                    return True, logs if debug else True
                else:
                    logs.append("❌ LIVE sans contexte jeu")
                    return False, logs if debug else False

            logs.append("❌ Aucune validation suffisante")
            return False, logs if debug else False

        except Exception as e:
            logs.append(f"❌ Exception: {e}")
            return False, logs if debug else False

    # autres méthodes: has_game_context_nearby, has_live_game_context, etc.

web_monitor = WebMonitor()

@bot.command(name='debugcheck')
async def debug_check(ctx, url: str):
    try:
        await ctx.send(f"🧪 Vérification DEBUG de {url}...")
        session = await web_monitor.get_session()
        async with session.get(url) as response:
            if response.status != 200:
                await ctx.send(f"❌ Erreur HTTP: {response.status}")
                return
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            indicators = await web_monitor.find_active_game_indicators(soup)

            if not indicators:
                await ctx.send("❌ Aucun indicateur trouvé.")
                return

            for i, elem in enumerate(indicators[:3]):  # Limite à 3 pour ne pas spam
                valid, logs = await web_monitor.validate_active_game_indicator(elem, soup, debug=True)
                embed = discord.Embed(title=f"🔍 Élément #{i+1}", color=0x00ffff)
                embed.description = elem.get_text()[:300] or "[vide]"
                embed.add_field(name="✅ Valide ?", value=str(valid))
                embed.add_field(name="🧾 Détails", value="\n".join(logs[:10]) or "Aucun log")
                await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Erreur debugcheck: {str(e)}")
