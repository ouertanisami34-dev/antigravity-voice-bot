"""Antigravity V3 — Bot Discord Ultime (Musique + IA + Animations)"""
import asyncio, discord, os, sys, collections, datetime, threading
import urllib.request, json, re, random, traceback
from discord.ext import commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import yt_dlp

# ══════════════════════════════════════════════════════════════════════
# INTERFACE MUSIQUE (Embeds)
# ══════════════════════════════════════════════════════════════════════
# Redirection des flux pour le débogage en ligne
class Logger(object):
    def __init__(self, filename="bot.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    def flush(self):
        self.terminal.flush()
        self.log.flush()

sys.stdout = Logger("bot.log")
sys.stderr = Logger("bot.log")

VIOLET, BLUE, GREEN, RED, PINK, GOLD = 0x7C3AED, 0x3B82F6, 0x10B981, 0xEF4444, 0xEC4899, 0xF59E0B

def fmt_dur(s):
    if not s: return "🔴 Live"
    s = int(s)
    if s >= 3600: return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"

def get_elapsed(song):
    if not song or 'start_time' not in song: return 0
    ref = song.get('pause_start', datetime.datetime.now())
    return max(0, int((ref - song['start_time']).total_seconds() - song.get('paused_duration', 0)))

def progress_bar(elapsed, total, length=20):
    if not total: return "🔴 `[▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬]` **Live**"
    pct = min(1.0, max(0, elapsed / total))
    filled = int(length * pct)
    bar = "▬" * filled + "🔘" + "▬" * max(0, length - filled - 1)
    return f"▶️ `{bar}` **[{fmt_dur(elapsed)} / {fmt_dur(total)}]**"

def playing_embed(song, is_paused=False, guild_id=None):
    elapsed = get_elapsed(song)
    total = song.get('duration', 0)
    status_icon = "⏸️" if is_paused else "▶️"
    
    em = discord.Embed(title=f"{status_icon} Lecture en cours",
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**\n\n{progress_bar(elapsed, total)}", color=PINK)
    if song.get('thumbnail'): em.set_image(url=song['thumbnail'])
    em.add_field(name="🎤 Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.add_field(name="⏱️ Durée", value=fmt_dur(total), inline=True)
    if song.get('requester'):
        em.add_field(name="👤 Par", value=song['requester'], inline=True)
    if guild_id:
        q = list(Q(guild_id))
        if q:
            lines = []
            for i, s in enumerate(q[:5]):
                lines.append(f"`#{i + 1}` **{s['title']}**")
            if len(q) > 5:
                lines.append(f"*...et {len(q) - 5} autres morceaux*")
            em.add_field(name="🎶 À venir", value="\n".join(lines), inline=False)
    em.set_footer(text="Antigravity Music 🎶 • !skip pour passer • !queue pour la file")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

def added_embed(song, position):
    em = discord.Embed(title="✅ Ajouté à la file d'attente",
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**", color=GREEN)
    if song.get('thumbnail'): em.set_thumbnail(url=song['thumbnail'])
    em.add_field(name="⏱️ Durée", value=fmt_dur(song.get('duration', 0)), inline=True)
    em.add_field(name="📍 Position", value=f"#{position}", inline=True)
    em.add_field(name="🎤 Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.set_footer(text="Antigravity Music 🎶")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

async def update_embed_loop(guild, song, message):
    while True:
        await asyncio.sleep(4)
        vc = guild.voice_client
        if not vc or not vc.is_connected() or now_playing.get(guild.id) != song:
            break
        if not vc.is_playing() and not vc.is_paused():
            break
        try:
            await message.edit(embed=playing_embed(song, vc.is_paused(), guild.id))
        except Exception as e:
            print(f"[UPDATE EMBED ERR] {e}", flush=True)
            break

async def delete_previous_embed(guild):
    cur = now_playing.get(guild.id)
    if cur and cur.get('embed_message_id'):
        try:
            ch = bot.get_channel(MUS_CH)
            if ch:
                msg = await ch.fetch_message(cur['embed_message_id'])
                await msg.delete()
        except Exception as e:
            print(f"[DELETE EMBED ERR] {e}", flush=True)
        cur['embed_message_id'] = None

def np_embed(song, is_paused=False, is_looped=False, volume=50):
    if not song:
        return discord.Embed(title="🎵 Rien en cours",
            description="Utilise `!play <titre>` pour lancer une musique !", color=VIOLET)
    elapsed = get_elapsed(song)
    total = song.get('duration', 0)
    icon = "⏸️" if is_paused else "🔁" if is_looped else "▶️"
    status = "En pause" if is_paused else "En boucle" if is_looped else "En cours"
    em = discord.Embed(title=f"🎵 {song['title']}", url=song.get('webpage_url', ''), color=VIOLET,
        description=f"{icon} **{status}**\n\n{progress_bar(elapsed, total)}")
    if song.get('thumbnail'): em.set_thumbnail(url=song['thumbnail'])
    em.add_field(name="🎤 Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.add_field(name="⏱️ Durée", value=fmt_dur(total), inline=True)
    em.add_field(name="🔊 Volume", value=f"{volume}%", inline=True)
    em.set_footer(text="Antigravity Music 🎶")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

def queue_embed(q_list, current, is_paused=False, is_looped=False, volume=50):
    em = discord.Embed(title="📋 File d'attente — Antigravity", color=BLUE)
    if current:
        elapsed = get_elapsed(current)
        total = current.get('duration', 0)
        icon = "⏸️" if is_paused else "🔁" if is_looped else "▶️"
        em.add_field(name=f"{icon} En cours", inline=False,
            value=f"**[{current['title']}]({current.get('webpage_url', '')})**\n"
                  f"{progress_bar(elapsed, total)}")
    else:
        em.add_field(name="▶️ En cours", value="*Rien en lecture*", inline=False)
    if q_list:
        lines = []
        for i, s in enumerate(q_list[:10]):
            lines.append(f"`{i + 1}.` **{s['title']}** — {fmt_dur(s.get('duration', 0))}")
        if len(q_list) > 10:
            lines.append(f"\n*...et {len(q_list) - 10} de plus*")
        total_dur = sum(s.get('duration', 0) for s in q_list)
        nb = len(q_list)
        em.add_field(name=f"🎶 À venir — {nb} titre{'s' if nb > 1 else ''}",
                     value="\n".join(lines), inline=False)
        em.set_footer(text=f"Durée totale : {fmt_dur(total_dur)} • 🔊 {volume}% • Antigravity Music 🎶")
    else:
        em.add_field(name="🎶 À venir", value="*File vide — `!play <titre>` pour ajouter*", inline=False)
        em.set_footer(text=f"🔊 {volume}% • Antigravity Music 🎶")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

# ══════════════════════════════════════════════════════════════════════
# Serveur web santé pour Render (obligatoire)
# ══════════════════════════════════════════════════════════════════════
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain")
        self.end_headers(); self.wfile.write(b"Antigravity V3 OK")
    def log_message(self, *a): pass

port = int(os.environ.get("PORT", 10000))
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), H).serve_forever(), daemon=True).start()
print(f"[BOOT] Port {port} OK", flush=True)

# Bootstrap FFmpeg statique (pour Render qui n'a pas ffmpeg)
try:
    import static_ffmpeg; static_ffmpeg.add_paths()
    print("[BOOT] FFmpeg static OK", flush=True)
except Exception:
    print("[BOOT] FFmpeg static indisponible, utilisation du PATH systeme", flush=True)

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN: sys.exit("[ERR] DISCORD_BOT_TOKEN manquant")

ZHIPU_KEY = "d67596b18ee34cf0b4bdc4b67d2d6cca.3GvLAH1h06OzPXiR"
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MEM_CH = 1523012733975658637   # Canal memoire IA (invisible)
MUS_CH = 1523144828341325905   # #musique
NGR_CH = 1523147101670735972   # #mini-ngr
CF_MUSIC = "https://icy-wind-36d1.gamxdmeta.workers.dev/music"

intents = discord.Intents.default()
intents.message_content = intents.voice_states = intents.guilds = True
intents.presences = intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

queues, now_playing, volumes, loops = {}, {}, {}, {}
def Q(gid): return queues.setdefault(gid, collections.deque())
def V(gid): return volumes.get(gid, 0.5)

# ══════════════════════════════════════════════════════════════════════
# Garde de salon
# ══════════════════════════════════════════════════════════════════════
MUS_CMDS = {"play", "p", "skip", "s", "pause", "resume", "stop", "queue", "q",
            "volume", "vol", "clearqueue", "cq", "remove", "rm", "loop",
            "shuffle", "np", "nowplaying", "help", "debuglogs"}

@bot.check
async def channel_guard(ctx):
    target = MUS_CH if ctx.command.name in MUS_CMDS else NGR_CH
    if ctx.channel.id != target:
        try: await ctx.message.delete()
        except discord.errors.Forbidden: pass
        a = await ctx.send(f"❌ {ctx.author.mention}, utilise <#{target}> pour cette commande !")
        await asyncio.sleep(4)
        try: await a.delete()
        except discord.errors.Forbidden: pass
        return False
    return True

# ══════════════════════════════════════════════════════════════════════
# YTDL + Extraction audio
# ══════════════════════════════════════════════════════════════════════
YTDL_OPTS = {
    'format': 'bestaudio[acodec=opus]/bestaudio/best',
    'noplaylist': True, 'quiet': True,
    'no_warnings': True, 'source_address': '0.0.0.0',
    'nocheckcertificate': True, 'geo_bypass': True,
    'prefer_free_formats': True,
}
FF = {
    # Amélioration des paramètres de reconnexion pour éviter les coupures sur Render
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -reconnect_on_network_error 1',
    'options': '-vn'
}
ytdl_client = yt_dlp.YoutubeDL(YTDL_OPTS)

def yt_id(url):
    m = re.search(r'(?:youtube\.com/(?:watch\?v=|embed/|v/|shorts/)|youtu\.be/)([^?&\s]+)', url or '')
    return m.group(1) if m else None

def is_url(query):
    """Detects if query is a direct URL (YouTube, SoundCloud, etc.)"""
    return bool(re.match(r'https?://', query.strip()))

def _make_song(d):
    return {'title': d.get('title', '?'), 'url': d.get('url', ''),
            'webpage_url': d.get('webpage_url', ''), 'thumbnail': d.get('thumbnail', ''),
            'duration': d.get('duration', 0), 'uploader': d.get('uploader', '?')}

async def fetch_youtube_oembed(vid):
    """
    Fetches clean metadata (title, uploader, thumbnail) from YouTube's public oEmbed API.
    This endpoint is lightweight, fast, and never blocked by bot detection.
    """
    try:
        url = f"https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D{vid}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(await asyncio.to_thread(
            lambda: urllib.request.urlopen(req, timeout=5).read().decode('utf-8')))
        return {
            'title': res.get('title', '?'),
            'uploader': res.get('author_name', '?'),
            'thumbnail': res.get('thumbnail_url', ''),
            'webpage_url': f"https://www.youtube.com/watch?v={vid}"
        }
    except Exception as e:
        print(f"[OEMBED ERR] {e}", flush=True)
        return None

async def extract(query):
    """
    2-step extraction:
    1. Metadata (title, duration, thumbnail, uploader) via yt-dlp/oEmbed — always accurate
    2. Stream URL via Cloudflare Worker — avoids YouTube bot detection
    Falls back to full yt-dlp stream URL if Worker fails.
    """
    query = query.strip()
    vid = yt_id(query)

    # ── Étape 1 : Métadonnées via yt-dlp ─────────────────────────
    meta = {}
    try:
        if vid:
            search = f"https://www.youtube.com/watch?v={vid}"
        elif is_url(query):
            search = query
        else:
            search = f"ytsearch:{query}"
        d = await asyncio.to_thread(lambda: ytdl_client.extract_info(search, download=False))
        if 'entries' in d: d = d['entries'][0]
        meta = _make_song(d)
        # Récupérer le vid depuis les métadonnées si on ne l'avait pas
        if not vid:
            vid = yt_id(meta.get('webpage_url', ''))
    except Exception as e:
        print(f"[META ERR] {e}", flush=True)
        # SÉCURITÉ : Récupérer via oEmbed si c'est une vidéo YouTube
        if vid:
            oembed_data = await fetch_youtube_oembed(vid)
            if oembed_data:
                meta = {
                    'title': oembed_data['title'],
                    'url': '',
                    'webpage_url': oembed_data['webpage_url'],
                    'thumbnail': oembed_data['thumbnail'],
                    'duration': 0,
                    'uploader': oembed_data['uploader']
                }
        if not meta:
            meta = {'title': query, 'url': '', 'webpage_url': query if is_url(query) else '',
                    'thumbnail': '', 'duration': 0, 'uploader': '?'}

    # ── Étape 2 : URL de stream via Worker Cloudflare ─────────────
    try:
        payload = json.dumps({"query": f"https://www.youtube.com/watch?v={vid}" if vid else query}).encode()
        req = urllib.request.Request(CF_MUSIC, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
        res = json.loads(await asyncio.to_thread(
            lambda: urllib.request.urlopen(req, timeout=15).read().decode()))
        if "error" in res: raise Exception(res["error"])
        stream_url = res.get('url')
        if not stream_url: raise Exception("Pas d'URL de stream dans la reponse Worker")
        # Combiner : métadonnées yt-dlp + URL stream Worker
        meta['url'] = stream_url
        if not meta.get('webpage_url') and vid:
            meta['webpage_url'] = f"https://www.youtube.com/watch?v={vid}"
        
        # SÉCURITÉ : Remplir les métadonnées manquantes depuis le Worker
        if not meta.get('title') or meta['title'] == query:
            meta['title'] = res.get('title', query)
        if not meta.get('duration'):
            meta['duration'] = res.get('duration', 0)
        if not meta.get('uploader') or meta['uploader'] == '?':
            meta['uploader'] = res.get('uploader', '?')
        if not meta.get('thumbnail'):
            meta['thumbnail'] = res.get('thumbnail', '')
            
        # Si le titre est toujours "Musique YouTube" ou une URL brute, forcer oEmbed
        target_vid = vid or yt_id(meta.get('webpage_url', '')) or yt_id(res.get('webpage_url', ''))
        if target_vid and (meta['title'] == "Musique YouTube" or is_url(meta['title']) or meta['uploader'] == "YouTube"):
            oembed_data = await fetch_youtube_oembed(target_vid)
            if oembed_data:
                meta['title'] = oembed_data['title']
                meta['uploader'] = oembed_data['uploader']
                if oembed_data['thumbnail']:
                    meta['thumbnail'] = oembed_data['thumbnail']
                if not meta.get('webpage_url'):
                    meta['webpage_url'] = oembed_data['webpage_url']

        return meta
    except Exception as e:
        print(f"[STREAM ERR] Worker echoue: {e}", flush=True)
        # Fallback : utiliser l'URL stream de yt-dlp (peut être bloquée parfois)
        if meta.get('url'):
            print("[STREAM] Utilisation de l'URL yt-dlp en fallback", flush=True)
            return meta
# ══════════════════════════════════════════════════════════════════════
def next_sync(guild):
    asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

async def play_next(guild):
    await delete_previous_embed(guild)
    q = Q(guild.id); vc = guild.voice_client
    if not vc or not vc.is_connected():
        now_playing[guild.id] = None; return
    cur = now_playing.get(guild.id)
    if cur and loops.get(guild.id):
        clone = {k: v for k, v in cur.items()
                 if k not in ('start_time', 'pause_start', 'paused_duration', 'embed_message_id')}
        q.appendleft(clone)
    if not q:
        now_playing[guild.id] = None
        await bot.change_presence(activity=None)
        return
    song = q.popleft(); now_playing[guild.id] = song
    try:
        await asyncio.sleep(0.3)
        fresh = await extract(
            song.get('webpage_url') or song.get('original_query') or song['title'])
        song.update(fresh)
        stream_url = song.get('url')
        if not stream_url:
            raise Exception("Pas d'URL de flux audio extraite")
        src = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **FF), volume=V(guild.id))
        song['start_time'] = datetime.datetime.now()
        song['paused_duration'] = 0
        vc.play(src, after=lambda e: next_sync(guild))
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening, name=song['title'][:50]))
        ch = bot.get_channel(MUS_CH)
        if ch:
            msg = await ch.send(embed=playing_embed(song, False, guild.id))
            song['embed_message_id'] = msg.id
            asyncio.create_task(update_embed_loop(guild, song, msg))
    except Exception as e:
        print(f"[PLAY ERR] {e}", flush=True)
        # On ajoute une alerte dans Discord pour savoir pourquoi ça a coupé
        ch = bot.get_channel(MUS_CH)
        if ch:
            asyncio.create_task(ch.send(f"⚠️ Impossible de lire **{song.get('title', 'la musique')}** (Raison: `{e}`). Passage à la suite...", delete_after=15))
        next_sync(guild)

async def run_play(guild, query, requester="?", channel=None):
    vc = guild.voice_client
    if not vc: raise Exception("Bot pas connecte au vocal")
    # Toujours mettre en file — play_next extrait l'URL fraiche au moment de jouer
    song = {
        'title': query,
        'url': '',
        'webpage_url': '',
        'thumbnail': '',
        'duration': 0,
        'uploader': '...',
        'original_query': query,
        'requester': requester
    }
    # Pre-fetch metadata (titre, thumbnail, durée) pour l'embed — mais PAS l'URL stream
    try:
        meta = await extract(query)
        song['title'] = meta.get('title', query)
        song['webpage_url'] = meta.get('webpage_url', '')
        song['thumbnail'] = meta.get('thumbnail', '')
        song['duration'] = meta.get('duration', 0)
        song['uploader'] = meta.get('uploader', '?')
        # On garde original_query pour la re-extraction dans play_next
    except Exception as e:
        print(f"[META ERR] {e}", flush=True)
    if now_playing.get(guild.id) is not None:
        Q(guild.id).append(song)
        if channel: await channel.send(embed=added_embed(song, len(Q(guild.id))), delete_after=10)
        return song
    # Pas de musique en cours → lancer directement
    now_playing[guild.id] = song  # placeholder pour bloquer les doubles appels
    Q(guild.id).appendleft(song)
    asyncio.create_task(play_next(guild))
    return song

# ══════════════════════════════════════════════════════════════════════
# Commandes Musique
# ══════════════════════════════════════════════════════════════════════
@bot.command(name="play", aliases=["p"])
async def cmd_play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Rejoins un salon vocal d'abord !", delete_after=5)
    vc = ctx.voice_client
    if not vc or not vc.is_connected():
        vc = await ctx.author.voice.channel.connect()
    try: await ctx.message.delete()
    except: pass
    msg = await ctx.send("🔍 Recherche en cours...")
    try:
        await run_play(ctx.guild, query, ctx.author.display_name, ctx.channel)
        try: await msg.delete()
        except: pass
    except Exception as e:
        await msg.edit(content=f"❌ Erreur : {e}")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass

@bot.command(name="skip", aliases=["s"])
async def cmd_skip(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("❌ Rien à skipper.", delete_after=5)
    loops[ctx.guild.id] = False
    vc.stop()
    await ctx.send("⏭️ Skip !", delete_after=5)

@bot.command(name="pause")
async def cmd_pause(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("❌ Rien en cours.", delete_after=5)
    vc.pause()
    s = now_playing.get(ctx.guild.id)
    if s:
        s['pause_start'] = datetime.datetime.now()
        if s.get('embed_message_id'):
            try:
                ch = bot.get_channel(MUS_CH)
                if ch:
                    msg = await ch.fetch_message(s['embed_message_id'])
                    await msg.edit(embed=playing_embed(s, is_paused=True, guild_id=ctx.guild.id))
            except Exception: pass
    await ctx.send("⏸️ En pause.", delete_after=5)

@bot.command(name="resume")
async def cmd_resume(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_paused():
        return await ctx.send("❌ Pas en pause.", delete_after=5)
    s = now_playing.get(ctx.guild.id)
    if s:
        if 'pause_start' in s:
            s['paused_duration'] = s.get('paused_duration', 0) + \
                (datetime.datetime.now() - s['pause_start']).total_seconds()
            del s['pause_start']
        if s.get('embed_message_id'):
            try:
                ch = bot.get_channel(MUS_CH)
                if ch:
                    msg = await ch.fetch_message(s['embed_message_id'])
                    await msg.edit(embed=playing_embed(s, is_paused=False, guild_id=ctx.guild.id))
            except Exception: pass
    vc.resume()
    await ctx.send("▶️ Reprise !", delete_after=5)

@bot.command(name="stop")
async def cmd_stop(ctx):
    try: await ctx.message.delete()
    except: pass
    await delete_previous_embed(ctx.guild)
    Q(ctx.guild.id).clear()
    loops[ctx.guild.id] = False
    now_playing[ctx.guild.id] = None
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
    await bot.change_presence(activity=None)
    await ctx.send("⏹️ Arrêté et déconnecté.", delete_after=5)

@bot.command(name="queue", aliases=["q"])
async def cmd_queue(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    paused = vc.is_paused() if vc else False
    await ctx.send(embed=queue_embed(
        list(Q(ctx.guild.id)), now_playing.get(ctx.guild.id),
        is_paused=paused, is_looped=loops.get(ctx.guild.id, False),
        volume=int(V(ctx.guild.id) * 100)), delete_after=20)

@bot.command(name="volume", aliases=["vol"])
async def cmd_vol(ctx, level: int):
    try: await ctx.message.delete()
    except: pass
    if not (0 <= level <= 100):
        return await ctx.send("❌ Volume entre 0 et 100.", delete_after=5)
    volumes[ctx.guild.id] = level / 100
    vc = ctx.voice_client
    if vc and vc.source and hasattr(vc.source, 'volume'):
        vc.source.volume = level / 100
    await ctx.send(f"🔊 Volume : **{level}%**", delete_after=5)

@bot.command(name="clearqueue", aliases=["cq"])
async def cmd_cq(ctx):
    try: await ctx.message.delete()
    except: pass
    Q(ctx.guild.id).clear()
    await ctx.send("🧹 File d'attente vidée !", delete_after=5)

@bot.command(name="remove", aliases=["rm"])
async def cmd_rm(ctx, index: int):
    try: await ctx.message.delete()
    except: pass
    q = Q(ctx.guild.id)
    if not (1 <= index <= len(q)):
        return await ctx.send(f"❌ Index entre 1 et {len(q)}.", delete_after=5)
    lst = list(q)
    removed = lst.pop(index - 1)
    queues[ctx.guild.id] = collections.deque(lst)
    await ctx.send(f"🗑️ Supprimé : **{removed['title']}**", delete_after=5)

@bot.command(name="loop")
async def cmd_loop(ctx):
    try: await ctx.message.delete()
    except: pass
    loops[ctx.guild.id] = not loops.get(ctx.guild.id, False)
    status = "🔁 Boucle activée !" if loops[ctx.guild.id] else "➡️ Boucle désactivée."
    await ctx.send(status, delete_after=5)

@bot.command(name="shuffle")
async def cmd_shuffle(ctx):
    try: await ctx.message.delete()
    except: pass
    q = Q(ctx.guild.id)
    if len(q) < 2:
        return await ctx.send("❌ Pas assez de titres à mélanger.", delete_after=5)
    lst = list(q)
    random.shuffle(lst)
    queues[ctx.guild.id] = collections.deque(lst)
    await ctx.send(f"🔀 File mélangée ! ({len(lst)} titres)", delete_after=5)

@bot.command(name="np", aliases=["nowplaying"])
async def cmd_np(ctx):
    try: await ctx.message.delete()
    except: pass
    s = now_playing.get(ctx.guild.id)
    vc = ctx.voice_client
    await ctx.send(embed=np_embed(s,
        is_paused=vc.is_paused() if vc else False,
        is_looped=loops.get(ctx.guild.id, False),
        volume=int(V(ctx.guild.id) * 100)), delete_after=15)

@bot.command(name="help")
async def cmd_help(ctx):
    try: await ctx.message.delete()
    except: pass
    em = discord.Embed(title="🚀 Antigravity V3 — Commandes", color=0x7C3AED,
        description="Le bot musique et IA ultime !")
    em.add_field(name="🎵 Musique (dans #musique)", inline=False, value=(
        "`!play <titre>` — Jouer / ajouter à la file\n"
        "`!skip` — Passer au suivant\n"
        "`!pause` / `!resume` — Pause / Reprendre\n"
        "`!stop` — Arrêter et déconnecter\n"
        "`!queue` — Voir la file d'attente\n"
        "`!np` — Titre en cours + progression\n"
        "`!volume <0-100>` — Régler le volume\n"
        "`!loop` — Activer/désactiver la boucle\n"
        "`!shuffle` — Mélanger la file\n"
        "`!remove <n>` — Supprimer le titre #n\n"
        "`!clearqueue` — Vider toute la file"))
    em.add_field(name="🤖 IA (dans #mini-ngr)", inline=False,
        value="Parle directement ! Ou utilise `!ask ta question` pour parler à l'IA.")
    em.set_footer(text="Antigravity V3 🎶 • Créé avec ❤️")
    await ctx.send(embed=em, delete_after=30)

@bot.command(name="debuglogs")
async def cmd_debuglogs(ctx):
    try:
        with open("bot.log", "r", encoding="utf-8") as f:
            lines = f.readlines()
        last_lines = "".join(lines[-40:])
        # Si trop long, couper
        if len(last_lines) > 1900:
            last_lines = last_lines[-1900:]
        await ctx.send(f"📋 **Derniers logs du bot :**\n```\n{last_lines}\n```")
    except Exception as e:
        await ctx.send(f"❌ Impossible de lire les logs : {e}")

# ══════════════════════════════════════════════════════════════════════
# IA + Mémoire
# ══════════════════════════════════════════════════════════════════════
local_mem_cache = {}

async def load_mem(uid):
    if uid in local_mem_cache:
        return local_mem_cache[uid]["mem"], local_mem_cache[uid]["mid"]
        
    mem = {"user_id": str(uid), "facts": [], "history": []}
    mid = None
    try:
        ch = bot.get_channel(MEM_CH) or await bot.fetch_channel(MEM_CH)
        prefix = f"MEMORY_FOR_{uid}"
        async for m in ch.history(limit=50):
            if m.content.startswith(prefix):
                mem = json.loads(m.content[len(prefix):].strip())
                mid = m.id
                break
    except Exception:
        pass
        
    local_mem_cache[uid] = {"mem": mem, "mid": mid}
    return mem, mid

async def _bg_save_mem(uid, mem, mid):
    try:
        ch = bot.get_channel(MEM_CH) or await bot.fetch_channel(MEM_CH)
        txt = f"MEMORY_FOR_{uid}\n{json.dumps(mem, ensure_ascii=False)}"
        if mid:
            m = await ch.fetch_message(mid)
            await m.edit(content=txt)
        else:
            m = await ch.send(content=txt)
            if uid in local_mem_cache:
                local_mem_cache[uid]["mid"] = m.id
    except Exception:
        pass

async def save_mem(uid, mem, mid):
    local_mem_cache[uid] = {"mem": mem, "mid": mid}
    asyncio.create_task(_bg_save_mem(uid, mem, mid))

def detect_games(guild):
    games = []
    for m in guild.members:
        if m.bot: continue
        for a in m.activities:
            if a.type == discord.ActivityType.playing:
                games.append(f"{m.display_name} joue a {a.name}")
            elif a.type == discord.ActivityType.streaming:
                games.append(f"{m.display_name} stream {a.name}")
    return games

async def ai_respond(user_id, username, question, guild):
    mem, mid = await load_mem(user_id)
    learn = re.search(r'(?:souviens[- ]?toi|retiens)\s+que\s+(.+)', question, re.I)
    if learn:
        fact = learn.group(1).strip()
        if fact not in mem.get('facts', []):
            mem.setdefault('facts', []).append(fact)
    games = detect_games(guild)
    game_ctx = "\n".join(f"- {g}" for g in games) if games else "Personne ne joue actuellement."
    facts_ctx = "\n".join(f"- {f}" for f in mem.get('facts', [])) if mem.get('facts') else "Aucun fait memorise."

    # Musique en cours et file d'attente pour éviter les doublons aléatoires
    cur = now_playing.get(guild.id) if guild else None
    q = list(Q(guild.id)) if guild else []
    queue_list = []
    if cur:
        queue_list.append(f"En cours de lecture : {cur['title']}")
    if q:
        for i, s in enumerate(q):
            queue_list.append(f"En attente #{i+1} : {s['title']}")
    queue_ctx = "\n".join(queue_list) if queue_list else "Aucune musique en cours de lecture ni en attente."

    sys_prompt = (
        f"Tu es Antigravity, un bot Discord cool et amical. "
        f"Reponds TOUJOURS en francais, de facon concise et naturelle. Utilise des emojis.\n"
        f"Utilisateur actuel : {username} (ID: {user_id}).\n"
        f"Heure locale : {datetime.datetime.now().strftime('%H:%M')}.\n\n"
        f"ACTIVITES SUR LE SERVEUR :\n{game_ctx}\n\n"
        f"MEMOIRE de {username} :\n{facts_ctx}\n\n"
        f"MUSIQUES ACTUELLES SUR LE SERVEUR :\n{queue_ctx}\n\n"
        f"CONTROLE MUSIQUE IMPORTANT :\n"
        f"Tu AS le pouvoir de controler la musique et de la faire jouer sur le serveur Discord !\n"
        f"Ne reponds JAMAIS que tu ne peux pas jouer de musique. Si l'utilisateur te demande de lancer/retirer une chanson, accepte et ajoute la balise en fin de reponse.\n\n"
        f"REGLES MUSIQUE CRITIQUES (Genere UNE SEULE balise d'action en fin de reponse, jamais de doublons) :\n"
        f"- Si l'utilisateur donne un LIEN / URL (youtube, etc.), utilise EXACTEMENT ce lien : [ACTION:PLAY:le_lien]\n"
        f"- Si l'utilisateur demande de jouer un titre, utilise : [ACTION:PLAY:Titre - Artiste]\n"
        f"- Si l'utilisateur demande de SUPPRIMER ou ENLEVER une musique (par son NUMERO ou son TITRE, ex: 'enleve la 2', 'retire Billie Jean'), regarde la liste 'MUSIQUES ACTUELLES' ci-dessus. Utilise OBLIGATOIREMENT : [ACTION:REMOVE:numero_ou_titre] (ex: [ACTION:REMOVE:2] ou [ACTION:REMOVE:Billie Jean]). INTERDICTION FORMELLE DE GENERER UNE BALISE PLAY SI L'UTILISATEUR DEMANDE DE SUPPRIMER.\n"
        f"- Si l'utilisateur demande une musique ALEATOIRE, choisis un titre qui n'est PAS dans la liste actuelle.\n"
        f"- Si l'utilisateur demande de passer/skipper, ajoute uniquement : [ACTION:SKIP]\n"
        f"- Si l'utilisateur demande d'arrêter/stopper, ajoute uniquement : [ACTION:STOP]\n"
        f"- Si l'utilisateur demande pause ou reprendre, utilise [ACTION:PAUSE] ou [ACTION:RESUME]\n"
        f"Exemple de bonne reponse: 'Je te mets ca tout de suite !' suivi de [ACTION:PLAY:https://youtu.be/hNbg9Jsdq9A]"
    )

    msgs = [{"role": "system", "content": sys_prompt}]
    for h in (mem.get('history') or [])[-6:]:  # Plus léger : 6 messages passés à l'IA
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": question})

    try:
        req = urllib.request.Request(ZHIPU_URL,
            data=json.dumps({"model": "glm-4-flash", "messages": msgs}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {ZHIPU_KEY}"},
            method="POST")
        res = json.loads(await asyncio.to_thread(
            lambda: urllib.request.urlopen(req, timeout=20).read().decode()))
        ai_text = res['choices'][0]['message']['content']
    except Exception as e:
        ai_text = f"Desole, erreur IA : {e}"

    mem.setdefault('history', []).append({"role": "user", "content": question})
    mem['history'].append({"role": "assistant", "content": ai_text})
    if len(mem['history']) > 10:  # Limite l'historique complet à 10
        mem['history'] = mem['history'][-10:]
    await save_mem(user_id, mem, mid)
    return ai_text

# ══════════════════════════════════════════════════════════════════════
# Événements et Commande Ask
# ══════════════════════════════════════════════════════════════════════
@bot.command(name="ask", aliases=["ia", "chat"])
async def cmd_ask(ctx, *, question: str):
    """Commande pour parler à l'IA directement (fallback)"""
    async with ctx.typing():
        response = await ai_respond(
            ctx.author.id, ctx.author.display_name,
            question, ctx.guild)
    
    if "[ACTION:SKIP]" in response:
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            loops[ctx.guild.id] = False
            vc.stop()
    if "[ACTION:PAUSE]" in response:
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            s = now_playing.get(ctx.guild.id)
            if s:
                s['pause_start'] = datetime.datetime.now()
                if s.get('embed_message_id'):
                    try:
                        ch = bot.get_channel(MUS_CH)
                        if ch:
                            msg = await ch.fetch_message(s['embed_message_id'])
                            await msg.edit(embed=playing_embed(s, is_paused=True, guild_id=ctx.guild.id))
                    except Exception: pass
    if "[ACTION:RESUME]" in response:
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            s = now_playing.get(ctx.guild.id)
            if s:
                if 'pause_start' in s:
                    s['paused_duration'] = s.get('paused_duration', 0) + (datetime.datetime.now() - s['pause_start']).total_seconds()
                    del s['pause_start']
                if s.get('embed_message_id'):
                    try:
                        ch = bot.get_channel(MUS_CH)
                        if ch:
                            msg = await ch.fetch_message(s['embed_message_id'])
                            await msg.edit(embed=playing_embed(s, is_paused=False, guild_id=ctx.guild.id))
                    except Exception: pass
            vc.resume()
    if "[ACTION:STOP]" in response:
        await delete_previous_embed(ctx.guild)
        Q(ctx.guild.id).clear()
        loops[ctx.guild.id] = False
        now_playing[ctx.guild.id] = None
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
        await bot.change_presence(activity=None)

    remove_actions = re.findall(r'\[ACTION:REMOVE:([^\]]+)\]', response)
    for target in remove_actions:
        try:
            target = target.strip()
            q = Q(ctx.guild.id)
            lst = list(q)
            removed = None
            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(lst):
                    removed = lst.pop(idx - 1)
            else:
                for i, s in enumerate(lst):
                    if target.lower() in s['title'].lower():
                        removed = lst.pop(i)
                        break
            if removed:
                queues[ctx.guild.id] = collections.deque(lst)
                mus_ch = bot.get_channel(MUS_CH)
                if mus_ch:
                    await mus_ch.send(f"🗑️ Supprimé par l'IA : **{removed['title']}**", delete_after=10)
        except Exception as e:
            print(f"[AI REMOVE ERR] {e}", flush=True)

    actions = re.findall(r'\[ACTION:(?:PLAY|QUEUE):([^\]]+)\]', response)
    clean = re.sub(r'\s*\[ACTION:(?:PLAY:[^\]]+|QUEUE:[^\]]+|REMOVE:[^\]]+|SKIP|PAUSE|RESUME|STOP)\]', '', response).strip()
    if clean: await ctx.send(f"🤖 {clean}")
    
    if actions:
        mus_ch = bot.get_channel(MUS_CH)
        for i, title in enumerate(actions):
            try:
                vc = ctx.guild.voice_client
                if not vc:
                    if ctx.author.voice:
                        vc = await ctx.author.voice.channel.connect()
                    else:
                        await ctx.send("❌ Rejoins un vocal pour la musique !")
                        break
                await run_play(ctx.guild, title.strip(), "Antigravity IA", mus_ch)
                if i < len(actions) - 1: await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[AI PLAY ERR] {title}: {e}", flush=True)
                await ctx.send(f"❌ Erreur pour **{title.strip()}** : {e}")

@bot.event
async def on_ready():
    print(f"[READY] {bot.user} en ligne !", flush=True)
    print(f"[READY] Guilds : {[g.name for g in bot.guilds]}", flush=True)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure): return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant. Ex: `!play jul alien`")
    elif isinstance(error, commands.CommandNotFound): pass
    else: print(f"[CMD ERR] {ctx.command}: {error}", flush=True)

@bot.event
async def on_message(message):
    if message.author.bot: return
    await bot.process_commands(message)
    if message.channel.id != NGR_CH or message.content.startswith("!"): return

    async with message.channel.typing():
        response = await ai_respond(
            message.author.id, message.author.display_name,
            message.content, message.guild)

    if "[ACTION:SKIP]" in response:
        vc = message.guild.voice_client
        if vc and vc.is_playing():
            loops[message.guild.id] = False
            vc.stop()
    if "[ACTION:PAUSE]" in response:
        vc = message.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            s = now_playing.get(message.guild.id)
            if s:
                s['pause_start'] = datetime.datetime.now()
                if s.get('embed_message_id'):
                    try:
                        ch = bot.get_channel(MUS_CH)
                        if ch:
                            msg = await ch.fetch_message(s['embed_message_id'])
                            await msg.edit(embed=playing_embed(s, is_paused=True, guild_id=message.guild.id))
                    except Exception: pass
    if "[ACTION:RESUME]" in response:
        vc = message.guild.voice_client
        if vc and vc.is_paused():
            s = now_playing.get(message.guild.id)
            if s:
                if 'pause_start' in s:
                    s['paused_duration'] = s.get('paused_duration', 0) + (datetime.datetime.now() - s['pause_start']).total_seconds()
                    del s['pause_start']
                if s.get('embed_message_id'):
                    try:
                        ch = bot.get_channel(MUS_CH)
                        if ch:
                            msg = await ch.fetch_message(s['embed_message_id'])
                            await msg.edit(embed=playing_embed(s, is_paused=False, guild_id=message.guild.id))
                    except Exception: pass
            vc.resume()
    if "[ACTION:STOP]" in response:
        await delete_previous_embed(message.guild)
        Q(message.guild.id).clear()
        loops[message.guild.id] = False
        now_playing[message.guild.id] = None
        if message.guild.voice_client:
            await message.guild.voice_client.disconnect()
        await bot.change_presence(activity=None)

    remove_actions = re.findall(r'\[ACTION:REMOVE:([^\]]+)\]', response)
    for target in remove_actions:
        try:
            target = target.strip()
            q = Q(message.guild.id)
            lst = list(q)
            removed = None
            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(lst):
                    removed = lst.pop(idx - 1)
            else:
                for i, s in enumerate(lst):
                    if target.lower() in s['title'].lower():
                        removed = lst.pop(i)
                        break
            if removed:
                queues[message.guild.id] = collections.deque(lst)
                mus_ch = bot.get_channel(MUS_CH)
                if mus_ch:
                    await mus_ch.send(f"🗑️ Supprimé par l'IA : **{removed['title']}**", delete_after=10)
        except Exception as e:
            print(f"[AI REMOVE ERR] {e}", flush=True)

    actions = re.findall(r'\[ACTION:(?:PLAY|QUEUE):([^\]]+)\]', response)
    clean = re.sub(r'\s*\[ACTION:(?:PLAY:[^\]]+|QUEUE:[^\]]+|REMOVE:[^\]]+|SKIP|PAUSE|RESUME|STOP)\]', '', response).strip()
    if clean: await message.channel.send(f"👾 {clean}")

    if actions:
        mus_ch = bot.get_channel(MUS_CH)
        for i, title in enumerate(actions):
            try:
                vc = message.guild.voice_client
                if not vc:
                    if message.author.voice:
                        vc = await message.author.voice.channel.connect()
                    else:
                        await message.channel.send("❌ Rejoins un vocal pour la musique !")
                        break
                await run_play(message.guild, title.strip(), "Antigravity IA", mus_ch)
                if i < len(actions) - 1: await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[AI PLAY ERR] {title}: {e}", flush=True)
                await message.channel.send(f"❌ Erreur pour **{title.strip()}** : {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    vc = member.guild.voice_client
    if not vc or not vc.channel: return
    
    # Récupérer la liste des humains actuellement dans le salon du bot
    humans_in_channel = [m for m in vc.channel.members if not m.bot]
    
    # CAS 1 : Quelqu'un quitte le salon et il n'y a plus aucun humain
    if before.channel == vc.channel and after.channel != vc.channel:
        if len(humans_in_channel) == 0:
            if vc.is_playing():
                vc.pause()
                s = now_playing.get(member.guild.id)
                if s:
                    s['pause_start'] = datetime.datetime.now()
                    # Met à jour le message embed pour dire que c'est en pause
                    if s.get('embed_message_id'):
                        try:
                            ch = bot.get_channel(MUS_CH)
                            if ch:
                                msg = await ch.fetch_message(s['embed_message_id'])
                                await msg.edit(embed=playing_embed(s, is_paused=True, guild_id=member.guild.id))
                        except Exception: pass
                print(f"[AUTO-PAUSE] Plus personne dans le vocal, mise en pause.", flush=True)

    # CAS 2 : Quelqu'un rejoint le salon et il y a au moins un humain (le nouveau ou ceux déjà là)
    if after.channel == vc.channel and before.channel != vc.channel:
        if len(humans_in_channel) > 0 and vc.is_paused():
            s = now_playing.get(member.guild.id)
            if s:
                if 'pause_start' in s:
                    # Calcule le temps passé en pause pour pas que la barre de progression bugue
                    s['paused_duration'] = s.get('paused_duration', 0) + (datetime.datetime.now() - s['pause_start']).total_seconds()
                    del s['pause_start']
                
                # Met à jour le message embed pour dire que ça a repris
                if s.get('embed_message_id'):
                    try:
                        ch = bot.get_channel(MUS_CH)
                        if ch:
                            msg = await ch.fetch_message(s['embed_message_id'])
                            await msg.edit(embed=playing_embed(s, is_paused=False, guild_id=member.guild.id))
                    except Exception: pass
            
            vc.resume()
            print(f"[AUTO-RESUME] Un humain est de retour, reprise de la lecture.", flush=True)

# ══════════════════════════════════════════════════════════════════════
bot.run(TOKEN)
