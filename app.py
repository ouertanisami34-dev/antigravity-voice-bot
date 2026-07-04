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
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Serveur web minimal pour Render (Port 10000)
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
if not TOKEN:
    print("[ERREUR CRITIQUE] Le token DISCORD_BOT_TOKEN est introuvable !", flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

# Prefix classique '!'
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
# Configuration YTDL & FFmpeg
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
# Fonctions utilitaires
# ============================================================
async def extract_audio(query):
    print(f"[YTDL] Extraction de la recherche : '{query}'", flush=True)
    try:
        data = await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))
        if 'entries' in data:
            data = data['entries'][0]
        
        info = {
            'title': data.get('title', 'Inconnu'),
            'url': data.get('url'),
            'webpage_url': data.get('webpage_url', ''),
            'thumbnail': data.get('thumbnail', ''),
            'duration': data.get('duration', 0),
            'uploader': data.get('uploader', 'Inconnu'),
        }
        print(f"[YTDL] Extraction reussie : {info['title']}", flush=True)
        return info
    except Exception as e:
        print(f"[YTDL ERREUR] Impossible d'extraire l'audio : {e}", flush=True)
        traceback.print_exc()
        raise e

def fmt_dur(s):
    if not s:
        return "🔴 Live"
    return str(datetime.timedelta(seconds=int(s)))

def play_next(guild):
    q = get_queue(guild.id)
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        print(f"[PLAY] Bot non connecte, arret de la boucle.", flush=True)
        return
    
    if not q:
        now_playing[guild.id] = None
        print(f"[PLAY] File d'attente vide. Deconnexion automatique du vocal...", flush=True)
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
        print(f"[PLAY] En cours de lecture : {song['title']}", flush=True)
    except Exception as e:
        print(f"[PLAY ERREUR] Erreur de lecture : {e}", flush=True)
        traceback.print_exc()

# ============================================================
# Evenements du Bot
# ============================================================
@bot.event
async def on_ready():
    print(f"[OK] Bot pret et connecte en tant que : {bot.user}", flush=True)
    print(f"[INFO] Connecte a {len(bot.guilds)} serveurs.", flush=True)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # Affiche absolument tous les messages recus dans la console Render
    print(f"[MESSAGE REÇU] De '{message.author.name}' dans #{message.channel.name} : '{message.content}'", flush=True)
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    print(f"[ERREUR COMMANDE] {ctx.command} : {error}", flush=True)
    await ctx.send(f"❌ Une erreur est survenue : `{error}`")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    if before.channel:
        vc = before.channel.guild.voice_client
        if vc and vc.channel == before.channel:
            # Si plus aucun humain n'est present dans le salon
            if all(m.bot for m in before.channel.members):
                get_queue(before.channel.guild.id).clear()
                now_playing[before.channel.guild.id] = None
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect()
                print("[AUTO] Salon vide, deconnexion automatique effectuee.", flush=True)

# ============================================================
# Commandes textuelles prefixe '!'
# ============================================================
@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
    print(f"[COMMANDE] !play recue de {ctx.author.name} avec la requete : '{query}'", flush=True)
    
    if not ctx.author.voice:
        print("[COMMANDE] Annulation : l'auteur n'est pas en vocal.", flush=True)
        return await ctx.send("❌ Tu dois d'abord rejoindre un salon vocal !")

    ch = ctx.author.voice.channel

    # Connexion ou deplacement
    try:
        if ctx.voice_client is None:
            print(f"[COMMANDE] Connexion au salon vocal : {ch.name}", flush=True)
            await ch.connect()
        elif ctx.voice_client.channel != ch:
            print(f"[COMMANDE] Deplacement vers le salon vocal : {ch.name}", flush=True)
            await ctx.voice_client.move_to(ch)
    except Exception as e:
        print(f"[COMMANDE ERREUR] Echec de la connexion vocale : {e}", flush=True)
        return await ctx.send(f"❌ Erreur de connexion vocale : `{e}`")

    # Indicateur d'ecriture
    async with ctx.typing():
        try:
            song = await extract_audio(query)
        except Exception as e:
            return await ctx.send(f"❌ Impossible de charger cette musique : `{e}`")

        gid = ctx.guild.id
        q = get_queue(gid)

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            q.append(song)
            print(f"[COMMANDE] Musique ajoutee a la file (Position #{len(q)})", flush=True)
            
            embed = discord.Embed(title="📋 Ajouté à la file", description=f"**[{song['title']}]({song['webpage_url']})**", color=0x57F287)
            if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
            embed.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
            embed.add_field(name="🎤 Artiste", value=song['uploader'], inline=True)
            await ctx.send(embed=embed)
        else:
            now_playing[gid] = song
            try:
                src = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS),
                    volume=get_vol(gid)
                )
                ctx.voice_client.play(src, after=lambda e: play_next(ctx.guild))
                print(f"[COMMANDE] Lancement direct de la lecture : {song['title']}", flush=True)
                
                embed = discord.Embed(title="🎵 En cours de lecture", description=f"**[{song['title']}]({song['webpage_url']})**", color=0x5865F2)
                if song['thumbnail']: embed.set_thumbnail(url=song['thumbnail'])
                embed.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
                embed.add_field(name="🎤 Artiste", value=song['uploader'], inline=True)
                await ctx.send(embed=embed)
            except Exception as e:
                print(f"[COMMANDE ERREUR] Echec lors du lancement audio : {e}", flush=True)
                traceback.print_exc()
                await ctx.send(f"❌ Erreur lors du lancement de la musique : `{e}`")

@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Musique mise en pause.")
    else:
        await ctx.send("❌ Rien ne joue actuellement.")

@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Lecture reprise.")
    else:
        await ctx.send("❌ La musique n'est pas en pause.")

@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Musique passée.")
    else:
        await ctx.send("❌ Aucune musique en cours.")

@bot.command(name="stop")
async def stop(ctx):
    if not ctx.voice_client:
        return await ctx.send("❌ Le bot n'est pas connecté.")
    get_queue(ctx.guild.id).clear()
    now_playing[ctx.guild.id] = None
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Musique arrêtée et bot déconnecté.")

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
        return await ctx.send("❌ Le bot n'est pas connecté en vocal.")
    if not (0 <= level <= 100):
        return await ctx.send("❌ Le volume doit être entre 0 et 100.")
    
    v = level / 100
    volumes[ctx.guild.id] = v
    if ctx.voice_client.source and hasattr(ctx.voice_client.source, 'volume'):
        ctx.voice_client.source.volume = v
    await ctx.send(f"🔊 Volume réglé à **{level}%**")

# Lancement du bot
bot.run(TOKEN)
