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

# Configuration du logging pour debug
logging.basicConfig(level=logging.INFO)

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

# === SERVEUR WEB (render) - Version simplifiée ===
async def start_web_server():
    try:
        async def health_check(request):
            return web.Response(text="Bot Discord actif ✅", status=200)
        app = web.Application()
        app.router.add_get('/', health_check)
        app.router.add_get('/health', health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        print(f"🌐 Serveur web démarré sur le port {os.getenv('PORT', 8080)}")
    except Exception as e:
        print(f"⚠️ Erreur serveur web: {e}")

# === VARIABLES GLOBALES ===
# Twitch
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
streamers = {}
stream_messages = {}
currently_live_streamers = {}
ping_roles = {}

# Events
events = {}
event_id_counter = 1
event_messages = {}
notifications_sent = {}
guild_role_configs = {}
notification_messages = {}

# === TWITCH API ===
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
                    print("✅ Token Twitch obtenu avec succès")
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

# === CLASSES EVENTS ===
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

# === COMMANDES SLASH ===

@bot.tree.command(name="ping", description="Test de connexion")
async def ping(interaction: discord.Interaction):
    """Commande simple pour tester"""
    try:
        latency = round(bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latence: {latency}ms")
        print(f"✅ Commande ping exécutée avec succès par {interaction.user}")
    except Exception as e:
        print(f"❌ Erreur dans ping: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'exécution", ephemeral=True)

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
        print(f"🎯 Création d'événement par {interaction.user}: {nom}")
        
        # Valider la date AVANT de defer
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
        
        event = Event(event_id_counter, nom, dt, interaction.user.display_name, interaction.guild_id, interaction.channel_id, 
                      role.id if role else None, category, stream, lieu, image, description)
        events[event_id_counter] = event
        embed = create_event_embed(event, detailed=True)
        
        # Envoyer l'embed dans le canal
        message = await interaction.followup.send(embed=embed)
        
        # Stocker le message pour pouvoir le supprimer plus tard
        event_messages[event_id_counter] = message
        
        notifications_sent[event_id_counter] = {"15min": False, "live": False}
        notification_messages[event_id_counter] = []
        event_id_counter += 1
        
        print(f"✅ Événement créé avec succès: ID {event_id_counter-1}")
        
    except Exception as e:
        print(f"❌ Erreur dans create_event: {e}")
        import traceback
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Erreur: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Erreur: {str(e)}", ephemeral=True)
        except:
            pass

@bot.tree.command(name="event-list", description="Afficher tous les événements")
async def list_events(interaction: discord.Interaction):
    try:
        print(f"📋 Liste des événements demandée par {interaction.user}")
        await interaction.response.defer()
        
        guild_events = [event for event in events.values() if event.guild_id == interaction.guild_id]
        guild_events.sort(key=lambda x: x.date)
        
        if not guild_events:
            await interaction.followup.send("📅 Aucun événement programmé pour le moment.")
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
        
        embed.set_footer(text=f"Total: {len(guild_events)} événement(s)")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"❌ Erreur dans list_events: {e}")
        await interaction.followup.send("❌ Erreur lors de la récupération des événements", ephemeral=True)

@bot.tree.command(name="helpalpine", description="Afficher toutes les commandes disponibles")
async def help_command(interaction: discord.Interaction):
    try:
        embed = discord.Embed(
            title="📋 Guide des Commandes - Bot Alpine",
            description="Voici toutes les commandes disponibles :",
            color=0x00AE86,
            timestamp=get_current_time()
        )
        
        # Événements
        events_commands = """
`/event-create` - Créer un nouvel événement
`/event-list` - Afficher tous les événements
`/ping` - Tester la connexion
`/helpalpine` - Afficher cette aide
        """
        embed.add_field(name="🎉 **Commandes Disponibles**", value=events_commands.strip(), inline=False)
        
        # Informations
        embed.add_field(
            name="ℹ️ **Informations**",
            value="• Format de date: **DD/MM/YYYY HH:MM**\n• Timezone: **Europe/Paris**",
            inline=False
        )
        
        embed.set_footer(text="Bot Alpine • Version simplifiée pour debug")
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"❌ Erreur dans help: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'affichage de l'aide", ephemeral=True)

# === TÂCHES EN ARRIÈRE-PLAN (SIMPLIFIÉES) ===

@tasks.loop(minutes=5)  # Réduit pour éviter les erreurs
async def check_streams():
    try:
        if not streamers:
            return
            
        for channel_id, streamer_list in streamers.items():
            if not streamer_list:
                continue
                
            channel = bot.get_channel(channel_id)
            if not channel:
                continue
                
            streams = await twitch_api.get_streams(streamer_list)
            # Logique simplifiée pour les streams
            
    except Exception as e:
        print(f"❌ Erreur check_streams: {e}")

@tasks.loop(minutes=1)
async def notification_system():
    try:
        if not events:
            return
            
        now = get_current_time()
        
        for event_id, event in list(events.items()):
            if event_id not in notifications_sent:
                continue
                
            delta = event.date - now
            minutes = int(delta.total_seconds() / 60)
            
            # Logique de notification simplifiée
            # TODO: Réimplémentation complète après tests de base
            
    except Exception as e:
        print(f"❌ Erreur notification_system: {e}")

# === ÉVÉNEMENTS DU BOT ===

@bot.event
async def on_ready():
    print(f"🟢 Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    print(f"🔗 Invité sur {len(bot.guilds)} serveur(s)")
    
    try:
        # Synchronisation des commandes
        print("🔄 Synchronisation des commandes...")
        
        # Sync global simple
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées!")
        
        # Afficher les commandes synced
        for cmd in synced:
            print(f"  - /{cmd.name}: {cmd.description}")
        
        # Initialiser l'API Twitch
        await twitch_api.get_token()
        
        # Démarrer le serveur web pour Render
        if os.getenv("PORT"):
            asyncio.create_task(start_web_server())
        
        print("🚀 Bot prêt à recevoir des commandes!")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_guild_join(guild):
    print(f"✅ Rejoint le serveur: {guild.name} (ID: {guild.id})")

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error):
    print(f"❌ Erreur de commande slash: {error}")
    print(f"   Commande: {interaction.command.name if interaction.command else 'Inconnue'}")
    print(f"   Utilisateur: {interaction.user}")
    print(f"   Serveur: {interaction.guild.name if interaction.guild else 'DM'}")
    
    import traceback
    traceback.print_exc()
    
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ Erreur lors de l'exécution de la commande: {str(error)}", 
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ Erreur lors de l'exécution de la commande: {str(error)}", 
                ephemeral=True
            )
    except Exception as e:
        print(f"❌ Impossible d'envoyer le message d'erreur: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ Erreur générale dans {event}: {args}")
    import traceback
    traceback.print_exc()

# === DÉMARRAGE ===
async def main():
    """Fonction principale pour démarrer le bot"""
    try:
        print("🔄 Démarrage du bot...")
        
        # Vérifier le token
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            print("❌ DISCORD_TOKEN manquant dans les variables d'environnement!")
            return
            
        print(f"✅ Token Discord trouvé (longueur: {len(token)})")
        
        # Démarrer le bot
        await bot.start(token)
        
    except Exception as e:
        print(f"❌ Erreur critique au démarrage: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot arrêté par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
