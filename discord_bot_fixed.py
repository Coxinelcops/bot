import discord
from discord.ext import commands
import json
import os

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

reaction_roles_file = "reaction_roles.json"

# Charger les messages depuis un fichier
def load_reaction_roles():
    if os.path.exists(reaction_roles_file):
        with open(reaction_roles_file, 'r') as f:
            return json.load(f)
    return {}

# Sauvegarder les messages dans un fichier
def save_reaction_roles():
    with open(reaction_roles_file, 'w') as f:
        json.dump(reaction_role_messages, f, indent=2)

# Initialiser au démarrage
reaction_role_messages = load_reaction_roles()

@bot.command(name='reactionrole')
@commands.has_permissions(manage_roles=True)
async def create_reaction_role(ctx, role: discord.Role = None, emoji: str = "🔔"):
    if role is None:
        await ctx.send("❌ Veuillez spécifier un rôle ! Exemple : `!reactionrole @Notifications 🔔`")
        return

    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ Je ne peux pas gérer ce rôle (il est au-dessus de mon rôle actuel).")
        return

    embed = discord.Embed(
        title="🎯 Rôle par Réaction",
        description=f"Réagis avec {emoji} pour obtenir le rôle **{role.name}**.\n"
                    f"Réagis à nouveau pour l'enlever.",
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

    reaction_role_messages[str(message.id)] = {
        'role_id': role.id,
        'emoji': emoji,
        'guild_id': ctx.guild.id
    }
    save_reaction_roles()

    await ctx.send(f"✅ Rôle {role.name} lié au message avec l’emoji {emoji}")

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    message_id = str(reaction.message.id)
    data = reaction_role_messages.get(message_id)
    if not data:
        return

    if str(reaction.emoji) != data['emoji']:
        return

    guild = bot.get_guild(data['guild_id'])
    if not guild:
        return

    member = guild.get_member(user.id)
    role = guild.get_role(data['role_id'])

    if member and role:
        try:
            await member.add_roles(role)
            print(f"[DEBUG] ✅ Rôle {role.name} ajouté à {member.name}")
        except Exception as e:
            print(f"[ERREUR] Ajout du rôle échoué : {e}")

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return

    message_id = str(reaction.message.id)
    data = reaction_role_messages.get(message_id)
    if not data:
        return

    if str(reaction.emoji) != data['emoji']:
        return

    guild = bot.get_guild(data['guild_id'])
    if not guild:
        return

    member = guild.get_member(user.id)
    role = guild.get_role(data['role_id'])

    if member and role:
        try:
            await member.remove_roles(role)
            print(f"[DEBUG] 🔁 Rôle {role.name} retiré de {member.name}")
        except Exception as e:
            print(f"[ERREUR] Suppression du rôle échouée : {e}")
