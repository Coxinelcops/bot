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
    app.run(host='0.0.0.0', port=8080)

# === Logger ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Bot Discord ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === Stockage des données ===
monitored_sites = {}  # {channel_id: [{'url': str, 'selector': str, 'name': str}]}
active_games = {}  # {channel_id: {game_id: message_id}}
reaction_game_messages = {}  # {message_id: {'url': str, 'game_info': dict}}

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

            # Exemple de parsing générique - à adapter selon le site
            if selector:
                # Utilise un sélecteur CSS personnalisé
                elements = soup.select(selector)
            else:
                # Recherche générique de parties LoL
                elements = soup.find_all(['div', 'a', 'span'], 
                    text=re.compile(r'league of legends|lol|spectate|game|match', re.I))

            for element in elements:
                game_info = await self.extract_game_info(element, base_url)
                if game_info:
                    games.append(game_info)

            return games
        except Exception as e:
            logger.error(f"Erreur lors du parsing: {e}")
            return []

    async def extract_game_info(self, element, base_url):
        """Extrait les informations d'une partie depuis un élément HTML"""
        try:
            # Chercher le lien de spectate
            link = element.find('a') if element.name != 'a' else element
            if not link:
                link = element.find_parent('a')
            
            if not link or not link.get('href'):
                return None

            url = link.get('href')
            if url.startswith('/'):
                url = base_url.rstrip('/') + url
            elif not url.startswith('http'):
                return None

            # Extraire les informations du jeu
            title = link.get_text(strip=True) or "Partie League of Legends"
            
            # Chercher des informations supplémentaires
            parent = element.find_parent(['div', 'section', 'article'])
            if parent:
                # Chercher le niveau, rang, etc.
                level_match = re.search(r'level\s*(\d+)', parent.get_text(), re.I)
                rank_match = re.search(r'(bronze|silver|gold|platinum|diamond|master|grandmaster|challenger)', parent.get_text(), re.I)
                
                level = level_match.group(1) if level_match else "?"
                rank = rank_match.group(1).title() if rank_match else "Non classé"
            else:
                level = "?"
                rank = "Non classé"

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

    async def close(self):
        if self.session:
            await self.session.close()

web_monitor = WebMonitor()

@bot.event
async def on_ready():
    print(f'{bot.user} est connecté et prêt !')
    if not check_lol_games.is_running():
        check_lol_games.start()

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
            name="👁️ Observer", 
            value="Réagissez avec 👁️ pour observer cette partie !", 
            inline=False
        )
        
        embed.set_footer(text=f"Détecté sur {site_name}")
        
        # Ajouter une image si disponible
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")  # Logo LoL

        message = await channel.send(embed=embed)
        await message.add_reaction("👁️")

        # Stocker les informations
        active_games[channel.id][game['id']] = message.id
        reaction_game_messages[message.id] = {
            'url': game['url'],
            'game_info': game,
            'site_name': site_name
        }

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
            if message_id in reaction_game_messages:
                game_info = reaction_game_messages[message_id]['game_info']
                if current_time - game_info['timestamp'] > 1800:  # 30 minutes
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
        reaction_game_messages.pop(message_id, None)

@bot.event
async def on_reaction_add(reaction, user):
    """Gère les réactions pour observer les parties"""
    if user.bot:
        return

    message_id = reaction.message.id
    if message_id not in reaction_game_messages:
        return

    # Vérifier si c'est la bonne réaction
    if str(reaction.emoji) != "👁️":
        return

    game_data = reaction_game_messages[message_id]
    
    try:
        # Envoyer le lien en DM
        embed = discord.Embed(
            title="🎮 Lien d'observation LoL",
            description=f"Voici le lien pour observer la partie :",
            color=0x0596AA
        )
        embed.add_field(name="🔗 Lien", value=f"[Cliquez ici pour observer]({game_data['url']})", inline=False)
        embed.add_field(name="📋 URL", value=game_data['url'], inline=False)
        embed.set_footer(text=f"Source: {game_data['site_name']}")

        await user.send(embed=embed)
        logger.info(f"Lien envoyé à {user.name} pour observer une partie LoL")

    except discord.Forbidden:
        # Si on ne peut pas envoyer en DM, répondre dans le channel
        try:
            await reaction.message.channel.send(
                f"{user.mention}, voici le lien pour observer: {game_data['url']}", 
                delete_after=30
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du lien: {e}")

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
    embed.add_field(name="Réaction 👁️", value="Réagir avec 👁️ sur une notification pour obtenir le lien", inline=False)
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
    Thread(target=run_flask).start()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Le token Discord est manquant !")
    else:
        try:
            print(f"🚀 Connexion avec le token: {token[:10]}...")
            bot.run(token)
        except discord.errors.LoginFailure:
            print("❌ Token Discord invalide !")
        except Exception as e:
            logger.error(f"Erreur lors du lancement du bot: {e}")
