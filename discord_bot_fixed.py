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
    app.run(host='0.0.0.0', port=8000)

# === Logger ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Bot Discord ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

# MODIFICATION: Désactiver la commande help par défaut
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# === Twitch credentials (variables d'environnement) ===
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")

# === Data Storage ===
streamers = {}
stream_messages = {}  # Format: {channel_id_username: {'message_id': id, 'last_update': timestamp}}
currently_live_streamers = {}  # Pour suivre qui est actuellement en live
ping_roles = {}
notification_channels = {}
reaction_role_messages = {}  # Format: {message_id: {emoji: role_id}}

def load_config():
    """Charge la configuration depuis le fichier JSON"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            global streamers, ping_roles, notification_channels, reaction_role_messages
            streamers = config.get('streamers', {})
            ping_roles = config.get('ping_roles', {})
            notification_channels = config.get('notification_channels', {})
            reaction_role_messages = config.get('reaction_role_messages', {})
            logger.info("Configuration chargée avec succès")
    except FileNotFoundError:
        logger.info("Aucun fichier de configuration trouvé, utilisation des valeurs par défaut")
        save_config()
    except Exception as e:
        logger.error(f"Erreur lors du chargement de la configuration: {e}")

def save_config():
    """Sauvegarde la configuration dans le fichier JSON"""
    try:
        config = {
            'streamers': streamers,
            'ping_roles': ping_roles,
            'notification_channels': notification_channels,
            'reaction_role_messages': reaction_role_messages
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("Configuration sauvegardée avec succès")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la configuration: {e}")

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
    load_config()
    await twitch_api.get_token()
    if not check_streams.is_running():
        check_streams.start()
        logger.info("Vérification des streams démarrée")

# === REACTION ROLE EVENTS ===
@bot.event
async def on_raw_reaction_add(payload):
    """Gère l'ajout de réactions pour attribuer des rôles"""
    # Ignorer les réactions du bot
    if bot.user and payload.user_id == bot.user.id:
        return
    
    message_id = str(payload.message_id)
    
    # Vérifier si ce message est configuré pour les réactions-rôles
    if message_id not in reaction_role_messages:
        return
    
    emoji_str = str(payload.emoji)
    role_config = reaction_role_messages[message_id]
    
    # Vérifier si cette emoji correspond à un rôle
    if emoji_str not in role_config:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        logger.error(f"Guild {payload.guild_id} non trouvée")
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        logger.error(f"Membre {payload.user_id} non trouvé")
        return
    
    role_id = role_config[emoji_str]
    role = guild.get_role(role_id)
    if not role:
        logger.error(f"Rôle {role_id} non trouvé")
        return
    
    try:
        await member.add_roles(role, reason="Réaction-rôle automatique")
        logger.info(f"Rôle {role.name} attribué à {member.display_name}")
    except discord.Forbidden:
        logger.error(f"Pas de permission pour attribuer le rôle {role.name} à {member.display_name}")
    except discord.HTTPException as e:
        logger.error(f"Erreur HTTP lors de l'attribution du rôle: {e}")
    except Exception as e:
        logger.error(f"Erreur lors de l'attribution du rôle: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    """Gère la suppression de réactions pour retirer des rôles"""
    # Ignorer les réactions du bot
    if bot.user and payload.user_id == bot.user.id:
        return
    
    message_id = str(payload.message_id)
    
    # Vérifier si ce message est configuré pour les réactions-rôles
    if message_id not in reaction_role_messages:
        return
    
    emoji_str = str(payload.emoji)
    role_config = reaction_role_messages[message_id]
    
    # Vérifier si cette emoji correspond à un rôle
    if emoji_str not in role_config:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        logger.error(f"Guild {payload.guild_id} non trouvée")
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        logger.error(f"Membre {payload.user_id} non trouvé")
        return
    
    role_id = role_config[emoji_str]
    role = guild.get_role(role_id)
    if not role:
        logger.error(f"Rôle {role_id} non trouvé")
        return
    
    try:
        await member.remove_roles(role, reason="Suppression réaction-rôle automatique")
        logger.info(f"Rôle {role.name} retiré de {member.display_name}")
    except discord.Forbidden:
        logger.error(f"Pas de permission pour retirer le rôle {role.name} de {member.display_name}")
    except discord.HTTPException as e:
        logger.error(f"Erreur HTTP lors du retrait du rôle: {e}")
    except Exception as e:
        logger.error(f"Erreur lors du retrait du rôle: {e}")

# === COMMANDES REACTION ROLE ===
@bot.command(name='reactionrole')
@commands.has_permissions(manage_roles=True)
async def create_reaction_role(ctx, *, message_content=None):
    """
    Crée un message de réaction-rôle interactif
    Usage: !reactionrole [message optionnel]
    """
    if not message_content:
        message_content = "Réagissez pour obtenir vos rôles !"
    
    # Créer l'embed initial
    embed = discord.Embed(
        title="🎭 Configuration des rôles par réaction",
        description=message_content,
        color=0x00ff00
    )
    embed.add_field(
        name="Instructions", 
        value="Utilisez `!addrole @role :emoji:` pour ajouter des rôles à ce message.", 
        inline=False
    )
    embed.set_footer(text="Réagissez avec les emojis pour obtenir les rôles correspondants")
    
    # Envoyer le message
    message = await ctx.send(embed=embed)
    
    # Initialiser la configuration pour ce message
    reaction_role_messages[str(message.id)] = {}
    save_config()
    
    # Répondre avec les instructions
    instructions_embed = discord.Embed(
        title="✅ Message de réaction-rôle créé !",
        description=f"ID du message: `{message.id}`",
        color=0x00ff00
    )
    instructions_embed.add_field(
        name="Prochaine étape",
        value=f"Utilisez `!addrole <@role> <:emoji:> {message.id}` pour ajouter des rôles à ce message.",
        inline=False
    )
    instructions_embed.add_field(
        name="Exemple",
        value=f"`!addrole @Membre ✅ {message.id}`",
        inline=False
    )
    
    await ctx.send(embed=instructions_embed, delete_after=30)
    logger.info(f"Message de réaction-rôle créé par {ctx.author} avec l'ID {message.id}")

@bot.command(name='addrole')
@commands.has_permissions(manage_roles=True)
async def add_role_to_message(ctx, role: discord.Role, emoji, message_id: int):
    """
    Ajoute un rôle à un message de réaction-rôle existant
    Usage: !addrole @role :emoji: message_id
    """
    message_id_str = str(message_id)
    
    # Vérifier si le message existe dans la configuration
    if message_id_str not in reaction_role_messages:
        embed = discord.Embed(
            title="❌ Erreur",
            description=f"Aucun message de réaction-rôle trouvé avec l'ID `{message_id}`",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Vérifier les permissions du bot
    if role >= ctx.guild.me.top_role:
        embed = discord.Embed(
            title="❌ Erreur de permission",
            description=f"Je ne peux pas attribuer le rôle {role.mention} car il est plus haut que mon rôle le plus élevé.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=15)
        return
    
    # Récupérer le message
    try:
        message = await ctx.fetch_message(message_id)
    except discord.NotFound:
        embed = discord.Embed(
            title="❌ Message non trouvé",
            description=f"Le message avec l'ID `{message_id}` n'existe pas dans ce canal.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Permission refusée",
            description="Je n'ai pas la permission de récupérer ce message.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Ajouter la configuration emoji-rôle
    emoji_str = str(emoji)
    reaction_role_messages[message_id_str][emoji_str] = role.id
    save_config()
    
    # Ajouter la réaction au message
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        embed = discord.Embed(
            title="⚠️ Attention",
            description=f"Impossible d'ajouter la réaction {emoji} au message. L'emoji est peut-être invalide.",
            color=0xffaa00
        )
        await ctx.send(embed=embed, delete_after=10)
    
    # Mettre à jour l'embed du message original
    if message.embeds:
        original_embed = message.embeds[0]
        
        # Récupérer les rôles actuels configurés
        roles_list = []
        for emoji_key, role_id in reaction_role_messages[message_id_str].items():
            role_obj = ctx.guild.get_role(role_id)
            if role_obj:
                roles_list.append(f"{emoji_key} → {role_obj.mention}")
        
        if roles_list:
            # Mettre à jour le champ des rôles
            updated_embed = discord.Embed(
                title=original_embed.title,
                description=original_embed.description,
                color=original_embed.color
            )
            updated_embed.add_field(
                name="🎭 Rôles disponibles",
                value="\n".join(roles_list),
                inline=False
            )
            updated_embed.set_footer(text="Réagissez avec les emojis pour obtenir les rôles correspondants")
            
            try:
                await message.edit(embed=updated_embed)
            except discord.Forbidden:
                logger.error("Pas de permission pour modifier le message de réaction-rôle")
    
    # Confirmer l'ajout
    embed = discord.Embed(
        title="✅ Rôle ajouté !",
        description=f"Le rôle {role.mention} a été lié à {emoji}",
        color=0x00ff00
    )
    await ctx.send(embed=embed, delete_after=10)
    logger.info(f"Rôle {role.name} ajouté au message {message_id} avec l'emoji {emoji}")

@bot.command(name='removerole')
@commands.has_permissions(manage_roles=True)
async def remove_role_from_message(ctx, emoji, message_id: int):
    """
    Supprime un rôle d'un message de réaction-rôle
    Usage: !removerole :emoji: message_id
    """
    message_id_str = str(message_id)
    emoji_str = str(emoji)
    
    # Vérifier si le message existe dans la configuration
    if message_id_str not in reaction_role_messages:
        embed = discord.Embed(
            title="❌ Erreur",
            description=f"Aucun message de réaction-rôle trouvé avec l'ID `{message_id}`",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Vérifier si l'emoji existe
    if emoji_str not in reaction_role_messages[message_id_str]:
        embed = discord.Embed(
            title="❌ Emoji non trouvé",
            description=f"L'emoji {emoji} n'est pas configuré pour ce message.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Supprimer la configuration
    role_id = reaction_role_messages[message_id_str].pop(emoji_str)
    save_config()
    
    # Récupérer le message et supprimer la réaction
    try:
        message = await ctx.fetch_message(message_id)
        await message.clear_reaction(emoji)
    except discord.NotFound:
        logger.warning(f"Message {message_id} non trouvé pour supprimer la réaction")
    except discord.Forbidden:
        logger.warning("Pas de permission pour supprimer les réactions")
    except discord.HTTPException as e:
        logger.error(f"Erreur lors de la suppression de la réaction: {e}")
    
    # Confirmer la suppression
    role = ctx.guild.get_role(role_id)
    role_name = role.name if role else f"Rôle ID {role_id}"
    
    embed = discord.Embed(
        title="✅ Rôle supprimé !",
        description=f"Le rôle {role_name} n'est plus lié à {emoji}",
        color=0x00ff00
    )
    await ctx.send(embed=embed, delete_after=10)
    logger.info(f"Rôle {role_name} supprimé du message {message_id}")

@bot.command(name='listroles')
@commands.has_permissions(manage_roles=True)
async def list_reaction_roles(ctx, message_id: int | None = None):
    """
    Liste tous les messages de réaction-rôle ou les détails d'un message spécifique
    Usage: !listroles [message_id]
    """
    if message_id:
        message_id_str = str(message_id)
        if message_id_str not in reaction_role_messages:
            embed = discord.Embed(
                title="❌ Message non trouvé",
                description=f"Aucun message de réaction-rôle avec l'ID `{message_id}`",
                color=0xff0000
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        # Afficher les détails du message spécifique
        roles_config = reaction_role_messages[message_id_str]
        embed = discord.Embed(
            title=f"🎭 Configuration du message {message_id}",
            color=0x0099ff
        )
        
        if roles_config:
            roles_list = []
            for emoji, role_id in roles_config.items():
                role = ctx.guild.get_role(role_id)
                role_name = role.mention if role else f"Rôle supprimé (ID: {role_id})"
                roles_list.append(f"{emoji} → {role_name}")
            
            embed.add_field(
                name="Rôles configurés",
                value="\n".join(roles_list),
                inline=False
            )
        else:
            embed.add_field(
                name="Aucun rôle configuré",
                value="Utilisez `!addrole` pour ajouter des rôles à ce message.",
                inline=False
            )
    else:
        # Lister tous les messages de réaction-rôle
        embed = discord.Embed(
            title="🎭 Tous les messages de réaction-rôle",
            color=0x0099ff
        )
        
        if reaction_role_messages:
            messages_list = []
            for msg_id, roles_config in reaction_role_messages.items():
                role_count = len(roles_config)
                messages_list.append(f"Message `{msg_id}`: {role_count} rôle(s)")
            
            embed.add_field(
                name="Messages configurés",
                value="\n".join(messages_list),
                inline=False
            )
            embed.add_field(
                name="Voir les détails",
                value="Utilisez `!listroles <message_id>` pour voir les détails d'un message.",
                inline=False
            )
        else:
            embed.add_field(
                name="Aucun message configuré",
                value="Utilisez `!reactionrole` pour créer votre premier message de réaction-rôle.",
                inline=False
            )
    
    await ctx.send(embed=embed)

# === GESTION DES ERREURS REACTION ROLE ===
@create_reaction_role.error
@add_role_to_message.error
@remove_role_from_message.error
@list_reaction_roles.error
async def reaction_role_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permission manquante",
            description="Vous devez avoir la permission `Gérer les rôles` pour utiliser cette commande.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=15)
    elif isinstance(error, commands.RoleNotFound):
        embed = discord.Embed(
            title="❌ Rôle non trouvé",
            description="Le rôle spécifié n'existe pas. Vérifiez le nom ou la mention du rôle.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=15)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Argument invalide",
            description="Vérifiez la syntaxe de votre commande. Utilisez `!help` pour plus d'informations.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=15)
    else:
        logger.error(f"Erreur dans une commande de réaction-rôle: {error}")
        embed = discord.Embed(
            title="❌ Erreur inattendue",
            description="Une erreur inattendue s'est produite. Contactez un administrateur.",
            color=0xff0000
        )
        await ctx.send(embed=embed, delete_after=15)

# === COMMANDE HELP PERSONNALISÉE ===
@bot.command(name='help')
async def custom_help(ctx, command_name=None):
    """Affiche l'aide personnalisée du bot"""
    if command_name:
        # Aide spécifique à une commande
        command_help = {
            'reactionrole': {
                'description': 'Crée un nouveau message de réaction-rôle',
                'usage': '!reactionrole [message optionnel]',
                'example': '!reactionrole Choisissez vos rôles !'
            },
            'addrole': {
                'description': 'Ajoute un rôle à un message de réaction-rôle existant',
                'usage': '!addrole @role :emoji: message_id',
                'example': '!addrole @Membre ✅ 123456789'
            },
            'removerole': {
                'description': 'Supprime un rôle d\'un message de réaction-rôle',
                'usage': '!removerole :emoji: message_id',
                'example': '!removerole ✅ 123456789'
            },
            'listroles': {
                'description': 'Liste les messages de réaction-rôle configurés',
                'usage': '!listroles [message_id]',
                'example': '!listroles 123456789'
            }
        }
        
        if command_name.lower() in command_help:
            cmd_info = command_help[command_name.lower()]
            embed = discord.Embed(
                title=f"📖 Aide - !{command_name}",
                description=cmd_info['description'],
                color=0x0099ff
            )
            embed.add_field(name="Usage", value=f"`{cmd_info['usage']}`", inline=False)
            embed.add_field(name="Exemple", value=f"`{cmd_info['example']}`", inline=False)
        else:
            embed = discord.Embed(
                title="❌ Commande non trouvée",
                description=f"La commande `{command_name}` n'existe pas.",
                color=0xff0000
            )
    else:
        # Aide générale
        embed = discord.Embed(
            title="🤖 Aide du Bot Discord",
            description="Voici la liste des commandes disponibles :",
            color=0x0099ff
        )
        
        embed.add_field(
            name="🎭 Système de réaction-rôles",
            value="`!reactionrole` - Créer un message de réaction-rôle\n"
                  "`!addrole` - Ajouter un rôle à un message\n"
                  "`!removerole` - Supprimer un rôle d'un message\n"
                  "`!listroles` - Lister les configurations",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ Plus d'informations",
            value="Utilisez `!help <commande>` pour plus de détails sur une commande spécifique.",
            inline=False
        )
        
        embed.set_footer(text="Besoin d'aide ? Contactez un administrateur.")
    
    await ctx.send(embed=embed)

@tasks.loop(minutes=2)
async def check_streams():
    try:
        logger.info("🔍 Vérification des streams en cours...")
        
        for channel_id, streamer_list in streamers.items():
            if not streamer_list:
                continue

            channel = bot.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Channel {channel_id} non trouvé")
                continue

            channel_name = getattr(channel, 'name', f'ID:{channel_id}')
            logger.info(f"Vérification de {len(streamer_list)} streamers pour le channel {channel_name}")
            
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
        
        # Créer l'embed de notification
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
        
        embed.set_footer(text=f"Stream démarré à {datetime.now(UTC).strftime('%H:%M:%S')} UTC")
        embed.timestamp = datetime.now(UTC)
        
        # Ajouter les mentions si configurées
        content = ""
        channel_id = channel.id
        if channel_id in ping_roles:
            role_id = ping_roles[channel_id]
            role = channel.guild.get_role(role_id)
            if role:
                content = f"{role.mention} {stream['user_name']} est en live !"
        
        # Envoyer le message
        message = await channel.send(content=content, embed=embed)
        
        # Sauvegarder les informations du message
        message_key = f"{channel_id}_{username}"
        stream_messages[message_key] = {
            'message_id': message.id,
            'last_update': datetime.now(UTC).timestamp()
        }
        
        logger.info(f"✅ Notification envoyée pour {username} dans {channel.name}")
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {e}", exc_info=True)

# === DÉMARRAGE ===
if __name__ == "__main__":
    # Démarrer Flask dans un thread séparé
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Serveur Flask démarré")
    
    # Démarrer le bot Discord
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        logger.error("❌ Token Discord manquant (DISCORD_BOT_TOKEN)")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
