import discord
from discord.ext import commands
import json
import os

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

reaction_roles_file = "reaction_roles.json"

def load_reaction_roles():
    if os.path.exists(reaction_roles_file):
        with open(reaction_roles_file, 'r') as f:
            return json.load(f)
    return {}

def save_reaction_roles():
    with open(reaction_roles_file, 'w') as f:
        json.dump(reaction_role_messages, f, indent=2)

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

@bot.command(name='reactionroledebug')
async def reactionrole_debug(ctx):
    """Affiche les données enregistrées pour les messages à rôle"""
    if not reaction_role_messages:
        await ctx.send("⚠️ Aucun message de rôle par réaction enregistré.")
        return

    msg = "**Messages enregistrés :**\n"
    for msg_id, data in reaction_role_messages.items():
        msg += f"• ID: `{msg_id}` | Rôle: `<@&{data['role_id']}>` | Emoji: `{data['emoji']}`\n"
    await ctx.send(msg)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    print(f"[DEBUG] Réaction détectée par {user.name}")
    print(f"[DEBUG] Message ID : {reaction.message.id}")
    print(f"[DEBUG] Emoji reçu : {reaction.emoji}")
    print(f"[DEBUG] Base de données : {reaction_role_messages}")

    message_id = str(reaction.message.id)
    data = reaction_role_messages.get(message_id)

    if not data:
        print("[DEBUG] 🔴 Aucune donnée trouvée pour ce message")
        return

    print(f"[DEBUG] Données trouvées : {data}")

    if str(reaction.emoji) != data['emoji']:
        print("[DEBUG] ❌ Emoji ne correspond pas à l’attendu")
        return

    guild = bot.get_guild(data['guild_id'])
    if not guild:
        print("[DEBUG] ❌ Guilde introuvable")
        return

    member = guild.get_member(user.id)
    role = guild.get_role(data['role_id'])

    if not role:
        print("[DEBUG] ❌ Rôle introuvable")
    if not member:
        print("[DEBUG] ❌ Membre introuvable")

    if member and role:
        try:
            await member.add_roles(role)
            print(f"[DEBUG] ✅ Rôle {role.name} ajouté à {member.name}")
        except Exception as e:
            print(f"[ERREUR] ❌ Impossible d’ajouter le rôle : {e}")
