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
            
            # APPROCHE SIMPLIFIÉE : Recherche d'éléments très spécifiques aux parties live
            
            # 1. RECHERCHE DE BOUTONS OU LIENS "SPECTATE" RÉELS
            logger.info(f"🔍 Recherche de boutons spectate authentiques...")
            spectate_buttons = soup.find_all(['button', 'a'], string=re.compile(r'spectate|spectater|watch live', re.I))
            for button in spectate_buttons:
                button_text = button.get_text().strip()
                if not any(demo in button_text.lower() for demo in ['pro-gamer', 'demo', 'example']):
                    logger.info(f"🎯 Bouton spectate authentique: {button_text}")
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
            
            # 2. RECHERCHE DE DONNÉES DE MATCH EN TEMPS RÉEL
            logger.info(f"🔍 Recherche de données de match en temps réel...")
            # Chercher des éléments avec des données de temps de jeu
            time_elements = soup.find_all(string=re.compile(r'\d+:\d+', re.I))  # Format XX:XX pour temps de jeu
            for time_elem in time_elements:
                if time_elem.parent:
                    parent_text = time_elem.parent.get_text().strip()
                    # Vérifier si c'est dans un contexte de partie live
                    if any(keyword in parent_text.lower() for keyword in ['live', 'current', 'ingame', 'spectate']):
                        logger.info(f"🎯 Temps de jeu live détecté: {parent_text}")
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
            
            # 3. RECHERCHE D'ÉLÉMENTS AVEC DONNÉES DE CHAMPION EN COURS
            logger.info(f"🔍 Recherche de données de champion en cours...")
            # Chercher des éléments indiquant un champion actuellement joué
            champion_elements = soup.find_all(attrs={'class': re.compile(r'champion.*current|current.*champion', re.I)})
            if champion_elements:
                logger.info(f"🎯 Éléments de champion en cours trouvés: {len(champion_elements)}")
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
            
            # 4. RECHERCHE D'INDICATEURS VISUELS DE PARTIE LIVE
            logger.info(f"🔍 Recherche d'indicateurs visuels live...")
            # Chercher des éléments avec des classes indiquant une partie live
            live_indicators = soup.find_all(attrs={'class': re.compile(r'live.*game|game.*live|spectate.*live|current.*match', re.I)})
            if live_indicators:
                logger.info(f"🎯 Indicateurs visuels live trouvés: {len(live_indicators)}")
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
            
            logger.info("❌ Aucun indicateur de partie live authentique trouvé")
            return games
            
        except Exception as e:
            logger.error(f"Erreur dans find_live_games_alternative: {e}")
            return []

    async def extract_player_name_from_url(self, url):
        """Extrait le nom du joueur depuis l'URL"""
        try:
            # Patterns courants pour OP.GG
            patterns = [
                r'/summoners/[^/]+/([^/?]+)',  # /summoners/euw/PLAYERNAME
                r'/summoner/[^/]+/([^/?]+)',   # /summoner/euw/PLAYERNAME
                r'userName=([^&]+)',           # userName=PLAYERNAME
                r'summonerName=([^&]+)',       # summonerName=PLAYERNAME
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    name = match.group(1).replace('%20', ' ').replace('+', ' ')
                    if self.is_valid_summoner_name(name):
                        return name
            
            return "Joueur inconnu"
            
        except Exception as e:
            logger.error(f"Erreur extraction nom depuis URL: {e}")
            return "Joueur inconnu"

    async def find_active_game_indicators(self, soup):
        """Recherche UNIQUEMENT des indicateurs concrets de partie en cours"""
        active_indicators = []

        # 1. DÉTECTION SPÉCIFIQUE POUR OP.GG
        # Rechercher des éléments avec des classes CSS spécifiques aux jeux actifs
        active_game_classes = [
            'in-game', 'ingame', 'currently-playing', 'active-game', 
            'game-active', 'playing-now', 'live-match', 'match-live',
            'spectate-active', 'game-status-live'
        ]
        
        for class_name in active_game_classes:
            elements = soup.find_all(attrs={'class': re.compile(f'\\b{re.escape(class_name)}\\b', re.I)})
            for element in elements:
                if element not in active_indicators:
                    active_indicators.append(element)
                    logger.info(f"🎯 Classe de jeu actif détectée: {class_name}")

        # 2. DÉTECTION SPÉCIFIQUE POUR OP.GG - Rechercher des boutons "Spectate" ou "Observer"
        spectate_buttons = soup.find_all(['button', 'a'], string=re.compile(r'spectate|observer|regarder|watch', re.I))
        for button in spectate_buttons:
            if button not in active_indicators:
                active_indicators.append(button)
                logger.info(f"🎯 Bouton de spectate détecté: {button.get_text()}")

        # 3. DÉTECTION SPÉCIFIQUE POUR OP.GG - Rechercher des liens de spectate avec paramètres
        spectate_links = soup.find_all('a', href=True)
        for link in spectate_links:
            href = link.get('href')
            
            # Vérifier que c'est un lien de spectate avec des paramètres de jeu
            if self.is_active_spectate_link(href):
                if link not in active_indicators:
                    active_indicators.append(link)
                    logger.info(f"🎯 Lien de spectate actif détecté: {href}")

        # 4. DÉTECTION SIMPLIFIÉE - Rechercher le mot "LIVE" dans le contexte de jeu
        # Approche plus permissive pour OP.GG
        live_elements = soup.find_all(string=re.compile(r'\b(LIVE|Live|EN COURS|En cours|Currently|In Game|Spectate|Observer)\b'))
        for text_element in live_elements:
            parent = text_element.parent
            if parent and parent not in active_indicators:
                # Vérification moins stricte - si on trouve ces mots, on considère que c'est potentiellement une partie
                active_indicators.append(parent)
                logger.info(f"🎯 Élément LIVE potentiel détecté: {text_element.strip()}")

        # 5. DÉTECTION SPÉCIFIQUE POUR OP.GG - Rechercher des éléments avec données de jeu
        # Chercher des éléments contenant des stats de jeu (KDA, CS, etc.)
        game_stats_elements = soup.find_all(string=re.compile(r'\b(\d+/\d+/\d+|\d+\s*CS|\d+\s*KDA|Level\s*\d+)\b', re.I))
        for stats_element in game_stats_elements:
            parent = stats_element.parent
            if parent and parent not in active_indicators:
                # Si on trouve des stats de jeu, c'est probablement une partie active
                active_indicators.append(parent)
                logger.info(f"🎯 Stats de jeu détectées: {stats_element.strip()}")

        # 6. DÉTECTION POUR OP.GG - Rechercher des divs ou sections avec des indicateurs de jeu
        # OP.GG utilise souvent des sections spécifiques pour les parties en cours
        game_sections = soup.find_all(['div', 'section'], attrs={'class': re.compile(r'game|match|live|spectate|current', re.I)})
        for section in game_sections:
            if section not in active_indicators:
                section_text = section.get_text().strip().lower()
                # Vérifier si la section contient des indicateurs de partie active
                if any(indicator in section_text for indicator in ['live', 'en cours', 'spectate', 'observer', 'currently']):
                    active_indicators.append(section)
                    logger.info(f"🎯 Section de jeu détectée avec classes: {section.get('class')}")

        logger.info(f"🎯 Total d'indicateurs trouvés: {len(active_indicators)}")
        return active_indicators

    def is_active_spectate_link(self, href):
        """Vérifie si un lien est un vrai lien de spectate actif"""
        href_lower = href.lower()
        
        # Doit contenir "spectate" ou "observer" ET des paramètres de jeu
        has_spectate = any(word in href_lower for word in ['spectate', 'observer', 'watch'])
        has_game_params = any(param in href_lower for param in [
            'game', 'match', 'user', 'summoner', 'player', 'gameid', 'matchid'
        ])
        
        # Ne doit pas être un lien générique
        is_not_generic = not any(generic in href_lower for generic in [
            '/spectate', '/observer', '/watch', 'spectate.html', 'observer.html'
        ])
        
        return has_spectate and has_game_params and is_not_generic

    async def has_game_context_nearby(self, element):
        """Vérifie si un élément a du contexte de jeu à proximité"""
        context_text = element.get_text().strip().lower()
        
        # Ajouter le contexte des éléments parents et enfants
        parent = element.parent
        if parent:
            context_text += " " + parent.get_text().strip().lower()
        
        children = element.find_all(text=True)
        for child in children:
            context_text += " " + child.strip().lower()
        
        # Vérifier la présence d'éléments de jeu
        game_context_words = [
            'champion', 'summoner', 'rank', 'level', 'kda', 'cs', 'kills', 
            'deaths', 'assists', 'match', 'game', 'spectate', 'observer'
        ]
        
        return any(word in context_text for word in game_context_words)

    async def has_live_game_context(self, element):
        """Vérifie si un élément contient un contexte de jeu live"""
        context_text = element.get_text().strip().lower()
        
        # Chercher des indicateurs de jeu + live
        has_live = any(word in context_text for word in ['live', 'en cours', 'spectate', 'observer'])
        has_game = any(word in context_text for word in [
            'champion', 'summoner', 'match', 'game', 'rank', 'level'
        ])
        
        return has_live and has_game

    async def validate_active_game_indicator(self, element, soup):
        """Validation ÉQUILIBRÉE pour League of Legends"""
        try:
            element_text = element.get_text().strip().lower()
            
            logger.info(f"🔍 Validation de l'indicateur: '{element_text[:50]}...'")

            # 1. EXCLUSIONS PRIORITAIRES - Rejeter immédiatement les faux positifs évidents
            hard_exclusions = [
                # Code JavaScript et éléments techniques
                'self.__next_f', 'push([', '__next_f', 'javascript', 'json',
                'script', 'function', 'var ', 'let ', 'const ', 'return',
                'props:', 'children:', 'module_', 'null,', 'undefined',
                'document.', 'window.', 'console.', 'error:', 'debug'
            ]
            
            for exclusion in hard_exclusions:
                if exclusion in element_text:
                    logger.info(f"❌ Code technique détecté: {exclusion}")
                    return False

            # 2. VALIDATION POSITIVE PRIORITAIRE - Accepter si indicateurs LoL forts
            strong_lol_indicators = [
                'live_game', 'partie en cours', 'currently playing',
                'in game', 'ingame', 'en partie', 'match en cours',
                'spectate', 'observer', 'regarder'
            ]
            
            # Si on trouve des indicateurs LoL forts, accepter même avec d'autres éléments
            has_strong_lol = any(indicator in element_text for indicator in strong_lol_indicators)
            if has_strong_lol:
                logger.info(f"✅ Indicateur LoL fort détecté")
                return True

            # 3. EXCLUSIONS SECONDAIRES - Autres jeux (mais pas si LoL présent)
            other_games = ['overwatch', 'valorant', 'apex', 'csgo', 'fortnite', 'pubg', 'minecraft', 'wow', 'hearthstone']
            has_other_games = any(game in element_text for game in other_games)
            
            # Vérifier si League of Legends est présent
            has_lol_context = any(lol_word in element_text for lol_word in ['league of legends', 'lol', 'summoner', 'champion'])
            
            if has_other_games and not has_lol_context:
                logger.info(f"❌ Autre jeu détecté sans contexte LoL")
                return False

            # 4. VALIDATION POUR LES STATISTIQUES DE JEU
            has_game_stats = (
                re.search(r'\d+/\d+/\d+', element_text) or  # Format KDA
                re.search(r'\d+\s*cs', element_text, re.I) or  # CS (minions)
                re.search(r'level\s*\d+', element_text, re.I) or  # Niveau
                re.search(r'\d+\s*kda', element_text, re.I) or  # KDA
                re.search(r'(iron|bronze|silver|gold|platinum|diamond|master|grandmaster|challenger)', element_text, re.I)  # Rangs LoL
            )
            
            if has_game_stats:
                logger.info(f"✅ Statistiques de jeu détectées")
                return True

            # 5. VALIDATION POUR LES INDICATEURS LIVE GÉNÉRAUX - Plus stricte
            live_indicators = ['live', 'en cours', 'currently', 'playing']
            has_live_indicators = any(indicator in element_text for indicator in live_indicators)
            
            if has_live_indicators:
                # Vérifier que ce n'est pas un faux positif informatif
                false_positive_patterns = [
                    'statsleague', 'league of legendsleague', 'teamfight tacticsleague',
                    'dropdown', 'module', 'service', 'menu', 'navigation',
                    'statistics', 'statistiques', 'recent games', 'parties récentes',
                    'champion list', 'liste de champions', 'win rate', 'taux de victoire'
                ]
                
                is_false_positive = any(pattern in element_text for pattern in false_positive_patterns)
                
                if is_false_positive:
                    logger.info(f"❌ Faux positif LIVE détecté (élément informatif)")
                    return False
                else:
                    logger.info(f"✅ Indicateurs LIVE authentiques détectés")
                    return True

            # 6. VALIDATION POUR LE CONTEXTE LOL - Plus stricte
            lol_keywords = [
                'league of legends', 'lol', 'summoner', 'champion', 'rift',
                'ranked', 'classé', 'cs', 'minions', 'kda', 'kills', 'deaths', 'assists',
                'baron', 'dragon', 'turret', 'inhibitor', 'nexus'
            ]
            
            has_lol_context = any(keyword in element_text for keyword in lol_keywords)
            
            if has_lol_context:
                # Vérifier que ce n'est pas juste du texte informatif
                informational_patterns = [
                    'statsleague', 'league of legendsleague', 'teamfight tacticsleague',
                    'liste de champions', 'parties récentes', 'statistiques',
                    'menu', 'dropdown', 'navigation'
                ]
                
                is_informational = any(pattern in element_text for pattern in informational_patterns)
                
                if is_informational:
                    logger.info(f"❌ Contexte LoL informatif détecté (pas de partie live)")
                    return False
                else:
                    logger.info(f"✅ Contexte LoL authentique détecté")
                    return True

            # 7. EXCLUSIONS FINALES - Éléments génériques
            generic_exclusions = [
                'navigation', 'menu', 'footer', 'header', 'sidebar',
                'advertisement', 'ads', 'promotional', 'banner',
                'social media', 'follow us', 'subscribe'
            ]
            
            if any(exclusion in element_text for exclusion in generic_exclusions):
                logger.info(f"❌ Élément générique détecté")
                return False

            # Si on arrive ici, pas assez d'éléments pour valider
            logger.info(f"❌ Pas assez d'éléments pour valider")
            return False

        except Exception as e:
            logger.error(f"Erreur dans validate_active_game_indicator: {e}")
            return False

    async def extract_game_info_from_validated_element(self, element, base_url, soup):
        """Extraction d'informations depuis un élément validé"""
        try:
            # Extraire le nom du joueur
            player_name = await self.extract_player_name(base_url, soup, element)
            
            # Extraire l'URL de spectate
            spectate_url = await self.extract_spectate_url(element, base_url)
            
            # Extraire les informations de jeu
            rank, level = await self.extract_game_details(soup, element)

            # Créer un ID unique basé sur le contenu réel
            timestamp = datetime.now(UTC)
            game_id = hash(f"{spectate_url}_{player_name}_{timestamp.strftime('%Y%m%d%H%M')}")

            game_info = {
                'id': game_id,
                'url': spectate_url,
                'title': f"🔴 Partie LIVE de {player_name}",
                'player': player_name,
                'level': level,
                'rank': rank,
                'timestamp': timestamp.timestamp(),
                'detected_at': timestamp.isoformat()
            }

            logger.info(f"✅ Informations de jeu extraites avec succès")
            return game_info

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des informations: {e}")
            return None

    async def extract_player_name(self, base_url, soup, element):
        """Extraction du nom du joueur avec validation stricte"""
        player_name = "Joueur inconnu"
        
        try:
            # 1. Depuis l'URL (paramètre userName) - priorité absolue
            match = re.search(r'userName=([^&]+)', base_url)
            if match:
                player_name = match.group(1).replace('%20', ' ').replace('+', ' ')
                logger.info(f"Nom du joueur trouvé dans l'URL: {player_name}")
                return player_name

            # 2. Depuis l'URL (autre patterns OP.GG)
            url_patterns = [
                r'/summoners/[^/]+/([^/?]+)',  # /summoners/euw/PLAYERNAME
                r'/summoner/[^/]+/([^/?]+)',   # /summoner/euw/PLAYERNAME
                r'summonerName=([^&]+)',       # summonerName=PLAYERNAME
            ]
            
            for pattern in url_patterns:
                match = re.search(pattern, base_url)
                if match:
                    potential_name = match.group(1).replace('%20', ' ').replace('+', ' ')
                    if self.is_valid_summoner_name(potential_name):
                        player_name = potential_name
                        logger.info(f"Nom du joueur trouvé dans l'URL (pattern {pattern}): {player_name}")
                        return player_name

            # 3. Depuis le titre de la page
            title_element = soup.find('title')
            if title_element:
                title_text = title_element.get_text()
                # Chercher le nom dans le titre (format: "NOM - OP.GG")
                title_patterns = [
                    r'^([^-|]+)\s*-\s*OP\.GG',  # NOM - OP.GG
                    r'^([^-|]+)\s*-\s*League of Legends',  # NOM - League of Legends
                    r'^([^-|]+)\s*\|',  # NOM | autres
                ]
                
                for pattern in title_patterns:
                    match = re.search(pattern, title_text)
                    if match:
                        potential_name = match.group(1).strip()
                        if self.is_valid_summoner_name(potential_name):
                            player_name = potential_name
                            logger.info(f"Nom du joueur trouvé dans le titre: {player_name}")
                            return player_name

            # 4. Depuis l'élément validé (en dernier recours)
            element_text = element.get_text().strip()
            # Chercher un pattern de nom de joueur strict
            name_match = re.search(r'\b([A-Za-z0-9\s]{3,16})\b', element_text)
            if name_match:
                potential_name = name_match.group(1).strip()
                if self.is_valid_summoner_name(potential_name):
                    player_name = potential_name
                    logger.info(f"Nom du joueur trouvé dans l'élément: {player_name}")
                    return player_name

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction du nom: {e}")

        return player_name
    
    def is_valid_summoner_name(self, name):
        """Valide si un nom est un nom d'invocateur LoL valide"""
        if not name or len(name) < 3 or len(name) > 16:
            return False
        
        # Exclusions - mots-clés techniques ou génériques
        invalid_names = [
            'live', 'spectate', 'observer', 'en cours', 'match', 'game',
            'self', 'null', 'undefined', 'function', 'var', 'let', 'const',
            'return', 'props', 'children', 'module', 'error', 'debug',
            'javascript', 'json', 'script', 'window', 'document', 'console',
            'overwatch', 'valorant', 'apex', 'csgo', 'dota', 'fortnite',
            # Exclusions supplémentaires
            'stats', 'league', 'legends', 'statsleague', 'league of',
            'of legends', 'teamfight', 'tactics', 'summoner', 'champion',
            'ranked', 'classé', 'partie', 'victoire', 'défaite',
            'visionnage', 'pro', 'demo', 'example', 'test', 'sample',
            'fake', 'placeholder', 'visionnage pro'
        ]
        
        name_lower = name.lower()
        if any(invalid in name_lower for invalid in invalid_names):
            return False
        
        # Vérifier que ce n'est pas du code JavaScript
        if any(char in name for char in ['(', ')', '[', ']', '{', '}', '<', '>', '/', '\\', '=', ';', ':']):
            return False
        
        # Vérifier que ce n'est pas un nombre pur
        if name.isdigit():
            return False
        
        # Vérifier que ce n'est pas un mot composé technique
        if any(tech_word in name_lower for tech_word in ['__', 'push', 'next', 'module', 'dropdown']):
            return False
        
        return True

    async def extract_spectate_url(self, element, base_url):
        """Extraction de l'URL de spectate"""
        try:
            # 1. Si l'élément est un lien
            if element.name == 'a' and element.get('href'):
                href = element.get('href')
                if href.startswith('/'):
                    return base_url.rstrip('/') + href
                elif href.startswith('http'):
                    return href

            # 2. Chercher un lien dans l'élément
            link = element.find('a', href=True)
            if link:
                href = link.get('href')
                if href.startswith('/'):
                    return base_url.rstrip('/') + href
                elif href.startswith('http'):
                    return href

            # 3. Par défaut, utiliser l'URL de base
            return base_url

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction de l'URL: {e}")
            return base_url

    async def extract_game_details(self, soup, element):
        """Extraction du rang et niveau"""
        rank = "Non classé"
        level = "?"
        
        try:
            # Chercher dans l'élément et ses environs
            context_text = element.get_text()
            
            # Ajouter le texte des éléments frères
            if element.parent:
                siblings = element.parent.find_all(text=True)
                context_text += " " + " ".join(siblings)

            # Patterns pour le rang
            rank_patterns = [
                r'(Iron|Bronze|Silver|Gold|Platinum|Diamond|Master|GrandMaster|Challenger)\s*([IVX]*)',
                r'(Fer|Bronze|Argent|Or|Platine|Diamant|Maître|Grand[Mm]aître|Challenger)\s*([IVX]*)'
            ]
            
            for pattern in rank_patterns:
                match = re.search(pattern, context_text, re.I)
                if match:
                    rank = match.group(1).title()
                    if match.group(2):
                        rank += f" {match.group(2)}"
                    break

            # Pattern pour le niveau
            level_match = re.search(r'(?:Level|Niveau|Lvl)\s*(\d+)', context_text, re.I)
            if level_match:
                level = level_match.group(1)

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des détails: {e}")

        return rank, level

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

        # Test de connexion
        logger.info(f"🔍 Analyse de la page {url} en cours...")
        games = await web_monitor.check_site(url)
        
        guild_id = ctx.guild.id
        if guild_id not in monitored_sites:
            monitored_sites[guild_id] = {}

        monitored_sites[guild_id][url] = {
            'channel_id': ctx.channel.id,
            'mention_role': mention_role,
            'last_check': datetime.now(UTC).timestamp(),
            'added_by': ctx.author.id
        }

        await ctx.send(f"✅ Surveillance ajoutée pour: {url}")
        if games:
            await ctx.send(f"🎮 {len(games)} partie(s) détectée(s) actuellement!")
        else:
            await ctx.send("💤 Aucune partie détectée pour le moment")

    except Exception as e:
        logger.error(f"Erreur dans add_monitor: {e}")
        await ctx.send(f"❌ Erreur lors de l'ajout de la surveillance: {str(e)}")

@bot.command(name='stop')
async def stop_monitor(ctx, url: str = None):
    """Arrêter la surveillance d'un site"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in monitored_sites:
            await ctx.send("❌ Aucune surveillance active sur ce serveur")
            return

        if url:
            if url in monitored_sites[guild_id]:
                del monitored_sites[guild_id][url]
                await ctx.send(f"✅ Surveillance arrêtée pour: {url}")
            else:
                await ctx.send(f"❌ Ce site n'est pas surveillé: {url}")
        else:
            # Arrêter toutes les surveillances
            count = len(monitored_sites[guild_id])
            monitored_sites[guild_id].clear()
            await ctx.send(f"✅ {count} surveillance(s) arrêtée(s)")

    except Exception as e:
        logger.error(f"Erreur dans stop_monitor: {e}")
        await ctx.send(f"❌ Erreur: {str(e)}")

@bot.command(name='check')
async def check_site(ctx, url: str):
    """Vérifier manuellement un site pour des parties en cours"""
    try:
        logger.info(f"🔍 Commande !check reçue de {ctx.author} pour {url}")
        
        if not url.startswith(('http://', 'https://')):
            await ctx.send("❌ L'URL doit commencer par http:// ou https://")
            return

        await ctx.send(f"🔍 Vérification de {url} en cours...")
        
        # Vérifier le site
        games = await web_monitor.check_site(url)
        
        if games:
            await ctx.send(f"✅ {len(games)} partie(s) LIVE détectée(s) !")
            
            for game in games:
                embed = discord.Embed(
                    title="🔴 PARTIE LIVE DÉTECTÉE!",
                    description=game['title'],
                    color=0xff0000,
                    timestamp=datetime.now(UTC)
                )
                
                embed.add_field(name="👤 Joueur", value=game['player'], inline=True)
                embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
                embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
                embed.add_field(name="🔗 Lien", value=f"[Regarder la partie]({game['url']})", inline=False)
                
                await ctx.send(embed=embed)
        else:
            await ctx.send("💤 Aucune partie LIVE détectée sur ce site")

    except Exception as e:
        logger.error(f"Erreur dans check_site: {e}")
        await ctx.send(f"❌ Erreur lors de la vérification: {str(e)}")

@bot.command(name='status')
async def status_monitor(ctx):
    """Afficher le statut des surveillances"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in monitored_sites or not monitored_sites[guild_id]:
            await ctx.send("❌ Aucune surveillance active sur ce serveur")
            return

        embed = discord.Embed(
            title="🔍 État des surveillances",
            color=0x00ff00,
            timestamp=datetime.now(UTC)
        )

        for url, config in monitored_sites[guild_id].items():
            last_check = datetime.fromtimestamp(config['last_check'], UTC)
            embed.add_field(
                name=f"📍 {url[:50]}...",
                value=f"Canal: <#{config['channel_id']}>\n"
                      f"Rôle: {config.get('mention_role', 'Aucun')}\n"
                      f"Dernière vérif: {last_check.strftime('%H:%M:%S')}",
                inline=False
            )

        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Erreur dans status_monitor: {e}")
        await ctx.send(f"❌ Erreur: {str(e)}")

@tasks.loop(minutes=2)
async def monitor_loop():
    """Boucle de surveillance principale"""
    if not bot.ready_flag:
        return

    try:
        for guild_id, sites in monitored_sites.items():
            for url, config in sites.items():
                try:
                    logger.info(f"🔍 Vérification de {url}")
                    
                    # Vérifier le site
                    games = await web_monitor.check_site(url)
                    
                    # Mettre à jour le timestamp
                    config['last_check'] = datetime.now(UTC).timestamp()
                    
                    if games:
                        logger.info(f"🎮 {len(games)} partie(s) LIVE détectée(s) sur {url}")
                        
                        # Envoyer les notifications
                        channel = bot.get_channel(config['channel_id'])
                        if channel:
                            for game in games:
                                # Éviter les doublons
                                game_key = f"{url}_{game['id']}"
                                
                                if game_key not in active_games:
                                    active_games[game_key] = {
                                        'timestamp': game['timestamp'],
                                        'notified': True
                                    }
                                    
                                    # Créer l'embed
                                    embed = discord.Embed(
                                        title="🔴 PARTIE LIVE DÉTECTÉE!",
                                        description=game['title'],
                                        color=0xff0000,
                                        timestamp=datetime.now(UTC)
                                    )
                                    
                                    embed.add_field(name="👤 Joueur", value=game['player'], inline=True)
                                    embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
                                    embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
                                    embed.add_field(name="🔗 Lien", value=f"[Regarder la partie]({game['url']})", inline=False)
                                    
                                    # Mention du rôle si configuré
                                    mention = ""
                                    if config.get('mention_role'):
                                        mention = f"<@&{config['mention_role']}> "
                                    
                                    await channel.send(content=mention, embed=embed)
                                    logger.info(f"✅ Notification envoyée pour {game['title']}")
                    else:
                        logger.info(f"💤 Aucune partie LIVE sur {url}")
                        
                except Exception as e:
                    logger.error(f"Erreur lors de la vérification de {url}: {e}")
                    continue
                    
        # Nettoyer les anciens jeux (plus de 30 minutes)
        current_time = datetime.now(UTC).timestamp()
        expired_games = []
        
        for game_key, game_data in active_games.items():
            if current_time - game_data['timestamp'] > 1800:  # 30 minutes
                expired_games.append(game_key)
        
        for game_key in expired_games:
            del active_games[game_key]
            logger.info(f"🧹 Jeu expiré supprimé: {game_key}")

    except Exception as e:
        logger.error(f"Erreur dans monitor_loop: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Gestion des erreurs de commandes"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant: {error.param.name}")
    else:
        logger.error(f"Erreur de commande: {error}")
        await ctx.send(f"❌ Une erreur s'est produite: {str(error)}")

# === Lancement ===
if __name__ == "__main__":
    # Démarrer Flask dans un thread séparé
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Démarrer le bot Discord
    token = os.getenv('DISCORD_TOKEN', 'your_discord_token_here')
    try:
        bot.run(token)
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
    finally:
        # Nettoyer la session HTTP
        asyncio.run(web_monitor.close_session())
