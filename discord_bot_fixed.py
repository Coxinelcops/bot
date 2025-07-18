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

bot = commands.Bot(command_prefix='!', intents=intents)

# === Twitch credentials (devraient être des variables d'environnement en prod) ===
TWITCH_CLIENT_ID = "tejcc6qy12vbclkl2qige9szpfoher"
TWITCH_CLIENT_SECRET = "18jywkay5xbbo5d2028f4fxwyf0txk"

streamers = {}
stream_messages = {}
ping_roles = {}
notification_channels = {}

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

twitch_api = TwitchAPI()

@bot.event
async def on_ready():
    print(f'{bot.user} est connecté et prêt !')
    await twitch_api.get_token()
    if not check_streams.is_running():
        check_streams.start()

@tasks.loop(minutes=1)
async def check_streams():
    try:
        for channel_id, streamer_list in streamers.items():
            if not streamer_list:
                continue

            channel = bot.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} non trouvé")
                continue

            streams = await twitch_api.get_streams(streamer_list)
            currently_live = {stream['user_login'].lower() for stream in streams}

            for stream in streams:
                username = stream['user_login'].lower()
                message_key = f"{channel_id}_{username}"

                if message_key not in stream_messages:
                    await send_stream_notification(channel, stream)

            to_remove = []
            for message_key, message_id in stream_messages.items():
                if message_key.startswith(f"{channel_id}_"):
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
                stream_messages.pop(message_key, None)

    except Exception as e:
        logger.error(f"Erreur dans check_streams: {e}")

@check_streams.before_loop
async def before_check_streams():
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
            thumbnail = stream['thumbnail_url'].replace('{width}', '320').replace('{height}', '180')
            embed.set_image(url=thumbnail)

        embed.timestamp = datetime.now(UTC)

        content = ""
        if channel.id in ping_roles:
            role = channel.guild.get_role(ping_roles[channel.id])
            if role:
                content = f"{role.mention} "

        message = await channel.send(content=content, embed=embed)
        message_key = f"{channel.id}_{username.lower()}"
        stream_messages[message_key] = message.id

        logger.info(f"Notification envoyée pour {username} dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}")

@bot.command(name='addstreamer')
@commands.has_permissions(manage_channels=True)
async def add_streamer(ctx, username=None):
    if username is None:
        await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
        return

    channel_id = ctx.channel.id
    username = username.lower().replace('@', '').strip()

    if not username:
        await ctx.send("❌ Nom d'utilisateur invalide !")
        return

    if channel_id not in streamers:
        streamers[channel_id] = []

    if username in streamers[channel_id]:
        await ctx.send(f"❌ {username} est déjà dans la liste !")
        return

    user_info = await twitch_api.get_user_info(username)
    if not user_info:
        await ctx.send(f"❌ Le streamer {username} n'existe pas sur Twitch !")
        return

    streamers[channel_id].append(username)
    await ctx.send(f"✅ {username} ajouté à la liste des streamers surveillés !")

@bot.command(name='removestreamer')
@commands.has_permissions(manage_channels=True)
async def remove_streamer(ctx, username=None):
    if username is None:
        await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
        return

    channel_id = ctx.channel.id
    username = username.lower().replace('@', '').strip()

    if channel_id not in streamers or username not in streamers[channel_id]:
        await ctx.send(f"❌ {username} n'est pas dans la liste !")
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

    await ctx.send(f"✅ {username} retiré de la liste des streamers surveillés !")

@bot.command(name='liststreamer')
async def list_streamers(ctx):
    channel_id = ctx.channel.id

    if channel_id not in streamers or not streamers[channel_id]:
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
            del ping_roles[channel_id]
        await ctx.send("✅ Rôle de ping désactivé pour ce channel !")
        return

    ping_roles[channel_id] = role.id
    await ctx.send(f"✅ Le rôle {role.mention} sera ping lors des notifications de stream !")

@bot.command(name='streamhelp')
async def stream_help(ctx):
    embed = discord.Embed(
        title="🤖 Aide du Bot Twitch",
        description="Commandes disponibles :",
        color=0x9146ff
    )
    embed.add_field(name="!addstreamer <username>", value="Ajouter un streamer à surveiller", inline=False)
    embed.add_field(name="!removestreamer <username>", value="Retirer un streamer de la surveillance", inline=False)
    embed.add_field(name="!liststreamer", value="Afficher la liste des streamers surveillés", inline=False)
    embed.add_field(name="!pingrole [@role]", value="Définir le rôle à ping (sans rôle = désactiver)", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide ! Utilisez `!streamhelp` pour voir les commandes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant ! Utilisez `!streamhelp` pour voir les commandes.")
    else:
        logger.error(f"Erreur non gérée: {error}")

@bot.event
async def on_disconnect():
    if check_streams.is_running():
        check_streams.cancel()

# === Lancement ===
if __name__ == "__main__":
    Thread(target=run_flask).start()  # ← rend Render content (port 8080 simulé)
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
