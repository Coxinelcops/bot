# bot_minimal_debug.py - Version ultra-simple pour diagnostic

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import logging

# Configuration du logging pour voir TOUT ce qui se passe
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

print("🔄 Démarrage du script...")

# Intents minimaux
intents = discord.Intents.default()
intents.message_content = True

# Bot avec prefix minimal
bot = commands.Bot(command_prefix='!', intents=intents)

print("✅ Bot créé avec succès")

# === COMMANDE ULTRA-SIMPLE ===
@bot.tree.command(name="test", description="Test ultra-simple")
async def test_command(interaction: discord.Interaction):
    """Commande la plus simple possible"""
    print(f"🎯 COMMANDE REÇUE de {interaction.user} dans {interaction.guild}")
    print(f"🎯 Type interaction: {type(interaction)}")
    print(f"🎯 Interaction ID: {interaction.id}")
    
    try:
        print("🔄 Tentative de réponse...")
        await interaction.response.send_message("✅ Bot fonctionnel!")
        print("✅ Réponse envoyée avec succès!")
    except Exception as e:
        print(f"❌ Erreur lors de la réponse: {e}")
        print(f"❌ Type d'erreur: {type(e)}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="debug", description="Informations de debug")
async def debug_command(interaction: discord.Interaction):
    """Commande de debug"""
    print(f"🔍 DEBUG demandé par {interaction.user}")
    
    try:
        info = f"""
**Debug Info:**
- Bot User: {bot.user}
- Bot ID: {bot.user.id}
- Latence: {round(bot.latency * 1000)}ms
- Serveur: {interaction.guild.name}
- Channel: {interaction.channel.name}
- User: {interaction.user}
"""
        await interaction.response.send_message(info)
        print("✅ Debug envoyé")
    except Exception as e:
        print(f"❌ Erreur debug: {e}")
        import traceback
        traceback.print_exc()

# === ÉVÉNEMENTS ===
@bot.event
async def on_ready():
    print(f"🟢 Bot connecté: {bot.user} (ID: {bot.user.id})")
    print(f"🔗 Serveurs: {len(bot.guilds)}")
    
    for guild in bot.guilds:
        print(f"  - {guild.name} (ID: {guild.id})")
    
    try:
        print("🔄 Synchronisation des commandes...")
        
        # Test 1: Sync global
        synced_global = await bot.tree.sync()
        print(f"✅ Sync global: {len(synced_global)} commandes")
        
        for cmd in synced_global:
            print(f"  - {cmd.name}: {cmd.description}")
        
        # Test 2: Sync spécifique pour chaque serveur
        for guild in bot.guilds:
            try:
                guild_obj = discord.Object(id=guild.id)
                synced_guild = await bot.tree.sync(guild=guild_obj)
                print(f"✅ Sync {guild.name}: {len(synced_guild)} commandes")
            except Exception as e:
                print(f"❌ Erreur sync {guild.name}: {e}")
        
        print("🚀 Bot prêt! Testez /test")
        
    except Exception as e:
        print(f"❌ Erreur lors de la synchronisation: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_guild_join(guild):
    print(f"✅ Rejoint: {guild.name} (ID: {guild.id})")

@bot.event
async def on_interaction(interaction):
    """Capturer TOUTES les interactions"""
    print(f"🎯 INTERACTION REÇUE!")
    print(f"  Type: {interaction.type}")
    print(f"  User: {interaction.user}")
    print(f"  Guild: {interaction.guild}")
    print(f"  Channel: {interaction.channel}")
    
    if interaction.type == discord.InteractionType.application_command:
        print(f"  Commande: {interaction.data.get('name', 'INCONNUE')}")

@bot.event
async def on_application_command_error(interaction, error):
    print(f"❌❌❌ ERREUR DE COMMANDE SLASH ❌❌❌")
    print(f"Commande: {interaction.command.name if interaction.command else 'INCONNUE'}")
    print(f"User: {interaction.user}")
    print(f"Guild: {interaction.guild}")
    print(f"Erreur: {error}")
    print(f"Type erreur: {type(error)}")
    
    import traceback
    traceback.print_exc()
    
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Erreur: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Erreur: {error}", ephemeral=True)
    except Exception as send_error:
        print(f"❌ Impossible d'envoyer l'erreur: {send_error}")

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌❌❌ ERREUR GÉNÉRALE ❌❌❌")
    print(f"Event: {event}")
    print(f"Args: {args}")
    print(f"Kwargs: {kwargs}")
    import traceback
    traceback.print_exc()

# === DÉMARRAGE ===
async def main():
    print("🔄 Fonction main() démarrée")
    
    # Vérifier le token
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant!")
        return
    
    print(f"✅ Token trouvé (longueur: {len(token)})")
    print(f"✅ Token commence par: {token[:10]}...")
    
    try:
        print("🔄 Tentative de connexion...")
        async with bot:
            await bot.start(token)
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print("🚀 Script lancé directement")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt manuel")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
