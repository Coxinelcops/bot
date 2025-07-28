# bot_fix_sync.py - Version avec synchronisation forcée

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

print("🔄 Démarrage du bot...")

# Intents
intents = discord.Intents.default()
intents.message_content = True

# Bot
bot = commands.Bot(command_prefix='!', intents=intents)

# === COMMANDES ===
@bot.tree.command(name="test", description="Commande de test")
async def test_command(interaction: discord.Interaction):
    """Commande de test simple"""
    print(f"✅ Commande /test reçue de {interaction.user}")
    await interaction.response.send_message("🎉 Le bot fonctionne parfaitement !")

@bot.tree.command(name="ping", description="Test de latence")
async def ping_command(interaction: discord.Interaction):
    """Test de ping"""
    latency = round(bot.latency * 1000)
    print(f"✅ Commande /ping reçue - Latence: {latency}ms")
    await interaction.response.send_message(f"🏓 Pong! Latence: {latency}ms")

@bot.tree.command(name="info", description="Informations du bot")
async def info_command(interaction: discord.Interaction):
    """Informations du bot"""
    embed = discord.Embed(
        title="ℹ️ Informations du Bot",
        color=0x00ff00
    )
    embed.add_field(name="Nom", value=bot.user.name, inline=True)
    embed.add_field(name="ID", value=bot.user.id, inline=True)
    embed.add_field(name="Latence", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="Serveur", value=interaction.guild.name, inline=True)
    embed.add_field(name="Utilisateur", value=interaction.user.display_name, inline=True)
    
    await interaction.response.send_message(embed=embed)

# === ÉVÉNEMENTS ===
@bot.event
async def on_ready():
    print(f"🟢 Bot connecté: {bot.user} (ID: {bot.user.id})")
    print(f"📊 Connecté à {len(bot.guilds)} serveur(s)")
    
    # Afficher les serveurs
    for guild in bot.guilds:
        print(f"  🏠 {guild.name} (ID: {guild.id}) - {guild.member_count} membres")
    
    # SYNCHRONISATION FORCÉE DES COMMANDES
    print("\n🔄 === SYNCHRONISATION DES COMMANDES ===")
    
    try:
        # 1. Vérifier que les commandes sont bien enregistrées
        print(f"📋 Commandes enregistrées dans le bot: {len(bot.tree.get_commands())}")
        for cmd in bot.tree.get_commands():
            print(f"  - {cmd.name}: {cmd.description}")
        
        if len(bot.tree.get_commands()) == 0:
            print("❌ PROBLÈME: Aucune commande trouvée dans bot.tree!")
            return
        
        # 2. Synchronisation globale
        print("🌍 Synchronisation globale...")
        synced_global = await bot.tree.sync()
        print(f"✅ Synchronisation globale: {len(synced_global)} commandes")
        
        # 3. Synchronisation par serveur (plus rapide)
        for guild in bot.guilds:
            print(f"🏠 Synchronisation pour {guild.name}...")
            try:
                # Copier les commandes globales vers le serveur
                bot.tree.copy_global_to(guild=guild)
                synced_guild = await bot.tree.sync(guild=guild)
                print(f"✅ {guild.name}: {len(synced_guild)} commandes synchronisées")
                
                # Afficher les commandes synced
                for cmd in synced_guild:
                    print(f"    - /{cmd.name}")
                    
            except Exception as e:
                print(f"❌ Erreur sync {guild.name}: {e}")
        
        print("\n🚀 === SYNCHRONISATION TERMINÉE ===")
        print("💡 Les commandes peuvent prendre quelques minutes à apparaître dans Discord")
        print("🔍 Commandes disponibles: /test, /ping, /info")
        
    except Exception as e:
        print(f"❌ ERREUR LORS DE LA SYNCHRONISATION: {e}")
        import traceback
        traceback.print_exc()

@bot.event 
async def on_interaction(interaction):
    """Capturer toutes les interactions pour debug"""
    if interaction.type == discord.InteractionType.application_command:
        cmd_name = interaction.data.get('name', 'INCONNUE')
        print(f"🎯 Interaction reçue: /{cmd_name} de {interaction.user}")

@bot.event
async def on_application_command_error(interaction, error):
    """Gestion des erreurs de commandes"""
    print(f"❌ Erreur commande: {error}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Erreur: {error}", ephemeral=True)
    except:
        pass

# === COMMANDE MANUELLE DE SYNC ===
@bot.command(name='sync')
async def sync_commands(ctx):
    """Commande prefix pour forcer la sync (backup)"""
    if ctx.author.guild_permissions.administrator:
        print("🔄 Synchronisation manuelle demandée...")
        try:
            # Sync global
            synced = await bot.tree.sync()
            await ctx.send(f"✅ {len(synced)} commandes synchronisées globalement!")
            
            # Sync guild
            if ctx.guild:
                bot.tree.copy_global_to(guild=ctx.guild)
                synced_guild = await bot.tree.sync(guild=ctx.guild)
                await ctx.send(f"✅ {len(synced_guild)} commandes synchronisées pour ce serveur!")
                
        except Exception as e:
            await ctx.send(f"❌ Erreur: {e}")
    else:
        await ctx.send("❌ Permissions administrateur requises!")

# === DÉMARRAGE ===
async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant!")
        return
    
    print(f"🔑 Token trouvé (longueur: {len(token)})")
    
    try:
        # Démarrage avec gestion propre
        async with bot:
            print("🔄 Connexion au bot...")
            await bot.start(token)
    except Exception as e:
        print(f"❌ Erreur de démarrage: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot arrêté")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
