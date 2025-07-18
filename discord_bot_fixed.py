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
import hashlib

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
        """Détection ULTRA STRICTE - Évite tous les faux positifs"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            logger.info(f"🔍 Détection STRICTE des parties LIVE...")

            # APPROCHE NOUVELLE : Détection par API ou données structurées
            api_game = await self.detect_from_api_data(soup, base_url)
            if api_game:
                games.append(api_game)
                logger.info(f"✅ Partie détectée via données API")
                return games

            # APPROCHE SPÉCIFIQUE OP.GG : Recherche d'éléments très spécifiques
            opgg_game = await self.detect_opgg_live_game(soup, base_url)
            if opgg_game:
                games.append(opgg_game)
                logger.info(f"✅ Partie détectée via OP.GG spécifique")
                return games

            # APPROCHE STRICTE : Détection par boutons de spectate réels
            spectate_game = await self.detect_real_spectate_buttons(soup, base_url)
            if spectate_game:
                games.append(spectate_game)
                logger.info(f"✅ Partie détectée via bouton spectate réel")
                return games

            # APPROCHE CONTEXTUELLE : Détection par contexte de jeu avec validation stricte
            context_game = await self.detect_with_strict_validation(soup, base_url)
            if context_game:
                games.append(context_game)
                logger.info(f"✅ Partie détectée avec validation stricte")
                return games

            logger.info(f"❌ Aucune partie LIVE authentique détectée")
            return games

        except Exception as e:
            logger.error(f"Erreur lors de la détection live: {e}")
            return []

    async def detect_from_api_data(self, soup, base_url):
        """Détecte les parties via les données API (JSON embarqué)"""
        try:
            # Chercher les scripts contenant des données JSON
            scripts = soup.find_all('script', string=re.compile(r'spectatorGameInfo|currentGame|liveGame|gameId', re.I))
            
            for script in scripts:
                script_content = script.string
                if not script_content:
                    continue
                
                # Chercher des patterns JSON spécifiques aux parties live
                json_patterns = [
                    r'"spectatorGameInfo"\s*:\s*({[^}]+})',
                    r'"currentGame"\s*:\s*({[^}]+})',
                    r'"liveGame"\s*:\s*({[^}]+})',
                    r'"gameId"\s*:\s*"?([^"',\s]+)"?'
                ]
                
                for pattern in json_patterns:
                    match = re.search(pattern, script_content)
                    if match:
                        try:
                            # Valider que c'est vraiment des données de jeu
                            if self.validate_game_json_data(match.group(0)):
                                player_name = await self.extract_player_name_from_url(base_url)
                                return {
                                    'id': self.generate_game_id(base_url, player_name),
                                    'url': base_url,
                                    'title': f"🔴 Partie LIVE de {player_name}",
                                    'player': player_name,
                                    'level': "?",
                                    'rank': "Non classé",
                                    'timestamp': datetime.now(UTC).timestamp(),
                                    'detected_at': datetime.now(UTC).isoformat(),
                                    'source': 'api_data'
                                }
                        except:
                            continue
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur detect_from_api_data: {e}")
            return None

    def validate_game_json_data(self, json_data):
        """Valide que les données JSON sont vraiment liées à une partie en cours"""
        # Vérifier que ce n'est pas du code technique générique
        if any(keyword in json_data.lower() for keyword in [
            'module', 'component', 'props', 'children', 'null,null', 
            'undefined', 'function', 'return', 'self.__next'
        ]):
            return False
        
        # Vérifier la présence d'indicateurs de jeu réels
        game_indicators = [
            'gameId', 'spectatorGameInfo', 'currentGame', 'participants',
            'gameLength', 'gameStartTime', 'gameMode'
        ]
        
        return any(indicator in json_data for indicator in game_indicators)

    async def detect_opgg_live_game(self, soup, base_url):
        """Détection spécifique pour OP.GG avec validation ultra stricte"""
        try:
            # 1. Chercher les classes CSS spécifiques à OP.GG pour les jeux actifs
            opgg_live_selectors = [
                '[class*="LiveGame"]',
                '[class*="live-game"]',
                '[class*="spectate"]',
                '[class*="InGame"]',
                '[class*="ingame"]',
                '[class*="CurrentGame"]'
            ]
            
            for selector in opgg_live_selectors:
                elements = soup.select(selector)
                for element in elements:
                    if await self.validate_opgg_element(element):
                        player_name = await self.extract_player_name_from_url(base_url)
                        return {
                            'id': self.generate_game_id(base_url, player_name),
                            'url': base_url,
                            'title': f"🔴 Partie LIVE de {player_name}",
                            'player': player_name,
                            'level': "?",
                            'rank': "Non classé",
                            'timestamp': datetime.now(UTC).timestamp(),
                            'detected_at': datetime.now(UTC).isoformat(),
                            'source': 'opgg_specific'
                        }
            
            # 2. Chercher des éléments avec du texte "LIVE" mais dans un contexte de jeu validé
            live_elements = soup.find_all(string=re.compile(r'\bLIVE\b|\bEn cours\b', re.I))
            for text_element in live_elements:
                parent = text_element.parent
                if parent and await self.validate_opgg_live_context(parent):
                    player_name = await self.extract_player_name_from_url(base_url)
                    return {
                        'id': self.generate_game_id(base_url, player_name),
                        'url': base_url,
                        'title': f"🔴 Partie LIVE de {player_name}",
                        'player': player_name,
                        'level': "?",
                        'rank': "Non classé",
                        'timestamp': datetime.now(UTC).timestamp(),
                        'detected_at': datetime.now(UTC).isoformat(),
                        'source': 'opgg_live_text'
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur detect_opgg_live_game: {e}")
            return None

    async def validate_opgg_element(self, element):
        """Validation stricte pour les éléments OP.GG"""
        try:
            element_text = element.get_text().strip().lower()
            element_classes = ' '.join(element.get('class', []))
            
            # EXCLUSION IMMÉDIATE - Éléments de navigation ou techniques
            strict_exclusions = [
                # Navigation et interface
                'dropdown', 'menu', 'nav', 'header', 'footer', 'sidebar',
                # Contenu technique
                'module', 'component', 'props', 'children', 'self.__next',
                # Faux contextes
                'statsleague', 'league of legendsleague', 'teamfight tacticsleague'
            ]
            
            if any(exclusion in element_text or exclusion in element_classes.lower() 
                   for exclusion in strict_exclusions):
                return False
            
            # VALIDATION POSITIVE - Doit contenir des indicateurs forts de jeu
            strong_indicators = [
                # Indicateurs de partie en cours
                'spectate', 'observer', 'live game', 'partie en cours',
                'currently playing', 'in game', 'ingame',
                # Stats de jeu spécifiques
                re.compile(r'\d+/\d+/\d+'),  # KDA
                re.compile(r'\d+\s*cs', re.I),  # CS
                re.compile(r'level\s*\d+', re.I)  # Niveau
            ]
            
            for indicator in strong_indicators:
                if isinstance(indicator, str):
                    if indicator in element_text:
                        return True
                else:  # regex
                    if indicator.search(element_text):
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erreur validate_opgg_element: {e}")
            return False

    async def validate_opgg_live_context(self, element):
        """Valide qu'un élément "LIVE" est dans un vrai contexte de jeu OP.GG"""
        try:
            # Récupérer tout le contexte (élément + parents + enfants)
            context_text = element.get_text().strip().lower()
            
            # Ajouter le contexte des parents
            parent = element.parent
            for _ in range(3):  # Remonter 3 niveaux
                if parent:
                    context_text += " " + parent.get_text().strip().lower()
                    parent = parent.parent
                else:
                    break
            
            # EXCLUSIONS STRICTES - Si présent, c'est un faux positif
            false_positive_patterns = [
                # Navigation et menus
                'dropdown', 'menu', 'navigation', 'nav-', 'navbar',
                # Contenu générique
                'statsleague', 'league of legendsleague', 'teamfight tacticsleague',
                # Éléments techniques
                'module', 'component', 'self.__next', 'props:', 'children:',
                # Listes et énumérations
                'recent games', 'parties récentes', 'match history',
                # Interface générale
                'champion list', 'liste champions', 'win rate', 'taux victoire'
            ]
            
            if any(pattern in context_text for pattern in false_positive_patterns):
                logger.info(f"❌ Contexte LIVE rejeté - faux positif détecté")
                return False
            
            # VALIDATION POSITIVE STRICTE - Doit avoir un contexte de jeu réel
            valid_game_context = [
                # Indicateurs de partie active
                'spectate', 'observer', 'regarder partie', 'watch game',
                # Stats de jeu en temps réel
                'kda', 'cs', 'kills', 'deaths', 'assists',
                # Éléments de partie
                'champion', 'summoner spell', 'item', 'gold', 'level'
            ]
            
            has_valid_context = any(indicator in context_text for indicator in valid_game_context)
            
            # VALIDATION ADDITIONNELLE - Chercher des patterns de données de jeu
            has_game_data = bool(
                re.search(r'\d+/\d+/\d+', context_text) or  # KDA
                re.search(r'\d+\s*cs', context_text) or     # CS
                re.search(r'level\s*\d+', context_text)     # Level
            )
            
            return has_valid_context or has_game_data
            
        except Exception as e:
            logger.error(f"Erreur validate_opgg_live_context: {e}")
            return False

    async def detect_real_spectate_buttons(self, soup, base_url):
        """Détecte uniquement les vrais boutons de spectate fonctionnels"""
        try:
            # Chercher les boutons avec du texte spécifique
            button_texts = ['spectate', 'observer', 'regarder', 'watch live', 'spectator']
            
            for button_text in button_texts:
                buttons = soup.find_all(['button', 'a'], string=re.compile(button_text, re.I))
                
                for button in buttons:
                    # Validation stricte du bouton
                    if await self.validate_real_spectate_button(button):
                        player_name = await self.extract_player_name_from_url(base_url)
                        return {
                            'id': self.generate_game_id(base_url, player_name),
                            'url': base_url,
                            'title': f"🔴 Partie LIVE de {player_name}",
                            'player': player_name,
                            'level': "?",
                            'rank': "Non classé",
                            'timestamp': datetime.now(UTC).timestamp(),
                            'detected_at': datetime.now(UTC).isoformat(),
                            'source': 'spectate_button'
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur detect_real_spectate_buttons: {e}")
            return None

    async def validate_real_spectate_button(self, button):
        """Valide qu'un bouton de spectate est réel et fonctionnel"""
        try:
            button_text = button.get_text().strip().lower()
            
            # EXCLUSIONS - Boutons qui ne sont pas de vrais spectates
            if any(fake in button_text for fake in [
                'demo', 'example', 'placeholder', 'test', 'sample',
                'pro-gamer', 'fake', 'disabled', 'coming soon'
            ]):
                return False
            
            # VALIDATION - Le bouton doit avoir des caractéristiques d'un vrai bouton
            # 1. Doit avoir un href ou être cliquable
            is_clickable = button.get('href') or button.get('onclick') or button.name == 'button'
            
            # 2. Ne doit pas être désactivé
            is_not_disabled = not button.get('disabled') and 'disabled' not in button.get('class', [])
            
            # 3. Doit être dans un contexte de jeu
            has_game_context = await self.button_has_game_context(button)
            
            return is_clickable and is_not_disabled and has_game_context
            
        except Exception as e:
            logger.error(f"Erreur validate_real_spectate_button: {e}")
            return False

    async def button_has_game_context(self, button):
        """Vérifie qu'un bouton est dans un contexte de jeu réel"""
        try:
            # Récupérer le contexte autour du bouton
            context_text = ""
            
            # Texte du bouton lui-même
            context_text += button.get_text().strip().lower()
            
            # Texte des éléments frères
            if button.parent:
                siblings = button.parent.find_all(string=True)
                context_text += " " + " ".join(sibling.strip().lower() for sibling in siblings)
            
            # Chercher des indicateurs de contexte de jeu
            game_context_indicators = [
                # Stats de jeu
                re.compile(r'\d+/\d+/\d+'),  # KDA
                re.compile(r'\d+\s*cs', re.I),  # CS
                re.compile(r'level\s*\d+', re.I),  # Level
                # Éléments de jeu
                'champion', 'summoner', 'rank', 'ranked', 'kda', 'kills',
                # Indicateurs temporels
                'live', 'en cours', 'currently', 'ingame', 'in game'
            ]
            
            for indicator in game_context_indicators:
                if isinstance(indicator, str):
                    if indicator in context_text:
                        return True
                else:  # regex
                    if indicator.search(context_text):
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erreur button_has_game_context: {e}")
            return False

    async def detect_with_strict_validation(self, soup, base_url):
        """Détection avec validation ultra stricte - dernier recours"""
        try:
            # Cette méthode ne s'active que si les autres ont échoué
            # Elle cherche des indicateurs très spécifiques avec validation maximale
            
            # 1. Chercher des éléments avec des données de temps de jeu (XX:XX format)
            time_elements = soup.find_all(string=re.compile(r'\b\d{1,2}:\d{2}\b'))
            
            for time_elem in time_elements:
                parent = time_elem.parent if hasattr(time_elem, 'parent') else time_elem.parent
                if parent and await self.validate_game_time_context(parent, time_elem):
                    player_name = await self.extract_player_name_from_url(base_url)
                    return {
                        'id': self.generate_game_id(base_url, player_name),
                        'url': base_url,
                        'title': f"🔴 Partie LIVE de {player_name}",
                        'player': player_name,
                        'level': "?",
                        'rank': "Non classé",
                        'timestamp': datetime.now(UTC).timestamp(),
                        'detected_at': datetime.now(UTC).isoformat(),
                        'source': 'time_validation'
                    }
            
            # 2. Chercher des patterns de données très spécifiques (KDA avec contexte)
            kda_elements = soup.find_all(string=re.compile(r'\b\d+/\d+/\d+\b'))
            
            for kda_elem in kda_elements:
                parent = kda_elem.parent if hasattr(kda_elem, 'parent') else kda_elem.parent
                if parent and await self.validate_kda_context(parent, kda_elem):
                    player_name = await self.extract_player_name_from_url(base_url)
                    return {
                        'id': self.generate_game_id(base_url, player_name),
                        'url': base_url,
                        'title': f"🔴 Partie LIVE de {player_name}",
                        'player': player_name,
                        'level': "?",
                        'rank': "Non classé",
                        'timestamp': datetime.now(UTC).timestamp(),
                        'detected_at': datetime.now(UTC).isoformat(),
                        'source': 'kda_validation'
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur detect_with_strict_validation: {e}")
            return None

    async def validate_game_time_context(self, element, time_text):
        """Valide qu'un temps affiché est bien un temps de jeu en cours"""
        try:
            context_text = element.get_text().strip().lower()
            time_value = time_text.strip()
            
            # Le temps doit être dans un format raisonnable (0:00 à 59:59)
            time_match = re.match(r'(\d{1,2}):(\d{2})', time_value)
            if not time_match:
                return False
            
            minutes, seconds = int(time_match.group(1)), int(time_match.group(2))
            if minutes > 59 or seconds > 59:
                return False
            
            # Le contexte doit indiquer que c'est un temps de jeu
            game_time_indicators = [
                'game time', 'temps de jeu', 'match time', 'duration',
                'live', 'en cours', 'current', 'spectate', 'observer'
            ]
            
            has_game_time_context = any(indicator in context_text for indicator in game_time_indicators)
            
            # Ne doit pas être dans un contexte non-jeu
            non_game_contexts = [
                'video duration', 'durée vidéo', 'replay', 'recorded',
                'timestamp', 'time ago', 'il y a', 'last seen'
            ]
            
            has_non_game_context = any(context in context_text for context in non_game_contexts)
            
            return has_game_time_context and not has_non_game_context
            
        except Exception as e:
            logger.error(f"Erreur validate_game_time_context: {e}")
            return False

    async def validate_kda_context(self, element, kda_text):
        """Valide qu'un KDA affiché est bien d'une partie en cours"""
        try:
            context_text = element.get_text().strip().lower()
            kda_value = kda_text.strip()
            
            # Valider le format KDA (doit être des chiffres raisonnables)
            kda_match = re.match(r'(\d+)/(\d+)/(\d+)', kda_value)
            if not kda_match:
                return False
            
            kills, deaths, assists = int(kda_match.group(1)), int(kda_match.group(2)), int(kda_match.group(3))
            
            # Valeurs raisonnables pour une partie en cours (pas des stats historiques)
            if kills > 50 or deaths > 50 or assists > 50:
                return False
            
            # Le contexte doit indiquer une partie actuelle
            current_game_indicators = [
                'current game', 'partie actuelle', 'live game', 'en cours',
                'spectate', 'observer', 'now playing', 'ingame'
            ]
            
            has_current_context = any(indicator in context_text for indicator in current_game_indicators)
            
            # Ne doit pas être des statistiques historiques
            historical_contexts = [
                'last game', 'dernière partie', 'recent', 'récent',
                'history', 'historique', 'average', 'moyenne',
                'total', 'career', 'carrière', 'season', 'saison'
            ]
            
            has_historical_context = any(context in context_text for context in historical_contexts)
            
            return has_current_context and not has_historical_context
            
        except Exception as e:
            logger.error(f"Erreur validate_kda_context: {e}")
            return False

    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL avec validation stricte"""
        try:
            # Patterns courants pour OP.GG et autres sites
            patterns = [
                r'userName=([^&]+)',           # userName=PLAYERNAME
                r'summonerName=([^&]+)',       # summonerName=PLAYERNAME
                r'/summoners/[^/]+/([^/?]+)',  # /summoners/euw/PLAYERNAME
                r'/summoner/[^/]+/([^/?]+)',   # /summoner/euw/PLAYERNAME
                r'/player/([^/?]+)',           # /player/PLAYERNAME
                r'/u/([^/?]+)',                # /u/PLAYERNAME
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    name = match.group(1).replace('%20', ' ').replace('+', ' ').replace('%2B', '+')
                    if self.is_valid_summoner_name(name):
                        return name
            
            return "Joueur inconnu"
            
        except Exception as e:
            logger.error(f"Erreur extraction nom depuis URL: {e}")
            return "Joueur inconnu"

    def is_valid_summoner_name(self, name):
        """Validation stricte des noms d'invocateur LoL"""
        if not name or len(name) < 3 or len(name) > 16:
            return False
        
        # Liste exhaustive d'exclusions
        invalid_patterns = [
            # Mots-clés techniques
            'live', 'spectate', 'observer', 'en cours', 'match', 'game',
            'self', 'null', 'undefined', 'function', 'var', 'let', 'const',
            'return', 'props', 'children', 'module', 'error', 'debug',
            'javascript', 'json', 'script', 'window', 'document', 'console',
            
            # Autres jeux
            'overwatch', 'valorant', 'apex', 'csgo', 'dota', 'fortnite',
            
            # Mots génériques LoL
            'stats', 'league', 'legends', 'statsleague', 'league of',
            'of legends', 'teamfight', 'tactics', 'summoner', 'champion',
            'ranked', 'classé', 'partie', 'victoire', 'défaite',
            
            # Éléments de démonstration
            'visionnage', 'pro', 'demo', 'example', 'test', 'sample',
            'fake', 'placeholder', 'visionnage pro', 'pro-gamer',
            
            # Interface
            'dropdown', 'menu', 'navigation', 'header', 'footer'
        ]
        
        name_lower = name.lower()
        if any(invalid in name_lower for invalid in invalid_patterns):
            return False
        
        # Vérifier les caractères spéciaux problématiques
        if any(char in name for char in ['(', ')', '[', ']', '{', '}', '<', '>', '/', '\\', '=', ';', ':', '"', "'"]):
            return False
        
        # Vérifier que ce n'est pas un nombre pur
        if name.isdigit():
            return False
        
        # Vérifier que ce n'est pas du code
        if any(code_pattern in name_lower for code_pattern in ['__', 'push', 'next', 'module_']):
            return False
        
        return True

    def generate_game_id(self, url, player_name):
        """Génère un ID unique pour un jeu"""
        timestamp = datetime.now(UTC)
        unique_string = f"{url}_{player_name}_{timestamp.strftime('%Y%m%d%H%M')}"
        return hashlib.md5(unique_string.encode()).hexdigest()[:8]

    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
            self.session = None

# Instance globale du moniteur
web_monitor = WebMonitor()

@bot.event
async def on_ready():
    logger.info(f'{bot.user} est connecté!')
    bot.ready_flag = True
    monitor_loop.start()

@bot.command(name='monitor')
async def add_monitor(ctx, url: str, mention_role: str = None):
    """Ajouter un site à surveiller"""
    try:
        logger.info(f"🔍 Commande !monitor reçue de {ctx.author} pour {url}")
        
        if not url.startswith(('http://', 'https://')):
            await ctx.send("❌ L'URL doit commencer par http:// ou https://")
            return

        # Test de connexion avec la nouvelle détection
        logger.info(f"🔍 Test de la nouvelle détection stricte pour {url}...")
        games = await web_monitor.check_site(url)
        
        guild_id = ctx.guild.id
        if guild_id not in monitored_sites:
            monitored_sites[guild_id] = {}

        monitored_sites[guild_id][url] = {
            'channel_id': ctx.channel.i
