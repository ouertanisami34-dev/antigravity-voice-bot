import asyncio
import discord
from discord.ext import commands
import speech_recognition as sr
from gtts import gTTS
import os
import sys
import urllib.request
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Serveur web minimal (thread secondaire) pour garder Render actif
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Antigravity Voice Bot is running!")
    def log_message(self, format, *args):
        pass  # Silence les logs HTTP

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()

# Lancer le serveur web dans un thread secondaire
threading.Thread(target=start_health_server, daemon=True).start()
print("Serveur web de sante lance sur le port 8000", flush=True)

# ============================================================
# Configuration du bot Discord (thread principal)
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CLOUDFLARE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"

if not TOKEN:
    print("Erreur: DISCORD_BOT_TOKEN non trouve dans les variables d'environnement", file=sys.stderr, flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

recording_active = False
voice_client = None

# Appel de l'API Cloudflare Worker
def query_cloudflare(user_id, username, question):
    payload = {
        "user_id": str(user_id),
        "username": username,
        "question": question
    }
    req = urllib.request.Request(
        CLOUDFLARE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AntigravityVoiceBot/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            if "response" in res_data:
                return res_data["response"]
            elif "error" in res_data:
                print(f"Erreur Worker : {res_data['error']}", flush=True)
                return "Desole, une erreur interne est survenue."
    except Exception as e:
        print(f"Erreur communication Worker : {e}", flush=True)
        return "Desole, je ne parviens pas a contacter le serveur."
    return "Aucune reponse recue."

# Boucle d'ecoute passive par tranches de 6 secondes
async def recording_loop(vc, channel):
    global recording_active
    recognizer = sr.Recognizer()
    print("Boucle d'ecoute vocale lancee.", flush=True)

    while recording_active and vc.is_connected():
        sink = discord.sinks.WaveSink()
        try:
            vc.start_recording(sink, dummy_callback)
        except Exception as e:
            print(f"Erreur enregistrement: {e}", flush=True)
            await asyncio.sleep(2)
            continue

        await asyncio.sleep(6)

        try:
            vc.stop_recording()
        except Exception as e:
            print(f"Erreur arret enregistrement: {e}", flush=True)
            continue

        await asyncio.sleep(0.5)

        for user_id, audio_file in list(sink.audio_data.items()):
            user = vc.guild.get_member(user_id)
            username = user.name if user else f"Membre {user_id}"

            if user and user.bot:
                continue

            audio_data = audio_file.file.read()
            if not audio_data:
                continue

            temp_filename = f"temp_{user_id}.wav"
            try:
                with open(temp_filename, "wb") as f:
                    f.write(audio_data)

                with sr.AudioFile(temp_filename) as source:
                    audio = recognizer.record(source)

                transcription = recognizer.recognize_google(audio, language="fr-FR")
                print(f"[{username}] : {transcription}", flush=True)

                trigger_phrases = ["big model", "bigmodel", "big-model", "beat model", "big modelle"]
                has_trigger = False
                found_trigger = ""

                for phrase in trigger_phrases:
                    if phrase in transcription.lower():
                        has_trigger = True
                        found_trigger = phrase
                        break

                if has_trigger:
                    parts = transcription.lower().split(found_trigger, 1)
                    question = parts[1].strip()
                    if not question:
                        question = "salut"

                    print(f"-> Declencheur detecte ! Question : '{question}'", flush=True)

                    ai_response = query_cloudflare(user_id, username, question)
                    print(f"-> Reponse IA : {ai_response}", flush=True)

                    tts = gTTS(text=ai_response, lang='fr')
                    tts_file = f"response_{user_id}.mp3"
                    tts.save(tts_file)

                    vc.play(discord.FFmpegPCMAudio(tts_file))

                    while vc.is_playing():
                        await asyncio.sleep(0.5)

                    try:
                        os.remove(tts_file)
                    except:
                        pass

            except sr.UnknownValueError:
                pass
            except Exception as err:
                print(f"Erreur audio pour {username}: {err}", flush=True)
            finally:
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except:
                        pass

        sink.audio_data.clear()

async def dummy_callback(sink, *args):
    pass

@bot.event
async def on_ready():
    global recording_active, voice_client
    print(f"Bot connecte : {bot.user}", flush=True)
    print("En attente de connexion vocale...", flush=True)

    await asyncio.sleep(3)

    target_channel_id = 1361031443177799751
    channel = bot.get_channel(target_channel_id)
    if channel and isinstance(channel, discord.VoiceChannel):
        humans = [m for m in channel.members if not m.bot]
        if len(humans) > 0:
            if voice_client is None or not voice_client.is_connected():
                try:
                    print(f"Demarrage : {len(humans)} membre(s) detecte(s). Connexion...", flush=True)
                    vc = await channel.connect()
                    voice_client = vc
                    recording_active = True
                    bot.loop.create_task(recording_loop(vc, channel))
                except Exception as e:
                    print(f"Erreur connexion au demarrage : {e}", flush=True)

@bot.event
async def on_voice_state_update(member, before, after):
    global recording_active, voice_client
    target_channel_id = 1361031443177799751

    if after.channel and after.channel.id == target_channel_id:
        if member.bot:
            return
        if voice_client is None or not voice_client.is_connected():
            try:
                print(f"Detection : {member.name} a rejoint. Connexion...", flush=True)
                vc = await after.channel.connect()
                voice_client = vc
                recording_active = True
                bot.loop.create_task(recording_loop(vc, after.channel))
            except Exception as e:
                print(f"Erreur connexion vocale : {e}", flush=True)

    if before.channel and before.channel.id == target_channel_id:
        if voice_client and voice_client.is_connected():
            humans_left = [m for m in before.channel.members if not m.bot]
            if len(humans_left) == 0:
                print("Plus d'humain. Deconnexion...", flush=True)
                recording_active = False
                await voice_client.disconnect()
                voice_client = None

# Lancer le bot Discord dans le thread principal
bot.run(TOKEN)
