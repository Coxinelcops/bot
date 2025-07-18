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

bot = commands.Bot(command_prefix='!', intents=intents)
bot.ready_flag = False  # Évite relance multiple

# === Stockage des données ===
monitored_sites = {}  # {channel_id: [{'url': str, 'selector': str, 'name': str}]}
active_games = {}  # {channel_id: {game_id: message_id}}

class WebMonitor:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    async def check_site(self, url, selector=None):
        """Vérifie un site pour des parties LoL disponibles"""
        try:
            session = await self.get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    return await self.parse_lol_games(html, url, selector)
                else:
                    logger.warning(f"Erreur HTTP {response.status} pour {url}")
                    return []
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {url}: {e}")
            return []

    async def parse_lol_games(self, html, base_url, selector=None):
        """Parse le HTML pour extraire les parties LoL disponibles"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            if selector:
                # Utilise un sélecteur CSS personnalisé
                elements = soup.select(selector)
            else:
                # Recherche améliorée selon les patterns courants des sites LoL
                patterns = [
                    # Liens de spectate directs
                    {'tag': 'a', 'href': re.compile(r'spectate|watch|view|live', re.I)},
                    # Éléments contenant des mots-clés LoL
                    {'tag': ['div', 'span', 'td', 'li'], 'text': re.compile(r'spectate|watch|live|in\s*game|playing|match|game', re.I)},
                    # Éléments avec des classes communes
                    {'tag': ['div', 'a'], 'class': re.compile(r'game|match|spectate|live|watch', re.I)},
                    # Boutons de spectate
                    {'tag': ['button', 'a'], 'text': re.compile(r'spectate|watch|view', re.I)}
                ]
                
                elements = []
                for pattern in patterns:
                    if 'href' in pattern:
                        found = soup.find_all(pattern['tag'], href=pattern['href'])
                    elif 'class' in pattern:
                        found = soup.find_all(pattern['tag'], class_=pattern['class'])
                    elif 'text' in pattern:
                        found = soup.find_all(pattern['tag'], string=pattern['text'])
                    else:
                        found = soup.find_all(pattern['tag'])
                    
                    elements.extend(found)
                
                # Supprime les doublons
                elements = list(set(elements))

            logger.info(f"Trouvé {len(elements)} éléments potentiels sur {base_url}")

            for element in elements:
                game_info = await self.extract_game_info(element, base_url)
                if game_info:
                    games.append(game_info)

            # Supprime les doublons basés sur l'URL
            unique_games = []
            seen_urls = set()
            for game in games:
                if game['url'] not in seen_urls:
                    unique_games.append(game)
                    seen_urls.add(game['url'])

            logger.info(f"Détecté {len(unique_games)} parties uniques")
            return unique_games
        except Exception as e:
            logger.error(f"Erreur lors du parsing: {e}")
            return []

    async def extract_game_info(self, element, base_url):
        """Extrait les informations d'une partie depuis un élément HTML"""
        try:
            # Chercher le lien de spectate de plusieurs façons
            link = None
            url = None
            
            # Cas 1: L'élément est déjà un lien
            if element.name == 'a' and element.get('href'):
                link = element
                url = element.get('href')
            
            # Cas 2: Chercher un lien enfant
            if not link:
                child_link = element.find('a')
                if child_link and child_link.get('href'):
                    link = child_link
                    url = child_link.get('href')
            
            # Cas 3: Chercher un lien parent
            if not link:
                parent_link = element.find_parent('a')
                if parent_link and parent_link.get('href'):
                    link = parent_link
                    url = parent_link.get('href')
            
            # Cas 4: Chercher un lien dans le même conteneur
            if not link:
                container = element.find_parent(['div', 'td', 'li'])
                if container:
                    container_link = container.find('a')
                    if container_link and container_link.get('href'):
                        link = container_link
                        url = container_link.get('href')
            
            if not url:
                return None

            # Normaliser l'URL
            if url.startswith('/'):
                url = base_url.rstrip('/') + url
            elif not url.startswith('http'):
                # Essayer de construire une URL relative
                if '.' in url:  # Probablement une URL relative
                    url = base_url.rstrip('/') + '/' + url
                else:
                    return None
            
            # Vérifier que l'URL semble être un lien de spectate
            if not self.is_spectate_url(url):
                return None

            # Extraire le titre
            title = self.extract_title(element, link)
            
            # Extraire les informations supplémentaires
            level, rank = self.extract_player_info(element)

            return {
                'id': hash(url),  # ID unique basé sur l'URL
                'url': url,
                'title': title,
                'level': level,
                'rank': rank,
                'timestamp': datetime.now(UTC).timestamp()
            }
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction: {e}")
            return None

    def is_spectate_url(self, url):
        """Vérifie si l'URL semble être un lien de spectate valide"""
        spectate_patterns = [
            r'spectate',
            r'watch',
            r'view',
            r'live',
            r'game',
            r'match',
            r'riot:',
            r'lol:',
            r'\.bat

    async def close(self):
        if self.session:
            await self.session.close()

web_monitor = WebMonitor()

@bot.event
async def on_ready():
    if not getattr(bot, "ready_flag", False):
        print(f'{bot.user} est connecté et prêt !')
    if not check_lol_games.is_running():
        check_lol_games.start()
        bot.ready_flag = True

@tasks.loop(minutes=2)  # Vérification toutes les 2 minutes
async def check_lol_games():
    """Vérifie les sites pour de nouvelles parties LoL"""
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
                games = await web_monitor.check_site(site['url'], site.get('selector'))
                
                for game in games:
                    game_id = game['id']
                    
                    # Vérifier si la partie est déjà affichée
                    if game_id not in active_games[channel_id]:
                        await send_game_notification(channel, game, site['name'])

        # Nettoyer les anciennes parties (plus de 30 minutes)
        await cleanup_old_games()

    except Exception as e:
        logger.error(f"Erreur dans check_lol_games: {e}")

@check_lol_games.before_loop
async def before_check_lol_games():
    await bot.wait_until_ready()

async def send_game_notification(channel, game, site_name):
    """Envoie une notification pour une nouvelle partie LoL"""
    try:
        embed = discord.Embed(
            title="🎮 Nouvelle partie League of Legends !",
            description=f"**{game['title']}**",
            color=0x0596AA,
            timestamp=datetime.now(UTC)
        )
        
        embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
        embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
        embed.add_field(name="🌐 Source", value=site_name, inline=True)
        
        embed.add_field(
            name="🔗 Lien d'observation", 
            value=f"[Cliquez ici pour observer]({game['url']})", 
            inline=False
        )
        
        embed.set_footer(text=f"Détecté sur {site_name}")
        
        # Ajouter une image si disponible
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")  # Logo LoL

        message = await channel.send(embed=embed)

        # Stocker les informations
        active_games[channel.id][game['id']] = message.id

        logger.info(f"Notification envoyée pour une partie LoL dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}")

async def cleanup_old_games():
    """Nettoie les anciennes parties (plus de 30 minutes)"""
    current_time = datetime.now(UTC).timestamp()
    to_remove = []

    for channel_id, games in active_games.items():
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for game_id, message_id in games.items():
            # Créer une info temporaire pour le timestamp
            if current_time - datetime.now(UTC).timestamp() > 1800:  # 30 minutes
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    to_remove.append((channel_id, game_id, message_id))
                except discord.NotFound:
                    to_remove.append((channel_id, game_id, message_id))
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression: {e}")

    # Supprimer les références
    for channel_id, game_id, message_id in to_remove:
        active_games[channel_id].pop(game_id, None)

# === Commandes ===

@bot.command(name='addsite')
@commands.has_permissions(manage_channels=True)
async def add_site(ctx, url=None, name=None, selector=None):
    """Ajoute un site à surveiller pour des parties LoL"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL !\nExemple: `!addsite https://example.com \"Mon Site\" \".game-link\"`")
        return

    if not name:
        name = url

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
        'name': name,
        'selector': selector
    }

    monitored_sites[channel_id].append(site_data)
    await ctx.send(f"✅ Site ajouté à la surveillance : **{name}**")

@bot.command(name='removesite')
@commands.has_permissions(manage_channels=True)
async def remove_site(ctx, url=None):
    """Supprime un site de la surveillance"""
    if not url:
        await ctx.send("❌ Veuillez spécifier l'URL du site à supprimer !")
        return

    channel_id = ctx.channel.id
    if channel_id not in monitored_sites:
        await ctx.send("❌ Aucun site surveillé dans ce channel !")
        return

    for i, site in enumerate(monitored_sites[channel_id]):
        if site['url'] == url:
            removed_site = monitored_sites[channel_id].pop(i)
            await ctx.send(f"✅ Site supprimé : **{removed_site['name']}**")
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
        title="📋 Sites surveillés",
        color=0x0596AA
    )

    for site in monitored_sites[channel_id]:
        embed.add_field(
            name=site['name'],
            value=f"URL: {site['url']}\nSélecteur: {site['selector'] or 'Automatique'}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='testsite')
@commands.has_permissions(manage_channels=True)
async def test_site(ctx, url=None, selector=None):
    """Test un site pour voir les parties détectées"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL à tester !")
        return

    await ctx.send("🔍 Test du site en cours...")

    games = await web_monitor.check_site(url, selector)
    
    if not games:
        await ctx.send("❌ Aucune partie détectée sur ce site.")
        return

    embed = discord.Embed(
        title=f"🎮 Parties détectées ({len(games)})",
        color=0x0596AA
    )

    for i, game in enumerate(games[:5]):  # Limiter à 5 résultats
        embed.add_field(
            name=f"Partie {i+1}",
            value=f"**{game['title']}**\nRang: {game['rank']}\nNiveau: {game['level']}\n[Lien]({game['url']})",
            inline=False
        )

    if len(games) > 5:
        embed.set_footer(text=f"Et {len(games) - 5} autres parties...")

    await ctx.send(embed=embed)

@bot.command(name='debug')
@commands.has_permissions(manage_channels=True)
async def debug_site(ctx, url=None):
    """Debug un site pour voir les éléments détectés"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL à déboguer !")
        return

    await ctx.send("🔍 Debug du site en cours...")

    try:
        session = await web_monitor.get_session()
        async with session.get(url) as response:
            if response.status != 200:
                await ctx.send(f"❌ Erreur HTTP {response.status}")
                return
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Statistiques de base
            total_links = len(soup.find_all('a'))
            total_divs = len(soup.find_all('div'))
            
            # Recherche d'éléments suspects
            spectate_links = soup.find_all('a', href=re.compile(r'spectate|watch|view|live|game', re.I))
            spectate_text = soup.find_all(text=re.compile(r'spectate|watch|live|in\s*game|playing', re.I))
            
            embed = discord.Embed(
                title="🔍 Debug du site",
                description=f"Analyse de: {url}",
                color=0xFFAA00
            )
            
            embed.add_field(name="📊 Statistiques", 
                          value=f"Liens: {total_links}\nDivs: {total_divs}", 
                          inline=True)
            
            embed.add_field(name="🎮 Éléments suspects", 
                          value=f"Liens spectate: {len(spectate_links)}\nTexte spectate: {len(spectate_text)}", 
                          inline=True)
            
            if spectate_links:
                links_text = "\n".join([f"• {link.get('href', 'N/A')}" for link in spectate_links[:3]])
                embed.add_field(name="🔗 Premiers liens", value=links_text, inline=False)
            
            await ctx.send(embed=embed)
            
    except Exception as e:
        await ctx.send(f"❌ Erreur lors du debug: {e}")
        logger.error(f"Erreur debug: {e}")

@bot.command(name='lolhelp')
async def lol_help(ctx):
    """Affiche l'aide pour les commandes LoL"""
    embed = discord.Embed(
        title="🎮 Aide du Bot LoL Monitor",
        description="Commandes disponibles :",
        color=0x0596AA
    )
    embed.add_field(name="!addsite URL [nom] [sélecteur]", value="Ajouter un site à surveiller", inline=False)
    embed.add_field(name="!removesite URL", value="Supprimer un site de la surveillance", inline=False)
    embed.add_field(name="!listsites", value="Afficher les sites surveillés", inline=False)
    embed.add_field(name="!testsite URL [sélecteur]", value="Tester un site pour voir les parties détectées", inline=False)
    embed.add_field(name="!debug URL", value="Déboguer un site pour voir les éléments détectés", inline=False)
    embed.set_footer(text="Le bot vérifie les sites toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide ! Utilisez !lolhelp pour voir les commandes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant ! Utilisez !lolhelp pour voir les commandes.")
    else:
        logger.error(f"Erreur non gérée: {error}")

@bot.event
async def on_disconnect():
    if check_lol_games.is_running():
        check_lol_games.cancel()
    await web_monitor.close()

# === Lancement ===

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant !")
    else:
        try:
            print(f"🚀 Connexion avec le token: {token[:10]}...")
        except discord.errors.LoginFailure:
            print("❌ Token Discord invalide !")
        except Exception as e:
            logger.error(f"Erreur lors du lancement du bot: {e}")

from threading import Thread
if __name__ == "__main__":
    Thread(target=bot.run, args=(os.getenv("DISCORD_BOT_TOKEN"),)).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port),
            r'\.exe

    async def close(self):
        if self.session:
            await self.session.close()

web_monitor = WebMonitor()

@bot.event
async def on_ready():
    if not getattr(bot, "ready_flag", False):
        print(f'{bot.user} est connecté et prêt !')
    if not check_lol_games.is_running():
        check_lol_games.start()
        bot.ready_flag = True

@tasks.loop(minutes=2)  # Vérification toutes les 2 minutes
async def check_lol_games():
    """Vérifie les sites pour de nouvelles parties LoL"""
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
                games = await web_monitor.check_site(site['url'], site.get('selector'))
                
                for game in games:
                    game_id = game['id']
                    
                    # Vérifier si la partie est déjà affichée
                    if game_id not in active_games[channel_id]:
                        await send_game_notification(channel, game, site['name'])

        # Nettoyer les anciennes parties (plus de 30 minutes)
        await cleanup_old_games()

    except Exception as e:
        logger.error(f"Erreur dans check_lol_games: {e}")

@check_lol_games.before_loop
async def before_check_lol_games():
    await bot.wait_until_ready()

async def send_game_notification(channel, game, site_name):
    """Envoie une notification pour une nouvelle partie LoL"""
    try:
        embed = discord.Embed(
            title="🎮 Nouvelle partie League of Legends !",
            description=f"**{game['title']}**",
            color=0x0596AA,
            timestamp=datetime.now(UTC)
        )
        
        embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
        embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
        embed.add_field(name="🌐 Source", value=site_name, inline=True)
        
        embed.add_field(
            name="🔗 Lien d'observation", 
            value=f"[Cliquez ici pour observer]({game['url']})", 
            inline=False
        )
        
        embed.set_footer(text=f"Détecté sur {site_name}")
        
        # Ajouter une image si disponible
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")  # Logo LoL

        message = await channel.send(embed=embed)

        # Stocker les informations
        active_games[channel.id][game['id']] = message.id

        logger.info(f"Notification envoyée pour une partie LoL dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}")

async def cleanup_old_games():
    """Nettoie les anciennes parties (plus de 30 minutes)"""
    current_time = datetime.now(UTC).timestamp()
    to_remove = []

    for channel_id, games in active_games.items():
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for game_id, message_id in games.items():
            # Créer une info temporaire pour le timestamp
            if current_time - datetime.now(UTC).timestamp() > 1800:  # 30 minutes
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    to_remove.append((channel_id, game_id, message_id))
                except discord.NotFound:
                    to_remove.append((channel_id, game_id, message_id))
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression: {e}")

    # Supprimer les références
    for channel_id, game_id, message_id in to_remove:
        active_games[channel_id].pop(game_id, None)

# === Commandes ===

@bot.command(name='addsite')
@commands.has_permissions(manage_channels=True)
async def add_site(ctx, url=None, name=None, selector=None):
    """Ajoute un site à surveiller pour des parties LoL"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL !\nExemple: `!addsite https://example.com \"Mon Site\" \".game-link\"`")
        return

    if not name:
        name = url

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
        'name': name,
        'selector': selector
    }

    monitored_sites[channel_id].append(site_data)
    await ctx.send(f"✅ Site ajouté à la surveillance : **{name}**")

@bot.command(name='removesite')
@commands.has_permissions(manage_channels=True)
async def remove_site(ctx, url=None):
    """Supprime un site de la surveillance"""
    if not url:
        await ctx.send("❌ Veuillez spécifier l'URL du site à supprimer !")
        return

    channel_id = ctx.channel.id
    if channel_id not in monitored_sites:
        await ctx.send("❌ Aucun site surveillé dans ce channel !")
        return

    for i, site in enumerate(monitored_sites[channel_id]):
        if site['url'] == url:
            removed_site = monitored_sites[channel_id].pop(i)
            await ctx.send(f"✅ Site supprimé : **{removed_site['name']}**")
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
        title="📋 Sites surveillés",
        color=0x0596AA
    )

    for site in monitored_sites[channel_id]:
        embed.add_field(
            name=site['name'],
            value=f"URL: {site['url']}\nSélecteur: {site['selector'] or 'Automatique'}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='testsite')
@commands.has_permissions(manage_channels=True)
async def test_site(ctx, url=None, selector=None):
    """Test un site pour voir les parties détectées"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL à tester !")
        return

    await ctx.send("🔍 Test du site en cours...")

    games = await web_monitor.check_site(url, selector)
    
    if not games:
        await ctx.send("❌ Aucune partie détectée sur ce site.")
        return

    embed = discord.Embed(
        title=f"🎮 Parties détectées ({len(games)})",
        color=0x0596AA
    )

    for i, game in enumerate(games[:5]):  # Limiter à 5 résultats
        embed.add_field(
            name=f"Partie {i+1}",
            value=f"**{game['title']}**\nRang: {game['rank']}\nNiveau: {game['level']}\n[Lien]({game['url']})",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='lolhelp')
async def lol_help(ctx):
    """Affiche l'aide pour les commandes LoL"""
    embed = discord.Embed(
        title="🎮 Aide du Bot LoL Monitor",
        description="Commandes disponibles :",
        color=0x0596AA
    )
    embed.add_field(name="!addsite URL [nom] [sélecteur]", value="Ajouter un site à surveiller", inline=False)
    embed.add_field(name="!removesite URL", value="Supprimer un site de la surveillance", inline=False)
    embed.add_field(name="!listsites", value="Afficher les sites surveillés", inline=False)
    embed.add_field(name="!testsite URL [sélecteur]", value="Tester un site pour voir les parties détectées", inline=False)
    embed.set_footer(text="Le bot vérifie les sites toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide ! Utilisez !lolhelp pour voir les commandes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant ! Utilisez !lolhelp pour voir les commandes.")
    else:
        logger.error(f"Erreur non gérée: {error}")

@bot.event
async def on_disconnect():
    if check_lol_games.is_running():
        check_lol_games.cancel()
    await web_monitor.close()

# === Lancement ===

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant !")
    else:
        try:
            print(f"🚀 Connexion avec le token: {token[:10]}...")
        except discord.errors.LoginFailure:
            print("❌ Token Discord invalide !")
        except Exception as e:
            logger.error(f"Erreur lors du lancement du bot: {e}")

from threading import Thread
if __name__ == "__main__":
    Thread(target=bot.run, args=(os.getenv("DISCORD_BOT_TOKEN"),)).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port),
            r'download',
            r'play\.tv',
            r'op\.gg',
            r'porofessor',
            r'lolimo',
            r'lolspectator'
        ]
        
        url_lower = url.lower()
        return any(re.search(pattern, url_lower) for pattern in spectate_patterns)

    def extract_title(self, element, link):
        """Extrait le titre de la partie"""
        # Essayer plusieurs sources pour le titre
        title_sources = [
            link.get_text(strip=True) if link else "",
            element.get_text(strip=True),
            element.get('title', ''),
            element.get('alt', '')
        ]
        
        for title in title_sources:
            if title and len(title) > 3:
                return title
        
        return "Partie League of Legends"

    def extract_player_info(self, element):
        """Extrait les informations du joueur (niveau, rang)"""
        # Chercher dans l'élément et ses parents
        search_elements = [element]
        parent = element.find_parent(['div', 'td', 'li', 'article', 'section'])
        if parent:
            search_elements.append(parent)
        
        level = "?"
        rank = "Non classé"
        
        for elem in search_elements:
            text = elem.get_text()
            
            # Chercher le niveau
            level_match = re.search(r'level\s*:?\s*(\d+)', text, re.I)
            if level_match:
                level = level_match.group(1)
            
            # Chercher le rang
            rank_match = re.search(r'(iron|bronze|silver|gold|platinum|diamond|master|grandmaster|challenger)', text, re.I)
            if rank_match:
                rank = rank_match.group(1).title()
        
        return level, rank

    async def close(self):
        if self.session:
            await self.session.close()

web_monitor = WebMonitor()

@bot.event
async def on_ready():
    if not getattr(bot, "ready_flag", False):
        print(f'{bot.user} est connecté et prêt !')
    if not check_lol_games.is_running():
        check_lol_games.start()
        bot.ready_flag = True

@tasks.loop(minutes=2)  # Vérification toutes les 2 minutes
async def check_lol_games():
    """Vérifie les sites pour de nouvelles parties LoL"""
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
                games = await web_monitor.check_site(site['url'], site.get('selector'))
                
                for game in games:
                    game_id = game['id']
                    
                    # Vérifier si la partie est déjà affichée
                    if game_id not in active_games[channel_id]:
                        await send_game_notification(channel, game, site['name'])

        # Nettoyer les anciennes parties (plus de 30 minutes)
        await cleanup_old_games()

    except Exception as e:
        logger.error(f"Erreur dans check_lol_games: {e}")

@check_lol_games.before_loop
async def before_check_lol_games():
    await bot.wait_until_ready()

async def send_game_notification(channel, game, site_name):
    """Envoie une notification pour une nouvelle partie LoL"""
    try:
        embed = discord.Embed(
            title="🎮 Nouvelle partie League of Legends !",
            description=f"**{game['title']}**",
            color=0x0596AA,
            timestamp=datetime.now(UTC)
        )
        
        embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
        embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
        embed.add_field(name="🌐 Source", value=site_name, inline=True)
        
        embed.add_field(
            name="🔗 Lien d'observation", 
            value=f"[Cliquez ici pour observer]({game['url']})", 
            inline=False
        )
        
        embed.set_footer(text=f"Détecté sur {site_name}")
        
        # Ajouter une image si disponible
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")  # Logo LoL

        message = await channel.send(embed=embed)

        # Stocker les informations
        active_games[channel.id][game['id']] = message.id

        logger.info(f"Notification envoyée pour une partie LoL dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}")

async def cleanup_old_games():
    """Nettoie les anciennes parties (plus de 30 minutes)"""
    current_time = datetime.now(UTC).timestamp()
    to_remove = []

    for channel_id, games in active_games.items():
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for game_id, message_id in games.items():
            # Créer une info temporaire pour le timestamp
            if current_time - datetime.now(UTC).timestamp() > 1800:  # 30 minutes
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    to_remove.append((channel_id, game_id, message_id))
                except discord.NotFound:
                    to_remove.append((channel_id, game_id, message_id))
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression: {e}")

    # Supprimer les références
    for channel_id, game_id, message_id in to_remove:
        active_games[channel_id].pop(game_id, None)

# === Commandes ===

@bot.command(name='addsite')
@commands.has_permissions(manage_channels=True)
async def add_site(ctx, url=None, name=None, selector=None):
    """Ajoute un site à surveiller pour des parties LoL"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL !\nExemple: `!addsite https://example.com \"Mon Site\" \".game-link\"`")
        return

    if not name:
        name = url

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
        'name': name,
        'selector': selector
    }

    monitored_sites[channel_id].append(site_data)
    await ctx.send(f"✅ Site ajouté à la surveillance : **{name}**")

@bot.command(name='removesite')
@commands.has_permissions(manage_channels=True)
async def remove_site(ctx, url=None):
    """Supprime un site de la surveillance"""
    if not url:
        await ctx.send("❌ Veuillez spécifier l'URL du site à supprimer !")
        return

    channel_id = ctx.channel.id
    if channel_id not in monitored_sites:
        await ctx.send("❌ Aucun site surveillé dans ce channel !")
        return

    for i, site in enumerate(monitored_sites[channel_id]):
        if site['url'] == url:
            removed_site = monitored_sites[channel_id].pop(i)
            await ctx.send(f"✅ Site supprimé : **{removed_site['name']}**")
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
        title="📋 Sites surveillés",
        color=0x0596AA
    )

    for site in monitored_sites[channel_id]:
        embed.add_field(
            name=site['name'],
            value=f"URL: {site['url']}\nSélecteur: {site['selector'] or 'Automatique'}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='testsite')
@commands.has_permissions(manage_channels=True)
async def test_site(ctx, url=None, selector=None):
    """Test un site pour voir les parties détectées"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL à tester !")
        return

    await ctx.send("🔍 Test du site en cours...")

    games = await web_monitor.check_site(url, selector)
    
    if not games:
        await ctx.send("❌ Aucune partie détectée sur ce site.")
        return

    embed = discord.Embed(
        title=f"🎮 Parties détectées ({len(games)})",
        color=0x0596AA
    )

    for i, game in enumerate(games[:5]):  # Limiter à 5 résultats
        embed.add_field(
            name=f"Partie {i+1}",
            value=f"**{game['title']}**\nRang: {game['rank']}\nNiveau: {game['level']}\n[Lien]({game['url']})",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='lolhelp')
async def lol_help(ctx):
    """Affiche l'aide pour les commandes LoL"""
    embed = discord.Embed(
        title="🎮 Aide du Bot LoL Monitor",
        description="Commandes disponibles :",
        color=0x0596AA
    )
    embed.add_field(name="!addsite URL [nom] [sélecteur]", value="Ajouter un site à surveiller", inline=False)
    embed.add_field(name="!removesite URL", value="Supprimer un site de la surveillance", inline=False)
    embed.add_field(name="!listsites", value="Afficher les sites surveillés", inline=False)
    embed.add_field(name="!testsite URL [sélecteur]", value="Tester un site pour voir les parties détectées", inline=False)
    embed.set_footer(text="Le bot vérifie les sites toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide ! Utilisez !lolhelp pour voir les commandes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant ! Utilisez !lolhelp pour voir les commandes.")
    else:
        logger.error(f"Erreur non gérée: {error}")

@bot.event
async def on_disconnect():
    if check_lol_games.is_running():
        check_lol_games.cancel()
    await web_monitor.close()

# === Lancement ===

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant !")
    else:
        try:
            print(f"🚀 Connexion avec le token: {token[:10]}...")
        except discord.errors.LoginFailure:
            print("❌ Token Discord invalide !")
        except Exception as e:
            logger.error(f"Erreur lors du lancement du bot: {e}")

from threading import Thread
if __name__ == "__main__":
    Thread(target=bot.run, args=(os.getenv("DISCORD_BOT_TOKEN"),)).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
