import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
import json
import os

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = "VOTRE_TOKEN_BOT_DISCORD"
CHANNEL_ID = 123456789  # ID du canal où envoyer les notifications
CHECK_INTERVAL = 180  # 3 minutes en secondes
ERROR_MESSAGE = "Veuillez réessayer quand l'invocateur sera dans une partie."
MAX_RETRIES = 3  # Nombre de vérifications avant de considérer un changement comme valide

class SiteMonitor:
    def __init__(self):
        self.monitored_sites = {}  # {url: {"status": "offline/online", "retries": 0, "last_check": datetime, "pseudo": str, "role": str}}
        
    def add_site(self, url, pseudo=None, role=None):
        """Ajouter un site à surveiller"""
        self.monitored_sites[url] = {
            "status": "unknown",
            "retries": 0,
            "last_check": None,
            "pseudo": pseudo,
            "role": role
        }
        
    def remove_site(self, url):
        """Supprimer un site de la surveillance"""
        if url in self.monitored_sites:
            del self.monitored_sites[url]
            return True
        return False
    
    async def check_site(self, url, session):
        """Vérifier l'état d'un site"""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    content = await response.text()
                    has_error_message = ERROR_MESSAGE in content
                    return "offline" if has_error_message else "online"
                else:
                    logger.warning(f"Status HTTP {response.status} pour {url}")
                    return "error"
        except asyncio.TimeoutError:
            logger.warning(f"Timeout pour {url}")
            return "error"
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de {url}: {e}")
            return "error"

class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.monitor = SiteMonitor()
        
    async def on_ready(self):
        logger.info(f'{self.user} s\'est connecté à Discord!')
        self.check_sites.start()
        
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        logger.error(f"Erreur de commande: {error}")
        await ctx.send(f"Une erreur s'est produite: {error}")

    @commands.command(name='monitor')
    async def add_monitor(self, ctx, url: str = None, pseudo: str = None, *, role: str = None):
        """Ajouter un site à surveiller avec pseudo et rôle optionnels
        
        Usage: 
        !monitor <url>
        !monitor <url> <pseudo>
        !monitor <url> <pseudo> <role>
        
        Exemples:
        !monitor https://exemple.com
        !monitor https://exemple.com PlayerName
        !monitor https://exemple.com PlayerName Tank Principal
        """
        if not url:
            embed = discord.Embed(
                title="❓ Utilisation de la commande monitor",
                description="**Syntaxe:**\n"
                           "`!monitor <url>`\n"
                           "`!monitor <url> <pseudo>`\n"
                           "`!monitor <url> <pseudo> <role>`\n\n"
                           "**Exemples:**\n"
                           "• `!monitor https://exemple.com`\n"
                           "• `!monitor https://exemple.com PlayerName`\n"
                           "• `!monitor https://exemple.com PlayerName Tank Principal`",
                color=0x3498db
            )
            await ctx.send(embed=embed)
            return
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        if url in self.monitor.monitored_sites:
            await ctx.send(f"⚠️ Ce site est déjà surveillé: {url}")
            return
            
        self.monitor.add_site(url, pseudo, role)
        
        # Création de l'embed de confirmation
        embed = discord.Embed(
            title="✅ Surveillance ajoutée",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="🔗 URL", value=url, inline=False)
        
        if pseudo:
            embed.add_field(name="👤 Pseudo", value=pseudo, inline=True)
        if role:
            embed.add_field(name="🎭 Rôle", value=role, inline=True)
            
        embed.set_footer(text="Le site sera vérifié toutes les 3 minutes")
        
        await ctx.send(embed=embed)
        logger.info(f"Site ajouté à la surveillance: {url} (pseudo: {pseudo}, rôle: {role})")

    @commands.command(name='unmonitor')
    async def remove_monitor(self, ctx, url: str = None):
        """Supprimer un site de la surveillance"""
        if not url:
            sites = list(self.monitor.monitored_sites.keys())
            if sites:
                sites_list = '\n'.join([f"• {site}" for site in sites])
                await ctx.send(f"Sites surveillés:\n```\n{sites_list}\n```\nUtilisez `!unmonitor <url>` pour supprimer un site.")
            else:
                await ctx.send("Aucun site n'est actuellement surveillé.")
            return
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        if self.monitor.remove_site(url):
            await ctx.send(f"✅ Surveillance supprimée pour: {url}")
            logger.info(f"Site supprimé de la surveillance: {url}")
        else:
            await ctx.send(f"❌ Ce site n'était pas surveillé: {url}")

    @commands.command(name='status')
    async def check_status(self, ctx):
        """Afficher l'état de tous les sites surveillés"""
        if not self.monitor.monitored_sites:
            await ctx.send("Aucun site n'est actuellement surveillé.")
            return
            
        embed = discord.Embed(title="🔍 État de la surveillance", color=0x00ff00)
        
        for url, data in self.monitor.monitored_sites.items():
            status_emoji = {
                "online": "🟢",
                "offline": "🔴", 
                "error": "⚠️",
                "unknown": "⚪"
            }
            
            status_text = {
                "online": "En ligne (joueur disponible)",
                "offline": "Hors ligne (en partie)",
                "error": "Erreur de connexion", 
                "unknown": "Non vérifié"
            }
            
            emoji = status_emoji.get(data["status"], "⚪")
            text = status_text.get(data["status"], "Inconnu")
            last_check = data["last_check"].strftime("%H:%M:%S") if data["last_check"] else "Jamais"
            
            # Construction du nom du field avec pseudo et rôle si disponibles
            field_title = f"{emoji} "
            if data.get("pseudo"):
                field_title += f"**{data['pseudo']}**"
                if data.get("role"):
                    field_title += f" ({data['role']})"
            else:
                field_title += url
            
            # Construction de la valeur avec les infos
            field_value = f"**Status:** {text}\n**Dernière vérification:** {last_check}"
            if data.get("pseudo") or data.get("role"):
                field_value += f"\n🔗 **URL:** {url}"
            
            embed.add_field(
                name=field_title,
                value=field_value,
                inline=False
            )
            
        embed.set_footer(text=f"Vérification automatique toutes les {CHECK_INTERVAL//60} minutes")
        await ctx.send(embed=embed)

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_sites(self):
        """Vérifier périodiquement tous les sites surveillés"""
        if not self.monitor.monitored_sites:
            return
            
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            logger.error(f"Canal avec l'ID {CHANNEL_ID} introuvable")
            return
            
        async with aiohttp.ClientSession() as session:
            for url, data in self.monitor.monitored_sites.items():
                try:
                    current_status = await self.monitor.check_site(url, session)
                    previous_status = data["status"]
                    
                    # Mise à jour de la dernière vérification
                    data["last_check"] = datetime.now()
                    
                    # Gestion des erreurs de connexion
                    if current_status == "error":
                        logger.warning(f"Erreur de connexion pour {url}")
                        continue
                    
                    # Première vérification
                    if previous_status == "unknown":
                        data["status"] = current_status
                        data["retries"] = 0
                        logger.info(f"État initial pour {url}: {current_status}")
                        continue
                    
                    # Pas de changement
                    if current_status == previous_status:
                        data["retries"] = 0
                        continue
                    
                    # Changement détecté - vérification anti-faux positif
                    data["retries"] += 1
                    logger.info(f"Changement potentiel pour {url}: {previous_status} -> {current_status} (tentative {data['retries']}/{MAX_RETRIES})")
                    
                    # Validation du changement après plusieurs vérifications
                    if data["retries"] >= MAX_RETRIES:
                        data["status"] = current_status
                        data["retries"] = 0
                        
                        # Envoi de notification
                        if current_status == "online" and previous_status == "offline":
                            # Titre de l'embed avec pseudo et rôle si disponibles
                            title = "🟢 Joueur en ligne !"
                            if data.get("pseudo"):
                                if data.get("role"):
                                    description = f"**{data['pseudo']}** ({data['role']}) est maintenant disponible !"
                                else:
                                    description = f"**{data['pseudo']}** est maintenant disponible !"
                            else:
                                description = f"Le joueur est maintenant disponible !"
                            
                            description += f"\n🔗 **Lien:** {url}"
                            
                            embed = discord.Embed(
                                title=title,
                                description=description,
                                color=0x00ff00,
                                timestamp=datetime.now()
                            )
                            
                            if data.get("pseudo"):
                                embed.set_author(name=data["pseudo"], icon_url="https://cdn.discordapp.com/emojis/✅.png")
                            if data.get("role"):
                                embed.add_field(name="🎭 Rôle", value=data["role"], inline=True)
                                
                            embed.set_footer(text="Surveillance automatique • Joueur disponible")
                            await channel.send(embed=embed)
                            logger.info(f"Notification envoyée: joueur en ligne sur {url} (pseudo: {data.get('pseudo')}, rôle: {data.get('role')})")
                            
                        elif current_status == "offline" and previous_status == "online":
                            title = "🔴 Joueur en partie"
                            if data.get("pseudo"):
                                if data.get("role"):
                                    description = f"**{data['pseudo']}** ({data['role']}) est maintenant en partie."
                                else:
                                    description = f"**{data['pseudo']}** est maintenant en partie."
                            else:
                                description = f"Le joueur est maintenant en partie."
                                
                            description += f"\n🔗 **Lien:** {url}"
                            
                            embed = discord.Embed(
                                title=title,
                                description=description,
                                color=0xff0000,
                                timestamp=datetime.now()
                            )
                            
                            if data.get("pseudo"):
                                embed.set_author(name=data["pseudo"], icon_url="https://cdn.discordapp.com/emojis/❌.png")
                            if data.get("role"):
                                embed.add_field(name="🎭 Rôle", value=data["role"], inline=True)
                                
                            embed.set_footer(text="Surveillance automatique • Joueur indisponible")
                            await channel.send(embed=embed)
                            logger.info(f"Notification envoyée: joueur en partie sur {url} (pseudo: {data.get('pseudo')}, rôle: {data.get('role')})")
                
                except Exception as e:
                    logger.error(f"Erreur lors de la vérification de {url}: {e}")
                
                # Délai entre les vérifications de sites
                await asyncio.sleep(1)

    @check_sites.before_loop
    async def before_check_sites(self):
        await self.wait_until_ready()

# Configuration et démarrage du bot
if __name__ == "__main__":
    bot = MonitorBot()
    
    # Vérification de la configuration
    if TOKEN == "VOTRE_TOKEN_BOT_DISCORD":
        print("❌ Veuillez configurer votre token Discord dans TOKEN")
        exit(1)
        
    if CHANNEL_ID == 123456789:
        print("❌ Veuillez configurer l'ID du canal Discord dans CHANNEL_ID")
        exit(1)
    
    print(f"🚀 Démarrage du bot...")
    print(f"📊 Intervalle de vérification: {CHECK_INTERVAL} secondes")
    print(f"🔍 Message d'erreur surveillé: '{ERROR_MESSAGE}'")
    print(f"🛡️ Vérifications anti-faux positif: {MAX_RETRIES}")
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
