
# === Système de rôles par réaction (sauvegarde + debug) ===
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

@bot.command(name='reactionroledebug')
async def reactionrole_debug(ctx):
    """Affiche les données enregistrées pour les messages à rôle"""
    if not reaction_role_messages:
        await ctx.send("⚠️ Aucun message de rôle par réaction enregistré.")
        return

    msg = "**Messages enregistrés :**\n"
    for msg_id, data in reaction_role_messages.items():
        role = ctx.guild.get_role(data['role_id'])
        msg += f"• ID: `{msg_id}` | Rôle: `{role.name if role else 'Inconnu'}` | Emoji: `{data['emoji']}`\n"
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
