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

# === SERVEUR WEB AMÉLIORÉ ===
web_runner = None
web_site = None

async def start_web_server():
    """Démarrer le serveur web avec gestion d'erreurs améliorée"""
    global web_runner, web_site
    
    try:
        async def health_check(request):
            """Endpoint de santé avec informations détaillées"""
            bot_status = "✅ CONNECTÉ" if bot.is_ready() else "❌ DÉCONNECTÉ"
            notif_status = "✅ ACTIF" if notification_system.is_running() else "❌ ARRÊTÉ"
            twitch_status = "✅ ACTIF" if check_streams.is_running() else "❌ ARRÊTÉ"
            
            health_data = {
                "status": "healthy",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
                "bot": {
                    "connected": bot.is_ready(),
                    "status": bot_status,
                    "latency": f"{round(bot.latency * 1000)}ms" if bot.is_ready() else "N/A",
                    "guilds": len(bot.guilds) if bot.is_ready() else 0
                },
                "services": {
                    "notifications": notif_status,
                    "twitch": twitch_status,
                    "events_count": len(events),
                    "streamers_count": sum(len(s) for s in streamers.values())
                }
            }
            
            return web.Response(
                text=f"🤖 Bot Discord Alpine - Status: {bot_status}\n"
                     f"🔔 Notifications: {notif_status}\n"
                     f"📺 Twitch: {twitch_status}\n"
                     f"⏰ {datetime.now(TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')} (Paris)\n"
                     f"📊 {len(events)} événements, {sum(len(s) for s in streamers.values())} streamers",
                status=200,
                headers={'Content-Type': 'text/plain; charset=utf-8'}
            )
        
        async def health_json(request):
            """Endpoint JSON pour monitoring avancé"""
            bot_status = bot.is_ready()
            notif_status = notification_system.is_running()
            twitch_status = check_streams.is_running()
            
            health_data = {
                "status": "healthy" if (bot_status and notif_status) else "degraded",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
                "bot": {
                    "connected": bot_status,
                    "latency_ms": round(bot.latency * 1000) if bot_status else None,
                    "guilds": len(bot.guilds) if bot_status else 0
                },
                "services": {
                    "notifications_running": notif_status,
                    "twitch_running": twitch_status,
                    "events_count": len(events),
                    "streamers_count": sum(len(s) for s in streamers.values()),
                    "active_streams": len(stream_messages)
                },
                "uptime": "running"  # Vous pouvez ajouter un vrai uptime si nécessaire
            }
            
            return web.json_response(health_data)
        
        async def ping(request):
            """Simple endpoint ping"""
            return web.Response(text="pong", status=200)
        
        # Créer l'application web
        app = web.Application()
        
        # Ajouter les routes
        app.router.add_get('/', health_check)
        app.router.add_get('/health', health_check)
        app.router.add_get('/health.json', health_json)
        app.router.add_get('/ping', ping)
        app.router.add_get('/status', health_check)
        
        # Configuration du serveur
        port = int(os.getenv('PORT', 8080))
        host = '0.0.0.0'
        
        # Démarrer le serveur avec gestion d'erreurs
        web_runner = web.AppRunner(app)
        await web_runner.setup()
        
        web_site = web.TCPSite(web_runner, host, port)
        await web_site.start()
        
        print(f"🌐 Serveur web démarré avec succès:")
        print(f"   - Adresse: http://{host}:{port}")
        print(f"   - Health check: http://{host}:{port}/health")
        print(f"   - JSON status: http://{host}:{port}/health.json")
        print(f"   - Ping: http://{host}:{port}/ping")
        
        return True
        
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE - Serveur web: {e}")
        import traceback
        traceback.print_exc()
        return False

async def stop_web_server():
    """Arrêter proprement le serveur web"""
    global web_runner, web_site
    
    try:
        if web_site:
            await web_site.stop()
            web_site = None
            print("🛑 Site web arrêté")
        
        if web_runner:
            await web_runner.cleanup()
            web_runner = None
            print("🛑 Runner web nettoyé")
            
    except Exception as e:
        print(f"⚠️ Erreur lors de l'arrêt du serveur web: {e}")

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

def format_viewer_count(count):
    """Formate le nombre de viewers de manière lisible"""
    if count >= 1000:
        return f"{count//1000}k"
    return str(count)

@tasks.loop(minutes=2)  # ✅ Confirmé : toutes les 2 minutes
async def check_streams():
    print(f"🔄 Vérification des streams Twitch - {datetime.now(TIMEZONE).strftime('%H:%M:%S')}")
    
    for channel_id, streamer_list in streamers.items():
        if not streamer_list:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        streams = await twitch_api.get_streams(streamer_list)
        live_now = {s['user_login']: s for s in streams}
        
        # Vérifier les nouveaux streams
        for username, stream in live_now.items():
            key = f"{channel_id}_{username}"
            if key in stream_messages:
                continue  # already live
            
            # ✅ NOUVEAU : Embed avec nombre de viewers
            embed = discord.Embed(
                title=f"🔴 {stream['user_name']} est en live !",
                description=stream['title'],
                url=f"https://twitch.tv/{username}",
                color=0x9146ff
            )
            
            # ✅ NOUVEAU : Ajouter le nombre de viewers
            viewer_count = stream.get('viewer_count', 0)
            embed.add_field(
                name="👥 Viewers", 
                value=f"**{format_viewer_count(viewer_count)}** spectateurs", 
                inline=True
            )
            
            # Ajouter la catégorie/jeu si disponible
            if stream.get('game_name'):
                embed.add_field(
                    name="🎮 Jeu", 
                    value=stream['game_name'], 
                    inline=True
                )
            
            # Thumbnail
            thumbnail_url = stream.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
            if thumbnail_url:
                embed.set_image(url=thumbnail_url)
            
            # ✅ NOUVEAU : Footer avec heure de début du stream
            started_at = datetime.fromisoformat(stream['started_at'].replace('Z', '+00:00'))
            started_at_paris = started_at.astimezone(TIMEZONE)
            embed.set_footer(
                text=f"Stream commencé à {started_at_paris.strftime('%H:%M')} • Mise à jour toutes les 2 min"
            )
            
            ping_content = f"<@&{ping_roles.get(channel_id)}>" if ping_roles.get(channel_id) else None
            msg = await channel.send(content=ping_content, embed=embed)
            stream_messages[key] = {
                'message_id': msg.id, 
                'last_update': datetime.now(UTC).timestamp(),
                'message_obj': msg  # ✅ NOUVEAU : Stocker l'objet message pour les mises à jour
            }
            
            print(f"📺 Nouveau stream détecté: {stream['user_name']} ({viewer_count} viewers)")

        # ✅ NOUVEAU : Mettre à jour les embeds existants avec le nouveau nombre de viewers
        for username in streamer_list:
            key = f"{channel_id}_{username}"
            
            # Si le stream est toujours live, mettre à jour les viewers
            if key in stream_messages and username in live_now:
                try:
                    stream = live_now[username]
                    stored_msg = stream_messages[key]
                    
                    # Récupérer le message Discord
                    if 'message_obj' in stored_msg:
                        message = stored_msg['message_obj']
                    else:
                        message = await channel.fetch_message(stored_msg['message_id'])
                        stream_messages[key]['message_obj'] = message
                    
                    # Créer l'embed mis à jour
                    updated_embed = discord.Embed(
                        title=f"🔴 {stream['user_name']} est en live !",
                        description=stream['title'],
                        url=f"https://twitch.tv/{username}",
                        color=0x9146ff
                    )
                    
                    viewer_count = stream.get('viewer_count', 0)
                    updated_embed.add_field(
                        name="👥 Viewers", 
                        value=f"**{format_viewer_count(viewer_count)}** spectateurs", 
                        inline=True
                    )
                    
                    if stream.get('game_name'):
                        updated_embed.add_field(
                            name="🎮 Jeu", 
                            value=stream['game_name'], 
                            inline=True
                        )
                    
                    thumbnail_url = stream.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
                    if thumbnail_url:
                        updated_embed.set_image(url=thumbnail_url)
                    
                    started_at = datetime.fromisoformat(stream['started_at'].replace('Z', '+00:00'))
                    started_at_paris = started_at.astimezone(TIMEZONE)
                    updated_embed.set_footer(
                        text=f"Stream commencé à {started_at_paris.strftime('%H:%M')} • Dernière MàJ: {datetime.now(TIMEZONE).strftime('%H:%M')}"
                    )
                    
                    # Mettre à jour le message
                    await message.edit(embed=updated_embed)
                    stream_messages[key]['last_update'] = datetime.now(UTC).timestamp()
                    
                    print(f"🔄 Stream mis à jour: {stream['user_name']} ({viewer_count} viewers)")
                    
                except Exception as e:
                    print(f"❌ Erreur mise à jour embed pour {username}: {e}")
            
            # Si le stream n'est plus live, supprimer le message
            elif key in stream_messages and username not in live_now:
                try:
                    if 'message_obj' in stream_messages[key]:
                        await stream_messages[key]['message_obj'].delete()
                    else:
                        message = await channel.fetch_message(stream_messages[key]['message_id'])
                        await message.delete()
                    print(f"📴 Stream terminé: {username}")
                except:
                    pass  # Message déjà supprimé ou inaccessible
                del stream_messages[key]

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
- Actif: {'✅ (2min)' if check_streams.is_running() else '❌'}
- Token valide: {'✅' if twitch_api.token else '❌'}
- Prochaine vérification: {check_streams.next_iteration}

**Serveur Web:**
- Runner actif: {'✅' if web_runner is not None else '❌'}
- Site actif: {'✅' if web_site is not None else '❌'}
- Port configuré: {os.getenv('PORT', '8080')}

**Données:**
- Événements: {len(events)}
- Notifications tracked: {len(notifications_sent)}
- Configurations rôles: {len(guild_role_configs)}
- Streamers suivis: {sum(len(s) for s in streamers.values())}
- Messages de stream actifs: {len(stream_messages)}

**Bot:**
- Connecté: {'✅' if bot.is_ready() else '❌'}
- Latence: {round(bot.latency * 1000)}ms
- Guilds: {len(bot.guilds)}
"""
    
    await interaction.response.send_message(debug_info, ephemeral=True)

@bot.tree.command(name="ping", description="Tester la connexion du bot")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 Pong !",
        color=0x00AE86,
        timestamp=get_current_time()
    )
    
    embed.add_field(name="⚡ Latence", value=f"{latency}ms", inline=True)
    embed.add_field(name="🤖 Statut", value="✅ En ligne" if bot.is_ready() else "❌ Hors ligne", inline=True)
    embed.add_field(name="🌐 Serveur Web", value="✅ Actif" if web_runner is not None else "❌ Inactif", inline=True)
    
    await interaction.response.send_message(embed=embed)

# === EVENTS DU BOT ===

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    print(f"🆔 ID du bot: {bot.user.id}")
    print(f"🏰 Connecté à {len(bot.guilds)} serveur(s)")
    
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
        
        print(f"📤 Commandes synchronisées:")
        for cmd in synced_global:
            print(f"  - /{cmd.name}")
        
        # Initialiser l'API Twitch
        print("🔗 Initialisation de l'API Twitch...")
        await twitch_api.get_token()
        if twitch_api.token:
            print("✅ Token Twitch obtenu avec succès!")
        else:
            print("⚠️ Impossible d'obtenir le token Twitch")
        
        # Démarrer les systèmes de tâches
        if not check_streams.is_running():
            check_streams.start()
            print("✅ Système de vérification Twitch démarré! (toutes les 2 minutes)")
        else:
            print("ℹ️ Système Twitch déjà en cours d'exécution")
        
        if not notification_system.is_running():
            notification_system.start()
            print("✅ Système de notifications démarré!")
        else:
            print("ℹ️ Système de notifications déjà en cours d'exécution")
        
        # Démarrer le serveur web si le PORT est défini
        port_env = os.getenv("PORT")
        if port_env:
            print(f"🌐 Démarrage du serveur web sur le port {port_env}...")
            success = await start_web_server()
            if success:
                print("✅ Serveur web démarré avec succès!")
            else:
                print("❌ ÉCHEC du démarrage du serveur web!")
        else:
            print("⚠️ Variable PORT non définie, serveur web non démarré")
            
        print("🚀 Bot complètement initialisé et prêt!")
        print("="*50)
        print("📊 RÉSUMÉ DE L'INITIALISATION:")
        print(f"  🤖 Bot connecté: ✅")
        print(f"  📋 Commandes sync: ✅ ({len(synced_global)})")
        print(f"  📺 Système Twitch: {'✅' if check_streams.is_running() else '❌'}")
        print(f"  🔔 Notifications: {'✅' if notification_system.is_running() else '❌'}")
        print(f"  🌐 Serveur web: {'✅' if web_runner is not None else '❌'}")
        print(f"  🔑 Token Twitch: {'✅' if twitch_api.token else '❌'}")
        print("="*50)
            
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE lors de l'initialisation: {e}")
        import traceback
        traceback.print_exc()
        print("⚠️ Le bot peut ne pas fonctionner correctement!")

# Gestion des erreurs améliorée
@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ Erreur dans l'event {event}: {args} {kwargs}")
    import traceback
    traceback.print_exc()

@bot.event
async def on_command_error(ctx, error):
    print(f"❌ Erreur de commande: {error}")
    import traceback
    traceback.print_exc()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    print(f"❌ Erreur de slash commande: {error}")
    import traceback
    traceback.print_exc()
    
    try:
        error_msg = "❌ Une erreur est survenue lors de l'exécution de la commande."
        
        # Messages d'erreur plus spécifiques
        if "Missing Access" in str(error):
            error_msg = "❌ Le bot n'a pas les permissions nécessaires pour cette action."
        elif "Unknown Channel" in str(error):
            error_msg = "❌ Canal introuvable ou inaccessible."
        elif "Unknown Guild" in str(error):
            error_msg = "❌ Serveur introuvable."
        elif "HTTPException" in str(error):
            error_msg = "❌ Erreur de communication avec Discord. Réessayez dans quelques secondes."
        
        if not interaction.response.is_done():
            await interaction.response.send_message(error_msg, ephemeral=True)
        else:
            await interaction.followup.send(error_msg, ephemeral=True)
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi du message d'erreur: {e}")

# === SIGNAL HANDLERS POUR ARRÊT PROPRE ===
import signal

def signal_handler(signum, frame):
    print(f"\n🛑 Signal {signum} reçu, arrêt du bot...")
    asyncio.create_task(shutdown_bot())

async def shutdown_bot():
    """Arrêt propre du bot et de tous ses services"""
    print("🔄 Arrêt en cours...")
    
    try:
        # Arrêter les tâches
        if check_streams.is_running():
            check_streams.cancel()
            print("🛑 Système Twitch arrêté")
        
        if notification_system.is_running():
            notification_system.cancel()
            print("🛑 Système de notifications arrêté")
        
        # Arrêter le serveur web
        await stop_web_server()
        
        # Fermer le bot
        await bot.close()
        print("🛑 Bot fermé proprement")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt: {e}")
    
    finally:
        print("👋 Goodbye!")

# Enregistrer les handlers de signaux
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, signal_handler)
if hasattr(signal, 'SIGINT'):
    signal.signal(signal.SIGINT, signal_handler)

# === DÉMARRAGE ===
if __name__ == '__main__':
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant dans les variables d'environnement!")
        print("💡 Assurez-vous que la variable DISCORD_TOKEN est définie")
        exit(1)
    
    print("🚀 Démarrage du Bot Alpine...")
    print(f"🔧 Variables d'environnement:")
    print(f"  - DISCORD_TOKEN: {'✅ Défini' if token else '❌ Manquant'}")
    print(f"  - TWITCH_CLIENT_ID: {'✅ Défini' if os.getenv('TWITCH_CLIENT_ID') else '❌ Manquant'}")
    print(f"  - TWITCH_CLIENT_SECRET: {'✅ Défini' if os.getenv('TWITCH_CLIENT_SECRET') else '❌ Manquant'}")
    print(f"  - PORT: {'✅ ' + os.getenv('PORT') if os.getenv('PORT') else '❌ Non défini'}")
    print("-" * 50)
    
    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt manuel détecté...")
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE lors du démarrage du bot: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("👋 Bot arrêté!")
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
    live_streamers = {s['user_login']: s for s in streams}
    
    online_list = []
    offline_list = []
    
    for streamer in streamer_list:
        if streamer in live_streamers:
            stream_data = live_streamers[streamer]
            viewer_count = stream_data.get('viewer_count', 0)
            online_list.append(f"🔴 **{streamer}** - {format_viewer_count(viewer_count)} viewers")
        else:
            offline_list.append(f"⚫ {streamer}")
    
    if online_list:
        embed.add_field(name="🔴 En ligne", value="\n".join(online_list), inline=False)
    
    if offline_list:
        embed.add_field(name="⚫ Hors ligne", value="\n".join(offline_list), inline=False)
    
    embed.set_footer(text="📡 Vérification toutes les 2 minutes")
    
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
`/twitchlist` - Voir les streamers suivis (avec viewers)
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
`/server-status` - Statut du serveur web 👑
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
        value="• Format de date: **DD/MM/YYYY HH:MM**\n• Notifications automatiques: 15min avant + live\n• Timezone: **Europe/Paris**\n• **Surveillance Twitch: toutes les 2 minutes avec viewers**",
        inline=False
    )
    
    embed.set_footer(text="Bot Alpine • Développé pour votre serveur Discord")
    
    await interaction.response.send_message(embed=embed)

# === COMMANDES ADMIN/DEBUG ===

@bot.tree.command(name="server-status", description="Vérifier le statut du serveur web (admin)")
async def server_status(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    global web_runner, web_site
    
    embed = discord.Embed(
        title="🌐 Statut du Serveur Web",
        color=0x00AE86,
        timestamp=get_current_time()
    )
    
    # Vérifier l'état du serveur
    web_running = web_runner is not None and web_site is not None
    port = os.getenv('PORT', 8080)
    
    embed.add_field(
        name="🚀 Serveur Web",
        value="✅ Actif" if web_running else "❌ Inactif",
        inline=True
    )
    
    embed.add_field(
        name="🔌 Port",
        value=f":{port}",
        inline=True
    )
    
    embed.add_field(
        name="🌍 Endpoints",
        value="• `/` - Status principal\n• `/health` - Santé\n• `/health.json` - JSON\n• `/ping` - Test simple",
        inline=False
    )
    
    # Test de connectivité interne
    try:
        # Simuler une requête interne
        if web_running:
            embed.add_field(
                name="🔍 Test Interne",
                value="✅ Serveur accessible",
                inline=True
            )
        else:
            embed.add_field(
                name="🔍 Test Interne",
                value="❌ Serveur non accessible",
                inline=True
            )
    except Exception as e:
        embed.add_field(
            name="🔍 Test Interne",
            value=f"❌ Erreur: {str(e)[:50]}...",
            inline=True
        )
    
    embed.add_field(
        name="📊 Variables d'environnement",
        value=f"PORT: {'✅ Défini' if os.getenv('PORT') else '❌ Non défini'}",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="restart-webserver", description="Redémarrer le serveur web (admin)")
async def restart_webserver(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent utiliser cette commande!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Arrêter le serveur existant
        await stop_web_server()
        await asyncio.sleep(2)
        
        # Redémarrer
        success = await start_web_server()
        
        if success:
            await interaction.followup.send("✅ Serveur web redémarré avec succès!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Échec du redémarrage du serveur web!", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur lors du redémarrage: {e}", ephemeral=True)

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
    twitch_running = check_streams.is_running()
    status_text += f"🔄 **Système actif:** {'✅ OUI' if is_running else '❌ NON'}\n"
    status_text += f"📺 **Twitch actif:** {'✅ OUI (2min)' if twitch_running else '❌ NON'}\n"
    status_text += f"🌐 **Serveur web:** {'✅ OUI' if web_runner is not None else '❌ NON'}\n"
    status_text += f"📊 **Événements totaux:** {len(events)}\n"
    status_text += f"🔔 **Dans le système de notif:** {len(notifications_sent)}\n"
    status_text += f"📡 **Streams suivis:** {sum(len(s) for s in streamers.values())}\n\n"
    
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
        await interaction.followup.send(
