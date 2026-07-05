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
import urllib.parse
import json
import re
import ssl
from http.server import HTTPServer, BaseHTTPRequestHandler

# Desactivation globale de la verification SSL pour eviter les blocages de certificats sur Render
ssl_context = ssl._create_unverified_context()

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

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
# Configuration YTDL & FFmpeg (Fallback uniquement)
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

# ============================================================
# Listes de serveurs Proxy (Piped & Invidious)
# ============================================================
PIPED_INSTANCES = [
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.us.to",
    "https://piped-api.lunar.icu",
    "https://piped-api.hostux.net"
]

INVIDIOUS_INSTANCES = [
    "https://yewtu.be",
    "https://invidious.projectsegfau.lt",
    "https://invidious.flokinet.to",
    "https://invidio.xamh.de",
    "https://invidious.privacydev.net"
]

def get_yt_video_id(url):
    pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([^?&\s]+)'
    match = re.search(pattern, url)
    return match.group(1) if match else None

# ============================================================
# Recherche hybride Proxy (YouTube Search)
# ============================================================
async def search_video(query):
    encoded = urllib.parse.quote(query)
    
    # 1. Tenter la recherche via Piped API
    print(f"[RECHERCHE] Tentative Piped pour : '{query}'", flush=True)
    for instance in PIPED_INSTANCES:
        try:
            url = f"{instance}/search?q={encoded}&filter=music_songs"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = await asyncio.to_thread(
                lambda u=req: urllib.request.urlopen(u, timeout=10, context=ssl_context).read().decode("utf-8")
            )
            items = json.loads(data).get("items", [])
            if items:
                v_id = get_yt_video_id(f"https://www.youtube.com{items[0].get('url', '')}")
                if v_id:
                    print(f"[RECHERCHE OK] Trouve via Piped ({instance}) : {v_id}", flush=True)
                    return v_id
        except Exception as e:
            print(f"[RECHERCHE FAIL] Piped ({instance}) : {e}", flush=True)
            continue

    # 2. Tenter la recherche via Invidious API
    print(f"[RECHERCHE] Tentative Invidious pour : '{query}'", flush=True)
    for instance in INVIDIOUS_INSTANCES:
        try:
            url = f"{instance}/api/v1/search?q={encoded}&type=video"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = await asyncio.to_thread(
                lambda u=req: urllib.request.urlopen(u, timeout=10, context=ssl_context).read().decode("utf-8")
            )
            results = json.loads(data)
            if results and isinstance(results, list):
                v_id = results[0].get("videoId")
                if v_id:
                    print(f"[RECHERCHE OK] Trouve via Invidious ({instance}) : {v_id}", flush=True)
                    return v_id
        except Exception as e:
            print(f"[RECHERCHE FAIL] Invidious ({instance}) : {e}", flush=True)
            continue
            
    return None

# ============================================================
# Extraction Audio via Proxys
# ============================================================
async def extract_audio(query):
    print(f"[EXTRACTION] Cible : '{query}'", flush=True)
    try:
        # Recuperer le Video ID
        video_id = get_yt_video_id(query)
        if not video_id:
            video_id = await search_video(query)
        
        # Si ce n'est pas du YouTube (SoundCloud, etc.), fallback standard
        if not video_id:
            if query.startswith(('http://', 'https://')):
                print(f"[YTDL FALLBACK] Extraction standard yt-dlp pour : {query}", flush=True)
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
            raise Exception("Aucun resultat trouve.")

        # 1. Recuperer le flux audio via Piped API
        print(f"[FLUX] Tentative Piped pour video: {video_id}", flush=True)
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = await asyncio.to_thread(
                    lambda u=req: urllib.request.urlopen(u, timeout=10, context=ssl_context).read().decode("utf-8")
                )
                res_json = json.loads(data)
                audio_streams = res_json.get("audioStreams", [])
                if audio_streams:
                    best_stream = max(audio_streams, key=lambda s: s.get("bitrate", 0))
                    info = {
                        'title': res_json.get('title', 'Inconnu'),
                        'url': best_stream.get('url'),
                        'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                        'thumbnail': res_json.get('thumbnailUrl', ''),
                        'duration': res_json.get('duration', 0),
                        'uploader': res_json.get('uploader', 'Inconnu'),
                    }
                    print(f"[FLUX OK] Piped ({instance}) : {info['title']}", flush=True)
                    return info
            except Exception as e:
                print(f"[FLUX FAIL] Piped ({instance}) : {e}", flush=True)
                continue

        # 2. Recuperer le flux audio via Invidious API
        print(f"[FLUX] Tentative Invidious pour video: {video_id}", flush=True)
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = await asyncio.to_thread(
                    lambda u=req: urllib.request.urlopen(u, timeout=10, context=ssl_context).read().decode("utf-8")
                )
                res_json = json.loads(data)
                adaptive = res_json.get("adaptiveFormats", [])
                audio_streams = [f for f in adaptive if f.get("type", "").startswith("audio/")]
                if audio_streams:
                    best_audio = audio_streams[0]
                    info = {
                        'title': res_json.get('title', 'Inconnu'),
                        'url': best_audio.get('url'),
                        'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                        'thumbnail': res_json.get('videoThumbnails', [{}])[0].get('url', ''),
                        'duration': res_json.get('lengthSeconds', 0),
                        'uploader': res_json.get('author', 'Inconnu'),
                    }
                    print(f"[FLUX OK] Invidious ({instance}) : {info['title']}", flush=True)
                    return info
            except Exception as e:
                print(f"[FLUX FAIL] Invidious ({instance}) : {e}", flush=True)
                continue

        raise Exception("Tous les serveurs de flux audio (Piped/Invidious) ont echoue.")
    except Exception as e:
        print(f"[EXTRACTION ERREUR GLOBAL] {e}", flush=True)
        raise e

def fmt_dur(s):
    if not s:
        return "🔴 Live"
    return str(datetime.timedelta(seconds=int(s)))

def play_next(guild):
    q = get_queue(guild.id)
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return
    if not q:
        now_playing[guild.id] = None
        asyncio.run_coroutine_threadsafe(vc.disconnect(), bot.loop)
        return
    song = q.popleft()
    now_playing[guild.id] = song
    try:
        src = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
            volume=get_vol(guild.id)
        )
        vc.play(src, after=lambda e: play_next(guild))
        print(f"[PLAY] {song['title']}", flush=True)
    except Exception as e:
        print(f"[PLAY ERREUR] {e}", flush=True)

# ============================================================
# Systeme de memoire IA
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
# Appel API Zhipu AI
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

    system_prompt = (
        "Tu es un robot amical nommé Antigravity. Réponds de manière EXTRÊMEMENT concise et courte "
        "(maximum 1 ou 2 phrases courtes, moins de 50 mots). Va droit au but, supprime les éléments non importants pour faire court."
    )
    system_prompt += f"\nL'utilisateur actuel s'appelle {username} (ID: {user_id})."
    if memory_obj.get("facts"):
        system_prompt += "\nVoici les informations mémorisées sur cet utilisateur :\n"
        for fact in memory_obj["facts"]:
            system_prompt += f"- {fact}\n"

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
        lambda: urllib.request.urlopen(req, timeout=15, context=ssl_context).read().decode("utf-8")
    )
    data = json.loads(response)

    try:
        ai_response = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        ai_response = "Désolé, je n'ai pas pu générer de réponse."

    memory_obj.setdefault("history", []).append({"role": "user", "content": question})
    memory_obj["history"].append({"role": "assistant", "content": ai_response})
    if len(memory_obj["history"]) > 10:
        memory_obj["history"] = memory_obj["history"][-10:]

    return ai_response, is_learning

# ============================================================
# Evenements
# ============================================================
@bot.event
async def on_ready():
    print(f"[OK] {bot.user} connecte — {len(bot.guilds)} serveur(s)", flush=True)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    print(f"[MSG] {message.author.name}: {message.content}", flush=True)
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
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
# Commande IA (!ask)
# ============================================================
@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"[ASK] {ctx.author.name}: '{question}'", flush=True)
    async with ctx.typing():
        try:
            memory_obj, memory_msg_id = await load_memory(ctx.author.id)
            ai_response, is_learning = await call_ai(
                str(ctx.author.id), ctx.author.name, question, memory_obj
            )
            await save_memory(ctx.author.id, memory_obj, memory_msg_id)

            if is_learning:
                await ctx.reply(f"📝 *C'est noté, je m'en souviendrai !*\n\n{ai_response}")
            else:
                await ctx.reply(ai_response)
        except Exception as e:
            print(f"[ASK ERREUR] {e}", flush=True)
            await ctx.send(f"❌ Erreur IA : `{e}`")

# ============================================================
# Commandes Musique
# ============================================================
@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
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

    async with ctx.typing():
        try:
            song = await extract_audio(query)
        except Exception as e:
            return await ctx.send(f"❌ Impossible de charger : `{e}`")

        gid = ctx.guild.id
        q = get_queue(gid)

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            q.append(song)
            embed = discord.Embed(title="📋 Ajouté à la file", description=f"**[{song['title']}]({song['webpage_url']})**", color=0x57F287)
            if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
            embed.add_field(name="⏱️", value=fmt_dur(song['duration']), inline=True)
            embed.add_field(name="📍", value=f"#{len(q)}", inline=True)
            await ctx.send(embed=embed)
        else:
            now_playing[gid] = song
            try:
                src = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
                    volume=get_vol(gid)
                )
                ctx.voice_client.play(src, after=lambda e: play_next(ctx.guild))
                embed = discord.Embed(title="🎵 En cours de lecture", description=f"**[{song['title']}]({song['webpage_url']})**", color=0x5865F2)
                if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
                embed.add_field(name="⏱️", value=fmt_dur(song['duration']), inline=True)
                embed.add_field(name="🎤", value=song['uploader'], inline=True)
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"❌ Erreur lecture : `{e}`")

@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Pause.")

@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Reprise.")

@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Passée.")

@bot.command(name="stop")
async def stop(ctx):
    if not ctx.voice_client:
        return await ctx.send("❌ Bot non connecté.")
    get_queue(ctx.guild.id).clear()
    now_playing[ctx.guild.id] = None
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Arrêté.")

@bot.command(name="queue", aliases=["q"])
async def queue_info(ctx):
    gid = ctx.guild.id
    q = get_queue(gid)
    cur = now_playing.get(gid)
    if not cur and not q:
        return await ctx.send("📋 File vide.")
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
        return await ctx.send("❌ Bot non connecté.")
    if not (0 <= level <= 100):
        return await ctx.send("❌ Volume entre 0 et 100.")
    v = level / 100
    volumes[ctx.guild.id] = v
    if ctx.voice_client.source and hasattr(ctx.voice_client.source, 'volume'):
        ctx.voice_client.source.volume = v
    await ctx.send(f"🔊 Volume : **{level}%**")

bot.run(TOKEN)
