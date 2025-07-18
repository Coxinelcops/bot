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
reaction_game_messages = {}

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
                    return await self.parse_opgg_games(html, url)
                else:
                    logger.warning(f"Erreur HTTP {response.status} pour {url}")
                    return []
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {url}: {e}")
            return []

    async def parse_opgg_games(self, html, base_url):
        """Parse spécifiquement les pages OP.GG pour détecter les parties en cours"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            # Recherche spécifique pour OP.GG - "Partie en cours" en vert
            # Plusieurs sélecteurs possibles selon la version d'OP.GG
            selectors_to_try = [
                # Sélecteurs pour le texte "Partie en cours" ou "In Game"
                'div:contains("Partie en cours")',
                'span:contains("Partie en cours")',
                'div:contains("In Game")',
                'span:contains("In Game")',
                '.live-game',
                '.in-game',
                '.game-status',
                # Sélecteurs pour les éléments avec couleur verte
                'div[style*="color: green"]',
                'span[style*="color: green"]',
                'div[style*="color:#00ff00"]',
                'span[style*="color:#00ff00"]',
                # Classes CSS communes pour les parties en cours
                '.status-live',
                '.status-ingame',
                '.live-indicator'
            ]

            # Essayer chaque sélecteur
            for selector in selectors_to_try:
                try:
                    if ':contains(' in selector:
                        # Pour les sélecteurs avec :contains, faire une recherche manuelle
                        text_to_find = selector.split(':contains("')[1].split('")')[0]
                        elements = soup.find_all(text=re.compile(text_to_find, re.I))
                        for text_element in elements:
                            parent = text_element.parent
                            if parent:
                                game_info = await self.extract_opgg_game_info(parent, base_url)
                                if game_info:
                                    games.append(game_info)
                    else:
                        # Pour les sélecteurs CSS standards
                        elements = soup.select(selector)
                        for element in elements:
                            game_info = await self.extract_opgg_game_info(element, base_url)
                            if game_info:
                                games.append(game_info)
                except Exception as e:
                    logger.debug(f"Erreur avec le sélecteur {selector}: {e}")
                    continue

            # Si aucune partie trouvée avec les sélecteurs, essayer une recherche plus générale
            if not games:
                games = await self.fallback_search(soup, base_url)

            # Éliminer les doublons
            unique_games = []
            seen_urls = set()
            for game in games:
                if game['url'] not in seen_urls:
                    unique_games.append(game)
                    seen_urls.add(game['url'])

            return unique_games

        except Exception as e:
            logger.error(f"Erreur lors du parsing OP.GG: {e}")
            return []

    async def fallback_search(self, soup, base_url):
        """Recherche de fallback pour trouver des parties en cours"""
        games = []
        
        # Rechercher tous les liens qui pourraient mener à des parties
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href')
            text = link.get_text(strip=True).lower()
            
            # Vérifier si c'est un lien de spectate ou de partie en cours
            if any(keyword in text for keyword in ['spectate', 'observer', 'partie', 'game', 'live']):
                # Vérifier si le parent contient des indicateurs de partie en cours
                parent = link.find_parent(['div', 'span', 'td', 'li'])
                if parent:
                    parent_text = parent.get_text().lower()
                    if any(keyword in parent_text for keyword in ['partie en cours', 'in game', 'live', 'en cours']):
                        game_info = await self.extract_opgg_game_info(link, base_url)
                        if game_info:
                            games.append(game_info)
        
        return games

    async def extract_opgg_game_info(self, element, base_url):
        """Extrait les informations d'une partie OP.GG"""
        try:
            # Trouver le lien de spectate
            spectate_link = None
            
            # Si l'élément est déjà un lien
            if element.name == 'a' and element.get('href'):
                spectate_link = element.get('href')
            
            # Sinon, chercher un lien dans l'élément ou ses enfants
            if not spectate_link:
                link_element = element.find('a', href=True)
                if link_element:
                    spectate_link = link_element.get('href')
            
            # Chercher un lien dans les éléments frères
            if not spectate_link:
                siblings = element.find_next_siblings('a', limit=3)
                for sibling in siblings:
                    if sibling.get('href'):
                        href = sibling.get('href')
                        if 'spectate' in href.lower() or 'observer' in href.lower():
                            spectate_link = href
                            break
            
            if not spectate_link:
                return None

            # Construire l'URL complète
            if spectate_link.startswith('/'):
                full_url = base_url.rstrip('/') + spectate_link
            elif spectate_link.startswith('http'):
                full_url = spectate_link
            else:
                full_url = base_url.rstrip('/') + '/' + spectate_link

            # Extraire les informations du joueur
            player_name = "Joueur inconnu"
            rank = "Non classé"
            level = "?"
            
            # Chercher le nom du joueur dans la page
            page_container = element.find_parent(['div', 'section', 'article', 'table'])
            if page_container:
                # Chercher dans le texte du conteneur
                container_text = page_container.get_text()
                
                # Extraction du rang
                rank_patterns = [
                    r'(Iron|Bronze|Silver|Gold|Platinum|Diamond|Master|GrandMaster|Challenger)\s*([IVX]*)',
                    r'(Fer|Bronze|Argent|Or|Platine|Diamant|Maître|Grand[Mm]aître|Challenger)\s*([IVX]*)'
                ]
                
                for pattern in rank_patterns:
                    match = re.search(pattern, container_text, re.I)
                    if match:
                        rank = match.group(1).title()
                        if match.group(2):
                            rank += f" {match.group(2)}"
                        break
                
                # Extraction du niveau
                level_match = re.search(r'(?:Level|Niveau|Lvl)\s*(\d+)', container_text, re.I)
                if level_match:
                    level = level_match.group(1)
                
                # Extraction du nom du joueur (souvent dans le title ou près du lien)
                title_element = page_container.find(['h1', 'h2', 'h3', 'title'])
                if title_element:
                    title_text = title_element.get_text(strip=True)
                    # Extraire le nom du joueur du titre
                    name_match = re.search(r'([a-zA-Z0-9\s]+)(?:\s-\s|$)', title_text)
                    if name_match:
                        player_name = name_match.group(1).strip()

            # Créer un ID unique pour cette partie
            game_id = hash(f"{full_url}_{player_name}_{datetime.now(UTC).strftime('%Y%m%d%H%M')}")

            return {
                'id': game_id,
                'url': full_url,
                'title': f"Partie de {player_name}",
                'player': player_name,
                'level': level,
                'rank': rank,
                'timestamp': datetime.now(UTC).timestamp()
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction OP.GG: {e}")
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
                logger.info(f"Vérification de {site['url']} pour le channel {channel.name}")
                games = await web_monitor.check_site(site['url'], site.get('selector'))
                
                logger.info(f"Trouvé {len(games)} parties sur {site['name']}")
                
                for game in games:
                    game_id = game['id']
                    
                    # Vérifier si la partie est déjà affichée
                    if game_id not in active_games[channel_id]:
                        await send_game_notification(channel, game, site)
                        active_games[channel_id][game_id] = None  # Marquer comme envoyée

        # Nettoyer les anciennes parties
        await cleanup_old_games()

    except Exception as e:
        logger.error(f"Erreur dans check_lol_games: {e}")

@check_lol_games.before_loop
async def before_check_lol_games():
    await bot.wait_until_ready()

async def send_game_notification(channel, game, site_data):
    """Envoie une notification pour une nouvelle partie LoL en cours"""
    try:
        # Utiliser les infos personnalisées si disponibles
        player_name = site_data.get('player_name', game['player'])
        player_role = site_data.get('role', None)
        
        embed = discord.Embed(
            title="🔴 Partie League of Legends en cours !",
            description=f"**{player_name}** est actuellement en jeu",
            color=0x00ff00,  # Vert pour "en cours"
            timestamp=datetime.now(UTC)
        )
        
        embed.add_field(name="👤 Joueur", value=player_name, inline=True)
        if player_role:
            embed.add_field(name="🎯 Rôle", value=player_role, inline=True)
        embed.add_field(name="🏆 Rang", value=game['rank'], inline=True)
        embed.add_field(name="📊 Niveau", value=game['level'], inline=True)
        embed.add_field(name="🌐 Source", value=site_data['name'], inline=True)
        
        embed.add_field(
            name="🔗 Lien direct",
            value=f"[Cliquer ici pour observer]({game['url']})",
            inline=False
        )
        
        embed.set_footer(text=f"Détecté sur {site_data['name']} • Partie en cours")
        embed.set_thumbnail(url="https://i.imgur.com/28W8RHN.png")

        message = await channel.send(embed=embed)

        # Stocker les informations
        if channel.id not in active_games:
            active_games[channel.id] = {}
        active_games[channel.id][game['id']] = message.id

        logger.info(f"Notification envoyée pour {player_name} dans {channel.name}")

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
            if message_id and message_id in reaction_game_messages:
                game_info = reaction_game_messages[message_id]['game_info']
                if current_time - game_info['timestamp'] > 1800:  # 30 minutes
                    try:
                        message = await channel.fetch_message(message_id)
                        
                        # Modifier le message pour indiquer que la partie est terminée
                        embed = message.embeds[0]
                        embed.title = "⚫ Partie terminée"
                        embed.color = 0x808080  # Gris
                        embed.set_footer(text=f"Partie terminée • Était sur {games[game_id] if isinstance(games[game_id], str) else 'OP.GG'}")
                        
                        await message.edit(embed=embed)
                        
                        to_remove.append((channel_id, game_id, message_id))
                    except discord.NotFound:
                        to_remove.append((channel_id, game_id, message_id))
                    except Exception as e:
                        logger.error(f"Erreur lors de la mise à jour du message: {e}")

    # Supprimer les références
    for channel_id, game_id, message_id in to_remove:
        active_games[channel_id].pop(game_id, None)

@bot.event
async def on_reaction_add(reaction, user):
    """Gère les réactions pour observer les parties"""
    if user.bot:
        return

    message_id = reaction.message.id
    if message_id not in reaction_game_messages:
        return

    if str(reaction.emoji) != "👁️":
        return

    game_data = reaction_game_messages[message_id]
    
    try:
        # Envoyer le lien en DM
        embed = discord.Embed(
            title="🎮 Lien d'observation LoL",
            description=f"Voici le lien pour observer la partie de **{game_data['game_info']['player']}** :",
            color=0x00ff00
        )
        embed.add_field(name="🔗 Lien", value=f"[Cliquez ici pour observer]({game_data['url']})", inline=False)
        embed.add_field(name="📋 URL complète", value=f"```{game_data['url']}```", inline=False)
        embed.add_field(name="ℹ️ Info", value="Copiez le lien et ouvrez-le dans votre navigateur", inline=False)
        embed.set_footer(text=f"Source: {game_data['site_name']}")

        await user.send(embed=embed)
        logger.info(f"Lien d'observation envoyé à {user.name}")

    except discord.Forbidden:
        # Si on ne peut pas envoyer en DM, répondre dans le channel
        try:
            await reaction.message.channel.send(
                f"{user.mention}, voici le lien pour observer la partie : {game_data['url']}", 
                delete_after=60
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du lien: {e}")

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
    
    # Embed de base ou personnalisé selon les paramètres
    if not player_name and not role:
        # Embed de base
        embed = discord.Embed(
            title="✅ Site ajouté",
            description=f"Surveillance activée",
            color=0x00ff00
        )
        embed.add_field(name="URL", value=url, inline=False)
    else:
        # Embed personnalisé
        embed = discord.Embed(
            title="✅ Site ajouté",
            description=f"**{player_name}** est maintenant surveillé",
            color=0x00ff00
        )
        embed.add_field(name="👤 Joueur", value=player_name, inline=True)
        if role:
            embed.add_field(name="🎯 Rôle", value=role, inline=True)
        embed.add_field(name="🔗 Profil OP.GG", value=f"[Voir le profil]({url})", inline=False)
    
    embed.add_field(name="🔍 Vérification", value="Toutes les 2 minutes", inline=True)
    embed.set_footer(text="Le bot détectera automatiquement les parties en cours")
    
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
        title="📋 Sites surveillés",
        description=f"**{len(monitored_sites[channel_id])}** site(s) surveillé(s)",
        color=0x0596AA
    )

    for i, site in enumerate(monitored_sites[channel_id], 1):
        field_value = f"[Lien OP.GG]({site['url']})"
        if site.get('role'):
            field_value += f"\n🎯 Rôle: {site['role']}"
        
        embed.add_field(
            name=f"{i}. {site.get('player_name', site['name'])}",
            value=field_value,
            inline=False
        )

    embed.set_footer(text="Vérification toutes les 2 minutes")
    await ctx.send(embed=embed)

@bot.command(name='testsite')
@commands.has_permissions(manage_channels=True)
async def test_site(ctx, url=None):
    """Test un site OP.GG pour voir si une partie est détectée"""
    if not url:
        await ctx.send("❌ Veuillez spécifier une URL OP.GG à tester !")
        return

    message = await ctx.send("🔍 Test du site OP.GG en cours...")

    games = await web_monitor.check_site(url)
    
    if not games:
        await message.edit(content="❌ Aucune partie en cours détectée sur ce profil OP.GG.")
        return

    embed = discord.Embed(
        title=f"🎮 Parties détectées ({len(games)})",
        description="Voici les parties en cours trouvées :",
        color=0x00ff00
    )

    for i, game in enumerate(games[:3], 1):  # Limiter à 3 résultats
        embed.add_field(
            name=f"Partie {i}",
            value=f"**{game['title']}**\n"
                  f"Joueur: {game['player']}\n"
                  f"Rang: {game['rank']}\n"
                  f"Niveau: {game['level']}\n"
                  f"[Lien d'observation]({game['url']})",
            inline=False
        )

    await message.edit(content="", embed=embed)

@bot.command(name='lolhelp')
async def lol_help(ctx):
    """Affiche l'aide pour les commandes LoL"""
    embed = discord.Embed(
        title="🎮 Aide du Bot LoL Monitor",
        description="Surveillez les parties LoL en cours sur OP.GG",
        color=0x0596AA
    )
    
    embed.add_field(
        name="!addsite URL [nom]", 
        value="Ajouter un profil OP.GG à surveiller\nExemple: `!addsite https://euw.op.gg/summoner/userName=Faker`", 
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
        value="Tester un profil OP.GG pour voir les parties détectées", 
        inline=False
    )
    embed.add_field(
        name="Réaction 👁️", 
        value="Réagir avec 👁️ sur une notification pour obtenir le lien d'observation en privé", 
        inline=False
    )
    
    embed.set_footer(text="Le bot vérifie les profils toutes les 2 minutes")
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
        print(f"🚀 Démarrage du bot...")
        logger.info("Démarrage du bot Discord LoL Monitor")
        
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
