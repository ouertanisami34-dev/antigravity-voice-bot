"""Antigravity V3 â€” Bot Discord Ultime (Musique + IA + Animations)"""
import asyncio, discord, os, sys, collections, datetime, threading
import urllib.request, json, re, random, traceback
from discord.ext import commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import yt_dlp

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# INTERFACE MUSIQUE (Embeds)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Redirection des flux pour le dÃ©bogage en ligne
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
    if not s: return "ðŸ”´ Live"
    s = int(s)
    if s >= 3600: return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"

def get_elapsed(song):
    if not song or 'start_time' not in song: return 0
    ref = song.get('pause_start', datetime.datetime.now())
    return max(0, int((ref - song['start_time']).total_seconds() - song.get('paused_duration', 0)))

def progress_bar(elapsed, total, length=20):
    if not total: return "ðŸ”´ `[â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬â–¬]` **Live**"
    pct = min(1.0, max(0, elapsed / total))
    filled = int(length * pct)
    bar = "â–¬" * filled + "ðŸ”˜" + "â–¬" * max(0, length - filled - 1)
    return f"â–¶ï¸ `{bar}` **[{fmt_dur(elapsed)} / {fmt_dur(total)}]**"

def playing_embed(song, is_paused=False, guild_id=None):
    elapsed = get_elapsed(song)
    total = song.get('duration', 0)
    status_icon = "â¸ï¸" if is_paused else "â–¶ï¸"
    
    em = discord.Embed(title=f"{status_icon} Lecture en cours",
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**\n\n{progress_bar(elapsed, total)}", color=PINK)
    if song.get('thumbnail'): em.set_image(url=song['thumbnail'])
    em.add_field(name="ðŸŽ¤ Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.add_field(name="â±ï¸ DurÃ©e", value=fmt_dur(total), inline=True)
    if song.get('requester'):
        em.add_field(name="ðŸ‘¤ Par", value=song['requester'], inline=True)
    if guild_id:
        q = list(Q(guild_id))
        if q:
            lines = []
            for i, s in enumerate(q[:5]):
                lines.append(f"`#{i + 1}` **{s['title']}**")
            if len(q) > 5:
                lines.append(f"*...et {len(q) - 5} autres morceaux*")
            em.add_field(name="ðŸŽ¶ Ã€ venir", value="\n".join(lines), inline=False)
    em.set_footer(text="Antigravity Music ðŸŽ¶ â€¢ !skip pour passer â€¢ !queue pour la file")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

def added_embed(song, position):
    em = discord.Embed(title="âœ… AjoutÃ© Ã  la file d'attente",
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**", color=GREEN)
    if song.get('thumbnail'): em.set_thumbnail(url=song['thumbnail'])
    em.add_field(name="â±ï¸ DurÃ©e", value=fmt_dur(song.get('duration', 0)), inline=True)
    em.add_field(name="ðŸ“ Position", value=f"#{position}", inline=True)
    em.add_field(name="ðŸŽ¤ Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.set_footer(text="Antigravity Music ðŸŽ¶")
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
        return discord.Embed(title="ðŸŽµ Rien en cours",
            description="Utilise `!play <titre>` pour lancer une musique !", color=VIOLET)
    elapsed = get_elapsed(song)
    total = song.get('duration', 0)
    icon = "â¸ï¸" if is_paused else "ðŸ”" if is_looped else "â–¶ï¸"
    status = "En pause" if is_paused else "En boucle" if is_looped else "En cours"
    em = discord.Embed(title=f"ðŸŽµ {song['title']}", url=song.get('webpage_url', ''), color=VIOLET,
        description=f"{icon} **{status}**\n\n{progress_bar(elapsed, total)}")
    if song.get('thumbnail'): em.set_thumbnail(url=song['thumbnail'])
    em.add_field(name="ðŸŽ¤ Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.add_field(name="â±ï¸ DurÃ©e", value=fmt_dur(total), inline=True)
    em.add_field(name="ðŸ”Š Volume", value=f"{volume}%", inline=True)
    em.set_footer(text="Antigravity Music ðŸŽ¶")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

def queue_embed(q_list, current, is_paused=False, is_looped=False, volume=50):
    em = discord.Embed(title="ðŸ“‹ File d'attente â€” Antigravity", color=BLUE)
    if current:
        elapsed = get_elapsed(current)
        total = current.get('duration', 0)
        icon = "â¸ï¸" if is_paused else "ðŸ”" if is_looped else "â–¶ï¸"
        em.add_field(name=f"{icon} En cours", inline=False,
            value=f"**[{current['title']}]({current.get('webpage_url', '')})**\n"
                  f"{progress_bar(elapsed, total)}")
    else:
        em.add_field(name="â–¶ï¸ En cours", value="*Rien en lecture*", inline=False)
    if q_list:
        lines = []
        for i, s in enumerate(q_list[:10]):
            lines.append(f"`{i + 1}.` **{s['title']}** â€” {fmt_dur(s.get('duration', 0))}")
        if len(q_list) > 10:
            lines.append(f"\n*...et {len(q_list) - 10} de plus*")
        total_dur = sum(s.get('duration', 0) for s in q_list)
        nb = len(q_list)
        em.add_field(name=f"ðŸŽ¶ Ã€ venir â€” {nb} titre{'s' if nb > 1 else ''}",
                     value="\n".join(lines), inline=False)
        em.set_footer(text=f"DurÃ©e totale : {fmt_dur(total_dur)} â€¢ ðŸ”Š {volume}% â€¢ Antigravity Music ðŸŽ¶")
    else:
        em.add_field(name="ðŸŽ¶ Ã€ venir", value="*File vide â€” `!play <titre>` pour ajouter*", inline=False)
        em.set_footer(text=f"ðŸ”Š {volume}% â€¢ Antigravity Music ðŸŽ¶")
    em.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return em

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Serveur web santÃ© pour Render (obligatoire)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Configuration
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Garde de salon
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
MUS_CMDS = {"play", "p", "skip", "s", "pause", "resume", "stop", "queue", "q",
            "volume", "vol", "clearqueue", "cq", "remove", "rm", "loop",
            "shuffle", "np", "nowplaying", "help", "debuglogs"}

@bot.check
async def channel_guard(ctx):
    target = MUS_CH if ctx.command.name in MUS_CMDS else NGR_CH
    if ctx.channel.id != target:
        try: await ctx.message.delete()
        except discord.errors.Forbidden: pass
        a = await ctx.send(f"âŒ {ctx.author.mention}, utilise <#{target}> pour cette commande !")
        await asyncio.sleep(4)
        try: await a.delete()
        except discord.errors.Forbidden: pass
        return False
    return True

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# YTDL + Extraction audio
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YTDL_OPTS = {
    'format': 'bestaudio[acodec=opus]/bestaudio/best',
    'noplaylist': True, 'quiet': True,
    'no_warnings': True, 'source_address': '0.0.0.0',
    'nocheckcertificate': True, 'geo_bypass': True,
    'prefer_free_formats': True,
}
FF = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -b:a 192k'
}
ytdl_client = yt_dlp.YoutubeDL(YTDL_OPTS)

def yt_id(url):
    m = re.search(r'(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([^?&\s]+)', url or '')
    return m.group(1) if m else None

def _make_song(d):
    return {'title': d.get('title', '?'), 'url': d.get('url', ''),
            'webpage_url': d.get('webpage_url', ''), 'thumbnail': d.get('thumbnail', ''),
            'duration': d.get('duration', 0), 'uploader': d.get('uploader', '?')}

async def extract(query):
    vid = yt_id(query)
    if not vid and query.startswith(('http://', 'https://')):
        d = await asyncio.to_thread(lambda: ytdl_client.extract_info(query, download=False))
        if 'entries' in d: d = d['entries'][0]
        return _make_song(d)
    try:
        payload = json.dumps({"video_id": vid} if vid else {"query": query}).encode()
        req = urllib.request.Request(CF_MUSIC, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
        res = json.loads(await asyncio.to_thread(
            lambda: urllib.request.urlopen(req, timeout=15).read().decode()))
        if "error" in res: raise Exception(res["error"])
        if not res.get("webpage_url") and vid:
            res["webpage_url"] = f"https://www.youtube.com/watch?v={vid}"
        return res
    except Exception as e:
        print(f"[EXTRACT ERR] Cloudflare Worker failed: {e}, falling back to direct yt-dlp", flush=True)
        d = await asyncio.to_thread(
            lambda: ytdl_client.extract_info(f"ytsearch:{query}", download=False))
        if 'entries' in d: d = d['entries'][0]
        return _make_song(d)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Moteur audio
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
        next_sync(guild)

async def run_play(guild, query, requester="?", channel=None):
    vc = guild.voice_client
    if not vc: raise Exception("Bot pas connecte au vocal")
    if now_playing.get(guild.id) is not None:
        song = {
            'title': query,
            'url': '',
            'webpage_url': '',
            'thumbnail': '',
            'duration': 0,
            'uploader': 'Attente de lecture...',
            'original_query': query,
            'requester': requester
        }
        Q(guild.id).append(song)
        if channel: await channel.send(embed=added_embed(song, len(Q(guild.id))), delete_after=10)
        return song
    song = await extract(query)
    song['original_query'] = query
    song['requester'] = requester
    now_playing[guild.id] = song
    src = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(song['url'], **FF), volume=V(guild.id))
    song['start_time'] = datetime.datetime.now()
    song['paused_duration'] = 0
    vc.play(src, after=lambda e: next_sync(guild))
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name=song['title'][:50]))
    if channel:
        msg = await channel.send(embed=playing_embed(song, False, guild.id))
        song['embed_message_id'] = msg.id
        asyncio.create_task(update_embed_loop(guild, song, msg))
    return song

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Commandes Musique
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@bot.command(name="play", aliases=["p"])
async def cmd_play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("âŒ Rejoins un salon vocal d'abord !", delete_after=5)
    vc = ctx.voice_client
    if not vc or not vc.is_connected():
        vc = await ctx.author.voice.channel.connect()
    try: await ctx.message.delete()
    except: pass
    msg = await ctx.send("ðŸ” Recherche en cours...")
    try:
        await run_play(ctx.guild, query, ctx.author.display_name, ctx.channel)
        try: await msg.delete()
        except: pass
    except Exception as e:
        await msg.edit(content=f"âŒ Erreur : {e}")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass

@bot.command(name="skip", aliases=["s"])
async def cmd_skip(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("âŒ Rien Ã  skipper.", delete_after=5)
    loops[ctx.guild.id] = False
    vc.stop()
    await ctx.send("â­ï¸ Skip !", delete_after=5)

@bot.command(name="pause")
async def cmd_pause(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("âŒ Rien en cours.", delete_after=5)
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
    await ctx.send("â¸ï¸ En pause.", delete_after=5)

@bot.command(name="resume")
async def cmd_resume(ctx):
    try: await ctx.message.delete()
    except: pass
    vc = ctx.voice_client
    if not vc or not vc.is_paused():
        return await ctx.send("âŒ Pas en pause.", delete_after=5)
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
    await ctx.send("â–¶ï¸ Reprise !", delete_after=5)

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
    await ctx.send("â¹ï¸ ArrÃªtÃ© et dÃ©connectÃ©.", delete_after=5)

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
        return await ctx.send("âŒ Volume entre 0 et 100.", delete_after=5)
    volumes[ctx.guild.id] = level / 100
    vc = ctx.voice_client
    if vc and vc.source and hasattr(vc.source, 'volume'):
        vc.source.volume = level / 100
    await ctx.send(f"ðŸ”Š Volume : **{level}%**", delete_after=5)

@bot.command(name="clearqueue", aliases=["cq"])
async def cmd_cq(ctx):
    try: await ctx.message.delete()
    except: pass
    Q(ctx.guild.id).clear()
    await ctx.send("ðŸ§¹ File d'attente vidÃ©e !", delete_after=5)

@bot.command(name="remove", aliases=["rm"])
async def cmd_rm(ctx, index: int):
    try: await ctx.message.delete()
    except: pass
    q = Q(ctx.guild.id)
    if not (1 <= index <= len(q)):
        return await ctx.send(f"âŒ Index entre 1 et {len(q)}.", delete_after=5)
    lst = list(q)
    removed = lst.pop(index - 1)
    queues[ctx.guild.id] = collections.deque(lst)
    await ctx.send(f"ðŸ—‘ï¸ SupprimÃ© : **{removed['title']}**", delete_after=5)

@bot.command(name="loop")
async def cmd_loop(ctx):
    try: await ctx.message.delete()
    except: pass
    loops[ctx.guild.id] = not loops.get(ctx.guild.id, False)
    status = "ðŸ” Boucle activÃ©e !" if loops[ctx.guild.id] else "âž¡ï¸ Boucle dÃ©sactivÃ©e."
    await ctx.send(status, delete_after=5)

@bot.command(name="shuffle")
async def cmd_shuffle(ctx):
    try: await ctx.message.delete()
    except: pass
    q = Q(ctx.guild.id)
    if len(q) < 2:
        return await ctx.send("âŒ Pas assez de titres Ã  mÃ©langer.", delete_after=5)
    lst = list(q)
    random.shuffle(lst)
    queues[ctx.guild.id] = collections.deque(lst)
    await ctx.send(f"ðŸ”€ File mÃ©langÃ©e ! ({len(lst)} titres)", delete_after=5)

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
    em = discord.Embed(title="ðŸš€ Antigravity V3 â€” Commandes", color=0x7C3AED,
        description="Le bot musique et IA ultime !")
    em.add_field(name="ðŸŽµ Musique (dans #musique)", inline=False, value=(
        "`!play <titre>` â€” Jouer / ajouter Ã  la file\n"
        "`!skip` â€” Passer au suivant\n"
        "`!pause` / `!resume` â€” Pause / Reprendre\n"
        "`!stop` â€” ArrÃªter et dÃ©connecter\n"
        "`!queue` â€” Voir la file d'attente\n"
        "`!np` â€” Titre en cours + progression\n"
        "`!volume <0-100>` â€” RÃ©gler le volume\n"
        "`!loop` â€” Activer/dÃ©sactiver la boucle\n"
        "`!shuffle` â€” MÃ©langer la file\n"
        "`!remove <n>` â€” Supprimer le titre #n\n"
        "`!clearqueue` â€” Vider toute la file"))
    em.add_field(name="ðŸ¤– IA (dans #mini-ngr)", inline=False,
        value="Parle directement ! Ou utilise `!ask ta question` pour parler Ã  l'IA.")
    em.set_footer(text="Antigravity V3 ðŸŽ¶ â€¢ CrÃ©Ã© avec â¤ï¸")
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
        await ctx.send(f"ðŸ“‹ **Derniers logs du bot :**\n```\n{last_lines}\n```")
    except Exception as e:
        await ctx.send(f"âŒ Impossible de lire les logs : {e}")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# IA + MÃ©moire
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async def load_mem(uid):
    try:
        ch = bot.get_channel(MEM_CH) or await bot.fetch_channel(MEM_CH)
        prefix = f"MEMORY_FOR_{uid}"
        async for m in ch.history(limit=100):
            if m.content.startswith(prefix):
                return json.loads(m.content[len(prefix):].strip()), m.id
    except Exception:
        pass
    return {"user_id": str(uid), "facts": [], "history": []}, None

async def save_mem(uid, mem, mid):
    try:
        ch = bot.get_channel(MEM_CH) or await bot.fetch_channel(MEM_CH)
        txt = f"MEMORY_FOR_{uid}\n{json.dumps(mem, ensure_ascii=False)}"
        if mid:
            m = await ch.fetch_message(mid)
            await m.edit(content=txt)
        else:
            await ch.send(content=txt)
    except Exception:
        pass

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

    sys_prompt = (
        f"Tu es Antigravity, un bot Discord cool et amical. "
        f"Reponds TOUJOURS en francais, de facon concise et naturelle. Utilise des emojis.\n"
        f"Utilisateur actuel : {username} (ID: {user_id}).\n"
        f"Heure locale : {datetime.datetime.now().strftime('%H:%M')}.\n\n"
        f"ACTIVITES SUR LE SERVEUR :\n{game_ctx}\n\n"
        f"MEMOIRE de {username} :\n{facts_ctx}\n\n"
        f"REGLES MUSIQUE CRITIQUES :\n"
        f"- Si l'utilisateur demande de jouer de la musique, ajoute EN FIN de ta reponse : [ACTION:PLAY:titre - artiste]\n"
        f"- Si l'utilisateur demande de passer/skipper la musique, ajoute EN FIN de ta reponse : [ACTION:SKIP]\n"
        f"- Si l'utilisateur demande d'arrÃªter/stopper la musique, ajoute EN FIN de ta reponse : [ACTION:STOP]\n"
        f"- Si l'utilisateur demande de mettre en pause la musique, ajoute EN FIN de ta reponse : [ACTION:PAUSE]\n"
        f"- Si l'utilisateur demande de reprendre la lecture, ajoute EN FIN de ta reponse : [ACTION:RESUME]\n"
        f"- Pour une LISTE (ex: '10 musiques de funk'), genere UNE balise play par musique.\n"
        f"- Le format EXACT de play est : [ACTION:PLAY:Titre - Artiste]"
    )

    msgs = [{"role": "system", "content": sys_prompt}]
    for h in (mem.get('history') or [])[-6:]:
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
    if len(mem['history']) > 12:
        mem['history'] = mem['history'][-12:]
    await save_mem(user_id, mem, mid)
    return ai_text

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Ã‰vÃ©nements et Commande Ask
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@bot.command(name="ask", aliases=["ia", "chat"])
async def cmd_ask(ctx, *, question: str):
    """Commande pour parler Ã  l'IA directement (fallback)"""
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

    actions = re.findall(r'\[ACTION:PLAY:([^\]]+)\]', response)
    clean = re.sub(r'\s*\[ACTION:(?:PLAY:[^\]]+|SKIP|PAUSE|RESUME|STOP)\]', '', response).strip()
    if clean: await ctx.send(f"ðŸ¤– {clean}")
    
    if actions:
        mus_ch = bot.get_channel(MUS_CH)
        for i, title in enumerate(actions):
            try:
                vc = ctx.guild.voice_client
                if not vc:
                    if ctx.author.voice:
                        vc = await ctx.author.voice.channel.connect()
                    else:
                        await ctx.send("âŒ Rejoins un vocal pour la musique !")
                        break
                await run_play(ctx.guild, title.strip(), "Antigravity IA", mus_ch)
                if i < len(actions) - 1: await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[AI PLAY ERR] {title}: {e}", flush=True)
                await ctx.send(f"âŒ Erreur pour **{title.strip()}** : {e}")

@bot.event
async def on_ready():
    print(f"[READY] {bot.user} en ligne !", flush=True)
    print(f"[READY] Guilds : {[g.name for g in bot.guilds]}", flush=True)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure): return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"âŒ Argument manquant. Ex: `!play jul alien`")
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

    actions = re.findall(r'\[ACTION:PLAY:([^\]]+)\]', response)
    clean = re.sub(r'\s*\[ACTION:(?:PLAY:[^\]]+|SKIP|PAUSE|RESUME|STOP)\]', '', response).strip()
    if clean: await message.channel.send(f"ðŸ‘¾ {clean}")

    if actions:
        mus_ch = bot.get_channel(MUS_CH)
        for i, title in enumerate(actions):
            try:
                vc = message.guild.voice_client
                if not vc:
                    if message.author.voice:
                        vc = await message.author.voice.channel.connect()
                    else:
                        await message.channel.send("âŒ Rejoins un vocal pour la musique !")
                        break
                await run_play(message.guild, title.strip(), "Antigravity IA", mus_ch)
                if i < len(actions) - 1: await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[AI PLAY ERR] {title}: {e}", flush=True)
                await message.channel.send(f"âŒ Erreur pour **{title.strip()}** : {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    vc = member.guild.voice_client
    if vc and vc.channel:
        humans = [m for m in vc.channel.members if not m.bot]
        if not humans:
            gid = member.guild.id
            Q(gid).clear(); loops[gid] = False; now_playing[gid] = None
            vc.stop(); await vc.disconnect()
            await bot.change_presence(activity=None)
            print(f"[AUTO-DC] Plus personne dans le vocal", flush=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
bot.run(TOKEN)
