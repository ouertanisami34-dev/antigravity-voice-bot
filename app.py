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
import gradio as gr

# Charger la configuration depuis les variables d'environnement (Koyeb/Render)
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CLOUDFLARE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"

if not TOKEN:
    print("Erreur: DISCORD_BOT_TOKEN non trouvé dans les variables d'environnement", file=sys.stderr)
    sys.exit(1)

# Configuration du bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

recording_active = False
voice_client = None

# Appel de l'API Cloudflare Worker (Pont vers le bot textuel et la mémoire commune)
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityVoiceBot/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            if "response" in res_data:
                return res_data["response"]
            elif "error" in res_data:
                print(f"Erreur renvoyée par le Worker : {res_data['error']}")
                return "Désolé, une erreur interne est survenue sur le serveur d'intelligence artificielle."
    except Exception as e:
        print(f"Erreur de communication avec le Worker Cloudflare : {e}")
        return "Désolé, je ne parviens pas à contacter le serveur de mon intelligence artificielle."
    return "Aucune réponse reçue."

# Boucle d'écoute passive par tranches de 6 secondes
async def recording_loop(vc, channel):
    global recording_active
    recognizer = sr.Recognizer()
    print("Boucle d'écoute vocale automatique lancée.")

    while recording_active and vc.is_connected():
        sink = discord.sinks.WaveSink()
        
        try:
            vc.start_recording(sink, dummy_callback)
        except Exception as e:
            print(f"Erreur lors du lancement de l'enregistrement: {e}")
            await asyncio.sleep(2)
            continue
            
        await asyncio.sleep(6)
        
        try:
            vc.stop_recording()
        except Exception as e:
            print(f"Erreur lors de l'arrêt de l'enregistrement: {e}")
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
                print(f"[{username}] : {transcription}")
                
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
                        
                    print(f"-> Déclencheur détecté ! Question : '{question}' (UserID: {user_id}, Name: {username})")
                    
                    # 1. IA via Cloudflare
                    ai_response = query_cloudflare(user_id, username, question)
                    print(f"-> Réponse IA : {ai_response}")
                    
                    # 2. TTS
                    tts = gTTS(text=ai_response, lang='fr')
                    tts_file = f"response_{user_id}.mp3"
                    tts.save(tts_file)
                    
                    # 3. Speak
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
                print(f"Erreur d'analyse audio pour {username}: {err}")
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
    print(f"Bot de voix connecté sous le pseudo : {bot.user}")
    print("Prêt pour la connexion vocale automatique dans le salon '🔊 Vocal Membres'")

    # Attendre 3 secondes pour s'assurer que le cache Discord est complètement chargé
    await asyncio.sleep(3)
    
    # Vérifier s'il y a déjà des membres dans le salon vocal au démarrage
    target_channel_id = 1361031443177799751
    channel = bot.get_channel(target_channel_id)
    if channel and isinstance(channel, discord.VoiceChannel):
        humans = [m for m in channel.members if not m.bot]
        if len(humans) > 0:
            # Vérifier si le bot n'est pas déjà connecté
            if voice_client is None or not voice_client.is_connected():
                try:
                    print(f"Détection au démarrage : {len(humans)} membre(s) présent(s) dans le salon vocal. Connexion automatique...")
                    vc = await channel.connect()
                    voice_client = vc
                    recording_active = True
                    bot.loop.create_task(recording_loop(vc, channel))
                except Exception as e:
                    print(f"Erreur de connexion automatique au démarrage : {e}")

# Détection de présence pour connexion/déconnexion en cours de route
@bot.event
async def on_voice_state_update(member, before, after):
    global recording_active, voice_client
    target_channel_id = 1361031443177799751  # ID du salon 🔊 Vocal Membres
    
    # 1. Détection quand un utilisateur rejoint le salon cible
    if after.channel and after.channel.id == target_channel_id:
        if member.bot:
            return
            
        if voice_client is None or not voice_client.is_connected():
            try:
                print(f"Détection : {member.name} a rejoint. Connexion automatique...")
                vc = await after.channel.connect()
                voice_client = vc
                recording_active = True
                bot.loop.create_task(recording_loop(vc, after.channel))
            except Exception as e:
                print(f"Erreur de connexion vocale automatique : {e}")
                
    # 2. Détection quand un utilisateur quitte le salon cible
    if before.channel and before.channel.id == target_channel_id:
        if voice_client and voice_client.is_connected():
            humans_left = [m for m in before.channel.members if not m.bot]
            if len(humans_left) == 0:
                print("Détection : Plus d'humain dans le salon. Déconnexion automatique...")
                recording_active = False
                await voice_client.disconnect()
                voice_client = None

# Interface Gradio minimale pour satisfaire le serveur web Koyeb/Render
def make_gradio_demo():
    with gr.Blocks() as demo:
        gr.Markdown("# 🎙️ Antigravity - Bot Vocal Discord")
        gr.Markdown("Le bot vocal est actif en tâche de fond !")
    return demo

def run_discord():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.start(TOKEN))

# Lancement du bot et du serveur Gradio
if __name__ == "__main__":
    # Lancer Discord dans un thread séparé
    threading.Thread(target=run_discord, daemon=True).start()
    
    # Lancer Gradio (qui écoute sur le port 8000 pour Koyeb/Render)
    demo = make_gradio_demo()
    demo.launch(server_name="0.0.0.0", server_port=8000)
