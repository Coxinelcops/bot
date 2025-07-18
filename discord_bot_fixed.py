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
            
            logger.info(f"🔍 Analyse STRICTE de la page pour partie LIVE...")
            
            # ÉTAPE 1: Vérifications préliminaires strictes
            if not soup or len(html.strip()) < 1000:
                logger.info("❌ Page trop courte ou vide - pas de partie live")
                return []
            
            page_text = soup.get_text().lower()
            
            # ÉTAPE 2: Vérifier les indicateurs NÉGATIFS (pas en jeu)
            negative_indicators = [
                'not in game', 'offline', 'last seen', 'not currently', 
                'not playing', 'idle', 'away', 'spectate match history',
                'match history', 'recent games', 'ranked stats only',
                'profile', 'statistics', 'no current game', 'not in a game'
            ]
            
            for negative in negative_indicators:
                if negative in page_text:
                    logger.info(f"❌ Indicateur négatif détecté: '{negative}' - pas en jeu")
                    return []
            
            # ÉTAPE 3: Chercher des indicateurs POSITIFS très spécifiques
            live_indicators = await self.find_strict_live_indicators(soup, page_text)
            
            if not live_indicators:
                logger.info("❌ Aucun indicateur LIVE strict trouvé")
                return []
            
            logger.info(f"✅ {len(live_indicators)} indicateur(s) LIVE strict(s) trouvé(s)")
            
            # ÉTAPE 4: Validation finale avec extraction d'infos
            validated_games = []
            for indicator in live_indicators:
                game_info = await self.validate_and_extract_game_info(indicator, base_url, soup)
                if game_info:
                    logger.info(f"🎮 Partie LIVE CONFIRMÉE: {game_info['title']}")
                    validated_games.append(game_info)
                    break  # Une seule partie suffît
            
            return validated_games

        except Exception as e:
            logger.error(f"Erreur lors de la détection live: {e}")
            return []

    async def find_live_games_alternative(self, soup, base_url):
        """Méthode alternative ULTRA-STRICTE - dernière chance"""
        try:
            # Cette méthode ne sera appelée QUE si la détection stricte échoue
            # Et seulement avec des critères TRÈS spécifiques
            
            logger.info("🔍 Méthode alternative ultra-stricte...")
            
            # Vérifier qu'on a bien du contenu
            if not soup or len(soup.get_text().strip()) < 500:
                logger.info("❌ Contenu insuffisant pour méthode alternative")
                return []
            
            page_text = soup.get_text().lower()
            
            # BLOQUER si on détecte des éléments "non-live"
            blocking_terms = [
                'match history', 'recent games', 'past games', 'statistics only',
                'profile overview', 'not currently playing', 'offline', 'last seen',
                'ranked stats', 'champion mastery', 'achievements'
            ]
            
            for term in blocking_terms:
                if term in page_text:
                    logger.info(f"❌ Terme bloquant détecté: '{term}' - pas de partie live")
                    return []
            
            # Chercher des éléments TRÈS spécifiques seulement
            specific_live_elements = soup.find_all(attrs={'data-live': True})
            specific_live_elements.extend(soup.find_all(attrs={'class': re.compile(r'live-game|current-game|in-game', re.I)}))
            
            if not specific_live_elements:
                logger.info("❌ Aucun élément 'live' spécifique trouvé")
                return []
            
            # Si on arrive ici, on a trouvé des éléments très spécifiques
            logger.info(f"⚠️  Éléments spécifiques détectés, validation finale...")
            
            # Validation finale très stricte
            for element in specific_live_elements:
                element_text = element.get_text().lower()
                if 'live' in element_text or 'current' in element_text:
                    # Vérifier qu'il n'y a pas de contexte négatif
                    if not any(neg in element_text for neg in ['history', 'past', 'previous', 'last']):
                        player_name = await self.extract_player_name_from_url(base_url)
                        if player_name and player_name != "Joueur inconnu":
                            logger.info(f"🎮 Partie alternative détectée pour {player_name}")
                            return [{
                                'title': f"🔴 Partie détectée - {player_name}",
                                'url': base_url,
                                'player': player_name,
                                'status': "Détection alternative",
                                'type': 'alternative'
                            }]
            
            logger.info("❌ Validation finale échouée - pas de partie live")
            return []

        except Exception as e:
            logger.error(f"Erreur dans méthode alternative: {e}")
            return []

    async def find_strict_live_indicators(self, soup, page_text):
        """Trouve uniquement les indicateurs STRICTS de partie en cours"""
        live_indicators = []
        
        # 1. Chercher des éléments avec timer/countdown actif
        timers = soup.find_all(attrs={'class': re.compile(r'timer|countdown|duration', re.I)})
        for timer in timers:
            timer_text = timer.get_text().strip()
            # Format timer: "12:34" ou "1:23:45"
            if re.match(r'^\d{1,2}:\d{2}(:\d{2})?
    
    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL de façon plus robuste"""
        try:
            # Patterns courants pour extraire le nom du joueur
            patterns = [
                r'/summoner/([^/\?]+)',  # /summoner/PlayerName
                r'/player/([^/\?]+)',    # /player/PlayerName  
                r'/profile/([^/\?]+)',   # /profile/PlayerName
                r'summoner=([^&\?]+)',   # ?summoner=PlayerName
                r'player=([^&\?]+)',     # ?player=PlayerName
                r'name=([^&\?]+)',       # ?name=PlayerName
                r'/([^/\?]+)/?
, timer_text):
                live_indicators.append({'type': 'timer', 'element': timer, 'text': timer_text})
                logger.info(f"🎯 Timer actif détecté: {timer_text}")
        
        # 2. Chercher "IN GAME" ou "LIVE" très spécifiques
        live_elements = soup.find_all(string=re.compile(r'\b(IN GAME|LIVE NOW|CURRENTLY PLAYING)\b', re.I))
        for element in live_elements:
            parent = element.parent if hasattr(element, 'parent') else None
            if parent and not self.is_static_content(parent):
                live_indicators.append({'type': 'status', 'element': parent, 'text': element.strip()})
                logger.info(f"🎯 Statut LIVE détecté: {element.strip()}")
        
        # 3. Chercher des boutons "Spectate" avec données de jeu
        spectate_buttons = soup.find_all(['button', 'a'], string=re.compile(r'spectate|watch', re.I))
        for button in spectate_buttons:
            # Vérifier qu'il y a des données de champion/stats à proximité
            parent_section = button.find_parent(['div', 'section'])
            if parent_section:
                section_text = parent_section.get_text().lower()
                if any(indicator in section_text for indicator in ['champion', 'kda', 'cs', 'level']):
                    # Vérifier qu'il n'y a pas "history" ou "past"
                    if not any(negative in section_text for negative in ['history', 'past', 'previous', 'last game']):
                        live_indicators.append({'type': 'spectate', 'element': button, 'section': parent_section})
                        logger.info(f"🎯 Bouton spectate avec données live détecté")
        
        return live_indicators

    def is_static_content(self, element):
        """Vérifie si l'élément fait partie du contenu statique (navigation, footer, etc.)"""
        if not element:
            return True
            
        # Vérifier les classes/IDs typiques du contenu statique
        static_patterns = [
            r'nav', r'menu', r'header', r'footer', r'sidebar', 
            r'banner', r'advertisement', r'promo', r'guide'
        ]
        
        element_classes = ' '.join(element.get('class', []))
        element_id = element.get('id', '')
        
        for pattern in static_patterns:
            if re.search(pattern, element_classes + ' ' + element_id, re.I):
                return True
                
        return False

    async def validate_and_extract_game_info(self, indicator, base_url, soup):
        """Valide un indicateur et extrait les informations de jeu"""
        try:
            if indicator['type'] == 'timer':
                # Pour un timer, chercher le contexte de jeu autour
                timer_element = indicator['element']
                game_context = timer_element.find_parent(['div', 'section'])
                
                if game_context:
                    context_text = game_context.get_text().lower()
                    if any(game_term in context_text for game_term in ['champion', 'rank', 'summoner']):
                        player_name = await self.extract_player_name_from_url(base_url)
                        return {
                            'title': f"🔴 LIVE - {player_name} ({indicator['text']})",
                            'url': base_url,
                            'player': player_name,
                            'status': f"En jeu depuis {indicator['text']}",
                            'type': 'timer'
                        }
            
            elif indicator['type'] == 'status':
                player_name = await self.extract_player_name_from_url(base_url)
                return {
                    'title': f"🔴 {indicator['text']} - {player_name}",
                    'url': base_url,
                    'player': player_name,
                    'status': indicator['text'],
                    'type': 'status'
                }
            
            elif indicator['type'] == 'spectate':
                # Extraire les infos depuis la section du bouton spectate
                section = indicator['section']
                section_text = section.get_text()
                
                # Chercher champion
                champion_match = re.search(r'champion[:\s]*(\w+)', section_text, re.I)
                champion = champion_match.group(1) if champion_match else "Inconnu"
                
                player_name = await self.extract_player_name_from_url(base_url)
                return {
                    'title': f"🔴 SPECTATE - {player_name} ({champion})",
                    'url': base_url,
                    'player': player_name,
                    'champion': champion,
                    'status': "Spectatable",
                    'type': 'spectate'
                }
                
        except Exception as e:
            logger.error(f"Erreur validation indicateur: {e}")
            
        return None
    
    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL"""
        # Implémentation à compléter
        return "Joueur inconnu"
         # Dernier segment de l'URL
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url, re.I)
                if match:
                    player_name = match.group(1)
                    # Nettoyer le nom (décoder URL, supprimer caractères spéciaux)
                    import urllib.parse
                    player_name = urllib.parse.unquote(player_name)
                    player_name = re.sub(r'[^\w\s-]', '', player_name).strip()
                    
                    # Vérifier que ce n'est pas un terme générique
                    generic_terms = ['index', 'home', 'main', 'search', 'api', 'stats', 'leaderboard']
                    if player_name.lower() not in generic_terms and len(player_name) > 2:
                        logger.info(f"🎯 Nom du joueur extrait: {player_name}")
                        return player_name
            
            logger.warning(f"⚠️ Impossible d'extraire le nom du joueur depuis: {url}")
            return "Joueur inconnu"
            
        except Exception as e:
            logger.error(f"Erreur extraction nom joueur: {e}")
            return "Joueur inconnu"

# Fonction utilitaire pour debug - à ajouter temporairement
monitor = WebMonitor()

async def debug_url(url):
    """Fonction de debug pour tester une URL"""
    logger.info(f"🐛 DEBUG: Test de {url}")
    
    try:
        session = await monitor.get_session()
        async with session.get(url) as response:
            if response.status == 200:
                html = await response.text()
                
                # Analyser le contenu
                soup = BeautifulSoup(html, 'html.parser')
                page_text = soup.get_text().lower()
                
                logger.info(f"📄 Taille de la page: {len(html)} caractères")
                logger.info(f"📝 Contient 'live': {'live' in page_text}")
                logger.info(f"📝 Contient 'in game': {'in game' in page_text}")
                logger.info(f"📝 Contient 'spectate': {'spectate' in page_text}")
                logger.info(f"📝 Contient 'offline': {'offline' in page_text}")
                logger.info(f"📝 Contient 'not playing': {'not playing' in page_text}")
                
                # Tester la détection
                games = await monitor.detect_live_game(html, url)
                logger.info(f"🎮 Résultat détection: {len(games)} partie(s) détectée(s)")
                
                for game in games:
                    logger.info(f"   - {game}")
                    
            else:
                logger.error(f"❌ Erreur HTTP {response.status}")
                
    except Exception as e:
        logger.error(f"❌ Erreur debug: {e}")

# Pour utiliser la fonction debug, ajoutez ceci dans votre bot:
# await debug_url("votre_url_ici")
, timer_text):
                live_indicators.append({'type': 'timer', 'element': timer, 'text': timer_text})
                logger.info(f"🎯 Timer actif détecté: {timer_text}")
        
        # 2. Chercher "IN GAME" ou "LIVE" très spécifiques
        live_elements = soup.find_all(string=re.compile(r'\b(IN GAME|LIVE NOW|CURRENTLY PLAYING)\b', re.I))
        for element in live_elements:
            parent = element.parent if hasattr(element, 'parent') else None
            if parent and not self.is_static_content(parent):
                live_indicators.append({'type': 'status', 'element': parent, 'text': element.strip()})
                logger.info(f"🎯 Statut LIVE détecté: {element.strip()}")
        
        # 3. Chercher des boutons "Spectate" avec données de jeu
        spectate_buttons = soup.find_all(['button', 'a'], string=re.compile(r'spectate|watch', re.I))
        for button in spectate_buttons:
            # Vérifier qu'il y a des données de champion/stats à proximité
            parent_section = button.find_parent(['div', 'section'])
            if parent_section:
                section_text = parent_section.get_text().lower()
                if any(indicator in section_text for indicator in ['champion', 'kda', 'cs', 'level']):
                    # Vérifier qu'il n'y a pas "history" ou "past"
                    if not any(negative in section_text for negative in ['history', 'past', 'previous', 'last game']):
                        live_indicators.append({'type': 'spectate', 'element': button, 'section': parent_section})
                        logger.info(f"🎯 Bouton spectate avec données live détecté")
        
        return live_indicators

    def is_static_content(self, element):
        """Vérifie si l'élément fait partie du contenu statique (navigation, footer, etc.)"""
        if not element:
            return True
            
        # Vérifier les classes/IDs typiques du contenu statique
        static_patterns = [
            r'nav', r'menu', r'header', r'footer', r'sidebar', 
            r'banner', r'advertisement', r'promo', r'guide'
        ]
        
        element_classes = ' '.join(element.get('class', []))
        element_id = element.get('id', '')
        
        for pattern in static_patterns:
            if re.search(pattern, element_classes + ' ' + element_id, re.I):
                return True
                
        return False

    async def validate_and_extract_game_info(self, indicator, base_url, soup):
        """Valide un indicateur et extrait les informations de jeu"""
        try:
            if indicator['type'] == 'timer':
                # Pour un timer, chercher le contexte de jeu autour
                timer_element = indicator['element']
                game_context = timer_element.find_parent(['div', 'section'])
                
                if game_context:
                    context_text = game_context.get_text().lower()
                    if any(game_term in context_text for game_term in ['champion', 'rank', 'summoner']):
                        player_name = await self.extract_player_name_from_url(base_url)
                        return {
                            'title': f"🔴 LIVE - {player_name} ({indicator['text']})",
                            'url': base_url,
                            'player': player_name,
                            'status': f"En jeu depuis {indicator['text']}",
                            'type': 'timer'
                        }
            
            elif indicator['type'] == 'status':
                player_name = await self.extract_player_name_from_url(base_url)
                return {
                    'title': f"🔴 {indicator['text']} - {player_name}",
                    'url': base_url,
                    'player': player_name,
                    'status': indicator['text'],
                    'type': 'status'
                }
            
            elif indicator['type'] == 'spectate':
                # Extraire les infos depuis la section du bouton spectate
                section = indicator['section']
                section_text = section.get_text()
                
                # Chercher champion
                champion_match = re.search(r'champion[:\s]*(\w+)', section_text, re.I)
                champion = champion_match.group(1) if champion_match else "Inconnu"
                
                player_name = await self.extract_player_name_from_url(base_url)
                return {
                    'title': f"🔴 SPECTATE - {player_name} ({champion})",
                    'url': base_url,
                    'player': player_name,
                    'champion': champion,
                    'status': "Spectatable",
                    'type': 'spectate'
                }
                
        except Exception as e:
            logger.error(f"Erreur validation indicateur: {e}")
            
        return None
    
    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL"""
        # Implémentation à compléter
        return "Joueur inconnu"
