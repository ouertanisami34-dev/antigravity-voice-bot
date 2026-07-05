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
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Serveur web minimal pour Render
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Antigravity Music Bot Active")
    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 10000))
threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(),
    daemon=True
).start()
print(f"[BOOT] Serveur web active sur le port {port}", flush=True)

# ============================================================
# Configuration du Bot
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CLOUDFLARE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"

if not TOKEN:
    sys.exit("[ERREUR] DISCORD_BOT_TOKEN manquant")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
# Configuration YTDL & FFmpeg
# ============================================================
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'geo_bypass': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'mweb'],
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    },
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
# Recherche via Piped API (proxy YouTube public, jamais bloque)
# ============================================================
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
]

async def search_piped(query):
    """Cherche une video YouTube via Piped API (proxy public)."""
    print(f"[PIPED] Recherche : '{query}'", flush=True)
    encoded = urllib.parse.quote(query)
    
    for instance in PIPED_INSTANCES:
        try:
            url = f"{instance}/search?q={encoded}&filter=music_songs"
            req = urllib.request.Request(url, headers={
                "User-Agent": "DiscordBot (Antigravity, 1.0)"
            })
            data = await asyncio.to_thread(lambda u=req: urllib.request.urlopen(u, timeout=5).read().decode("utf-8"))
            results = json.loads(data)
            
            items = results.get("items", [])
            if items:
                video = items[0]
                video_url = f"https://www.youtube.com{video.get('url', '')}"
                print(f"[PIPED] Trouve : {video.get('title')} -> {video_url}", flush=True)
                return video_url
        except Exception as e:
            print(f"[PIPED] Instance {instance} echouee : {e}", flush=True)
            continue
    
    return None

# ============================================================
# Extraction audio (avec recherche Piped)
# ============================================================
async def extract_audio(query):
    print(f"[YTDL] Extraction : '{query}'", flush=True)
    try:
        is_url = query.startswith(('http://', 'https://'))
        
        if not is_url:
            # Recherche via Piped API (proxy YouTube)
            found_url = await search_piped(query)
            if not found_url:
                raise Exception("Aucun resultat trouve. Essayez avec un lien YouTube direct.")
            query = found_url
        
        # Extraction audio via yt-dlp (lien direct uniquement)
        data = await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))
        
        if 'entries' in data:
            if not data['entries']:
                raise Exception("Aucun resultat dans l'extraction.")
            data = data['entries'][0]
        
        if not data.get('url'):
            raise Exception("Pas d'URL audio trouvee.")
        
        info = {
            'title': data.get('title', 'Inconnu'),
            'url': data.get('url'),
            'webpage_url': data.get('webpage_url', ''),
            'thumbnail': data.get('thumbnail', ''),
            'duration': data.get('duration', 0),
            'uploader': data.get('uploader', 'Inconnu'),
        }
        print(f"[YTDL] OK : {info['title']}", flush=True)
        return info
    except Exception as e:
        print(f"[YTDL ERREUR] {e}", flush=True)
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
                print("[AUTO] Salon vide — deconnexion", flush=True)

# ============================================================
# Commande IA (!ask)
# ============================================================
@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"[ASK] {ctx.author.name}: '{question}'", flush=True)
    async with ctx.typing():
        try:
            payload = json.dumps({
                "user_id": str(ctx.author.id),
                "username": ctx.author.name,
                "question": question
            }).encode("utf-8")
            req = urllib.request.Request(
                CLOUDFLARE_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            response = await asyncio.to_thread(
                lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            )
            ai_response = json.loads(response).get("response", "Désolé, pas de réponse.")
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
