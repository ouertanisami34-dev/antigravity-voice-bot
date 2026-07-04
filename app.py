import asyncio
import discord
import yt_dlp
import os
import sys
import collections
import datetime
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
        self.wfile.write(b"Antigravity Music Bot OK")
    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 8000))
threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(),
    daemon=True
).start()
print(f"[BOOT] Serveur web sur le port {port}", flush=True)

# ============================================================
# Configuration
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    sys.exit("DISCORD_BOT_TOKEN manquant")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = discord.Bot(intents=intents)

# ============================================================
# yt-dlp et FFmpeg
# ============================================================
YTDL_OPTS = {
    'format': 'bestaudio[acodec=opus]/bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['web']}},
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# ============================================================
# Etat par serveur
# ============================================================
queues = {}
now_playing = {}
volumes = {}

def get_queue(gid):
    return queues.setdefault(gid, collections.deque())

def get_vol(gid):
    return volumes.get(gid, 0.5)

# ============================================================
# Extraction audio
# ============================================================
async def extract(query):
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

def fmt_dur(s):
    if not s:
        return "🔴 Live"
    return str(datetime.timedelta(seconds=int(s)))

# ============================================================
# Lecture enchainee
# ============================================================
def play_next(guild):
    q = get_queue(guild.id)
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return
    if not q:
        now_playing[guild.id] = None
        asyncio.run_coroutine_threadsafe(auto_leave(guild), bot.loop)
        return
    song = q.popleft()
    now_playing[guild.id] = song
    src = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
        volume=get_vol(guild.id)
    )
    vc.play(src, after=lambda e: play_next(guild))
    print(f"[PLAY] {song['title']}", flush=True)

async def auto_leave(guild, delay=180):
    await asyncio.sleep(delay)
    vc = guild.voice_client
    if vc and vc.is_connected() and not vc.is_playing():
        await vc.disconnect()
        print(f"[AUTO] Deconnexion apres inactivite", flush=True)

# ============================================================
# Embeds
# ============================================================
def embed_playing(song, who):
    e = discord.Embed(
        title="🎵 En cours de lecture",
        description=f"**[{song['title']}]({song['webpage_url']})**",
        color=0x5865F2
    )
    if song['thumbnail']:
        e.set_thumbnail(url=song['thumbnail'])
    e.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
    e.add_field(name="🎤 Artiste", value=song['uploader'], inline=True)
    e.add_field(name="👤 Par", value=who.mention, inline=True)
    return e

def embed_queued(song, pos, who):
    e = discord.Embed(
        title="📋 Ajouté à la file",
        description=f"**[{song['title']}]({song['webpage_url']})**",
        color=0x57F287
    )
    if song['thumbnail']:
        e.set_thumbnail(url=song['thumbnail'])
    e.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
    e.add_field(name="📍 Position", value=f"#{pos}", inline=True)
    e.add_field(name="👤 Par", value=who.mention, inline=True)
    return e

def embed_err(msg):
    return discord.Embed(title="❌ Erreur", description=msg, color=0xED4245)

# ============================================================
# Evenements
# ============================================================
@bot.event
async def on_ready():
    print(f"[OK] {bot.user} connecte — {len(bot.guilds)} serveur(s)", flush=True)

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
                print("[AUTO] Plus personne — deconnexion", flush=True)

# ============================================================
# Commandes Slash
# ============================================================
@bot.slash_command(name="play", description="🎵 Joue une musique (lien ou recherche)")
async def cmd_play(
    ctx,
    query: discord.Option(str, description="Lien YouTube/SoundCloud ou nom de la chanson")
):
    if not ctx.author.voice:
        return await ctx.respond(
            embed=embed_err("Rejoins un salon vocal d'abord !"), ephemeral=True
        )

    ch = ctx.author.voice.channel

    if ctx.voice_client is None:
        await ch.connect()
    elif ctx.voice_client.channel != ch:
        await ctx.voice_client.move_to(ch)

    await ctx.defer()

    try:
        song = await extract(query)
    except Exception as e:
        return await ctx.followup.send(
            embed=embed_err(f"Impossible de charger cette musique.\n`{e}`")
        )

    gid = ctx.guild.id
    q = get_queue(gid)

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        q.append(song)
        await ctx.followup.send(embed=embed_queued(song, len(q), ctx.author))
    else:
        now_playing[gid] = song
        src = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
            volume=get_vol(gid)
        )
        ctx.voice_client.play(src, after=lambda e: play_next(ctx.guild))
        await ctx.followup.send(embed=embed_playing(song, ctx.author))


@bot.slash_command(name="pause", description="⏸️ Met la musique en pause")
async def cmd_pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.respond(
            embed=discord.Embed(title="⏸️ En pause", color=0xFEE75C)
        )
    else:
        await ctx.respond(
            embed=embed_err("Rien ne joue actuellement."), ephemeral=True
        )


@bot.slash_command(name="resume", description="▶️ Reprend la lecture")
async def cmd_resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.respond(
            embed=discord.Embed(title="▶️ Reprise", color=0x57F287)
        )
    else:
        await ctx.respond(
            embed=embed_err("La musique n'est pas en pause."), ephemeral=True
        )


@bot.slash_command(name="skip", description="⏭️ Passe à la chanson suivante")
async def cmd_skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.respond(
            embed=discord.Embed(title="⏭️ Chanson passée", color=0x5865F2)
        )
    else:
        await ctx.respond(embed=embed_err("Rien à passer."), ephemeral=True)


@bot.slash_command(name="stop", description="🛑 Arrête tout et déconnecte le bot")
async def cmd_stop(ctx):
    if not ctx.voice_client:
        return await ctx.respond(
            embed=embed_err("Le bot n'est pas connecté."), ephemeral=True
        )
    get_queue(ctx.guild.id).clear()
    now_playing[ctx.guild.id] = None
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.respond(
        embed=discord.Embed(
            title="🛑 Arrêté",
            description="À bientôt ! 👋",
            color=0xED4245
        )
    )


@bot.slash_command(name="queue", description="📋 Affiche la file d'attente")
async def cmd_queue(ctx):
    gid = ctx.guild.id
    q = get_queue(gid)
    cur = now_playing.get(gid)

    if not cur and not q:
        return await ctx.respond(
            embed=embed_err("File d'attente vide."), ephemeral=True
        )

    e = discord.Embed(title="📋 File d'attente", color=0x5865F2)

    if cur:
        e.add_field(
            name="🎵 En cours",
            value=f"**{cur['title']}** — {fmt_dur(cur['duration'])}",
            inline=False
        )

    if q:
        lines = []
        for i, s in enumerate(list(q)[:10], 1):
            lines.append(f"`{i}.` **{s['title']}** — {fmt_dur(s['duration'])}")
        if len(q) > 10:
            lines.append(f"... et {len(q) - 10} autre(s)")
        e.add_field(name="⏳ À suivre", value="\n".join(lines), inline=False)

    e.set_footer(text=f"{len(q)} chanson(s) en attente")
    await ctx.respond(embed=e)


@bot.slash_command(name="nowplaying", description="🎵 Affiche la musique en cours")
async def cmd_np(ctx):
    cur = now_playing.get(ctx.guild.id)
    if not cur:
        return await ctx.respond(
            embed=embed_err("Rien ne joue."), ephemeral=True
        )
    await ctx.respond(embed=embed_playing(cur, ctx.author))


@bot.slash_command(name="volume", description="🔊 Règle le volume (0-100)")
async def cmd_vol(
    ctx,
    level: discord.Option(
        int, description="Niveau de volume (0-100)", min_value=0, max_value=100
    )
):
    if not ctx.voice_client:
        return await ctx.respond(
            embed=embed_err("Bot non connecté."), ephemeral=True
        )

    v = level / 100
    volumes[ctx.guild.id] = v

    if ctx.voice_client.source and hasattr(ctx.voice_client.source, 'volume'):
        ctx.voice_client.source.volume = v

    icon = "🔇" if level == 0 else "🔈" if level < 33 else "🔉" if level < 66 else "🔊"
    await ctx.respond(
        embed=discord.Embed(title=f"{icon} Volume : {level}%", color=0x5865F2)
    )


# ============================================================
# Lancement
# ============================================================
bot.run(TOKEN)
