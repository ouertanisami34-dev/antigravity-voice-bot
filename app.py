import asyncio
import discord
from discord.ext import commands
import yt_dlp
import os
import sys
import collections
import datetime
import traceback
import threading
import urllib.request
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Serveur web minimal pour Render (Port 10000)
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Antigravity OK")
    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 10000))
threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(),
    daemon=True
).start()
print(f"[BOOT] Serveur web active sur le port {port}", flush=True)

# ============================================================
# Configuration
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    sys.exit("[ERREUR] DISCORD_BOT_TOKEN manquant")

ZHIPU_API_KEY = "d67596b18ee34cf0b4bdc4b67d2d6cca.3GvLAH1h06OzPXiR"
ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

MEMORY_CHANNEL_ID = 1523012733975658637
MUSIC_CHANNEL_ID = 1523144828341325905
MINI_NGR_CHANNEL_ID = 1523147101670735972

# Ponts Cloudflare
CLOUDFLARE_VOICE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"
CLOUDFLARE_MUSIC_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/music"

# Activation de tous les intents indispensables pour pister l'activite
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.presences = True
intents.members = True

# Charger tous les membres et presences au démarrage
bot = commands.Bot(command_prefix="!", intents=intents, chunk_guilds_at_startup=True)

# ============================================================
# Base de donnees d'activite horaire en memoire
# ============================================================
hourly_events = {
    "games": set(),
    "songs": set(),
    "bot_songs": set(),
    "chatters": set()
}

# ============================================================
# Sécurité : Vérifier si la question est bien liée à la musique
# ============================================================
def is_music_request(question):
    q = question.lower().strip()
    
    # Mots-clés indiquant une question sur les jeux ou une salutation simple (ne jamais lancer de musique)
    neutral_keywords = [
        "quel jeu", "à quoi je", "qui joue", "tu fais quoi", "bonjour", "salut", 
        "ça va", "hello", "coucou", "qui est en ligne", "qu'est-ce que", "qui écoute"
    ]
    for kw in neutral_keywords:
        if kw in q:
            return False
            
    # Mots-clés de musique typiques
    music_keywords = [
        "joue", "mets", "met", "lance", "écoute", "chante", "musique", "son", 
        "chanson", "play", "music", "song", "url", "youtube", "spotify"
    ]
    if any(kw in q for kw in music_keywords):
        return True
        
    # Si le message est très court (max 4 mots, ex: "pnl da" ou "jul"), on accepte comme demande de musique
    if len(q.split()) <= 4:
        return True
        
    return False

# ============================================================
# Modérateur de salons (Restriction des commandes)
# ============================================================
@bot.check
async def check_command_channels(ctx):
    music_commands = {"play", "p", "pause", "resume", "skip", "s", "stop", "queue", "q", "volume", "vol"}
    ai_commands = {"ask", "trigger_hourly", "timer", "alarm", "remind", "poll", "userinfo", "serverinfo"}

    target_channel = None
    if ctx.command.name in music_commands:
        target_channel = MUSIC_CHANNEL_ID
    elif ctx.command.name in ai_commands:
        target_channel = MINI_NGR_CHANNEL_ID

    if target_channel and ctx.channel.id != target_channel:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        alert = await ctx.send(f"❌ {ctx.author.mention}, utilise le salon <#{target_channel}> pour cette commande !")
        await asyncio.sleep(5)
        try:
            await alert.delete()
        except Exception:
            pass
        return False

    return True

# ============================================================
# Configuration YTDL & FFmpeg (Fallback SoundCloud, etc.)
# ============================================================
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'geo_bypass': True,
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)
queues = {}
now_playing = {}
volumes = {}

def get_queue(gid):
    return queues.setdefault(gid, collections.deque())

def get_vol(gid):
    return volumes.get(gid, 0.5)

def get_yt_video_id(url):
    pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([^?&\s]+)'
    match = re.search(pattern, url)
    return match.group(1) if match else None

# ============================================================
# Extraction Audio via Cloudflare Worker Proxy
# ============================================================
async def extract_audio(query):
    print(f"[EXTRACTION] Query : '{query}'", flush=True)
    try:
        video_id = get_yt_video_id(query)

        if not video_id and query.startswith(('http://', 'https://')):
            print(f"[YTDL FALLBACK] Extraction standard pour : {query}", flush=True)
            data = await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))
            if 'entries' in data:
                data = data['entries'][0]
            return {
                'title': data.get('title', 'Inconnu'),
                'url': data.get('url'),
                'webpage_url': data.get('webpage_url', ''),
                'thumbnail': data.get('thumbnail', ''),
                'duration': data.get('duration', 0),
                'uploader': data.get('uploader', 'Inconnu'),
            }

        print(f"[CLOUDFLARE PROXY] Appel du pont /music pour YouTube", flush=True)
        payload = {}
        if video_id:
            payload["video_id"] = video_id
        else:
            payload["query"] = query

        req = urllib.request.Request(
            CLOUDFLARE_MUSIC_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )

        try:
            response = await asyncio.to_thread(
                lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            )
        except urllib.error.HTTPError as he:
            error_details = he.read().decode("utf-8")
            print(f"[CLOUDFLARE ERREUR DETEE] {error_details}", flush=True)
            raise Exception(f"Cloudflare : {error_details}")

        res_data = json.loads(response)
        if "error" in res_data:
            raise Exception(res_data["error"])

        return res_data

    except Exception as e:
        print(f"[EXTRACTION ERREUR] {e}", flush=True)
        raise e

def fmt_dur(s):
    if not s:
        return "🔴 Live"
    return str(datetime.timedelta(seconds=int(s)))

# ============================================================
# Logique de file d'attente threadsafe asynchrone
# ============================================================
def play_next_threadsafe(guild):
    coro = play_next_async(guild)
    asyncio.run_coroutine_threadsafe(coro, bot.loop)

async def play_next_async(guild):
    q = get_queue(guild.id)
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return
    if not q:
        now_playing[guild.id] = None
        await vc.disconnect()
        return
        
    song = q.popleft()
    now_playing[guild.id] = song
    try:
        # Pause d'une demi-seconde pour laisser l'ancien lecteur se fermer proprement
        await asyncio.sleep(0.5)
        
        src = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
            volume=get_vol(guild.id)
        )
        vc.play(src, after=lambda e: play_next_threadsafe(guild))
        print(f"[PLAY] {song['title']}", flush=True)
    except Exception as e:
        print(f"[PLAY ERREUR] {e}", flush=True)

# ============================================================
# Systeme de memoire IA (mini-NGR)
# ============================================================
async def load_memory(user_id):
    try:
        channel = bot.get_channel(MEMORY_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(MEMORY_CHANNEL_ID)
        prefix = f"MEMORY_FOR_{user_id}"
        async for message in channel.history(limit=100):
            if message.content.startswith(prefix):
                json_text = message.content[len(prefix):].strip()
                return json.loads(json_text), message.id
    except Exception as e:
        print(f"[MEMOIRE] Erreur lecture : {e}", flush=True)
    return {"user_id": str(user_id), "facts": [], "history": []}, None

async def save_memory(user_id, memory_obj, message_id):
    try:
        channel = bot.get_channel(MEMORY_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(MEMORY_CHANNEL_ID)
        content = f"MEMORY_FOR_{user_id}\n{json.dumps(memory_obj)}"
        if message_id:
            msg = await channel.fetch_message(message_id)
            await msg.edit(content=content)
        else:
            await channel.send(content=content)
    except Exception as e:
        print(f"[MEMOIRE] Erreur sauvegarde : {e}", flush=True)

# ============================================================
# Appel API Zhipu AI (mini-NGR)
# ============================================================
async def call_ai(user_id, username, question, memory_obj):
    import re
    learn_match = re.search(r'(?:souviens-toi|retiens)\s+que\s+(.+)', question, re.IGNORECASE)
    is_learning = False
    if learn_match:
        is_learning = True
        new_fact = learn_match.group(1).strip()
        if new_fact not in memory_obj.get("facts", []):
            memory_obj.setdefault("facts", []).append(new_fact)

    # Récupérer les activités et jeux en temps réel de tous les membres
    active_activities = []
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            for act in member.activities:
                if act.type == discord.ActivityType.playing:
                    active_activities.append(f"{member.name} joue à {act.name}")
                elif act.type == discord.ActivityType.listening and act.name == "Spotify":
                    try:
                        title = getattr(act, "title", None)
                        artist = getattr(act, "artist", None)
                        if title and artist:
                            active_activities.append(f"{member.name} écoute Spotify : {title} (par {artist})")
                    except Exception:
                        pass

    system_prompt = (
        "Tu es mini-NGR, le petit bot mascotte du serveur Discord THE NGR. "
        "Tu parles comme un pote, de manière décontractée, drôle et directe. "
        "Tu as le contrôle sur le lecteur de musique du serveur ! "
        "Uniquement si l'utilisateur te demande explicitement de contrôler la musique (jouer, passer, couper, etc.), "
        "ajoute l'une de ces balises à la toute fin de ta réponse (elle sera invisible pour lui) :\n"
        "- [ACTION:PLAY:nom de la musique ou URL] (cela l'ajoutera à la file d'attente si une musique est déjà en cours, donc utilise cette balise même s'il y a déjà du son !)\n"
        "- [ACTION:SKIP] (seulement s'il te demande de passer à la suivante)\n"
        "- [ACTION:PAUSE] (seulement s'il te demande de mettre en pause)\n"
        "- [ACTION:RESUME] (seulement s'il te demande de reprendre)\n"
        "- [ACTION:STOP] (seulement s'il te demande d'arrêter ou de quitter)\n\n"
        "IMPORTANT : Si l'utilisateur te dit bonjour, te parle normalement ou te pose une question générale, "
        "réponds-lui simplement sans ajouter de balise [ACTION:...] à la fin. Ne mets JAMAIS de balise pour une simple discussion !"
        "\nExemple de discussion simple : 'Salut frérot ! Ça va ?'\n"
        "Exemple de commande musique : 'Pas de soucis, je te mets du Jul ! [ACTION:PLAY:Jul Da]'\n"
        "Réponds de manière TRÈS concise (1 à 2 phrases max, moins de 50 mots)."
    )
    system_prompt += f"\nTu parles avec {username} (ID: {user_id})."
    if memory_obj.get("facts"):
        system_prompt += "\nCe que tu sais sur cette personne (ses goûts en général) :\n"
        for fact in memory_obj["facts"]:
            system_prompt += f"- {fact}\n"

    # Ajouter l'activité EN DIRECT au prompt système
    if active_activities:
        system_prompt += "\nVoici l'activité en temps réel (jeux/musique) de TOUS les membres sur le serveur actuellement :\n"
        for act in active_activities:
            system_prompt += f"- {act}\n"
    else:
        system_prompt += "\nAucun membre ne joue à un jeu ou n'écoute de musique actuellement sur le serveur."

    messages = [{"role": "system", "content": system_prompt}]
    history = memory_obj.get("history", [])
    for msg in history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    payload = json.dumps({
        "model": "glm-4-flash",
        "messages": messages,
        "max_tokens": 150
    }).encode("utf-8")

    req = urllib.request.Request(
        ZHIPU_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ZHIPU_API_KEY}"
        },
        method="POST"
    )

    response = await asyncio.to_thread(
        lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    )
    data = json.loads(response)

    try:
        ai_response = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        ai_response = "Oups, j'ai bugué là 😅"

    memory_obj.setdefault("history", []).append({"role": "user", "content": question})
    memory_obj["history"].append({"role": "assistant", "content": ai_response})
    if len(memory_obj["history"]) > 10:
        memory_obj["history"] = memory_obj["history"][-10:]

    return ai_response, is_learning

# ============================================================
# Générateur et Gestionnaire du Rapport d'Activité Horaire
# ============================================================
async def process_hourly_summary():
    global hourly_events
    
    # Vérifier s'il y a eu de l'activité
    has_activity = (
        len(hourly_events["games"]) > 0 or 
        len(hourly_events["songs"]) > 0 or 
        len(hourly_events["bot_songs"]) > 0 or 
        len(hourly_events["chatters"]) > 0
    )
    
    if not has_activity:
        print("[HOURLY] Aucune activite durant l'heure passee. Annulation de l'appel API.", flush=True)
        return

    # Mettre en forme le résumé
    lines = []
    if hourly_events["chatters"]:
        lines.append(f"Membres actifs dans le chat : {', '.join(hourly_events['chatters'])}")
    if hourly_events["games"]:
        lines.append(f"Activites et jeux : {', '.join(hourly_events['games'])}")
    if hourly_events["songs"]:
        lines.append(f"Musique ecoutee (Spotify) : {', '.join(hourly_events['songs'])}")
    if hourly_events["bot_songs"]:
        lines.append(f"Musique lances par le bot : {', '.join(hourly_events['bot_songs'])}")

    summary_text = "\n".join(lines)
    print(f"[HOURLY] Lancement de la synthese IA pour :\n{summary_text}", flush=True)

    # Réinitialisation de la mémoire horaire
    hourly_events = {
        "games": set(),
        "songs": set(),
        "bot_songs": set(),
        "chatters": set()
    }

    try:
        system_prompt = (
            "Tu es mini-NGR, le bot mascotte décontracté du serveur Discord THE NGR. "
            "Voici la liste des activités que les membres ont faites durant l'heure passée. "
            "Rédige un message en français à la fois drôle, amical et intelligent pour réagir "
            "dans le salon des bots, charrier gentiment les membres (roast amical de gamer) "
            "et demander des nouvelles. Reste TRÈS court et naturel (max 60 mots). "
            "Utilise le tutoiement, le langage familier de pote et quelques émojis."
        )

        payload = json.dumps({
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Voici le résumé d'activité :\n{summary_text}"}
            ],
            "max_tokens": 150
        }).encode("utf-8")

        req = urllib.request.Request(
            ZHIPU_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ZHIPU_API_KEY}"
            },
            method="POST"
        )

        response = await asyncio.to_thread(
            lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        )
        data = json.loads(response)
        ai_msg = data["choices"][0]["message"]["content"]

        channel = bot.get_channel(MINI_NGR_CHANNEL_ID)
        if channel:
            await channel.send(f"👾 {ai_msg}")
            
    except Exception as e:
        print(f"[HOURLY ERREUR] {e}", flush=True)

async def hourly_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # Attendre 1 heure (3600 secondes)
        await asyncio.sleep(3600)
        await process_hourly_summary()

# ============================================================
# Evenements de Suivi d'Activite
# ============================================================
@bot.event
async def on_ready():
    print(f"[OK] {bot.user} connecte — {len(bot.guilds)} serveur(s)", flush=True)
    # Lancement de la boucle d'activite horaire en arriere-plan
    bot.loop.create_task(hourly_loop())
    
    # Forcer le chunking de tous les serveurs pour charger les presences des membres
    for guild in bot.guilds:
        try:
            await guild.chunk()
            print(f"[CHUNK] Serveur {guild.name} charge avec succes.", flush=True)
        except Exception as e:
            print(f"[CHUNK ERREUR] Impossible de charger {guild.name} : {e}", flush=True)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Enregistrer l'activite de chat de l'utilisateur dans l'historique de l'heure
    hourly_events["chatters"].add(message.author.name)
    
    # Si le message est dans #👾-mini-ngr et ne commence pas par !, l'IA repond en direct sans avoir besoin de taper !ask
    if message.channel.id == MINI_NGR_CHANNEL_ID and not message.content.startswith("!"):
        ctx = await bot.get_context(message)
        await run_ask(ctx, message.content)
        return
        
    print(f"[MSG] {message.author.name}: {message.content}", flush=True)
    await bot.process_commands(message)

@bot.event
async def on_presence_update(before, after):
    if after.bot:
        return
        
    # Parcourir les activites en cours de l'utilisateur
    for act in after.activities:
        # Pister les jeux
        if act.type == discord.ActivityType.playing:
            hourly_events["games"].add(f"{after.name} joue à {act.name}")
        # Pister Spotify
        elif act.type == discord.ActivityType.listening and act.name == "Spotify":
            try:
                title = getattr(act, "title", None)
                artist = getattr(act, "artist", None)
                if title and artist:
                    hourly_events["songs"].add(f"{after.name} écoute {title} - {artist}")
            except Exception:
                pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande de contrôle.")
        return
    print(f"[ERR] {ctx.command}: {error}", flush=True)
    await ctx.send(f"❌ Erreur : `{error}`")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    if before.channel:
        vc = before.channel.guild.voice_client
        if vc and vc.channel == before.channel:
            if all(m.bot for m in before.channel.members):
                get_queue(before.channel.guild.id).clear()
                now_playing[before.channel.guild.id] = None
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect()

# ============================================================
# Fonction centrale d'execution de la Musique (Partagee)
# ============================================================
async def run_play(ctx, query):
    if not ctx.author.voice:
        return await ctx.send("❌ Rejoins un salon vocal d'abord !")
    ch = ctx.author.voice.channel
    try:
        if ctx.voice_client is None:
            await ch.connect()
        elif ctx.voice_client.channel != ch:
            await ctx.voice_client.move_to(ch)
    except Exception as e:
        return await ctx.send(f"❌ Connexion vocale impossible : `{e}`")

    try:
        song = await extract_audio(query)
    except Exception as e:
        return await ctx.send(f"❌ Impossible de charger : `{e}`")

    gid = ctx.guild.id
    q = get_queue(gid)
    
    hourly_events["bot_songs"].add(song['title'])

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        q.append(song)
        description = (
            f"**[{song['title']}]({song['webpage_url']})**\n\n"
            "ℹ️ *Tapez `!queue` pour voir la file d'attente.*"
        )
        embed = discord.Embed(title="📋 Ajouté à la file d'attente", description=description, color=0x57F287)
        if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
        embed.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
        embed.add_field(name="📍 Position", value=f"#{len(q)}", inline=True)
        await ctx.send(embed=embed)
    else:
        now_playing[gid] = song
        try:
            src = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
                volume=get_vol(gid)
            )
            ctx.voice_client.play(src, after=lambda e: play_next_threadsafe(ctx.guild))

            desc_play = (
                f"**[{song['title']}]({song['webpage_url']})**\n\n"
                "**🎛️ Commandes :**\n"
                "⏸️ `!pause`  |  ▶️ `!resume`  |  ⏭️ `!skip`  |  🛑 `!stop`"
            )

            embed = discord.Embed(title="🎵 En cours de lecture", description=desc_play, color=0x5865F2)
            if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
            embed.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
            embed.add_field(name="🎤 Chaîne", value=song['uploader'], inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Erreur lecture : `{e}`")

# ============================================================
# Fonction centrale d'appel de l'IA (mini-NGR)
# ============================================================
async def run_ask(ctx, question):
    print(f"[ASK] {ctx.author.name}: '{question}'", flush=True)
    async with ctx.typing():
        try:
            # 1. Appel direct de l'IA pour obtenir une réponse décontractée
            memory_obj, memory_msg_id = await load_memory(ctx.author.id)
            ai_response, is_learning = await call_ai(
                str(ctx.author.id), ctx.author.name, question, memory_obj
            )
            await save_memory(ctx.author.id, memory_obj, memory_msg_id)

            # 2. Extraction de l'action de musique à partir du message IA
            action_type = None
            action_arg = ""
            action_match = re.search(r"\[ACTION:(\w+)(?::(.*?))?\]", ai_response)
            if action_match:
                action_type = action_match.group(1).upper()
                action_arg = action_match.group(2) if action_match.group(2) else ""
            
            # Nettoyer les balises d'action du message affiché
            ai_response = re.sub(r"\[ACTION:.*?\]", "", ai_response).strip()

            # 3. Envoyer la réponse du bot dans le chat
            if is_learning:
                await ctx.reply(f"📝 *C'est noté frérot, je m'en souviendrai !*\n\n{ai_response}")
            else:
                await ctx.reply(f"👾 {ai_response}")

            # 4. Exécuter l'action musicale détectée par l'IA (avec contrôle de sécurité)
            if action_type:
                await asyncio.sleep(0.5) # Délai naturel
                if action_type == "PLAY" and action_arg:
                    if is_music_request(question):
                        await run_play(ctx, action_arg)
                    else:
                        print(f"[SECURITY] PLAY filtre pour la question hors-sujet musique : '{question}'", flush=True)
                elif action_type == "SKIP":
                    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                        ctx.voice_client.stop()
                        await ctx.send("⏭️ Musique passée par mini-NGR !")
                elif action_type == "PAUSE":
                    if ctx.voice_client and ctx.voice_client.is_playing():
                        ctx.voice_client.pause()
                        await ctx.send("⏸️ Musique mise en pause par mini-NGR.")
                elif action_type == "RESUME":
                    if ctx.voice_client and ctx.voice_client.is_paused():
                        ctx.voice_client.resume()
                        await ctx.send("▶️ Lecture reprise par mini-NGR.")
                elif action_type == "STOP":
                    if ctx.voice_client:
                        get_queue(ctx.guild.id).clear()
                        now_playing[ctx.guild.id] = None
                        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                            ctx.voice_client.stop()
                        await ctx.voice_client.disconnect()
                        await ctx.send("🛑 Lecture arrêtée par mini-NGR.")

        except Exception as e:
            print(f"[ASK ERREUR] {e}", flush=True)
            await ctx.send(f"❌ mini-NGR a bugué : `{e}`")

# ============================================================
# Commande IA standard (!ask)
# ============================================================
@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await run_ask(ctx, question)

# ============================================================
# Commande de Déclenchement Manuel pour Tester l'Activite
# ============================================================
@bot.command(name="trigger_hourly")
@commands.has_permissions(administrator=True)
async def trigger_hourly(ctx):
    await ctx.send("⚡ Lancement manuel de la synthèse d'activité...")
    global hourly_events
    
    # Si aucune activite n'est enregistree, simuler une activite de test
    if not (hourly_events["games"] or hourly_events["songs"] or hourly_events["bot_songs"] or hourly_events["chatters"]):
        hourly_events["chatters"].add(ctx.author.name)
        hourly_events["games"].add(f"{ctx.author.name} code sur son serveur")
        
    await process_hourly_summary()

# ============================================================
# Commandes d'Administration Utiles (Contrôle du serveur)
# ============================================================
@bot.command(name="clear", aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear_messages(ctx, limit: int):
    """Supprime un nombre défini de messages dans le salon."""
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=limit)
    alert = await ctx.send(f"🧹 **{len(deleted)} messages** ont été supprimés par mini-NGR !")
    await asyncio.sleep(4)
    await alert.delete()

@bot.command(name="vmove")
@commands.has_permissions(move_members=True)
async def voice_move(ctx, member: discord.Member, *, channel_name: str):
    """Déplace un membre vers un autre salon vocal."""
    target = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
    if not target:
        target = next((c for c in ctx.guild.voice_channels if channel_name.lower() in c.name.lower()), None)
        
    if not target:
        return await ctx.send("❌ Salon vocal introuvable.")
        
    if not member.voice:
        return await ctx.send(f"❌ {member.mention} n'est connecté à aucun salon vocal.")
        
    await member.move_to(target)
    await ctx.send(f"🚀 {member.mention} a été déplacé vers **{target.name}** !")

@bot.command(name="vmute")
@commands.has_permissions(mute_members=True)
async def voice_mute(ctx, member: discord.Member):
    """Mute un membre dans le salon vocal."""
    if not member.voice:
        return await ctx.send(f"❌ {member.mention} n'est pas en vocal.")
    await member.edit(mute=True)
    await ctx.send(f"🔇 {member.mention} a été réduit au silence par mini-NGR.")

@bot.command(name="vunmute")
@commands.has_permissions(mute_members=True)
async def voice_unmute(ctx, member: discord.Member):
    """Redonne la parole à un membre muté en vocal."""
    if not member.voice:
        return await ctx.send(f"❌ {member.mention} n'est pas en vocal.")
    await member.edit(mute=False)
    await ctx.send(f"🔊 {member.mention} peut à nouveau parler.")

# ============================================================
# Commandes Utilitaires & Jeux (Minuteur, Sondage, Profils)
# ============================================================
def parse_time(time_str):
    match = re.match(r"^(\d+)([smh])$", time_str.lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return val
    elif unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    return None

@bot.command(name="timer", aliases=["alarm", "remind"])
async def start_timer(ctx, duration: str, *, reminder: str = "Le temps est écoulé !"):
    """Lance un minuteur et ping l'utilisateur quand c'est fini."""
    seconds = parse_time(duration)
    if seconds is None:
        return await ctx.send("❌ Format invalide. Exemple : `!timer 10s`, `!timer 5m`, `!timer 1h`.")
        
    await ctx.send(f"⏳ Minuteur lancé pour **{duration}** : *\"{reminder}\"*")
    await asyncio.sleep(seconds)
    await ctx.send(f"⏰ {ctx.author.mention} **Alarme !** {reminder}")

@bot.command(name="poll")
async def create_poll(ctx, *, args: str):
    """Crée un sondage. Syntaxe : !poll Question | Option1 | Option2..."""
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 3:
        return await ctx.send("❌ Syntaxe : `!poll Question | Choix 1 | Choix 2...` (2 choix minimum)")
        
    question = parts[0]
    options = parts[1:10]  # Max 9 choix
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    
    desc = ""
    for i, opt in enumerate(options):
        desc += f"{emojis[i]} {opt}\n"
        
    embed = discord.Embed(title=f"📊 {question}", description=desc, color=0x5865F2)
    embed.set_footer(text=f"Sondage créé par {ctx.author.name}")
    poll_msg = await ctx.send(embed=embed)
    
    for i in range(len(options)):
        await poll_msg.add_reaction(emojis[i])

@bot.command(name="userinfo")
async def user_info(ctx, member: discord.Member = None):
    """Affiche les infos de profil d'un membre."""
    member = member or ctx.author
    embed = discord.Embed(title=f"👤 Profil de {member.name}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    roles = [r.mention for r in member.roles[1:]]  # Exclure @everyone
    roles_str = ", ".join(roles) if roles else "Aucun rôle"
    
    act = member.activity
    act_str = f"{act.name}" if act else "Aucune activité en cours"
    
    embed.add_field(name="Pseudo", value=member.nick or "Aucun", inline=True)
    embed.add_field(name="Statut", value=str(member.status).upper(), inline=True)
    embed.add_field(name="Activité", value=act_str, inline=True)
    embed.add_field(name="Création du compte", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Rejoint le serveur", value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Rôles", value=roles_str, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="serverinfo")
async def server_info(ctx):
    """Affiche les statistiques et infos du serveur."""
    guild = ctx.guild
    embed = discord.Embed(title=f"🏰 {guild.name}", color=0x5865F2)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
        
    embed.add_field(name="Créateur", value=guild.owner.mention if guild.owner else "Inconnu", inline=True)
    embed.add_field(name="Date de création", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Membres", value=str(guild.member_count), inline=True)
    embed.add_field(name="Salons Textuels", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="Salons Vocaux", value=str(len(guild.voice_channels)), inline=True)
    
    await ctx.send(embed=embed)

# ============================================================
# Commandes Musique (Redirigées vers run_play)
# ============================================================
@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
    async with ctx.typing():
        await run_play(ctx, query)

@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Musique en pause. Tapez `!resume` pour reprendre.")

@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Reprise de la lecture.")

@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Musique passée !")

@bot.command(name="stop")
async def stop(ctx):
    if not ctx.voice_client:
        return await ctx.send("❌ Le bot n'est pas connecté.")
    get_queue(ctx.guild.id).clear()
    now_playing[ctx.guild.id] = None
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Lecture arrêtée et déconnexion.")

@bot.command(name="queue", aliases=["q"])
async def queue_info(ctx):
    gid = ctx.guild.id
    q = get_queue(gid)
    cur = now_playing.get(gid)
    if not cur and not q:
        return await ctx.send("📋 La file d'attente est vide.")
    e = discord.Embed(title="📋 File d'attente", color=0x5865F2)
    if cur:
        e.add_field(name="🎵 En cours", value=f"**{cur['title']}** — {fmt_dur(cur['duration'])}", inline=False)
    if q:
        lines = [f"`{i}.` **{s['title']}** — {fmt_dur(s['duration'])}" for i, s in enumerate(list(q)[:10], 1)]
        if len(q) > 10: lines.append(f"... et {len(q) - 10} autre(s)")
        e.add_field(name="⏳ À suivre", value="\n".join(lines), inline=False)
    await ctx.send(embed=e)

@bot.command(name="volume", aliases=["vol"])
async def volume(ctx, level: int):
    if not ctx.voice_client:
        return await ctx.send("❌ Le bot n'est pas connecté.")
    if not (0 <= level <= 100):
        return await ctx.send("❌ Le volume doit être entre 0 et 100.")
    v = level / 100
    volumes[ctx.guild.id] = v
    if ctx.voice_client.source and hasattr(ctx.voice_client.source, 'volume'):
        ctx.voice_client.source.volume = v
    await ctx.send(f"🔊 Volume : **{level}%**")

bot.run(TOKEN)
