import asyncio
import discord
from discord.ext import commands
from gtts import gTTS
import os
import sys
import urllib.request
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Serveur web minimal pour garder Render actif
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Antigravity Voice Bot is running!")
    def log_message(self, format, *args):
        pass

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
print("Serveur web lance sur le port 8000", flush=True)

# ============================================================
# Configuration du bot Discord
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CLOUDFLARE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"

if not TOKEN:
    print("Erreur: DISCORD_BOT_TOKEN non trouve", file=sys.stderr, flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

voice_client = None

# ============================================================
# Appel de l'API Cloudflare Worker
# ============================================================
def query_cloudflare(user_id, username, question):
    payload = {"user_id": str(user_id), "username": username, "question": question}
    req = urllib.request.Request(
        CLOUDFLARE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AntigravityVoiceBot/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            if "response" in res_data:
                return res_data["response"]
    except Exception as e:
        print(f"Erreur Worker : {e}", flush=True)
    return "Desole, une erreur est survenue."

# ============================================================
# Bot pret
# ============================================================
@bot.event
async def on_ready():
    global voice_client
    print(f"Bot connecte : {bot.user}", flush=True)
    print("En attente...", flush=True)

    await asyncio.sleep(3)

    # Rejoindre le vocal si quelqu'un est deja present
    target_channel_id = 1361031443177799751
    channel = bot.get_channel(target_channel_id)
    if channel and isinstance(channel, discord.VoiceChannel):
        humans = [m for m in channel.members if not m.bot]
        if len(humans) > 0 and (voice_client is None or not voice_client.is_connected()):
            try:
                print(f"Demarrage : {len(humans)} membre(s). Connexion au vocal...", flush=True)
                voice_client = await channel.connect()
            except Exception as e:
                print(f"Erreur connexion demarrage : {e}", flush=True)

# ============================================================
# Connexion/deconnexion automatique du vocal
# ============================================================
@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client
    target_channel_id = 1361031443177799751

    # Un humain rejoint le salon vocal cible
    if after.channel and after.channel.id == target_channel_id:
        if member.bot:
            return
        if voice_client is None or not voice_client.is_connected():
            try:
                print(f"{member.name} a rejoint le vocal. Connexion...", flush=True)
                voice_client = await after.channel.connect()
            except Exception as e:
                print(f"Erreur connexion vocale : {e}", flush=True)

    # Un humain quitte le salon vocal cible
    if before.channel and before.channel.id == target_channel_id:
        if voice_client and voice_client.is_connected():
            humans_left = [m for m in before.channel.members if not m.bot]
            if len(humans_left) == 0:
                print("Plus personne dans le vocal. Deconnexion...", flush=True)
                await voice_client.disconnect()
                voice_client = None

# ============================================================
# Detection du mot "big model" dans les messages texte
# ============================================================
@bot.event
async def on_message(message):
    global voice_client

    # Ignorer les messages du bot lui-meme
    if message.author.bot:
        return

    text = message.content.lower()

    # Chercher le declencheur "big model"
    trigger_phrases = ["big model", "bigmodel", "big-model", "big modelle"]
    found_trigger = None
    for phrase in trigger_phrases:
        if phrase in text:
            found_trigger = phrase
            break

    if not found_trigger:
        # Laisser les autres commandes fonctionner
        await bot.process_commands(message)
        return

    # Extraire la question apres le mot declencheur
    parts = text.split(found_trigger, 1)
    question = parts[1].strip() if len(parts) > 1 else ""
    if not question:
        question = "salut"

    user_id = message.author.id
    username = message.author.name

    print(f"[{username}] big model -> '{question}'", flush=True)

    # Indicateur de frappe pour montrer que le bot reflechit
    async with message.channel.typing():
        # Appeler l'IA via Cloudflare
        ai_response = await asyncio.to_thread(query_cloudflare, user_id, username, question)

    print(f"Reponse IA : {ai_response}", flush=True)

    # Repondre par ecrit dans le chat
    await message.reply(f"🤖 {ai_response}")

    # Parler la reponse dans le vocal si le bot est connecte
    if voice_client and voice_client.is_connected():
        try:
            # Generer l'audio TTS
            tts = gTTS(text=ai_response, lang='fr')
            tts_file = f"response_{user_id}.mp3"
            tts.save(tts_file)

            # Jouer l'audio dans le vocal
            voice_client.play(discord.FFmpegPCMAudio(tts_file))

            # Attendre que l'audio soit termine
            while voice_client.is_playing():
                await asyncio.sleep(0.5)

            # Nettoyer le fichier temporaire
            try:
                os.remove(tts_file)
            except:
                pass

            print("Audio joue avec succes dans le vocal.", flush=True)
        except Exception as e:
            print(f"Erreur lecture audio : {e}", flush=True)
    else:
        print("Bot pas connecte au vocal, reponse texte uniquement.", flush=True)

    await bot.process_commands(message)

# Lancer le bot
bot.run(TOKEN)
