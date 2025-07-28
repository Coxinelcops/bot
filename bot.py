# discord_bot_merged.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import os
import json
import logging
from datetime import datetime, UTC, timedelta
from threading import Thread
from aiohttp import web
import pytz
from typing import Optional

# === CONFIG ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === TIMEZONE ===
TIMEZONE = pytz.timezone('Europe/Paris')
def get_current_time(): return datetime.now(TIMEZONE)
def parse_date(date_str):
    try:
        naive = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return TIMEZONE.localize(naive)
    except: return None

def format_date(date):
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"{days[date.weekday()]} {date.day} {months[date.month - 1]} {date.year} à {date.strftime('%H:%M')}"

# === FLASK (render) ===
web_server_started = False

async def start_web_server():
    global web_server_started
    if web_server_started:
        print("🌐 Serveur web déjà démarré. Ignoré.")
        return
    web_server_started = True
    async def health_check(request):
        return web.Response(text="Bot Discord actif ✅", status=200)
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 Tentative de démarrage du serveur web sur le port {port}")
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Serveur web démarré sur le port {os.getenv('PORT', 8080)}")

# === TWITCH ===
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
streamers = {}
stream_messages = {}
currently_live_streamers = {}
ping_roles = {}
reaction_role_messages = {}

class TwitchAPI:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.token_expires_at = None

    async def get_token(self):
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            print("⚠️ Variables Twitch manquantes, fonctionnalités Twitch désactivées")
            return
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': TWITCH_CLIENT_ID,
            'client_secret': TWITCH_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as resp:
                    data = await resp.json()
                    self.token = data['access_token']
                    self.token_expires_at = datetime.now(UTC).timestamp() + data['expires_in']
                    self.headers = {
                        'Client-ID': TWITCH_CLIENT_ID,
                        'Authorization': f'Bearer {self.token}'
                    }
        except Exception as e:
            print(f"❌ Erreur Twitch API: {e}")

    async def ensure_valid_token(self):
        if not self.token or datetime.now(UTC).timestamp() >= self.token_expires_at - 300:
            await self.get_token()

    async def get_streams(self, usernames):
        if not self.token:
            return []
        await self.ensure_valid_token()
        url = "https://api.twitch.tv/helix/streams"
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
            except Exception as e:
                print(f"❌ Erreur lors de la récupération des streams: {e}")
        return all_streams

twitch_api = TwitchAPI()

@tasks.loop(minutes=2)
async def check_streams():
    for channel_id, streamer_list in streamers.items():
        if not streamer_list:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        streams = await twitch_api.get_streams(streamer_list)
        live_now = {s['user_login']: s for s in streams}
        for username, stream in live_now.items():
            key = f"{channel_id}_{username}"
            if key in stream_messages:
                continue  # already live
            embed = discord.Embed(
                title=f"🔴 {stream['user_name']} est en live !",
                description=stream['title'],
                url=f"https://twitch.tv/{username}",
                color=0x9146ff
            )
            thumbnail_url = stream.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
            if thumbnail_url:
                embed.set_image(url=thumbnail_url)
            ping_content = f"<@&{ping_roles.get(channel_id)}>" if ping_roles.get(channel_id) else None
            msg = await channel.send(content=ping_content, embed=embed)
            stream_messages[key] = {'message_id': msg.id, 'last_update': datetime.now(UTC).timestamp()}

@check_streams.before_loop
async def before_check(): await bot.wait_until_ready()

# === EVENTS ===
events = {}
event_id_counter = 1
event_messages = {}
notifications_sent = {}
guild_role_configs = {}
notification_messages = {}

class Event:
    def __init__(self, id, name, date, creator, guild_id, channel_id, role_id=None, category=None, stream=None, lieu=None, image=None, description=None):
        self.id = id
        self.name = name
        self.date = date
        self.creator = creator
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.role_id = role_id
        self.category = category
        self.stream = stream
        self.lieu = lieu
        self.image = image
        self.description = description
        self.created_at = get_current_time()

def save_guild_config(guild_id, config):
    guild_role_configs[guild_id] = config

def get_guild_config(guild_id):
    return guild_role_configs.get(guild_id, {})

def get_role_by_category(guild, category):
    """Récupérer le rôle configuré pour une catégorie"""
    config = get_guild_config(guild.id)
    role_id = config.get(category)
    
    if role_id:
        return guild.get_role(role_id)
    return None

def create_event_embed(event, detailed=False):
    embed = discord.Embed(title=f"🎉 {event.name}", timestamp=event.created_at, color=0x00AE86)
    embed.add_field(name="📅 Date", value=format_date(event.date), inline=True)
    
    # TOUJOURS afficher la catégorie en premier si elle existe
    if hasattr(event, 'category') and event.category:
        category_names = {
            'lec': '🏆 LEC',
            'lfl': '🇫🇷 LFL', 
            'rl': '🚗 Rocket League',
            'r6': '🎯 Rainbow Six',
            'chess': '♟️ Échecs'
        }
        category_display = category_names.get(event.category, f"🎮 {event.category.upper()}")
        embed.add_field(name="🎮 Catégorie", value=category_display, inline=True)
    else:
        # Ajouter un champ vide pour l'alignement
        embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    if event.lieu:
        embed.add_field(name="📍 Lieu", value=event.lieu, inline=True)
    if event.stream:
        embed.add_field(name="📺 Stream", value=event.stream, inline=False)
    if event.description and detailed:
        embed.add_field(name="📝 Description", value=event.description, inline=False)
    
    # Image
    if event.image and event.image.strip():
        if event.image.startswith(('http://', 'https://')):
            embed.set_image(url=event.image)
        else:
            embed.add_field(name="⚠️ Image", value="URL d'image invalide", inline=False)
    
    embed.set_footer(text=f"Créé par {event.creator}")
    return embed

def create_notification_embed(event, minutes_before):
    """Créer un embed pour les notifications"""
    if minutes_before == 0:
        title = f"🔴 LIVE MAINTENANT - {event.name}"
        color = 0xFF0000  # Rouge
        message = "L'événement commence maintenant !"
    else:
        title = f"⏰ {event.name} - Dans {minutes_before} minutes"
        color = 0xFFA500  # Orange
        message = f"L'événement commence dans {minutes_before} minutes !"
    
    embed = discord.Embed(
        title=title,
        description=message,
        color=color,
        timestamp=get_current_time()
    )
    
    embed.add_field(name="📅 Heure de début", value=format_date(event.date), inline=True)
    
    # Afficher la catégorie dans les notifications
    if hasattr(event, 'category') and event.category:
        category_names = {
            'lec': '🏆 LEC',
            'lfl': '🇫🇷 LFL', 
            'rl': '🚗 Rocket League',
            'r6': '🎯 Rainbow Six',
            'chess': '♟️ Échecs'
        }
        category_display = category_names.get(event.category, event.category.upper())
        embed.add_field(name="🎮 Catégorie", value=category_display, inline=True)
    
    if event.lieu:
        embed.add_field(name="📍 Lieu", value=event.lieu, inline=True)
    
    if event.stream:
        embed.add_field(name="📺 Stream", value=event.stream, inline=False)
    
    # Image en grand format pour les notifications aussi
    if event.image and event.image.startswith(('http://', 'https://')):
        embed.set_image(url=event.image)
    
    return embed

@bot.tree.command(name="event-create", description="Créer un événement")
@app_commands.describe(
    nom="Nom de l'événement",
    date="Date et heure (format: DD/MM/YYYY HH:MM)",
    category="Catégorie de l'événement",
    role="Rôle à mentionner pour les notifications (optionnel - auto si catégorie configurée)",
    stream="Lien du stream (optionnel)",
    lieu="Lieu de l'événement (optionnel)",
    image="URL complète de l'image (doit commencer par http:// ou https://)",
    description="Description de l'événement (optionnel)"
)
@app_commands.choices(category=[
    app_commands.Choice(name="LEC", value="lec"),
    app_commands.Choice(name="LFL", value="lfl"),
    app_commands.Choice(name="Rocket League", value="rl"),
    app_commands.Choice(name="Rainbow Six", value="r6"),
    app_commands.Choice(name="Échecs", value="chess"),
    app_commands.Choice(name="Autre", value="autre")
])
async def create_event(
    interaction: discord.Interaction,
    nom: str,
    date: str,
    category: str,
    role: Optional[discord.Role] = None,
    stream: Optional[str] = None,
    lieu: Optional[str] = None,
    image: Optional[str] = None,
    description: Optional[str] = None
):
    global event_id_counter
    
    try:
        # Valider la date AVANT de defer pour éviter l'expiration
        dt = parse_date(date)
        if not dt:
            await interaction.response.send_message(
                "❌ Format de date invalide! Utilisez le format: DD/MM/YYYY HH:MM (ex: 25/12/2024 20:30)",
                ephemeral=True
            )
            return
        
        # Vérifier si la date n'est pas dans le passé
        if dt < get_current_time():
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas créer un événement dans le passé!",
                ephemeral=True
            )
            return
        
        # Valider l'URL de l'image si fournie
        if image and not image.startswith(('http://', 'https://')):
            await interaction.response.send_message(
                "❌ L'URL de l'image doit commencer par http:// ou https://",
                ephemeral=True
            )
            return
        
        # MAINTENANT qu'on a validé, on peut defer
        await interaction.response.defer()
        
        # Si aucun rôle n'est spécifié, essayer de le trouver automatiquement par catégorie
        if not role and category != 'autre':
            role = get_role_by_category(interaction.guild, category)
            if role:
                print(f"🎯 DEBUG - Rôle automatique trouvé pour {category}: {role.name}")
            else:
                print(f"⚠️ DEBUG - Aucun rôle automatique trouvé pour {category}")
        
        event = Event(event_id_counter, nom, dt, interaction.user.display_name, interaction.guild_id, interaction.channel_id, 
                      role.id if role else None, category, stream, lieu, image, description)
        events[event_id_counter] = event
        embed = create_event_embed(event, detailed=True)
        
        # Envoyer l'embed dans le canal
        message = await interaction.followup.send(embed=embed)
        
        # Stocker le message pour pouvoir le supprimer plus tard
        try:
            event_messages[event_id_counter] = message
        except Exception as e:
            print(f"Erreur lors du stockage du message: {e}")
        
        notifications_sent[event_id_counter] = {"15min": False, "live": False}
        notification_messages[event_id_counter] = []
        event_id_counter += 1
        
    except Exception as e:
        print(f"❌ Erreur dans create_event: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Erreur lors de la création de l'événement: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Erreur lors de la création de l'événement: {str(e)}",
                    ephemeral=True
                )
        except:
            pass

# Fonction pour supprimer un message après un délai
async def delete_message_after_delay(message, delay_minutes):
    await asyncio.sleep(delay_minutes * 60)
    try:
        await message.delete()
    except:
        pass  # Ignore si le message est déjà supprimé ou inaccessible

@tasks.loop(minutes=1)
async def notification_system():
    try:
        now = get_current_time()
        print(f"🔔 DEBUG - Vérification des notifications à {now.strftime('%d/%m/%Y %H:%M:%S')} (heure française)")
        
        for event_id, event in list(events.items()):
            if event_id not in notifications_sent:
                continue
            
            delta = event.date - now
            minutes = int(delta.total_seconds() / 60)
            
            # Notification 15 minutes avant
            if minutes <= 15 and not notifications_sent[event_id]["15min"]:
                notification_msg = await send_event_notification(event, 15)
                if notification_msg:
                    notification_messages[event_id].append(notification_msg)
                    # Programmer la suppression du message de notification après 5 minutes
                    asyncio.create_task(delete_message_after_delay(notification_msg, 5))
                notifications_sent[event_id]["15min"] = True
            
            # Notification live (0 minute)
            elif minutes <= 0 and not notifications_sent[event_id]["live"]:
                notification_msg = await send_event_notification(event, 0)
                if notification_msg:
                    notification_messages[event_id].append(notification_msg)
                    # Programmer la suppression du message de notification après 5 minutes
                    asyncio.create_task(delete_message_after_delay(notification_msg, 5))
                notifications_sent[event_id]["live"] = True
            
            # Supprimer le message principal 30 minutes après l'heure de début de l'événement
            elif delta.total_seconds() < -1800:  # -30 minutes après l'événement
                if event_id in event_messages:
                    try: 
                        await event_messages[event_id].delete()
                    except: 
                        pass
                    del event_messages[event_id]
            
            # Nettoyage des événements passés (après 2 heures)
            elif delta.total_seconds() < -7200:  # 2 heures après l'événement
                await delete_event_message(event_id)
                
    except Exception as e:
        print(f"❌ ERREUR dans notification_system: {e}")
        import traceback
        traceback.print_exc()

async def send_event_notification(event, minutes_before):
    try:
        channel = bot.get_channel(event.channel_id)
        if not channel: 
            return None
        
        embed = create_notification_embed(event, minutes_before)
        
        content = ""
        if event.role_id:
            role = channel.guild.get_role(event.role_id)
            if role:
                content = role.mention
        
        sent_message = await channel.send(content=content, embed=embed)
        return sent_message
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de notification: {e}")
        return None

async def delete_event_message(event_id):
    """Supprimer complètement un événement et nettoyer toutes ses données"""
    try:
        # Nettoyer les données (ne pas essayer de supprimer le message principal ici car déjà fait)
        if event_id in events:
            del events[event_id]
        if event_id in notifications_sent:
            del notifications_sent[event_id]
        if event_id in notification_messages:
            del notification_messages[event_id]
    except Exception as e:
        print(f"Erreur lors du nettoyage: {e}")

@notification_system.before_loop
async def before_notification_system():
    await bot.wait_until_ready()

# === COMMANDES SUPPLÉMENTAIRES ===

@bot.tree.command(name="config-roles", description="Configurer les rôles de notification par catégorie")
@app_commands.describe(
    category="Catégorie à configurer",
    role="Rôle à associer à cette catégorie (laisser vide pour supprimer)"
)
@app_commands.choices(category=[
    app_commands.Choice(name="🏆 LEC", value="lec"),
    app_commands.Choice(name="🇫🇷 LFL", value="lfl"),
    app_commands.Choice(name="🚗 Rocket League", value="rl"),
    app_commands.Choice(name="🎯 Rainbow Six", value="r6"),
    app_commands.Choice(name="♟️ Échecs", value="chess")
])
async def config_roles(interaction: discord.Interaction, category: str, role: Optional[discord.Role] = None):
    # Vérifier les permissions
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "❌ Vous n'avez pas les permissions pour configurer les rôles!",
            ephemeral=True
        )
        return
    
    # Récupérer la config actuelle
    config = get_guild_config(interaction.guild_id)
    
    category_names = {
        'lec': '🏆 LEC',
        'lfl': '🇫🇷 LFL', 
        'rl': '🚗 Rocket League',
        'r6': '🎯 Rainbow Six',
        'chess': '♟️ Échecs'
    }
    
    if role is None:
        # Supprimer la configuration pour cette catégorie
        if category in config:
            del config[category]
            save_guild_config(interaction.guild_id, config)
            await interaction.response.send_message(
                f"✅ Configuration supprimée!\n"
                f"**{category_names.get(category, category.upper())}** n'aura plus de rôle de notification.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Aucune configuration trouvée pour **{category_names.get(category, category.upper())}**",
                ephemeral=True
            )
    else:
        # Mettre à jour la config
        config[category] = role.id
        save_guild_config(interaction.guild_id, config)
        
        await interaction.response.send_message(
            f"✅ Configuration mise à jour!\n"
            f"**{category_names.get(category, category.upper())}** → {role.mention}",
            ephemeral=True
        )

@bot.tree.command(name="show-config", description="Afficher la configuration des rôles")
async def show_config(interaction: discord.Interaction):
    config = get_guild_config(interaction.guild_id)
    
    if not config:
        await interaction.response.send_message(
            "❌ Aucune configuration de rôles définie!\nUtilisez `/config-roles` pour configurer.",
            ephemeral=True
        )
        return
    
    category_names = {
        'lec': '🏆 LEC',
        'lfl': '🇫🇷 LFL', 
        'rl': '🚗 Rocket League',
        'r6': '🎯 Rainbow Six',
        'chess': '♟️ Échecs'
    }
    
    embed = discord.Embed(
        title="⚙️ Configuration des Rôles",
        color=0x00AE86,
        timestamp=get_current_time()
    )
    
    for category, role_id in config.items():
        role = interaction.guild.get_role(role_id)
        role_text = role.mention if role else f"❌ Rôle supprimé (ID: {role_id})"
        category_display = category_names.get(category, category.upper())
        
        embed.add_field(
            name=category_display,
            value=role_text,
            inline=True
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="event-list", description="Afficher tous les événements")
async def list_events(interaction: discord.Interaction):
    # Répondre immédiatement avec defer
    await interaction.response.defer()
    
    guild_events = [event for event in events.values() if event.guild_id == interaction.guild_id]
    guild_events.sort(key=lambda x: x.date)
    
    if not guild_events:
        await interaction.followup.send(
            "📅 Aucun événement programmé pour le moment."
        )
        return
    
    # Séparer les événements futurs et passés
    now = get_current_time()
    future_events = [event for event in guild_events if event.date > now]
    past_events = [event for event in guild_events if event.date <= now]
    
    embed = discord.Embed(
        title="📅 Liste des Événements",
        color=0x00AE86,
        timestamp=get_current_time()
    )
    
    if future_events:
        future_list = []
        for event in future_events[:10]:  # Limiter à 10 événements
            event_text = f"**{event.id}** - {event.name}\n📅 {format_date(event.date)}"
            if event.lieu:
                event_text += f"\n📍 {event.lieu}"
            future_list.append(event_text)
        
        embed.add_field(
            name="🔮 Événements à venir",
            value="\n\n".join(future_list),
            inline=False
        )
    
    if past_events:
        past_list = []
        for event in past_events[-5:]:  # Les 5 derniers événements passés
            event_text = f"**{event.id}** - {event.name}\n📅 {format_date(event.date)}"
            past_list.append(event_text)
        
        embed.add_field(
            name="📜 Événements passés",
            value="\n\n".join(past_list),
            inline=False
        )
    
    embed.set_footer(text=f"Total: {len(guild_events)} événement(s) | Utilisez /event-info <id> pour plus de détails")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="event-delete", description="Supprimer un événement")
@app_commands.describe(id="ID de l'événement à supprimer")
async def delete_event(interaction: discord.Interaction, id: int):
    # Vérifier les permissions
    if not interaction.user.guild_permissions.manage_events:
        await interaction.response.send_message(
            "❌ Vous n'avez pas les permissions pour supprimer des événements!",
            ephemeral=True
        )
        return
    
    if id not in events or events[id].guild_id != interaction.guild_id:
        await interaction.response.send_message(
            "❌ Événement introuvable!",
            ephemeral=True
        )
        return
    
    event_name = events[id].name
    await delete_event_message(id)
    
    await interaction.response.send_message(
        f"✅ L'événement \"{event_name}\" a été supprimé avec succès!",
        ephemeral=True
    )

@bot.tree.command(name="event-info", description="Afficher les détails d'un événement")
@app_commands.describe(id="ID de l'événement")
async def event_info(interaction: discord.Interaction, id: int):
    if id not in events or events[id].guild_id != interaction.guild_id:
        await interaction.response.send_message(
            "❌ Événement introuvable!",
            ephemeral=True
        )
        return
    
    event = events[id]
    embed = create_event_embed(event, detailed=True)
    
    # Ajouter des informations supplémentaires
    time_until = event.date - get_current_time()
    if time_until.total_seconds() > 0:
        days = time_until.days
        hours, remainder = divmod(time_until.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        time_string = ""
        if days > 0:
            time_string += f"{days}j "
        if hours > 0:
            time_string += f"{hours}h "
        if minutes > 0:
            time_string += f"{minutes}min"
        
        embed.add_field(
            name="⏰ Temps restant",
            value=time_string or "Moins d'une minute",
            inline=True
        )
    else:
        embed.add_field(
            name="⏰ Statut",
            value="Événement passé",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed)

# === COMMANDES TWITCH MODIFIEES ===

@bot.tree.command(name="twitchadd", description="Ajouter un ou plusieurs streamers à suivre")
@app_commands.describe(usernames="Noms d'utilisateur Twitch séparés par des espaces (sans @)")
async def add_streamer(interaction: discord.Interaction, usernames: str):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Vous n'avez pas les permissions pour gérer les streamers!", ephemeral=True)
        return

    # Nettoyer les noms d'utilisateur
    username_list = [u.lower().replace('@', '').strip() for u in usernames.split() if u.strip()]
    if not username_list:
        await interaction.response.send_message("❌ Veuillez fournir au moins un nom d'utilisateur valide!", ephemeral=True)
        return

    # Defer la réponse APRÈS la validation
    await interaction.response.defer(ephemeral=True)

    channel_id = interaction.channel_id

    if channel_id not in streamers:
        streamers[channel_id] = []

    added = []
    already_exists = []

    for username in username_list:
        if username in streamers[channel_id]:
            already_exists.append(username)
        else:
            streamers[channel_id].append(username)
            added.append(username)

    response_parts = []
    if added:
        response_parts.append(f"✅ **Ajouté{'s' if len(added) > 1 else ''} :** {', '.join(added)}")
    if already_exists:
        response_parts.append(f"⚠️ **Déjà suivi{'s' if len(already_exists) > 1 else ''} :** {', '.join(already_exists)}")
    if not added and already_exists:
        response_parts = ["⚠️ Tous les streamers sont déjà suivis dans ce salon!"]

    await interaction.followup.send('\n'.join(response_parts))


@bot.tree.command(name="twitchremove", description="Retirer un ou plusieurs streamers de la liste")
@app_commands.describe(usernames="Noms d'utilisateur Twitch à retirer, séparés par des espaces")
async def remove_streamer(interaction: discord.Interaction, usernames: str):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Vous n'avez pas les permissions pour gérer les streamers!", ephemeral=True)
        return
    
    # Séparer les noms d'utilisateur et les nettoyer
    username_list = [username.lower().replace('@', '').strip() for username in usernames.split()]
    username_list = [username for username in username_list if username]  # Supprimer les chaînes vides
    
    if not username_list:
        await interaction.response.send_message("❌ Veuillez fournir au moins un nom d'utilisateur valide!", ephemeral=True)
        return
    
    channel_id = interaction.channel_id
    
    if channel_id not in streamers or not streamers[channel_id]:
        await interaction.response.send_message("❌ Aucun streamer n'est suivi dans ce salon!", ephemeral=True)
        return
    
    # Defer APRÈS les validations
    await interaction.response.defer()
    
    removed = []
    not_found = []
    
    for username in username_list:
        if username in streamers[channel_id]:
            streamers[channel_id].remove(username)
            removed.append(username)
            
            # Nettoyer le message de stream s'il existe
            key = f"{channel_id}_{username}"
            if key in stream_messages:
                del stream_messages[key]
        else:
            not_found.append(username)
    
    # Construire le message de réponse
    response_parts = []
    
    if removed:
        response_parts.append(f"✅ **Retiré{'s' if len(removed) > 1 else ''}:** {', '.join(removed)}")
    
    if not_found:
        response_parts.append(f"❌ **Non trouvé{'s' if len(not_found) > 1 else ''}:** {', '.join(not_found)}")
    
    await interaction.followup.send('\n'.join(response_parts))

@bot.tree.command(name="twitchlist", description="Voir la liste des streamers suivis")
async def list_streamers(interaction: discord.Interaction):
    # Répondre immédiatement avec defer
    await interaction.response.defer()
    
    channel_id = interaction.channel_id
    
    if channel_id not in streamers or not streamers[channel_id]:
        await interaction.followup.send("📺 Aucun streamer suivi dans ce salon.")
        return
    
    streamer_list = streamers[channel_id]
    embed = discord.Embed(
        title="📺 Streamers Suivis",
        description=f"**{len(streamer_list)}** streamer(s) suivi(s) dans ce salon:",
        color=0x9146ff,
        timestamp=get_current_time()
    )
    
    # Vérifier le statut des streamers
    streams = await twitch_api.get_streams(streamer_list)
    live_streamers = {s['user_login'] for s in streams}
    
    online_list = []
    offline_list = []
    
    for streamer in streamer_list:
        if streamer in live_streamers:
            online_list.append(f"🔴 **{streamer}** (EN LIVE)")
        else:
            offline_list.append(f"⚫ {streamer}")
    
    if online_list:
        embed.add_field(name="🔴 En ligne", value="\n".join(online_list), inline=False)
    
    if offline_list:
        embed.add_field(name="⚫ Hors ligne", value="\n".join(offline_list), inline=False)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="twitchclear", description="Vider la liste des streamers suivis")
async def clear_streamers(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Vous n'avez pas les permissions pour gérer les streamers!", ephemeral=True)
        return
    
    channel_id = interaction.channel_id
    
    if channel_id not in streamers or not streamers[channel_id]:
        await interaction.response.send_message("⚠️ Aucun streamer à supprimer dans ce salon.", ephemeral=True)
        return
    
    count = len(streamers[channel_id])
    streamers[channel_id] = []
    
    # Nettoyer les messages de stream
    keys_to_remove = [key for key in stream_messages.keys() if key.startswith(f"{channel_id}_")]
    for key in keys_to_remove:
        del stream_messages[key]
    
    await interaction.response.send_message(f"✅ Liste vidée! **{count}** streamer(s) retiré(s) de ce salon.")

@bot.tree.command(name="pingrole", description="Associer un rôle à ping quand un stream est en live dans ce salon")
@app_commands.describe(role="Rôle à mentionner")
async def set_ping_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Vous n'avez pas la permission!", ephemeral=True)
        return
    try:
        ping_roles[interaction.channel_id] = role.id
        await interaction.response.send_message(f"✅ Le rôle {role.mention} sera ping lorsque quelqu'un sera en live dans ce salon.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

# === COMMANDE HELP ===

@bot.tree.command(name="helpalpine", description="Afficher toutes les commandes disponibles")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Guide des Commandes - Bot Alpine",
        description="Voici toutes les commandes disponibles organisées par catégorie :",
        color=0x00AE86,
        timestamp=get_current_time()
    )
    
    # Événements
    events_commands = """
`/event-create` - Créer un nouvel événement
`/event-list` - Afficher tous les événements
`/event-info <id>` - Détails d'un événement
`/event-delete <id>` - Supprimer un événement 🔒
    """
    embed.add_field(name="🎉 **Événements**", value=events_commands.strip(), inline=False)
    
    # Configuration
    config_commands = """
`/config-roles` - Configurer les rôles par catégorie 🔒
`/show-config` - Afficher la configuration des rôles
    """
    embed.add_field(name="⚙️ **Configuration**", value=config_commands.strip(), inline=False)
    
    # Twitch
    twitch_commands = """
`/twitchadd <streamers>` - Ajouter streamer(s) à suivre 🔒
`/twitchremove <streamers>` - Retirer streamer(s) 🔒
`/twitchlist` - Voir les streamers suivis
`/twitchclear` - Vider la liste des streamers 🔒
`/pingrole <role>` - Configurer le rôle à ping pour les lives 🔒
    """
    embed.add_field(name="📺 **Twitch**", value=twitch_commands.strip(), inline=False)
    
    # Notifications
    notification_commands = """
`/notification-status` - Statut des notifications
`/restart-notifications` - Redémarrer le système 👑
`/check-notifications` - Forcer une vérification 👑
`/test-notification <id>` - Tester une notification 👑
    """
    embed.add_field(name="🔔 **Notifications**", value=notification_commands.strip(), inline=False)
    
    # Administration
    admin_commands = """
`/sync-commands` - Synchroniser les commandes 👑
`/debug-bot` - Informations de debug 👑
`/ping` - Tester la connexion
`/helpalpine` - Afficher cette aide
    """
    embed.add_field(name="🔧 **Administration**", value=admin_commands.strip(), inline=False)
    
    # Légende
    embed.add_field(
        name="📝 **Légende**",
        value="🔒 = Permissions requises\n👑 = Administrateur seulement",
        inline=False
    )
    
    # Informations supplémentaires
    embed.add_field(
        name="ℹ️ **Informations**",
        value="• Format de date: **DD/MM/YYYY HH:MM**\n• Notifications automatiques: 15min avant + live\n• Timezone: **Europe/Paris**\n• Surveillance Twitch: toutes les 2 minutes",
        inline=False
    )
    
    embed.set_footer(text="Bot Alpine • Développé pour votre serveur Discord")
    
    await interaction.response.send_message(embed=embed)

# === COMMANDES ADMIN/DEBUG ===

@bot.tree.command(name="sync-commands", description="Synchroniser les commandes (admin seulement)")
async def sync_commands(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    try:
        synced_global = await bot.tree.sync()
        guild = discord.Object(id=interaction.guild_id)
        synced_guild = await bot.tree.sync(guild=guild)
        
        await interaction.response.send_message(
            f"✅ Synchronisation terminée!\n"
            f"**Global:** {len(synced_global)} commandes\n"
            f"**Serveur:** {len(synced_guild)} commandes\n"
            f"Commandes disponibles: {[cmd.name for cmd in synced_guild]}",
            ephemeral=True
        )
        print(f"Synchronisé manuellement - Global: {len(synced_global)}, Guild: {len(synced_guild)}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur lors de la synchronisation: {e}", ephemeral=True)
        print(f"Erreur sync: {e}")

@bot.tree.command(name="notification-status", description="Voir le statut des notifications")
async def notification_status(interaction: discord.Interaction):
    status_text = "**📡 Statut du système de notifications:**\n\n"
    
    # Statut du système
    is_running = notification_system.is_running()
    status_text += f"🔄 **Système actif:** {'✅ OUI' if is_running else '❌ NON'}\n"
    status_text += f"📊 **Événements totaux:** {len(events)}\n"
    status_text += f"🔔 **Dans le système de notif:** {len(notifications_sent)}\n\n"
    
    if not events:
        status_text += "📅 Aucun événement en cours."
        await interaction.response.send_message(status_text, ephemeral=True)
        return
    
    now = get_current_time()
    
    for event_id, event in events.items():
        if event.guild_id != interaction.guild_id:
            continue
            
        time_diff = event.date - now
        minutes_until = int(time_diff.total_seconds() / 60)
        
        status_text += f"**Event {event_id}:** {event.name}\n"
        status_text += f"⏰ Dans {minutes_until} minutes ({event.date.strftime('%d/%m %H:%M')})\n"
        
        if event_id in notifications_sent:
            notif_15 = "✅" if notifications_sent[event_id]['15min'] else "❌"
            notif_live = "✅" if notifications_sent[event_id]['live'] else "❌"
            status_text += f"15min: {notif_15} | Live: {notif_live}\n"
        else:
            status_text += "❌ Pas dans le système de notifications\n"
        
        status_text += f"📍 Channel: <#{event.channel_id}>\n\n"
    
    await interaction.response.send_message(status_text, ephemeral=True)

@bot.tree.command(name="restart-notifications", description="Redémarrer le système de notifications (admin)")
async def restart_notifications(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    try:
        # Arrêter le système s'il fonctionne
        if notification_system.is_running():
            notification_system.cancel()
            print("🛑 Système de notifications arrêté")
        
        # Attendre un peu
        await asyncio.sleep(1)
        
        # Redémarrer
        notification_system.start()
        print("🔄 Système de notifications redémarré")
        
        await interaction.response.send_message("✅ Système de notifications redémarré!", ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)
        print(f"Erreur restart notifications: {e}")

@bot.tree.command(name="check-notifications", description="Forcer une vérification des notifications (admin)")
async def check_notifications(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    await interaction.response.send_message("🔍 Vérification forcée des notifications...", ephemeral=True)
    
    # Appeler manuellement la fonction de notification
    try:
        await notification_system.coro()
        await interaction.followup.send("✅ Vérification terminée! Consultez les logs.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)
        print(f"Erreur check notifications: {e}")

@bot.tree.command(name="test-notification", description="Tester une notification (admin seulement)")
@app_commands.describe(event_id="ID de l'événement à tester")
async def test_notification(interaction: discord.Interaction, event_id: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    if event_id not in events:
        await interaction.response.send_message(f"❌ Événement {event_id} introuvable!", ephemeral=True)
        return
    
    event = events[event_id]
    await interaction.response.send_message(f"🧪 Test de notification pour: {event.name}", ephemeral=True)
    
    # Tester notification 15min
    success1 = await send_event_notification(event, 15)
    
    # Attendre 2 secondes puis tester notification live
    await asyncio.sleep(2)
    success2 = await send_event_notification(event, 0)
    
    result = f"Notification 15min: {'✅' if success1 else '❌'}\nNotification Live: {'✅' if success2 else '❌'}"
    await interaction.followup.send(result, ephemeral=True)

@bot.tree.command(name="debug-bot", description="Informations de debug du bot")
async def debug_bot(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    debug_info = f"""**🔧 Debug Bot Info:**

**Système de notifications:**
- Actif: {'✅' if notification_system.is_running() else '❌'}
- Prochaine exécution: {notification_system.next_iteration}

**Système Twitch:**
- Actif: {'✅' if check_streams.is_running() else '❌'}
- Token valide: {'✅' if twitch_api.token else '❌'}

**Données:**
- Événements: {len(events)}
- Notifications tracked: {len(notifications_sent)}
- Configurations rôles: {len(guild_role_configs)}
- Streamers suivis: {len(streamers)}

**Bot:**
- Connecté: {'✅' if bot.is_ready() else '❌'}
- Latence: {round(bot.latency * 1000)}ms
"""
    
    await interaction.response.send_message(debug_info, ephemeral=True)

@bot.tree.command(name="ping", description="Réponds pong")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong !")

# === EVENTS DU BOT ===

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    
    try:
        # Attendre un peu pour être sûr que le bot est prêt
        await asyncio.sleep(2)
        
        # Synchronisation des commandes
        print(f"📋 Commandes enregistrées dans le bot:")
        for cmd in bot.tree.get_commands():
            print(f"  - {cmd.name}: {cmd.description}")
        
        print(f"🔄 Synchronisation des commandes avec Discord...")
        
        # Synchronisation globale ET locale pour être sûr
        synced_global = await bot.tree.sync()
        print(f'✅ {len(synced_global)} commandes synchronisées globalement!')
        
        # Synchronisation spécifique au serveur (optionnel mais peut aider)
        try:
            # Si vous voulez synchroniser pour un serveur spécifique, décommentez ces lignes :
            # guild = discord.Object(id=VOTRE_GUILD_ID_ICI)
            # synced_guild = await bot.tree.sync(guild=guild)
            # print(f'✅ {len(synced_guild)} commandes synchronisées pour le serveur!')
            pass
        except Exception as e:
            print(f"⚠️ Erreur synchronisation serveur: {e}")
        
        print(f"📤 Commandes synchronisées:")
        for cmd in synced_global:
            print(f"  - /{cmd.name}")
        
        # Initialiser l'API Twitch
        await twitch_api.get_token()
        
        # Démarrer les systèmes de tâches
        if not check_streams.is_running():
            check_streams.start()
            print("✅ Système de vérification Twitch démarré!")
        
        if not notification_system.is_running():
            notification_system.start()
            print("✅ Système de notifications démarré!")
        
        # Démarrer le serveur web si nécessaire
        if os.getenv("PORT"):
            asyncio.create_task(start_web_server())
            
        print("🚀 Bot complètement initialisé et prêt!")
            
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        import traceback
        traceback.print_exc()

# Gestion des erreurs
@bot.event
async def on_error(event, *args, **kwargs):
    print(f"Erreur dans {event}: {args} {kwargs}")

@bot.event
async def on_command_error(ctx, error):
    print(f"Erreur de commande: {error}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    print(f"❌ Erreur de slash commande: {error}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Une erreur est survenue lors de l'exécution de la commande.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Une erreur est survenue lors de l'exécution de la commande.", ephemeral=True)
    except Exception as e:
        print(f"Erreur lors de l'envoi du message d'erreur: {e}")

# === DÉMARRAGE ===
async def main():
    try:
        if os.getenv("PORT"):
            asyncio.create_task(start_web_server())
        await bot.start(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        print(f"❌ Erreur dans main(): {e}")

if __name__ == "__main__":
    asyncio.run(main())
