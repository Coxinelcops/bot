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
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_resumed():
    if not check_streams.is_running():
        check_streams.start()
        logger.info("🔁 Tâche check_streams relancée après reconnexion")

# === Twitch credentials (variables d'environnement) ===
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

streamers = {}
stream_messages = {}  # Format: {channel_id_username: {'message_id': id, 'last_update': timestamp}}
currently_live_streamers = {}  # Pour suivre qui est actuellement en live
ping_roles = {}
notification_channels = {}
reaction_role_messages = {}

class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    async def get_token(self):
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            logger.error("❌ Variables d'environnement Twitch manquantes (TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)")
            return False
            
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
        
        # L'API Twitch accepte jusqu'à 100 utilisateurs à la fois
        all_streams = []
        for i in range(0, len(usernames), 100):
            batch = usernames[i:i+100]
            params = {'user_login': batch}

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=self.headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            all_streams.extend(data['data'])
                        elif response.status == 401:
                            logger.warning("Token Twitch invalide, renouvellement...")
                            await self.get_token()
                            # Retry with new token
                            async with session.get(url, headers=self.headers, params=params) as retry_response:
                                if retry_response.status == 200:
                                    data = await retry_response.json()
                                    all_streams.extend(data['data'])
                        else:
                            logger.error(f"Erreur API Twitch streams: {response.status}")
                            
            except Exception as e:
                logger.error(f"Exception lors de la récupération des streams: {e}")
                
        return all_streams

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
        logger.info("Vérification des streams démarrée")

@tasks.loop(minutes=2)
async def check_streams():
    try:
        logger.info("🔍 Vérification des streams en cours...")
        
        for channel_id, streamer_list in streamers.items():
            if not streamer_list:
                continue

            channel = bot.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} non trouvé")
                continue

            logger.info(f"Vérification de {len(streamer_list)} streamers pour le channel {channel.name}")
            
            # Récupérer les streams actuels
            streams = await twitch_api.get_streams(streamer_list)
            currently_live = {stream['user_login'].lower(): stream for stream in streams}
            
            logger.info(f"Streamers en live: {list(currently_live.keys())}")

            # Gérer les nouveaux streams ou mises à jour
            for username, stream in currently_live.items():
                message_key = f"{channel_id}_{username}"
                
                # Vérifier si le streamer était déjà en live
                was_live = message_key in stream_messages
                
                if was_live:
                    # Mettre à jour le message existant
                    await update_stream_message(channel, stream, message_key)
                else:
                    # Nouveau stream - envoyer une notification
                    await send_stream_notification(channel, stream)
                    currently_live_streamers[message_key] = True

            # Gérer les streams qui se sont arrêtés
            to_remove = []
            for message_key, message_data in stream_messages.items():
                if message_key.startswith(f"{channel_id}_"):
                    username = message_key.split('_', 1)[1]
                    if username not in currently_live:
                        logger.info(f"Stream terminé pour {username}")
                        await remove_stream_message(channel, message_key, username)
                        to_remove.append(message_key)

            # Nettoyer les références
            for message_key in to_remove:
                stream_messages.pop(message_key, None)
                currently_live_streamers.pop(message_key, None)

        logger.info("✅ Vérification des streams terminée")
                        
    except Exception as e:
        logger.error(f"Erreur dans check_streams: {e}", exc_info=True)

async def update_stream_message(channel, stream, message_key):
    """Met à jour un message de stream existant avec les nouvelles informations"""
    try:
        message_data = stream_messages.get(message_key)
        if not message_data:
            logger.warning(f"Message data non trouvée pour {message_key}")
            return
            
        message_id = message_data['message_id']
        
        # Récupérer le message existant
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            logger.warning(f"Message {message_id} non trouvé, création d'un nouveau")
            await send_stream_notification(channel, stream)
            return
        
        username = stream['user_login']
        game_name = stream['game_name'] or "Pas de catégorie"
        viewer_count = stream['viewer_count']
        title = stream['title'] or "Pas de titre"
        
        # Créer l'embed mis à jour
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
            thumbnail += f"?t={int(datetime.now().timestamp())}"
            embed.set_image(url=thumbnail)
        
        embed.set_footer(text=f"Dernière mise à jour: {datetime.now(UTC).strftime('%H:%M:%S')} UTC")
        embed.timestamp = datetime.now(UTC)
        
        # Mettre à jour le message
        await message.edit(embed=embed)
        
        # Mettre à jour le timestamp de dernière mise à jour
        stream_messages[message_key]['last_update'] = datetime.now(UTC).timestamp()
        
        logger.info(f"✅ Message mis à jour pour {username} dans {channel.name}")
        
    except discord.Forbidden:
        logger.error(f"Pas de permission pour modifier le message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du message: {e}", exc_info=True)

async def remove_stream_message(channel, message_key, username):
    """Supprime un message de stream quand le stream se termine"""
    try:
        message_data = stream_messages.get(message_key)
        if not message_data:
            return
            
        message_id = message_data['message_id']
        
        try:
            message = await channel.fetch_message(message_id)
            
            # Créer un embed de fin de stream
            end_embed = discord.Embed(
                title=f"⚫ {username} n'est plus en live",
                description="Le stream s'est terminé",
                color=0x808080
            )
            end_embed.set_footer(text=f"Stream terminé à {datetime.now(UTC).strftime('%H:%M:%S')} UTC")
            
            # Modifier le message pour indiquer la fin
            await message.edit(embed=end_embed)
            
            # Supprimer après 30 secondes
            await asyncio.sleep(30)
            await message.delete()
            
            logger.info(f"Message de fin de stream pour {username} supprimé")
            
        except discord.NotFound:
            logger.info(f"Message pour {username} déjà supprimé")
        except discord.Forbidden:
            logger.warning(f"Pas de permission pour modifier/supprimer le message de {username}")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du message: {e}")
            
    except Exception as e:
        logger.error(f"Erreur générale dans remove_stream_message: {e}")

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
            thumbnail += f"?t={int(datetime.now().timestamp())}"
            embed.set_image(url=thumbnail)

        embed.set_footer(text=f"Stream démarré • Mise à jour toutes les 2 minutes")
        embed.timestamp = datetime.now(UTC)

        content = ""
        if channel.id in ping_roles:
            role = channel.guild.get_role(ping_roles[channel.id])
            if role:
                content = f"{role.mention} "

        message = await channel.send(content=content, embed=embed)
        message_key = f"{channel.id}_{username.lower()}"
        stream_messages[message_key] = {
            'message_id': message.id,
            'last_update': datetime.now(UTC).timestamp()
        }

        logger.info(f"🎉 Notification envoyée pour {username} dans {channel.name}")

    except discord.Forbidden:
        logger.error(f"Pas de permission pour envoyer un message dans {channel.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}", exc_info=True)

async def delete_command_messages(ctx, response_message=None):
    """Supprime le message de commande et la réponse du bot après un délai"""
    try:
        await asyncio.sleep(5)
        if ctx.message:
            await ctx.message.delete()
        if response_message:
            await response_message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass

@bot.command(name='addstreamer')
@commands.has_permissions(manage_channels=True)
async def add_streamer(ctx, username=None):
    if username is None:
        response = await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    channel_id = ctx.channel.id
    username = username.lower().replace('@', '').strip()

    if not username:
        response = await ctx.send("❌ Nom d'utilisateur invalide !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    if channel_id not in streamers:
        streamers[channel_id] = []

    if username in streamers[channel_id]:
        response = await ctx.send(f"❌ {username} est déjà dans la liste !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    user_info = await twitch_api.get_user_info(username)
    if not user_info:
        response = await ctx.send(f"❌ Le streamer {username} n'existe pas sur Twitch !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    streamers[channel_id].append(username)
    response = await ctx.send(f"✅ {username} ajouté à la liste des streamers surveillés !")
    asyncio.create_task(delete_command_messages(ctx, response))
    
    logger.info(f"Streamer {username} ajouté au channel {ctx.channel.name}")

@bot.command(name='addstreamers')
@commands.has_permissions(manage_channels=True)
async def add_streamers(ctx, *usernames):
    if not usernames:
        response = await ctx.send("❌ Veuillez spécifier au moins un nom d'utilisateur Twitch !\nExemple: `!addstreamers streamer1 streamer2 streamer3`")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    channel_id = ctx.channel.id
    if channel_id not in streamers:
        streamers[channel_id] = []

    added_streamers = []
    already_exists = []
    invalid_streamers = []

    for username in usernames:
        username = username.lower().replace('@', '').strip()
        
        if not username:
            continue
            
        if username in streamers[channel_id]:
            already_exists.append(username)
            continue

        user_info = await twitch_api.get_user_info(username)
        if not user_info:
            invalid_streamers.append(username)
            continue

        streamers[channel_id].append(username)
        added_streamers.append(username)

    # Construire le message de réponse
    message_parts = []
    
    if added_streamers:
        message_parts.append(f"✅ **Streamers ajoutés:** {', '.join(added_streamers)}")
    
    if already_exists:
        message_parts.append(f"⚠️ **Déjà dans la liste:** {', '.join(already_exists)}")
    
    if invalid_streamers:
        message_parts.append(f"❌ **Streamers introuvables:** {', '.join(invalid_streamers)}")

    if not message_parts:
        message_parts.append("❌ Aucun streamer valide fourni !")

    response = await ctx.send("\n".join(message_parts))
    asyncio.create_task(delete_command_messages(ctx, response))

@bot.command(name='removestreamer')
@commands.has_permissions(manage_channels=True)
async def remove_streamer(ctx, username=None):
    if username is None:
        response = await ctx.send("❌ Veuillez spécifier un nom d'utilisateur Twitch !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    channel_id = ctx.channel.id
    username = username.lower().replace('@', '').strip()

    if channel_id not in streamers or username not in streamers[channel_id]:
        response = await ctx.send(f"❌ {username} n'est pas dans la liste !")
        asyncio.create_task(delete_command_messages(ctx, response))
        return

    streamers[channel_id].remove(username)

    message_key = f"{channel_id}_{username}"
    if message_key in stream_messages:
        try:
            message_id = stream_messages[message_key]['message_id']
            message = await ctx.channel.fetch_message(message_id)
            await message.delete()
        except:
            pass
        finally:
            stream_messages.pop(message_key, None)
            currently_live_streamers.pop(message_key, None)

    response = await ctx.send(f"✅ {username} retiré de la liste des streamers surveillés !")
    asyncio.create_task(delete_command_messages(ctx, response))

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
    embed.set_footer(text="Mise à jour automatique toutes les 2 minutes")
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

@bot.command(name='reactionrole')
@commands.has_permissions(manage_roles=True)
async def create_reaction_role(ctx, role: discord.Role = None, emoji: str = "🔔"):
    """Crée un message sur lequel les utilisateurs peuvent réagir pour obtenir un rôle"""
    if role is None:
        await ctx.send("❌ Veuillez spécifier un rôle !\nExemple: `!reactionrole @Notifications 🔔`")
        return

    embed = discord.Embed(
        title="🎯 Rôle par Réaction",
        description=f"Réagissez avec {emoji} pour obtenir le rôle **{role.name}**\n\nRéagissez à nouveau pour retirer le rôle.",
        color=0x9146ff
    )
    embed.add_field(name="Rôle", value=role.mention, inline=True)
    embed.add_field(name="Emoji", value=emoji, inline=True)
    embed.set_footer(text="Système de rôles automatique")

    try:
        await ctx.message.delete()
    except:
        pass

    message = await ctx.send(embed=embed)
    await message.add_reaction(emoji)

    reaction_role_messages[message.id] = {
        'role_id': role.id,
        'emoji': emoji,
        'guild_id': ctx.guild.id
    }

    logger.info(f"Message de réaction créé pour le rôle {role.name} avec l'emoji {emoji}")

@bot.event
async def on_reaction_add(reaction, user):
    """Gère l'ajout de réactions pour donner des rôles"""
    if user.bot:
        return

    message_id = reaction.message.id
    if message_id not in reaction_role_messages:
        return

    role_data = reaction_role_messages[message_id]
    
    if str(reaction.emoji) != role_data['emoji']:
        return

    guild = bot.get_guild(role_data['guild_id'])
    if not guild:
        return

    role = guild.get_role(role_data['role_id'])
    member = guild.get_member(user.id)

    if not role or not member:
        return

    try:
        await member.add_roles(role)
        logger.info(f"Rôle {role.name} ajouté à {member.name}")
    except discord.Forbidden:
        logger.error(f"Pas de permission pour ajouter le rôle {role.name} à {member.name}")
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du rôle: {e}")

@bot.event
async def on_reaction_remove(reaction, user):
    """Gère la suppression de réactions pour retirer des rôles"""
    if user.bot:
        return

    message_id = reaction.message.id
    if message_id not in reaction_role_messages:
        return

    role_data = reaction_role_messages[message_id]
    
    if str(reaction.emoji) != role_data['emoji']:
        return

    guild = bot.get_guild(role_data['guild_id'])
    if not guild:
        return

    role = guild.get_role(role_data['role_id'])
    member = guild.get_member(user.id)

    if not role or not member:
        return

    try:
        await member.remove_roles(role)
        logger.info(f"Rôle {role.name} retiré de {member.name}")
    except discord.Forbidden:
        logger.error(f"Pas de permission pour retirer le rôle {role.name} de {member.name}")
    except Exception as e:
        logger.error(f"Erreur lors du retrait du rôle: {e}")

@bot.command(name='streamhelp')
async def stream_help(ctx):
    response = """**🤖 Commandes du Bot Twitch :**

`!addstreamer <username>` - Ajouter un streamer à surveiller
`!addstreamers <user1> <user2> ...` - Ajouter plusieurs streamers
`!removestreamer <username>` - Retirer un streamer
`!liststreamer` - Liste des streamers surveillés
`!pingrole [@role]` - Définir le rôle à ping (sans rôle = désactiver)
`!reactionrole [@role] [emoji]` - Message pour obtenir un rôle par réaction

⏱️ Mise à jour automatique toutes les 2 minutes"""
    
    await ctx.send(response)

# Test command pour vérifier que la vérification fonctionne
@bot.command(name='checkstreams')
@commands.has_permissions(manage_channels=True)
async def manual_check_streams(ctx):
    """Commande pour tester manuellement la vérification des streams"""
    response = await ctx.send("🔍 Vérification manuelle des streams en cours...")
    await check_streams()
    await response.edit(content="✅ Vérification terminée ! Consultez les logs pour plus de détails.")
    asyncio.create_task(delete_command_messages(ctx, response))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        response = await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande !")
        if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers']:
            asyncio.create_task(delete_command_messages(ctx, response))
    elif isinstance(error, commands.BadArgument):
        response = await ctx.send("❌ Argument invalide ! Utilisez `!streamhelp` pour voir les commandes.")
        if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers']:
            asyncio.create_task(delete_command_messages(ctx, response))
    elif isinstance(error, commands.MissingRequiredArgument):
        response = await ctx.send("❌ Argument manquant ! Utilisez `!streamhelp` pour voir les commandes.")
        if ctx.command.name in ['addstreamer', 'removestreamer', 'addstreamers']:
            asyncio.create_task(delete_command_messages(ctx, response))
    else:
        logger.error(f"Erreur non gérée: {error}")

@bot.event
async def on_disconnect():
    logger.warning("🔌 Déconnecté de Discord")

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
