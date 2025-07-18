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
        """Détection STRICTE basée sur le mot 'live' et variantes"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            # Mots-clés STRICTS pour détecter une partie en cours
            live_keywords = [
                'live', 'LIVE', 'Live',
                'en cours', 'En cours', 'EN COURS',
                'in game', 'In Game', 'IN GAME', 'ingame',
                'partie en cours', 'Partie en cours',
                'spectate', 'Spectate', 'SPECTATE',
                'observer', 'Observer', 'OBSERVER'
            ]

            # Recherche dans tout le texte de la page
            page_text = soup.get_text()
            logger.info(f"Recherche de mots-clés LIVE dans la page...")
            
            # Vérifier chaque mot-clé avec logging
            found_keywords = []
            for keyword in live_keywords:
                if keyword in page_text:
                    found_keywords.append(keyword)
            
            if found_keywords:
                logger.info(f"Mots-clés trouvés: {found_keywords}")
                
                # Recherche STRICTE dans les éléments spécifiques
                for keyword in found_keywords:
                    # Recherche dans les éléments contenant le mot-clé
                    elements = soup.find_all(text=re.compile(rf'\b{re.escape(keyword)}\b', re.I))
                    logger.info(f"Éléments trouvés pour '{keyword}': {len(elements)}")
                    
                    for element in elements:
                        parent = element.parent
                        if parent:
                            # Vérification STRICTE
                            if await self.is_valid_live_indicator(parent, keyword):
                                game_info = await self.extract_game_info_from_element(parent, base_url)
                                if game_info:
                                    logger.info(f"✅ Partie LIVE confirmée avec '{keyword}'")
                                    games.append(game_info)
                                    break  # Une seule détection suffit
                
                # Si aucune partie trouvée malgré les mots-clés, ce sont probablement des faux positifs
                if not games:
                    logger.info(f"❌ Mots-clés trouvés mais aucune partie LIVE valide détectée")
            else:
                logger.info(f"❌ Aucun mot-clé LIVE trouvé sur la page")

            return games

        except Exception as e:
            logger.error(f"Erreur lors de la détection live: {e}")
            return []

    async def is_valid_live_indicator(self, element, keyword):
        """Vérifie STRICTEMENT si l'élément est un vrai indicateur de partie en cours"""
        try:
            # Obtenir le texte de l'élément et de ses parents
            element_text = element.get_text().strip().lower()
            parent_text = ""
            if element.parent:
                parent_text = element.parent.get_text().strip().lower()
            
            logger.info(f"Validation de l'élément avec '{keyword}': '{element_text[:50]}...'")
            
            # Vérifications STRICTES
            
            # 1. Vérifier que ce n'est pas dans un menu, footer, ou navigation
            if any(word in element_text for word in ['menu', 'navigation', 'footer', 'header', 'sidebar']):
                logger.info(f"❌ Élément dans navigation/menu - ignoré")
                return False
            
            # 2. Vérifier que ce n'est pas un lien générique
            if element.name == 'a' and element.get('href'):
                href = element.get('href').lower()
                if any(word in href for word in ['/live', '/watch', '/spectate']) and 'game' not in href:
                    logger.info(f"❌ Lien générique - ignoré")
                    return False
            
            # 3. Vérifier la présence d'indicateurs de partie en cours
            game_indicators = [
                'match', 'game', 'partie', 'spectate', 'observer', 'champion', 'summoner'
            ]
            
            has_game_context = any(indicator in element_text or indicator in parent_text for indicator in game_indicators)
            
            if not has_game_context:
                logger.info(f"❌ Pas de contexte de jeu - ignoré")
                return False
            
            # 4. Vérifier la couleur (si disponible)
            style = element.get('style', '')
            if style:
                # Chercher des couleurs vertes/rouges typiques du "live"
                if any(color in style.lower() for color in ['green', '#00ff00', '#00f', 'rgb(0,255,0)', 'red', '#ff0000']):
                    logger.info(f"✅ Couleur live détectée")
                    return True
            
            # 5. Vérifier les classes CSS
            classes = element.get('class', [])
            if isinstance(classes, list):
                class_str = ' '.join(classes).lower()
                if any(cls in class_str for cls in ['live', 'active', 'online', 'ingame', 'current', 'playing']):
                    logger.info(f"✅ Classe CSS live détectée: {class_str}")
                    return True
            
            # 6. Vérifier que le mot-clé n'est pas dans une phrase générique
            generic_phrases = [
                'live streams', 'live updates', 'live news', 'live chat',
                'watch live', 'follow live', 'see live', 'live broadcasts'
            ]
            
            if any(phrase in element_text for phrase in generic_phrases):
                logger.info(f"❌ Phrase générique détectée - ignoré")
                return False
                
            # 7. Validation finale : le mot-clé doit être proche d'éléments de jeu
            nearby_text = element_text + " " + parent_text
            if any(word in nearby_text for word in ['champion', 'summoner', 'rank', 'level', 'kda', 'cs']):
                logger.info(f"✅ Contexte de jeu confirmé")
                return True
            
            logger.info(f"❌ Validation échouée - pas assez d'indicateurs")
            return False
            
        except Exception as e:
            logger.debug(f"Erreur dans is_valid_live_indicator: {e}")
            return False

    async def extract_game_info_simple(self, soup, base_url):
        """Extraction simple des informations de partie"""
        try:
            # Extraire le nom du joueur de l'URL ou du titre
            player_name = "Joueur inconnu"
            
            # Depuis l'URL
            match = re.search(r'userName=([^&]+)', base_url)
            if match:
                player_name = match.group(1).replace('%20', ' ').replace('+', ' ')
            
            # Depuis le titre de la page
            title_element = soup.find('title')
            if title_element:
                title_text = title_element.get_text()
                # Extraire le nom du joueur du titre (souvent au début)
                title_match = re.search(r'^([^-|]+)', title_text)
                if title_match:
                    potential_name = title_match.group(1).strip()
                    if len(potential_name) > 2 and len(potential_name) < 30:
                        player_name = potential_name

            # Chercher des liens de spectate
            spectate_url = base_url  # Par défaut
            spectate_links = soup.find_all('a', href=True)
            for link in spectate_links:
                href = link.get('href')
                link_text = link.get_text().lower()
                if any(word in link_text for word in ['spectate', 'observer', 'watch', 'live']):
                    if href.startswith('/'):
                        spectate_url = base_url.rstrip('/') + href
                    elif href.startswith('http'):
                        spectate_url = href
                    break

            # Extraire rang et niveau depuis le contenu
            page_text = soup.get_text()
            
            # Rang
            rank = "Non classé"
            rank_patterns = [
                r'(Iron|Bronze|Silver|Gold|Platinum|Diamond|Master|GrandMaster|Challenger)\s*([IVX]*)',
                r'(Fer|Bronze|Argent|Or|Platine|Diamant|Maître|Grand[Mm]aître|Challenger)\s*([IVX]*)'
            ]
            
            for pattern in rank_patterns:
                match = re.search(pattern, page_text, re.I)
                if match:
                    rank = match.group(1).title()
                    if match.group(2):
                        rank += f" {match.group(2)}"
                    break
            
            # Niveau
            level = "?"
            level_match = re.search(r'(?:Level|Niveau|Lvl)\s*(\d+)', page_text, re.I)
            if level_match:
                level = level_match.group(1)

            # Créer un ID unique
            game_id = hash(f"{spectate_url}_{player_name}_{datetime.now(UTC).strftime('%Y%m%d%H%M')}")

            return {
                'id': game_id,
                'url': spectate_url,
                'title': f"Partie de {player_name}",
                'player': player_name,
                'level': level,
                'rank': rank,
                'timestamp': datetime.now(UTC).timestamp()
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction simple: {e}")
            return None

    async def extract_game_info_from_element(self, element, base_url):
        """Extraction depuis un élément spécifique"""
        try:
            # Chercher un lien dans l'élément
            link = element.find('a', href=True)
            if link:
                href = link.get('href')
                if href.startswith('/'):
                    spectate_url = base_url.rstrip('/') + href
                elif href.startswith('http'):
                    spectate_url = href
                else:
                    spectate_url = base_url
            else:
                spectate_url = base_url

            # Nom du joueur depuis l'URL
            player_name = "Joueur inconnu"
            match = re.search(r'userName=([^&]+)', base_url)
            if match:
                player_name = match.group(1).replace('%20', ' ').replace('+', ' ')

            # Informations basiques
            game_id = hash(f"{spectate_url}_{player_name}_{datetime.now(UTC).strftime('%Y%m%d%H%M')}")

            return {
                'id': game_id,
                'url': spectate_url,
                'title': f"Partie LIVE de {player_name}",
                'player': player_name,
                'level': "?",
                'rank': "Non classé",
                'timestamp': datetime.now(UTC).timestamp()
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction depuis élément: {e}")
            return None

    async def close(self):
        if self.session:
            await self.session.close()

web_monitor = WebMonitor()

@bot.event
async def on_ready():
    if not getattr(bot, "ready_flag", False):
        print(f'{bot.user} est connecté et prêt !')
        logger.info(f'Bot connecté en tant que {bot.user}')
    if not check_lol_games.is_running():
        check_lol_games.start()
        bot.ready_flag = True

@tasks.loop(minutes=2)
async def check_lol_games():
    """Vérifie les sites pour de nouvelles parties LoL en cours"""
    try:
        for channel_id, sites in monitored_sites.items():
            if not sites:
                continue

            channel = bot.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} non trouvé")
                continue

            if channel_id not in active_games:
                active_games[channel_id] = {}

            for site in sites:
                logger.info(f"Vérification LIVE de {site['url']} pour le channel {channel.name}")
                games = await web_monitor.check_site(site['url'], site.get('selector'))
                
                if games:
                    logger.info(f"🔴 {len(games)} partie(s) LIVE détectée(s) sur {site['name']}")
                else:
                    logger.info(f"⚫ Aucune partie LIVE sur {site['name']}")
                
                for game in games:
                    game_id = game['id']
                    
                    # Vérifier si la partie est déjà affichée
                    if game_id not in active_games[channel_id]:
                        await send_game_notification(channel, game, site)
                        active_games[channel_id][game_id] = None

        # Nettoyer les anciennes parties
        await cleanup_old_games()

    except Exception as e:
        logger.error(f"Erreur dans check_lol_games: {e}")

@check_lol_games.before_loop
async def before_check_lol_games():
    await bot.wait_until_ready()

async def send_game_notification(channel, game, site_data):
    """Envoie une notification pour une nouvelle partie LoL LIVE"""
    try:
        player_name = site_data.get('player_name', game['player'])
        player_role = site_data.get('role', None)
        
        embed = discord.Embed(
            title="🔴 LIVE - Partie League of Legends !",
            description=f"**{player_name}** est actuellement en jeu",
            color=0xFF0000,  # Rouge vif pour LIVE
            timestamp=datetime.now(UTC)
        )
        
        embed.add_field(name="👤 Joueur", value=player_name, inline=True)
        if player_role:
            embed.add_field(name="🎯 Rôle", value=player_role, inline=True)
        embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
        embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
        embed.add_field(name="🌐 Source", value=site_data['name'], inline=True)
        embed.add_field(name="🔴 Statut", value="**LIVE**", inline=True)
        
        embed.add_field(
            name="🔗 Lien d'observation",
            value=f"[🎮 Regarder la partie]({game['url']})",
            inline=False
        )
        
        embed.set_footer(text=f"Détecté LIVE sur {site_data['name']}")
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")

        message = await channel.send(embed=embed)

        # Stocker les informations
        if channel.id not in active_games:
            active_games[channel.id] = {}
        active_games[channel.id][game['id']] = message.id

        logger.info(f"🔴 Notification LIVE envoyée pour {player_name} dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}")

async def cleanup_old_games():
    """Nettoie les anciennes parties (plus de 30 minutes)"""
    current_time = datetime.now(UTC).timestamp()
    to_remove = []

    for channel_id, games in active_games.items():
        if not games:
            continue
            
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for game_id, message_id in games.items():
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    
                    # Vérifier l'âge du message (30 minutes)
                    message_age = (current_time - message.created_at.timestamp()) / 60
                    if message_age > 30:
                        # Modifier le message pour indiquer que la partie est terminée
                        embed = message.embeds[0]
                        embed.title = "⚫ Partie terminée"
                        embed.color = 0x808080  # Gris
                        embed.set_footer(text=f"Partie terminée • Était LIVE sur {embed.footer.text.split(' sur ')[1] if ' sur ' in embed.footer.text else 'OP.GG'}")
                        
                        # Modifier le champ statut
                        for i, field in enumerate(embed.fields):
                            if field.name == "🔴 Statut":
                                embed.set_field_at(i, name="⚫ Statut", value="**Terminée**", inline=True)
                        
                        await message.edit(embed=embed)
                        to_remove.append((channel_id, game_id, message_id))
                        
                except discord.NotFound:
                    to_remove.append((channel_id, game_id, message_id))
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour du message: {e}")

    # Supprimer les références
    for channel_id, game_id, message_id in to_remove:
        active_games[channel_id].pop(game_id, None)

# === Commandes ===

@bot.command(name='addsite')
@commands.has_permissions(manage_channels=True)
async def add_site(ctx, url=None, player_name=None, role=None):
    """Ajoute un site OP.GG à surveiller avec nom et rôle optionnels"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL OP.GG !\nExemple: `!addsite https://euw.op.gg/summoner/userName=pseudo [nom_joueur] [rôle]`")
        return

    # Nom par défaut extrait de l'URL si non fourni
    if not player_name:
        match = re.search(r'userName=([^&]+)', url)
        if match:
            player_name = match.group(1).replace('%20', ' ')
        else:
            player_name = "Joueur inconnu"

    channel_id = ctx.channel.id
    if channel_id not in monitored_sites:
        monitored_sites[channel_id] = []

    # Vérifier si le site existe déjà
    for site in monitored_sites[channel_id]:
        if site['url'] == url:
            await ctx.send(f"❌ Ce site est déjà surveillé !")
            return

    site_data = {
        'url': url,
        'name': player_name,
        'player_name': player_name,
        'role': role,
        'selector': None
    }

    monitored_sites[channel_id].append(site_data)
    
    embed = discord.Embed(
        title="✅ Site ajouté à la surveillance LIVE",
        description=f"**{player_name}** sera surveillé pour les parties LIVE",
        color=0x00ff00
    )
    embed.add_field(name="👤 Joueur", value=player_name, inline=True)
    if role:
        embed.add_field(name="🎯 Rôle", value=role, inline=True)
    embed.add_field(name="🔗 Profil OP.GG", value=f"[Voir le profil]({url})", inline=False)
    embed.add_field(name="🔍 Détection", value="Recherche du mot **LIVE** toutes les 2 minutes", inline=True)
    embed.set_footer(text="Le bot détectera automatiquement les parties LIVE")
    
    await ctx.send(embed=embed)

@bot.command(name='removesite')
@commands.has_permissions(manage_channels=True)
async def remove_site(ctx, *, identifier=None):
    """Supprime un site de la surveillance (par URL ou nom)"""
    if not identifier:
        await ctx.send("❌ Veuillez spécifier l'URL ou le nom du site à supprimer !")
        return

    channel_id = ctx.channel.id
    if channel_id not in monitored_sites:
        await ctx.send("❌ Aucun site surveillé dans ce channel !")
        return

    for i, site in enumerate(monitored_sites[channel_id]):
        if site['url'] == identifier or site.get('player_name', site['name']).lower() == identifier.lower():
            removed_site = monitored_sites[channel_id].pop(i)
            await ctx.send(f"✅ Site supprimé : **{removed_site.get('player_name', removed_site['name'])}**")
            return

    await ctx.send("❌ Site non trouvé dans la liste !")

@bot.command(name='listsites')
async def list_sites(ctx):
    """Affiche la liste des sites surveillés"""
    channel_id = ctx.channel.id

    if channel_id not in monitored_sites or not monitored_sites[channel_id]:
        await ctx.send("📋 Aucun site surveillé dans ce channel !")
        return

    embed = discord.Embed(
        title="📋 Sites surveillés (LIVE)",
        description=f"**{len(monitored_sites[channel_id])}** profil(s) surveillé(s) pour les parties LIVE",
        color=0x0596AA
    )

    for i, site in enumerate(monitored_sites[channel_id], 1):
        field_value = f"[Lien OP.GG]({site['url']})"
        if site.get('role'):
            field_value += f"\n🎯 Rôle: {site['role']}"
        field_value += f"\n🔍 Détection: **LIVE**"
        
        embed.add_field(
            name=f"{i}. {site.get('player_name', site['name'])}",
            value=field_value,
            inline=False
        )

    embed.set_footer(text="Vérification LIVE toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.command(name='testsite')
@commands.has_permissions(manage_channels=True)
async def test_site(ctx, url=None):
    """Test un site OP.GG pour voir si une partie LIVE est détectée"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL OP.GG à tester !")
        return

    message = await ctx.send("🔍 Test de détection LIVE en cours...")

    # Faire le test avec logs détaillés
    try:
        session = await web_monitor.get_session()
        async with session.get(url) as response:
            if response.status == 200:
                html = await response.text()
                
                # Analyser la page
                soup = BeautifulSoup(html, 'html.parser')
                page_text = soup.get_text()
                
                # Rechercher les mots-clés
                live_keywords = [
                    'live', 'LIVE', 'Live',
                    'en cours', 'En cours', 'EN COURS',
                    'in game', 'In Game', 'IN GAME', 'ingame',
                    'partie en cours', 'Partie en cours',
                    'spectate', 'Spectate', 'SPECTATE',
                    'observer', 'Observer', 'OBSERVER'
                ]
                
                found_keywords = []
                for keyword in live_keywords:
                    if keyword in page_text:
                        found_keywords.append(keyword)
                
                # Tester la détection complète
                games = await web_monitor.detect_live_game(html, url)
                
                # Créer le rapport
                embed = discord.Embed(
                    title="🔍 Rapport de test de détection LIVE",
                    color=0x0596AA
                )
                
                embed.add_field(
                    name="🌐 URL testée",
                    value=f"[Lien]({url})",
                    inline=False
                )
                
                embed.add_field(
                    name="📝 Mots-clés trouvés",
                    value=f"**{len(found_keywords)}** mots-clés: {', '.join(found_keywords) if found_keywords else 'Aucun'}",
                    inline=False
                )
                
                if games:
                    embed.color = 0x00ff00
                    embed.add_field(
                        name="✅ Résultat",
                        value=f"**{len(games)} partie(s) LIVE détectée(s)**",
                        inline=False
                    )
                    
                    for i, game in enumerate(games[:2], 1):
                        embed.add_field(
                            name=f"🔴 Partie LIVE {i}",
                            value=f"👤 {game['player']}\n[🎮 Regarder]({game['url']})",
                            inline=True
                        )
                else:
                    embed.color = 0xff0000
                    embed.add_field(
                        name="❌ Résultat",
                        value="**Aucune partie LIVE détectée**",
                        inline=False
                    )
                    
                    if found_keywords:
                        embed.add_field(
                            name="💡 Explication",
                            value="Des mots-clés ont été trouvés mais la validation stricte a échoué.\nIls sont probablement dans des menus ou liens génériques.",
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="💡 Explication",
                            value="Aucun mot-clé LIVE trouvé sur la page.\nLe joueur n'est probablement pas en partie actuellement.",
                            inline=False
                        )
                
                embed.set_footer(text="Test terminé • Vérification stricte activée")
                await message.edit(content="", embed=embed)
                
            else:
                await message.edit(content=f"❌ Erreur HTTP {response.status} - Impossible d'accéder au site")
                
    except Exception as e:
        logger.error(f"Erreur lors du test: {e}")
        await message.edit(content=f"❌ Erreur lors du test: {str(e)}")



@bot.command(name='lolhelp')
async def lol_help(ctx):
    """Affiche l'aide pour les commandes LoL"""
    embed = discord.Embed(
        title="🎮 Aide du Bot LoL Monitor LIVE",
        description="Surveillez les parties LoL LIVE sur OP.GG",
        color=0x0596AA
    )
    
    embed.add_field(
        name="🔴 Détection LIVE", 
        value="Le bot recherche les mots: **LIVE**, **en cours**, **spectate**, **observer**, etc.", 
        inline=False
    )
    embed.add_field(
        name="!addsite URL [nom] [rôle]", 
        value="Ajouter un profil OP.GG à surveiller\nExemple: `!addsite https://euw.op.gg/summoner/userName=Faker \"Faker\" \"Mid\"`", 
        inline=False
    )
    embed.add_field(
        name="!removesite [URL/nom]", 
        value="Supprimer un site de la surveillance", 
        inline=False
    )
    embed.add_field(
        name="!listsites", 
        value="Afficher tous les profils surveillés", 
        inline=False
    )
    embed.add_field(
        name="!testsite URL", 
        value="Tester un profil OP.GG pour voir les parties LIVE détectées", 
        inline=False
    )
    embed.add_field(
        name="🔴 Avantages", 
        value="• Détection simplifiée et plus fiable\n• Recherche du mot LIVE\n• Notifications en temps réel", 
        inline=False
    )
    
    embed.set_footer(text="Vérification LIVE toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide ! Utilisez `!lolhelp` pour voir les commandes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant ! Utilisez `!lolhelp` pour voir les commandes.")
    else:
        logger.error(f"Erreur de commande: {error}")

@bot.event
async def on_disconnect():
    logger.info("Bot déconnecté")
    if check_lol_games.is_running():
        check_lol_games.cancel()
    await web_monitor.close()

# === Lancement ===
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant !")
        exit(1)
    
    try:
        print(f"🚀 Démarrage du bot LoL Monitor LIVE...")
        logger.info("Démarrage du bot Discord LoL Monitor LIVE")
        
        # Démarrer Flask dans un thread séparé
        flask_thread = Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Démarrer le bot Discord
        bot.run(token)
        
    except discord.errors.LoginFailure:
        print("❌ Token Discord invalide !")
        logger.error("Token Discord invalide")
    except Exception as e:
        logger.error(f"Erreur lors du lancement du bot: {e}")
        print(f"❌ Erreur: {e}")
