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
from bs4 import BeautifulSoup
import re
# === Flask (pour Render) ===
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
    intents.reactions = True
    bot = commands.Bot(command_prefix='!', intents=intents)
    bot.remove_command('help')  # Supprime la commande help par défaut pour ajouter la tienne
    # === Twitch credentials ===
    TWITCH_CLIENT_ID = "tejcc6qy12vbclkl2qige9szpfoher"
    TWITCH_CLIENT_SECRET = "18jywkay5xbbo5d2028f4fxwyf0txk"
    # === Stockage des données ===
    streamers = {}
    stream_messages = {}
    ping_roles = {}
    notification_channels = {}
    reaction_role_messages = {}
    # === Nouveaux dictionnaires pour OP.GG ===
    lol_players = {}  # {channel_id: [list of players]}
    lol_game_messages = {}  # {channel_id_playername: message_id}
    lol_ping_roles = {}  # {channel_id: role_id}

class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.token = data['access_token']
                        self.headers = {
                            'Client-ID': TWITCH_CLIENT_ID,
                            'Authorization': f'Bearer {self.token}'
                        }
                        self.token_expires_at = datetime.now(UTC).timestamp() + data.get('expires_in', 3600)
                        logger.info("Token Twitch obtenu avec succès")
                        return True
                    else:
                        logger.error(f"Erreur lors de l'obtention du token Twitch: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Exception lors de l'obtention du token Twitch: {e}")
            return False

    async def ensure_valid_token(self):
        if not self.token or (self.token_expires_at and datetime.now(UTC).timestamp() >= self.token_expires_at - 300):
            await self.get_token()

    async def get_streams(self, usernames):
        if not usernames:
            return []

        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/streams"
        params = {'user_login': usernames}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['data']
                    elif response.status == 401:
                        logger.warning("Token Twitch invalide, renouvellement...")
                        await self.get_token()
                        return await self.get_streams(usernames)
                    else:
                        logger.error(f"Erreur API Twitch streams: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Exception lors de la récupération des streams: {e}")
            return []

    async def get_user_info(self, username):
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/users"
        params = {'login': username}
        logger.info("get_user_info called")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['data'][0] if data['data'] else None
                    elif response.status == 401:
                        logger.warning("Token Twitch invalide, renouvellement...")
                        await self.get_token()
                        return await self.get_user_info(username)
                    else:
                        logger.error(f"Erreur API Twitch user: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Exception lors de la récupération de l'utilisateur: {e}")
            return None
        def __init__(self):
            self.token = None
            self.headers = {}
            self.token_expires_at = None

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.token = data['access_token']
                        self.headers = {
                            'Client-ID': TWITCH_CLIENT_ID,
                            'Authorization': f'Bearer {self.token}'
                        }
                        self.token_expires_at = datetime.now(timezone.utc).timestamp() + data.get('expires_in', 3600)
                        print("Token OK :", self.token)
                        return True
                    else:
                        print("Erreur:", response.status)
                        return False
        except Exception as e:
            print("Exception:", e)
            return False
        async def ensure_valid_token(self):
            if not self.token or (self.token_expires_at and datetime.now(UTC).timestamp() >= self.token_expires_at - 300):
                 pass
            await self.get_token()

            async def get_streams(self, usernames):
                if not usernames:
                     pass
                return []

            await self.ensure_valid_token()
            url = "https://api.twitch.tv/helix/streams"
            params = {'user_login': usernames}

         try:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=self.headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data['data']
            elif response.status == 401:
                logger.warning("Token Twitch invalide, renouvellement...")
                await self.get_token()
                return await self.get_streams(usernames)
            else:
                logger.error(f"Erreur API Twitch streams: {response.status}")
                return []
except Exception as e:
    logger.error(f"Exception lors de la récupération des streams: {e}")
    return []

    async def get_user_info(self, username):
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/users"
        params = {'login': username}
        logger.info("get_user_info called")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['data'][0] if data['data'] else None
                    elif response.status == 401:
                        logger.warning("Token Twitch invalide, renouvellement...")
                        await self.get_token()
                        return await self.get_user_info(username)
                    else:
                        logger.error(f"Erreur API Twitch user: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Exception lors de la récupération de l'utilisateur: {e}")
            return None
        def __init__(self):
            self.token = None
            self.headers = {}
            self.token_expires_at = None

            def __init__(self):
                self.token = None
                self.headers = {}
                self.token_expires_at = None
    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.token = data['access_token']
                        self.headers = {
                            'Client-ID': TWITCH_CLIENT_ID,
                            'Authorization': f'Bearer {self.token}'
                        }
                        self.token_expires_at = datetime.now(timezone.utc).timestamp() + data.get('expires_in', 3600)
                        print("Token OK :", self.token)
                        return True
                    else:
                        print("Erreur:", response.status)
                        return False
        except Exception as e:
            print("Exception:", e)
            return False
            async def ensure_valid_token(self):
                if not self.token or (self.token_expires_at and datetime.now(UTC).timestamp() >= self.token_expires_at - 300):
                     pass
                await self.get_token()
                async def get_streams(self, usernames):
                    if not usernames:
                         pass
                    return []
                await self.ensure_valid_token()
                url = "https://api.twitch.tv/helix/streams"
                params = {'user_login': usernames}
                async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                     pass
                data = await response.json()
                return data['data']
            elif response.status == 401:
                 pass
            logger.warning("Token Twitch invalide, renouvellement...")
            await self.get_token()
            return await self.get_streams(usernames)
        else:
            logger.error(f"Erreur API Twitch streams: {response.status}")
            return []
        except Exception as e:
            logger.error(f"Exception lors de la récupération des streams: {e}")
            return []
    async def get_user_info(self, username):
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/users"
        params = {'login': username}
        logger.info("get_user_info called")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['data'][0] if data['data'] else None
                    elif response.status == 401:
                        logger.warning("Token Twitch invalide, renouvellement...")
                        await self.get_token()
                        return await self.get_user_info(username)
                    else:
                        logger.error(f"Erreur API Twitch user: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Exception lors de la récupération de l'utilisateur: {e}")
            return None
    class OpGGAPI:
        def __init__(self):
            self.session = None
            self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        async def get_session(self):
            if not self.session:
                 pass
            self.session = aiohttp.ClientSession(headers=self.headers)
            return self.session
        async def close_session(self):
            if self.session:
                 pass
            await self.session.close()
            self.session = None
            async def check_player_ingame(self, summoner_name, region='euw'):
                """Vérifie si un joueur est en game sur op.gg"""
                try:
                    session = await self.get_session()
                    # Nettoyer le nom du joueur
                    clean_name = summoner_name.replace(' ', '%20')
                    url = f"https://op.gg/summoners/{region}/{clean_name}"

                    async with session.get(url) as response:
                    if response.status == 200:
                         pass
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Chercher les indicateurs de partie en cours
                    # Op.gg affiche "Live Game" ou "En direct" quand quelqu'un est en game
                    live_indicators = [
                    'Live Game',
                    'En direct',
                    'live-game',
                    'spectate',
                    'In Game'
                    ]

                    for indicator in live_indicators:
                    if indicator.lower() in html.lower():
                         pass
                    # Extraire plus d'informations sur la partie
                    game_info = await self.extract_game_info(html, summoner_name)
                    return game_info

                return None
            else:
                logger.warning(f"Erreur {response.status} pour {summoner_name}")
                return None

            except Exception as e:
                logger.error(f"Erreur lors de la vérification de {summoner_name}: {e}")
                return None
            async def extract_game_info(self, html, summoner_name):
                """Extrait les informations de la partie en cours"""
                try:
                    soup = BeautifulSoup(html, 'html.parser')

                    game_info = {
                    'player': summoner_name,
                    'is_live': True,
                    'game_mode': 'Partie classée',  # Par défaut
                    'champion': 'Inconnu',
                    'rank': 'Inconnu',
                    'spectate_url': f"https://op.gg/summoners/euw/{summoner_name.replace(' ', '%20')}"
                }

                # Essayer d'extraire le champion joué
                champion_img = soup.find('img', {'class': re.compile(r'champion|Champion')})
                if champion_img and champion_img.get('alt'):
                     pass
                game_info['champion'] = champion_img['alt']

                # Essayer d'extraire le rang
                rank_element = soup.find('div', {'class': re.compile(r'tier|Tier|rank|Rank')})
                if rank_element:
                     pass
                game_info['rank'] = rank_element.get_text(strip=True)

                return game_info

            except Exception as e:
                logger.error(f"Erreur lors de l'extraction des infos de partie: {e}")
                return {
            'player': summoner_name,
            'is_live': True,
            'game_mode': 'Partie en cours',
            'champion': 'Inconnu',
            'rank': 'Inconnu',
            'spectate_url': f"https://op.gg/summoners/euw/{summoner_name.replace(' ', '%20')}"
        }
        async def validate_summoner(self, summoner_name, region='euw'):
            """Valide qu'un nom d'invocateur existe"""
            try:
                session = await self.get_session()
                clean_name = summoner_name.replace(' ', '%20')
                url = f"https://op.gg/summoners/{region}/{clean_name}"

                async with session.get(url) as response:
                if response.status == 200:
                     pass
                html = await response.text()
                # Vérifier si la page contient des informations de joueur
                if 'summoner not found' not in html.lower() and 'niveau' in html.lower():
                     pass
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur lors de la validation de {summoner_name}: {e}")
            return False
        twitch_api = TwitchAPI()
        opgg_api = OpGGAPI()
        async def on_ready():
            print(f'{bot.user} est connecté et prêt !')
            await twitch_api.get_token()
            if not check_streams.is_running():
                 pass
            check_streams.start()
            if not check_lol_games.is_running():
                 pass
            check_lol_games.start()
            @tasks.loop(minutes=1)
            async def check_streams():
                for channel_id, streamer_list in streamers.items():
                if not streamer_list:
                     pass
                continue
            channel = bot.get_channel(channel_id)
            if not channel:
                 pass
            logger.warning(f"Channel {channel_id} non trouvé")
            continue
        streams = await twitch_api.get_streams(streamer_list)
        currently_live = {stream['user_login'].lower() for stream in streams}
        for stream in streams:
             pass
        username = stream['user_login'].lower()
        message_key = f"{channel_id}_{username}"
        if message_key not in stream_messages:
             pass
        await send_stream_notification(channel, stream)
        to_remove = []
        for message_key, message_id in stream_messages.items():
        if message_key.startswith(f"{channel_id}_"):
             pass
        username = message_key.split('_', 1)[1]
        if username not in currently_live:
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
            to_remove.append(message_key)
            except discord.NotFound:
                to_remove.append(message_key)
                except discord.Forbidden:
                    logger.warning(f"Pas de permission pour supprimer le message de {username}")
                    to_remove.append(message_key)
                    except Exception as e:
                        logger.error(f"Erreur lors de la suppression du message: {e}")
                        to_remove.append(message_key)
                        for message_key in to_remove:
                             pass
                        stream_messages.pop(message_key, None)
                        logger.error(f"Erreur dans check_streams: {e}")
                        @tasks.loop(minutes=2)  # Vérifier toutes les 2 minutes pour éviter de spam op.gg
                        async def check_lol_games():
                            """Vérifie les parties LoL en cours"""
                            for channel_id, player_list in lol_players.items():
                            if not player_list:
                                 pass
                            continue
                        channel = bot.get_channel(channel_id)
                        if not channel:
                             pass
                        logger.warning(f"Channel {channel_id} non trouvé")
                        continue
                    currently_ingame = set()
                    for player in player_list:
                         pass
                    game_info = await opgg_api.check_player_ingame(player)
                    if game_info:
                         pass
                    currently_ingame.add(player.lower())
                    message_key = f"{channel_id}_{player.lower()}"

                    if message_key not in lol_game_messages:
                         pass
                    await send_lol_game_notification(channel, game_info)
                    # Supprimer les messages des parties terminées
                    to_remove = []
                    for message_key, message_id in lol_game_messages.items():
                    if message_key.startswith(f"{channel_id}_"):
                         pass
                    player = message_key.split('_', 1)[1]
                    if player not in currently_ingame:
                    try:
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        to_remove.append(message_key)
                        except discord.NotFound:
                            to_remove.append(message_key)
                            except discord.Forbidden:
                                logger.warning(f"Pas de permission pour supprimer le message de {player}")
                                to_remove.append(message_key)
                                except Exception as e:
                                    logger.error(f"Erreur lors de la suppression du message: {e}")
                                    to_remove.append(message_key)
                                    for message_key in to_remove:
                                         pass
                                    lol_game_messages.pop(message_key, None)
                                    except Exception as e:
                                        logger.error(f"Erreur dans check_lol_games: {e}")
                                        @check_streams.before_loop
                                        async def before_check_streams():
                                            await bot.wait_until_ready()
                                            @check_lol_games.before_loop
                                            async def before_check_lol_games():
                                                await bot.wait_until_ready()
                                                async def send_stream_notification(channel, stream):
                                                    try:
                                                        username = stream['user_login']
                                                        game_name = stream['game_name'] or "Pas de catégorie"
                                                        viewer_count = stream['viewer_count']
                                                        title = stream['title'] or "Pas de titre"
                                                        embed = discord.Embed(
                                                        title=f"🔴 {stream['user_name']} est en live !",
                                                        description=f"**{title}**",
                                                        color=0x9146ff,
                                                        url=f"https://twitch.tv/{username}"
                                                        )
                                                        embed.add_field(name="🎮 Catégorie", value=game_name, inline=True)
                                                        embed.add_field(name="👥 Viewers", value=f"{viewer_count:,}", inline=True)
                                                        embed.add_field(name="🔗 Lien", value=f"[Regarder le stream](https://twitch.tv/{username})", inline=False)
                                                        if stream.get('thumbnail_url'):
                                                             pass
                                                        thumbnail = stream['thumbnail_url'].replace('{width}', '320').replace('{height}', '180')
                                                        embed.set_image(url=thumbnail)
                                                        embed.timestamp = datetime.now(UTC)
                                                        content = ""
                                                        if channel.id in ping_roles:
                                                             pass
                                                        role = channel.guild.get_role(ping_roles[channel.id])
                                                        if role:
                                                             pass
                                                        content = f"{role.mention} "
                                                        message = await channel.send(content=content, embed=embed)
                                                        message_key = f"{channel.id}_{username.lower()}"
                                                        stream_messages[message_key] = message.id
                                                        logger.info(f"Notification envoyée pour {username} dans {channel.name}")
                                                        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
                                                        except Exception as e:
                                                            logger.error(f"Erreur lors de l'envoi de la notification: {e}")
                                                            async def send_lol_game_notification(channel, game_info):
                                                                """Envoie une notification pour une partie LoL"""
                                                                try:
                                                                    player = game_info['player']
                                                                    champion = game_info['champion']
                                                                    rank = game_info['rank']
                                                                    spectate_url = game_info['spectate_url']
                                                                    embed = discord.Embed(
                                                                    title=f"🎮 {player} est en partie !",
                                                                    description=f"**{champion}** • {rank}",
                                                                    color=0x0f2027,
                                                                    url=spectate_url
                                                                    )
                                                                    embed.add_field(name="🏆 Champion", value=champion, inline=True)
                                                                    embed.add_field(name="📊 Rang", value=rank, inline=True)
                                                                    embed.add_field(name="👁️ Spectate", value=f"[Regarder la partie]({spectate_url})", inline=False)
                                                                    embed.timestamp = datetime.now(UTC)
                                                                    embed.set_footer(text="League of Legends • OP.GG")
                                                                    content = ""
                                                                    if channel.id in lol_ping_roles:
                                                                         pass
                                                                    role = channel.guild.get_role(lol_ping_roles[channel.id])
                                                                    if role:
                                                                         pass
                                                                    content = f"{role.mention} "
                                                                    message = await channel.send(content=content, embed=embed)
                                                                    # Ajouter une réaction pour accès rapide
                                                                    await message.add_reaction("👁️")
                                                                    message_key = f"{channel.id}_{player.lower()}"
                                                                    lol_game_messages[message_key] = message.id
                                                                    logger.info(f"Notification LoL envoyée pour {player} dans {channel.name}")
                                                                    except discord.Forbidden:
                                                                        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
                                                                        except Exception as e:
                                                                            logger.error(f"Erreur lors de l'envoi de la notification LoL: {e}")
                                                                            async def delete_command_messages(ctx, response_message=None):
                                                                                """Supprime le message de commande et la réponse du bot après un délai"""
                                                                                try:
                                                                                    await asyncio.sleep(5)
                                                                                    if ctx.message:
                                                                                         pass
                                                                                    await ctx.message.delete()
                                                                                    if response_message:
                                                                                         pass
                                                                                    await response_message.delete()
                                                                                    except discord.NotFound:
                                                                                        except discord.Forbidden:
                                                                                            pass
                                                                                        # === Commandes LoL ===
                                                                                        try:
                                                                                             pass





                                                                                            # === Commandes Twitch existantes ===






















                                                                                            try:
                                                                                                 pass










                                                                                                try:
                                                                                                    pass










                                                                                                try:
                                                                                                    except Exception as e:
                                                                                                         pass








                                                                                                        try:
                                                                                                            except discord.Forbidden:
                                                                                                                except Exception as e:
                                                                                                                     pass





                                                                                                                    @bot.event

                                                                                                                    # === Lancement ===

                                                                                                                    # === Commandes ===
                                                                                                                    @bot.command(name='addlol')
                                                                                                                    @commands.has_permissions(manage_channels=True)
                                                                                                                    async def add_lol_player(ctx, summoner_name=None, region='euw'):
                                                                                                                        """Ajoute un joueur LoL à surveiller"""
                                                                                                                        if summoner_name is None:
                                                                                                                             pass
                                                                                                                        response = await ctx.send("❌ Veuillez spécifier un nom d'invocateur !\nExemple: `!addlol Faker`")
                                                                                                                        asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                                        return

                                                                                                                    channel_id = ctx.channel.id
                                                                                                                    summoner_name = summoner_name.strip()

                                                                                                                    if not summoner_name:
                                                                                                                         pass
                                                                                                                    response = await ctx.send("❌ Nom d'invocateur invalide !")
                                                                                                                    asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                                    return

                                                                                                                if channel_id not in lol_players:
                                                                                                                     pass
                                                                                                                lol_players[channel_id] = []

                                                                                                                if summoner_name.lower() in [p.lower() for p in lol_players[channel_id]]:
                                                                                                                     pass
                                                                                                                response = await ctx.send(f"❌ {summoner_name} est déjà dans la liste !")
                                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                                return

                                                                                                            # Valider que le joueur existe
                                                                                                            if not await opgg_api.validate_summoner(summoner_name, region):
                                                                                                                 pass
                                                                                                            response = await ctx.send(f"❌ Le joueur {summoner_name} n'existe pas sur {region.upper()} !")
                                                                                                            asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                            return

                                                                                                        lol_players[channel_id].append(summoner_name)
                                                                                                        response = await ctx.send(f"✅ {summoner_name} ajouté à la liste des joueurs LoL surveillés !")
                                                                                                        asyncio.create_task(delete_command_messages(ctx, response))


                                                                                                        @bot.command(name='removelol')
                                                                                                        @commands.has_permissions(manage_channels=True)
                                                                                                        async def remove_lol_player(ctx, summoner_name=None):
                                                                                                            """Retire un joueur LoL de la surveillance"""
                                                                                                            if summoner_name is None:
                                                                                                                 pass
                                                                                                            response = await ctx.send("❌ Veuillez spécifier un nom d'invocateur !")
                                                                                                            asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                            return

                                                                                                        channel_id = ctx.channel.id
                                                                                                        summoner_name = summoner_name.strip()

                                                                                                        if channel_id not in lol_players:
                                                                                                             pass
                                                                                                        response = await ctx.send("❌ Aucun joueur LoL surveillé dans ce channel !")
                                                                                                        asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                        return

                                                                                                    # Chercher le joueur (insensible à la casse)
                                                                                                    player_to_remove = None
                                                                                                    for player in lol_players[channel_id]:
                                                                                                    if player.lower() == summoner_name.lower():
                                                                                                         pass
                                                                                                    player_to_remove = player
                                                                                                    break

                                                                                                if not player_to_remove:
                                                                                                     pass
                                                                                                response = await ctx.send(f"❌ {summoner_name} n'est pas dans la liste !")
                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                return

                                                                                            lol_players[channel_id].remove(player_to_remove)

                                                                                            # Supprimer le message de notification s'il existe
                                                                                            message_key = f"{channel_id}_{summoner_name.lower()}"
                                                                                            if message_key in lol_game_messages:
                                                                                            try:
                                                                                                message = await ctx.channel.fetch_message(lol_game_messages[message_key])
                                                                                                await message.delete()
                                                                                                except:
                                                                                                    pass
                                                                                                finally:
                                                                                                    lol_game_messages.pop(message_key, None)

                                                                                                    response = await ctx.send(f"✅ {player_to_remove} retiré de la liste des joueurs LoL surveillés !")
                                                                                                    asyncio.create_task(delete_command_messages(ctx, response))


                                                                                                    @bot.command(name='listlol')
                                                                                                    async def list_lol_players(ctx):
                                                                                                        """Affiche la liste des joueurs LoL surveillés"""
                                                                                                        channel_id = ctx.channel.id

                                                                                                        if channel_id not in lol_players or not lol_players[channel_id]:
                                                                                                             pass
                                                                                                        await ctx.send("📋 Aucun joueur LoL surveillé dans ce channel !")
                                                                                                        return

                                                                                                    embed = discord.Embed(
                                                                                                    title="📋 Joueurs LoL surveillés",
                                                                                                    description="\n".join(f"• {player}" for player in lol_players[channel_id]),
                                                                                                    color=0x0f2027
                                                                                                    )
                                                                                                    embed.set_footer(text="League of Legends • OP.GG")
                                                                                                    await ctx.send(embed=embed)


                                                                                                    @bot.command(name='lolping')
                                                                                                    @commands.has_permissions(manage_roles=True)
                                                                                                    async def set_lol_ping_role(ctx, role: discord.Role = None):
                                                                                                        """Définit le rôle à ping pour les notifications LoL"""
                                                                                                        channel_id = ctx.channel.id

                                                                                                        if role is None:
                                                                                                        if channel_id in lol_ping_roles:
                                                                                                             pass
                                                                                                        del lol_ping_roles[channel_id]
                                                                                                        await ctx.send("✅ Rôle de ping LoL désactivé pour ce channel !")
                                                                                                        return

                                                                                                    lol_ping_roles[channel_id] = role.id
                                                                                                    await ctx.send(f"✅ Le rôle {role.mention} sera ping lors des notifications LoL !")


                                                                                                    @bot.command(name='addstreamer')
                                                                                                    @commands.has_permissions(manage_channels=True)
                                                                                                    async def add_streamer(ctx, username=None):
                                                                                                        if username is None:
                                                                                                             pass
                                                                                                        response = await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
                                                                                                        asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                        return

                                                                                                    channel_id = ctx.channel.id
                                                                                                    username = username.lower().replace('@', '').strip()

                                                                                                    if not username:
                                                                                                         pass
                                                                                                    response = await ctx.send("❌ Nom d'utilisateur invalide !")
                                                                                                    asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                    return

                                                                                                if channel_id not in streamers:
                                                                                                     pass
                                                                                                streamers[channel_id] = []

                                                                                                if username in streamers[channel_id]:
                                                                                                     pass
                                                                                                response = await ctx.send(f"❌ {username} est déjà dans la liste !")
                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                return

                                                                                            user_info = await twitch_api.get_user_info(username)
                                                                                            if not user_info:
                                                                                                 pass
                                                                                            response = await ctx.send(f"❌ Le streamer {username} n'existe pas sur Twitch !")
                                                                                            asyncio.create_task(delete_command_messages(ctx, response))
                                                                                            return

                                                                                        streamers[channel_id].append(username)
                                                                                        response = await ctx.send(f"✅ {username} ajouté à la liste des streamers surveillés !")
                                                                                        asyncio.create_task(delete_command_messages(ctx, response))


                                                                                        @bot.command(name='addstreamers')
                                                                                        @commands.has_permissions(manage_channels=True)
                                                                                        async def add_streamers(ctx, *usernames):
                                                                                            if not usernames:
                                                                                                 pass
                                                                                            response = await ctx.send("❌ Veuillez spécifier au moins un nom d'utilisateur Twitch !\nExemple: `!addstreamers streamer1 streamer2 streamer3`")
                                                                                            asyncio.create_task(delete_command_messages(ctx, response))
                                                                                            return

                                                                                        channel_id = ctx.channel.id
                                                                                        if channel_id not in streamers:
                                                                                             pass
                                                                                        streamers[channel_id] = []

                                                                                        added_streamers = []
                                                                                        already_exists = []
                                                                                        invalid_streamers = []

                                                                                        for username in usernames:
                                                                                             pass
                                                                                        username = username.lower().replace('@', '').strip()

                                                                                        if not username:
                                                                                             pass
                                                                                        continue

                                                                                    if username in streamers[channel_id]:
                                                                                         pass
                                                                                    already_exists.append(username)
                                                                                    continue

                                                                                user_info = await twitch_api.get_user_info(username)
                                                                                if not user_info:
                                                                                     pass
                                                                                invalid_streamers.append(username)
                                                                                continue

                                                                            streamers[channel_id].append(username)
                                                                            added_streamers.append(username)

                                                                            message_parts = []

                                                                            if added_streamers:
                                                                                 pass
                                                                            message_parts.append(f"✅ **Streamers ajoutés:** {', '.join(added_streamers)}")

                                                                            if already_exists:
                                                                                 pass
                                                                            message_parts.append(f"⚠️ **Déjà dans la liste:** {', '.join(already_exists)}")

                                                                            if invalid_streamers:
                                                                                 pass
                                                                            message_parts.append(f"❌ **Streamers introuvables:** {', '.join(invalid_streamers)}")

                                                                            if not message_parts:
                                                                                 pass
                                                                            message_parts.append("❌ Aucun streamer valide fourni !")

                                                                            response = await ctx.send("\n".join(message_parts))
                                                                            asyncio.create_task(delete_command_messages(ctx, response))


                                                                            @bot.command(name='removestreamer')
                                                                            @commands.has_permissions(manage_channels=True)
                                                                            async def remove_streamer(ctx, username=None):
                                                                                if username is None:
                                                                                     pass
                                                                                response = await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                return

                                                                            channel_id = ctx.channel.id
                                                                            username = username.lower().replace('@', '').strip()

                                                                            if channel_id not in streamers or username not in streamers[channel_id]:
                                                                                 pass
                                                                            response = await ctx.send(f"❌ {username} n'est pas dans la liste !")
                                                                            asyncio.create_task(delete_command_messages(ctx, response))
                                                                            return

                                                                        streamers[channel_id].remove(username)

                                                                        message_key = f"{channel_id}_{username}"
                                                                        if message_key in stream_messages:
                                                                        try:
                                                                            message = await ctx.channel.fetch_message(stream_messages[message_key])
                                                                            await message.delete()
                                                                            except:
                                                                                pass
                                                                            finally:
                                                                                stream_messages.pop(message_key, None)

                                                                                response = await ctx.send(f"✅ {username} retiré de la liste des streamers surveillés !")
                                                                                asyncio.create_task(delete_command_messages(ctx, response))


                                                                                @bot.command(name='liststreamer')
                                                                                async def list_streamers(ctx):
                                                                                    channel_id = ctx.channel.id

                                                                                    if channel_id not in streamers or not streamers[channel_id]:
                                                                                         pass
                                                                                    await ctx.send("📋 Aucun streamer surveillé dans ce channel !")
                                                                                    return

                                                                                embed = discord.Embed(
                                                                                title="📋 Streamers surveillés",
                                                                                description="\n".join(f"• {streamer}" for streamer in streamers[channel_id]),
                                                                                color=0x9146ff
                                                                                )
                                                                                await ctx.send(embed=embed)


                                                                                @bot.command(name='pingrole')
                                                                                @commands.has_permissions(manage_roles=True)
                                                                                async def set_ping_role(ctx, role: discord.Role = None):
                                                                                    channel_id = ctx.channel.id

                                                                                    if role is None:
                                                                                    if channel_id in ping_roles:
                                                                                         pass
                                                                                    del ping_roles[channel_id]
                                                                                    await ctx.send("✅ Rôle de ping Twitch désactivé pour ce channel !")
                                                                                    return

                                                                                ping_roles[channel_id] = role.id
                                                                                await ctx.send(f"✅ Le rôle {role.mention} sera ping lors des notifications Twitch !")


                                                                                @bot.command(name='reactionrole')
                                                                                @commands.has_permissions(manage_roles=True)
                                                                                async def create_reaction_role(ctx, role: discord.Role = None, emoji: str = "🔔"):
                                                                                    """Crée un message sur lequel les utilisateurs peuvent réagir pour obtenir un rôle"""
                                                                                    if role is None:
                                                                                         pass
                                                                                    await ctx.send("❌ Veuillez spécifier un rôle !\nExemple: `!reactionrole @Notifications 🔔`")
                                                                                    return

                                                                                # Créer l'embed pour le message de réaction
                                                                                embed = discord.Embed(
                                                                                title="🎯 Rôle par Réaction",
                                                                                description=f"Réagissez avec {emoji} pour obtenir le rôle **{role.name}**\n\nRéagissez à nouveau pour retirer le rôle.",
                                                                                color=0x9146ff
                                                                                )
                                                                                embed.add_field(name="Rôle", value=role.mention, inline=True)
                                                                                embed.add_field(name="Emoji", value=emoji, inline=True)
                                                                                embed.set_footer(text="Système de rôles automatique")

                                                                                # Supprimer le message de commande
                                                                                try:
                                                                                    await ctx.message.delete()
                                                                                    except:
                                                                                        pass

                                                                                    # Envoyer le message et ajouter la réaction
                                                                                    message = await ctx.send(embed=embed)
                                                                                    await message.add_reaction(emoji)

                                                                                    # Stocker les informations pour le système de réaction
                                                                                    reaction_role_messages[message.id] = {
                                                                                    'role_id': role.id,
                                                                                    'emoji': emoji,
                                                                                    'guild_id': ctx.guild.id
                                                                                }

                                                                                logger.info(f"Message de réaction créé pour le rôle {role.name} avec l'emoji {emoji}")

                                                                                @bot.event
                                                                                async def on_reaction_add(reaction, user):
                                                                                    """Gère l'ajout de réactions pour donner des rôles et accès rapide aux liens"""
                                                                                    if user.bot:
                                                                                         pass
                                                                                    return

                                                                                # Système de rôles par réaction
                                                                                message_id = reaction.message.id
                                                                                if message_id in reaction_role_messages:
                                                                                     pass
                                                                                role_data = reaction_role_messages[message_id]

                                                                                # Vérifier si c'est le bon emoji
                                                                                if str(reaction.emoji) != role_data['emoji']:
                                                                                     pass
                                                                                return

                                                                            # Récupérer le rôle et l'utilisateur
                                                                            guild = bot.get_guild(role_data['guild_id'])
                                                                            if not guild:
                                                                                 pass
                                                                            return

                                                                        role = guild.get_role(role_data['role_id'])
                                                                        member = guild.get_member(user.id)

                                                                        if not role or not member:
                                                                             pass
                                                                        return

                                                                    # Ajouter le rôle
                                                                    try:
                                                                        await member.add_roles(role)
                                                                        logger.info(f"Rôle {role.name} ajouté à {member.name}")
                                                                        except discord.Forbidden:
                                                                            logger.error(f"Pas de permission pour ajouter le rôle {role.name} à {member.name}")
                                                                            except Exception as e:
                                                                                logger.error(f"Erreur lors de l'ajout du rôle: {e}")
                                                                                return

                                                                            # Gestion des réactions sur les messages LoL (accès rapide au spectate)
                                                                            if str(reaction.emoji) == "👁️":
                                                                                 pass
                                                                            # Vérifier si c'est un message de notification LoL
                                                                            for message_key, stored_message_id in lol_game_messages.items():
                                                                            if stored_message_id == message_id:
                                                                                 pass
                                                                            # Extraire le nom du joueur
                                                                            player_name = message_key.split('_', 1)[1]
                                                                            spectate_url = f"https://op.gg/summoners/euw/{player_name.replace(' ', '%20')}"

                                                                            try:
                                                                                # Envoyer le lien en message privé
                                                                                await user.send(f"🎮 **Lien direct pour spectater {player_name}:**\n{spectate_url}")
                                                                                except discord.Forbidden:
                                                                                    # Si impossible d'envoyer en MP, envoyer dans le channel
                                                                                    await reaction.message.channel.send(f"{user.mention} 🎮 **Lien pour spectater {player_name}:** {spectate_url}", delete_after=30)
                                                                                    except Exception as e:
                                                                                        logger.error(f"Erreur lors de l'envoi du lien spectate: {e}")
                                                                                        break

                                                                                    @bot.event
                                                                                    async def on_reaction_remove(reaction, user):
                                                                                        """Gère la suppression de réactions pour retirer des rôles"""
                                                                                        if user.bot:
                                                                                             pass
                                                                                        return

                                                                                    message_id = reaction.message.id
                                                                                    if message_id not in reaction_role_messages:
                                                                                         pass
                                                                                    return

                                                                                role_data = reaction_role_messages[message_id]

                                                                                # Vérifier si c'est le bon emoji
                                                                                if str(reaction.emoji) != role_data['emoji']:
                                                                                     pass
                                                                                return

                                                                            # Récupérer le rôle et l'utilisateur
                                                                            guild = bot.get_guild(role_data['guild_id'])
                                                                            if not guild:
                                                                                 pass
                                                                            return

                                                                        role = guild.get_role(role_data['role_id'])
                                                                        member = guild.get_member(user.id)

                                                                        if not role or not member:
                                                                             pass
                                                                        return

                                                                    # Retirer le rôle
                                                                    try:
                                                                        await member.remove_roles(role)
                                                                        logger.info(f"Rôle {role.name} retiré de {member.name}")
                                                                        except discord.Forbidden:
                                                                            logger.error(f"Pas de permission pour retirer le rôle {role.name} de {member.name}")
                                                                            except Exception as e:
                                                                                logger.error(f"Erreur lors du retrait du rôle: {e}")


                                                                                @bot.command(name='help')
                                                                                async def bot_help(ctx):
                                                                                    """Affiche toutes les commandes disponibles"""
                                                                                    embed = discord.Embed(
                                                                                    title="🤖 Aide du Bot Multi-Fonctions",
                                                                                    description="Toutes les commandes disponibles :",
                                                                                    color=0x00ff00
                                                                                    )

                                                                                    # Commandes Twitch
                                                                                    embed.add_field(
                                                                                    name="📺 **Commandes Twitch**",
                                                                                    value=(
                                                                                    "`!addstreamer <username>` - Ajouter un streamer\n"
                                                                                    "`!addstreamers <user1> <user2> ...` - Ajouter plusieurs streamers\n"
                                                                                    "`!removestreamer <username>` - Retirer un streamer\n"
                                                                                    "`!liststreamer` - Afficher les streamers surveillés\n"
                                                                                    "`!pingrole [@role]` - Définir le rôle à ping Twitch"
                                                                                    ),
                                                                                    inline=False
                                                                                    )

                                                                                    # Commandes LoL
                                                                                    embed.add_field(
                                                                                    name="🎮 **Commandes League of Legends**",
                                                                                    value=(
                                                                                    "`!addlol <summoner>` - Ajouter un joueur LoL\n"
                                                                                    "`!removelol <summoner>` - Retirer un joueur LoL\n"
                                                                                    "`!listlol` - Afficher les joueurs LoL surveillés\n"
                                                                                    "`!lolping [@role]` - Définir le rôle à ping LoL"
                                                                                    ),
                                                                                    inline=False
                                                                                    )

                                                                                    # Commandes générales
                                                                                    embed.add_field(
                                                                                    name="⚙️ **Commandes Générales**",
                                                                                    value=(
                                                                                    "`!reactionrole [@role] [emoji]` - Créer un rôle par réaction\n"
                                                                                    "`!help` - Afficher cette aide"
                                                                                    ),
                                                                                    inline=False
                                                                                    )

                                                                                    embed.add_field(
                                                                                    name="ℹ️ **Informations**",
                                                                                    value=(
                                                                                    "• Les notifications LoL incluent une réaction 👁️ pour un accès rapide au spectate\n"
                                                                                    "• Les commandes de gestion s'auto-suppriment après 5 secondes\n"
                                                                                    "• Vérification Twitch: chaque minute\n"
                                                                                    "• Vérification LoL: toutes les 2 minutes"
                                                                                    ),
                                                                                    inline=False
                                                                                    )

                                                                                    embed.set_footer(text="Bot créé pour surveiller Twitch et League of Legends")
                                                                                    await ctx.send(embed=embed)


                                                                                    @bot.command(name='streamhelp')
                                                                                    async def stream_help(ctx):
                                                                                        """Aide spécifique pour les commandes Twitch (rétrocompatibilité)"""
                                                                                        embed = discord.Embed(
                                                                                        title="📺 Aide Twitch",
                                                                                        description="Commandes Twitch disponibles :",
                                                                                        color=0x9146ff
                                                                                        )
                                                                                        embed.add_field(name="!addstreamer <username>", value="Ajouter un streamer à surveiller", inline=False)
                                                                                        embed.add_field(name="!addstreamers <user1> <user2> ...", value="Ajouter plusieurs streamers d'un coup", inline=False)
                                                                                        embed.add_field(name="!removestreamer <username>", value="Retirer un streamer de la surveillance", inline=False)
                                                                                        embed.add_field(name="!liststreamer", value="Afficher la liste des streamers surveillés", inline=False)
                                                                                        embed.add_field(name="!pingrole [@role]", value="Définir le rôle à ping (sans rôle = désactiver)", inline=False)
                                                                                        embed.set_footer(text="Les commandes addstreamer et removestreamer s'auto-suppriment après 5 secondes")
                                                                                        await ctx.send(embed=embed)


                                                                                        @bot.command(name='lolhelp')
                                                                                        async def lol_help(ctx):
                                                                                            """Aide spécifique pour les commandes LoL"""
                                                                                            embed = discord.Embed(
                                                                                            title="🎮 Aide League of Legends",
                                                                                            description="Commandes LoL disponibles :",
                                                                                            color=0x0f2027
                                                                                            )
                                                                                            embed.add_field(name="!addlol <summoner>", value="Ajouter un joueur LoL à surveiller", inline=False)
                                                                                            embed.add_field(name="!removelol <summoner>", value="Retirer un joueur LoL de la surveillance", inline=False)
                                                                                            embed.add_field(name="!listlol", value="Afficher la liste des joueurs LoL surveillés", inline=False)
                                                                                            embed.add_field(name="!lolping [@role]", value="Définir le rôle à ping LoL (sans rôle = désactiver)", inline=False)
                                                                                            embed.add_field(
                                                                                            name="ℹ️ **Fonctionnalités**",
                                                                                            value=(
                                                                                            "• Surveillance via OP.GG\n"
                                                                                            "• Notifications avec réaction 👁️ pour spectate rapide\n"
                                                                                            "• Région par défaut: EUW\n"
                                                                                            "• Vérification toutes les 2 minutes"
                                                                                            ),
                                                                                            inline=False
                                                                                            )
                                                                                            embed.set_footer(text="Les commandes s'auto-suppriment après 5 secondes")
                                                                                            await ctx.send(embed=embed)

                                                                                            @bot.event
                                                                                            async def on_command_error(ctx, error):
                                                                                                if isinstance(error, commands.MissingPermissions):
                                                                                                     pass
                                                                                                response = await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
                                                                                                if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers', 'addlol', 'removelol']:
                                                                                                     pass
                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                elif isinstance(error, commands.BadArgument):
                                                                                                     pass
                                                                                                response = await ctx.send("❌ Argument invalide ! Utilisez `!help` pour voir les commandes.")
                                                                                                if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers', 'addlol', 'removelol']:
                                                                                                     pass
                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                elif isinstance(error, commands.MissingRequiredArgument):
                                                                                                     pass
                                                                                                response = await ctx.send("❌ Argument manquant ! Utilisez `!help` pour voir les commandes.")
                                                                                                if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers', 'addlol', 'removelol']:
                                                                                                     pass
                                                                                                asyncio.create_task(delete_command_messages(ctx, response))
                                                                                                else:
                                                                                                    logger.error(f"Erreur non gérée: {error}")

                                                                                                    @bot.event
                                                                                                    async def on_disconnect():
                                                                                                        if check_streams.is_running():
                                                                                                             pass
                                                                                                        check_streams.cancel()
                                                                                                        if check_lol_games.is_running():
                                                                                                             pass
                                                                                                        check_lol_games.cancel()
                                                                                                        await opgg_api.close_session()


                                                                                                        if __name__ == "__main__":
                                                                                                             pass
                                                                                                        Thread(target=run_flask).start()
                                                                                                        token = os.getenv("DISCORD_BOT_TOKEN")
                                                                                                        if not token:
                                                                                                             pass
                                                                                                        print("❌ Le token Discord est manquant !")
                                                                                                        else:
                                                                                                            try:
                                                                                                                print(f"🚀 Connexion avec le token: {token[:10]}...")
                                                                                                                bot.run(token)
                                                                                                                except discord.errors.LoginFailure:
                                                                                                                    print("❌ Token Discord invalide !")
                                                                                                                    except Exception as e:
                                                                                                                        logger.error(f"Erreur lors du lancement du bot: {e}")
                                                                                                                        finally:
                                                                                                                            # Nettoyage des sessions
                                                                                                                            asyncio.run(opgg_api.close_session())
