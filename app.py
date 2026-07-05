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
    def log_message(self, format, *args): pass

port = int(os.environ.get("PORT", 10000))
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(), daemon=True).start()
print(f"[BOOT] Serveur web active sur le port {port}", flush=True)

# ============================================================
# Configuration
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN: sys.exit("[ERREUR] DISCORD_BOT_TOKEN manquant")

ZHIPU_API_KEY = "d67596b18ee34cf0b4bdc4b67d2d6cca.3GvLAH1h06OzPXiR"
ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

MEMORY_CHANNEL_ID = 1523012733975658637
MUSIC_CHANNEL_ID = 1523144828341325905
MINI_NGR_CHANNEL_ID = 1523147101670735972

CLOUDFLARE_VOICE_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/voice"
CLOUDFLARE_MUSIC_URL = "https://icy-wind-36d1.gamxdmeta.workers.dev/music"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.presences = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, chunk_guilds_at_startup=True)
hourly_events = {"games": set(), "songs": set(), "bot_songs": set(), "chatters": set()}

# ============================================================
# Sécurité : Vérifier si la question est liée à la musique
# ============================================================
def is_music_request(question):
    q = question.lower().strip()
    neutral = ["quel jeu", "à quoi je", "qui joue", "tu fais quoi", "bonjour", "salut", "ça va", "hello", "coucou", "qui est en ligne"]
    if any(kw in q for kw in neutral): return False
    music = ["joue", "mets", "met", "lance", "écoute", "chante", "musique", "son", "chanson", "play", "music", "song"]
    return any(kw in q for kw in music) or len(q.split()) <= 4

# ============================================================
# Modérateur de salons (Restriction des commandes)
# ============================================================
@bot.check
async def check_command_channels(ctx):
    music_cmds = {"play", "p", "pause", "resume", "skip", "s", "stop", "queue", "q", "volume", "vol", "clearqueue", "cq", "clean", "empty"}
    target = MUSIC_CHANNEL_ID if ctx.command.name in music_cmds else MINI_NGR_CHANNEL_ID
    if ctx.channel.id != target:
        try: await ctx.message.delete()
        except: pass
        alert = await ctx.send(f"❌ {ctx.author.mention}, utilise <#{target}> pour cette commande !")
        await asyncio.sleep(5)
        try: await alert.delete()
        except: pass
        return False
    return True

# ============================================================
# Configuration YTDL & FFmpeg
# ============================================================
YTDL_OPTS = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True, 'no_warnings': True, 'source_address': '0.0.0.0', 'nocheckcertificate': True, 'geo_bypass': True}
FFMPEG_OPTS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)
queues, now_playing, volumes = {}, {}, {}

def get_queue(gid): return queues.setdefault(gid, collections.deque())
def get_vol(gid): return volumes.get(gid, 0.5)
def get_yt_video_id(url):
    m = re.search(r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([^?&\s]+)', url)
    return m.group(1) if m else None

# ============================================================
# Extraction Audio via Cloudflare Worker Proxy
# ============================================================
async def extract_audio(query):
    print(f"[EXTRACTION] Query : '{query}'", flush=True)
    try:
        video_id = get_yt_video_id(query)
        if not video_id and query.startswith(('http://', 'https://')):
            data = await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))
            if 'entries' in data: data = data['entries'][0]
            return {'title': data.get('title', 'Inconnu'), 'url': data.get('url'), 'webpage_url': data.get('webpage_url', ''), 'thumbnail': data.get('thumbnail', ''), 'duration': data.get('duration', 0), 'uploader': data.get('uploader', 'Inconnu')}

        req = urllib.request.Request(CLOUDFLARE_MUSIC_URL, data=json.dumps({"video_id": video_id} if video_id else {"query": query}).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
        response = await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        res_data = json.loads(response)
        if "error" in res_data: raise Exception(res_data["error"])
        if not res_data.get("webpage_url") and video_id: res_data["webpage_url"] = f"https://www.youtube.com/watch?v={video_id}"
        return res_data
    except Exception as e:
        print(f"[EXTRACTION ERREUR] {e}", flush=True)
        raise e

def fmt_dur(s): return "🔴 Live" if not s else str(datetime.timedelta(seconds=int(s)))

def get_elapsed_time(song):
    if not song or 'start_time' not in song: return 0
    ref = song['pause_start'] if 'pause_start' in song else datetime.datetime.now()
    return max(0, int((ref - song['start_time']).total_seconds() - song.get('paused_duration', 0)))

def make_progress_bar(elapsed, total):
    if not total: return "🔴 [▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬] Live"
    length = 20
    percent = elapsed / total
    filled = max(0, min(length, int(length * percent)))
    bar = "▬" * filled + "🔘" + "▬" * (length - filled - 1)
    return f"▶️ {bar} `[{fmt_dur(elapsed)} / {fmt_dur(total)}]`"

# ============================================================
# Logique de file d'attente threadsafe asynchrone
# ============================================================
def play_next_threadsafe(guild):
    asyncio.run_coroutine_threadsafe(play_next_async(guild), bot.loop)

async def play_next_async(guild):
    q = get_queue(guild.id)
    vc = guild.voice_client
    if not vc or not vc.is_connected(): return
    if not q:
        now_playing[guild.id] = None
        await vc.disconnect()
        return
    song = q.popleft()
    now_playing[guild.id] = song
    try:
        await asyncio.sleep(0.5)
        print(f"[PLAY_NEXT] Rafraichissement pour : '{song['title']}'", flush=True)
        try:
            fresh = await extract_audio(song.get('webpage_url') or song.get('original_query') or song['title'])
            stream_url = fresh['url']
        except Exception as re_err:
            print(f"[REFRESH ERR] Utilisation backup : {re_err}", flush=True)
            stream_url = song['url']
        
        src = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS), volume=get_vol(guild.id))
        song['start_time'] = datetime.datetime.now()
        song['paused_duration'] = 0
        vc.play(src, after=lambda e: play_next_threadsafe(guild))
        print(f"[PLAY] {song['title']}", flush=True)
    except Exception as e:
        print(f"[PLAY ERREUR] {e}", flush=True)

# ============================================================
# Systeme de memoire IA (mini-NGR)
# ============================================================
async def load_memory(user_id):
    try:
        channel = bot.get_channel(MEMORY_CHANNEL_ID) or await bot.fetch_channel(MEMORY_CHANNEL_ID)
        prefix = f"MEMORY_FOR_{user_id}"
        async for msg in channel.history(limit=100):
            if msg.content.startswith(prefix):
                return json.loads(msg.content[len(prefix):].strip()), msg.id
    except Exception as e: print(f"[MEMOIRE] Erreur lecture : {e}", flush=True)
    return {"user_id": str(user_id), "facts": [], "history": []}, None

async def save_memory(user_id, memory_obj, message_id):
    try:
        channel = bot.get_channel(MEMORY_CHANNEL_ID) or await bot.fetch_channel(MEMORY_CHANNEL_ID)
        content = f"MEMORY_FOR_{user_id}\n{json.dumps(memory_obj)}"
        if message_id:
            msg = await channel.fetch_message(message_id)
            await msg.edit(content=content)
        else: await channel.send(content=content)
    except Exception as e: print(f"[MEMOIRE] Erreur sauvegarde : {e}", flush=True)

# ============================================================
# Appel API Zhipu AI (mini-NGR)
# ============================================================
async def call_ai(user_id, username, question, memory_obj):
    import re
    learn_match = re.search(r'(?:souviens-toi|retiens)\s+que\s+(.+)', question, re.IGNORECASE)
    if learn_match:
        new_fact = learn_match.group(1).strip()
        if new_fact not in memory_obj.get("facts", []): memory_obj.setdefault("facts", []).append(new_fact)

    active_activities = []
    for guild in bot.guilds:
        for m in guild.members:
            if m.bot: continue
            for act in m.activities:
                if act.type == discord.ActivityType.playing: active_activities.append(f"{m.name} joue à {act.name}")
                elif act.type == discord.ActivityType.listening and act.name == "Spotify":
                    title = getattr(act, "title", None)
                    artist = getattr(act, "artist", None)
                    if title and artist: active_activities.append(f"{m.name} écoute Spotify : {title} (par {artist})")

    system_prompt = (
        "Tu es mini-NGR, le bot mascotte du serveur Discord THE NGR. Tu parles comme un pote décontracté et direct.\n"
        "Tu as le contrôle sur le lecteur de musique ! Si l'utilisateur te demande une action sur la musique, "
        "ajoute impérativement l'une de ces balises à la toute fin (invisible pour lui) :\n"
        "- [ACTION:PLAY:nom de la musique] (ajoute à la file d'attente)\n"
        "- [ACTION:PLAY_NOW:nom de la musique] (si on demande TOUT DE SUITE, MAINTENANT ou EN PRIORITÉ, cela coupe le son actuel)\n"
        "- [ACTION:SKIP] (passer la musique)\n"
        "- [ACTION:PAUSE] (mettre en pause)\n"
        "- [ACTION:RESUME] (reprendre la musique)\n"
        "- [ACTION:STOP] (arrêter et déconnecter le bot)\n"
        "- [ACTION:CLEARQUEUE] (vider la liste ou la file d'attente)\n"
        "- [ACTION:QUEUE] (montrer la liste de lecture)\n\n"
        "Tu peux enchaîner plusieurs balises de PLAY si on te demande plusieurs chansons d'un coup (ex: [ACTION:PLAY:Jul] [ACTION:PLAY:PNL]). "
        "Si l'utilisateur te demande une liste ou un genre (ex: 'lance 10 fonk'), liste-les et mets ABSOLUMENT toutes les balises [ACTION:PLAY:...] correspondantes à la toute fin.\n\n"
        "IMPORTANT : Si on te parle normalement ou dit bonjour, réponds simplement SANS balise [ACTION:...]. Réponds de manière très concise (max 2 phrases)."
    )
    system_prompt += f"\nTu parles avec {username} (ID: {user_id})."
    if memory_obj.get("facts"):
        system_prompt += "\nInfos sur lui :\n"
        for fact in memory_obj["facts"]: system_prompt += f"- {fact}\n"
    if active_activities:
        system_prompt += "\nActivité en direct sur le serveur :\n"
        for act in active_activities: system_prompt += f"- {act}\n"

    messages = [{"role": "system", "content": system_prompt}]
    for msg in memory_obj.get("history", [])[-6:]: messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    payload = json.dumps({"model": "glm-4-flash", "messages": messages, "max_tokens": 250}).encode("utf-8")
    req = urllib.request.Request(ZHIPU_API_URL, data=payload, headers={"Content-Type": "application/json", "Authorization": f"Bearer {ZHIPU_API_KEY}"}, method="POST")
    response = await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    data = json.loads(response)
    try: ai_response = data["choices"][0]["message"]["content"]
    except: ai_response = "Oups, j'ai bugué là 😅"

    memory_obj.setdefault("history", []).append({"role": "user", "content": question})
    memory_obj["history"].append({"role": "assistant", "content": ai_response})
    if len(memory_obj["history"]) > 10: memory_obj["history"] = memory_obj["history"][-10:]
    return ai_response, learn_match is not None

# ============================================================
# Rapport d'Activité Horaire
# ============================================================
async def process_hourly_summary():
    global hourly_events
    if not (hourly_events["games"] or hourly_events["songs"] or hourly_events["bot_songs"] or hourly_events["chatters"]): return
    lines = []
    if hourly_events["chatters"]: lines.append(f"Membres actifs : {', '.join(hourly_events['chatters'])}")
    if hourly_events["games"]: lines.append(f"Jeux : {', '.join(hourly_events['games'])}")
    if hourly_events["songs"]: lines.append(f"Spotify : {', '.join(hourly_events['songs'])}")
    if hourly_events["bot_songs"]: lines.append(f"Bot musique : {', '.join(hourly_events['bot_songs'])}")
    summary_text = "\n".join(lines)
    hourly_events = {"games": set(), "songs": set(), "bot_songs": set(), "chatters": set()}
    try:
        system = "Tu es mini-NGR, bot mascotte de THE NGR. Réagis de façon drôle et courte (max 50 mots) à l'activité passée."
        payload = json.dumps({"model": "glm-4-flash", "messages": [{"role": "system", "content": system}, {"role": "user", "content": summary_text}], "max_tokens": 150}).encode("utf-8")
        req = urllib.request.Request(ZHIPU_API_URL, data=payload, headers={"Content-Type": "application/json", "Authorization": f"Bearer {ZHIPU_API_KEY}"}, method="POST")
        res = await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        channel = bot.get_channel(MINI_NGR_CHANNEL_ID)
        if channel: await channel.send(f"👾 {json.loads(res)['choices'][0]['message']['content']}")
    except Exception as e: print(f"[HOURLY ERR] {e}", flush=True)

async def hourly_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        await process_hourly_summary()

# ============================================================
# Evenements de Suivi d'Activite
# ============================================================
@bot.event
async def on_ready():
    print(f"[OK] {bot.user} connecte", flush=True)
    bot.loop.create_task(hourly_loop())
    for g in bot.guilds:
        try: await g.chunk()
        except: pass

@bot.event
async def on_message(message):
    if message.author.bot: return
    hourly_events["chatters"].add(message.author.name)
    if message.channel.id == MINI_NGR_CHANNEL_ID and not message.content.startswith("!"):
        await run_ask(await bot.get_context(message), message.content)
        return
    await bot.process_commands(message)

@bot.event
async def on_presence_update(before, after):
    if after.bot: return
    for act in after.activities:
        if act.type == discord.ActivityType.playing: hourly_events["games"].add(f"{after.name} joue à {act.name}")
        elif act.type == discord.ActivityType.listening and act.name == "Spotify":
            t, a = getattr(act, "title", None), getattr(act, "artist", None)
            if t and a: hourly_events["songs"].add(f"{after.name} écoute {t} - {a}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.MissingPermissions)): return
    await ctx.send(f"❌ Erreur : `{error}`")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if before.channel:
        vc = before.channel.guild.voice_client
        if vc and vc.channel == before.channel and all(m.bot for m in before.channel.members):
            get_queue(before.channel.guild.id).clear()
            now_playing[before.channel.guild.id] = None
            if vc.is_playing() or vc.is_paused(): vc.stop()
            await vc.disconnect()

# ============================================================
# Affichage de la file d'attente (Interface Premium)
# ============================================================
async def show_queue(ctx):
    q = get_queue(ctx.guild.id)
    cur = now_playing.get(ctx.guild.id)
    music_channel = bot.get_channel(MUSIC_CHANNEL_ID) or ctx.channel
    if not cur and not q: return await music_channel.send("📋 La file d'attente est vide.")
    e = discord.Embed(title="🎼 FILE D'ATTENTE ACTUELLE", color=0x5865F2)
    if cur:
        progress = make_progress_bar(get_elapsed_time(cur), cur.get('duration', 0))
        e.add_field(name="🎵 En cours de lecture", value=f"**[{cur['title']}]({cur['webpage_url']})**\n{progress}\n*Par : {cur['uploader']}*", inline=False)
        if cur.get('thumbnail'): e.set_thumbnail(url=cur['thumbnail'])
    if q:
        lines = [f"`{i}.` ⏳ **[{s['title']}]({s['webpage_url']})** `[{fmt_dur(s['duration'])}]`" for i, s in enumerate(list(q)[:10], 1)]
        if len(q) > 10: lines.append(f"\n*... et {len(q) - 10} autre(s) musique(s)*")
        e.add_field(name="⏳ À suivre", value="\n".join(lines), inline=False)
        e.set_footer(text=f"Total : {len(q)} musique(s) en attente • Durée totale : {fmt_dur(sum(int(s.get('duration', 0)) for s in q))}")
    else: e.set_footer(text="Aucune musique suivante • Fin de lecture après ce morceau.")
    await music_channel.send(embed=e)

# ============================================================
# Mode d'exécution de la lecture
# ============================================================
async def play_song_immediately(ctx, music_channel, song):
    now_playing[ctx.guild.id] = song
    try:
        src = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTS), volume=get_vol(ctx.guild.id))
        song['start_time'] = datetime.datetime.now()
        song['paused_duration'] = 0
        ctx.voice_client.play(src, after=lambda e: play_next_threadsafe(ctx.guild))
        desc = f"**[{song['title']}]({song['webpage_url']})**\n\n**🎛️ Commandes :**\n⏸️ `!pause`  |  ▶️ `!resume`  |  ⏭️ `!skip`  |  🛑 `!stop`"
        e = discord.Embed(title="🎵 En cours de lecture", description=desc, color=0x5865F2)
        if song['thumbnail']: e.set_thumbnail(url=song['thumbnail'])
        e.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
        e.add_field(name="🎤 Chaîne", value=song['uploader'], inline=True)
        await music_channel.send(embed=e)
    except Exception as err: await music_channel.send(f"❌ Erreur lecture : `{err}`")

async def run_play(ctx, query, play_now=False):
    if not ctx.author.voice: return await ctx.send("❌ Rejoins un salon vocal d'abord !")
    try:
        if ctx.voice_client is None: await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel: await ctx.voice_client.move_to(ctx.author.voice.channel)
    except Exception as e: return await ctx.send(f"❌ Connexion vocale impossible : `{e}`")

    music_channel = bot.get_channel(MUSIC_CHANNEL_ID) or ctx.channel
    try:
        song = await extract_audio(query)
        song['original_query'] = query
    except Exception as e: return await music_channel.send(f"❌ Impossible de charger : `{e}`")

    q = get_queue(ctx.guild.id)
    hourly_events["bot_songs"].add(song['title'])

    if play_now:
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            q.appendleft(song)
            ctx.voice_client.stop()
            e = discord.Embed(title="⚡ Lecture Prioritaire Immédiate", description=f"**[{song['title']}]({song['webpage_url']})** lance !", color=0xE91E63)
            if song['thumbnail']: e.set_thumbnail(url=song['thumbnail'])
            await music_channel.send(embed=e)
        else: await play_song_immediately(ctx, music_channel, song)
    else:
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            q.append(song)
            desc = f"**[{song['title']}]({song['webpage_url']})**\n\nℹ️ *Tapez `!queue` pour voir la file d'attente.*"
            e = discord.Embed(title="📋 Ajouté à la file d'attente", description=desc, color=0x57F287)
            if song['thumbnail']: e.set_thumbnail(url=song['thumbnail'])
            e.add_field(name="⏱️ Durée", value=fmt_dur(song['duration']), inline=True)
            e.add_field(name="📍 Position", value=f"#{len(q)}", inline=True)
            await music_channel.send(embed=e)
        else: await play_song_immediately(ctx, music_channel, song)

# ============================================================
# Fonction centrale d'appel de l'IA (mini-NGR)
# ============================================================
async def run_ask(ctx, question):
    print(f"[ASK] {ctx.author.name}: '{question}'", flush=True)
    async with ctx.typing():
        try:
            mem, mem_id = await load_memory(ctx.author.id)
            ai_resp, is_learn = await call_ai(ctx.author.id, ctx.author.name, question, mem)
            await save_memory(ctx.author.id, mem, mem_id)

            actions = [(m.group(1).upper(), m.group(2) if m.group(2) else "") for m in re.finditer(r"\[ACTION:(\w+)(?::(.*?))?\]", ai_resp)]
            ai_resp = re.sub(r"\[ACTION:.*?\]", "", ai_resp).strip()

            if is_learn: await ctx.reply(f"📝 *C'est noté frérot, je m'en souviendrai !*\n\n{ai_resp}")
            else: await ctx.reply(f"👾 {ai_resp}")

            for a_type, a_arg in actions:
                await asyncio.sleep(0.5)
                now_intent = any(x in question.lower() for x in ["tout de suite", "maintenant", "priorite", "direct", "prioritaire"])
                
                if a_type == "PLAY" and a_arg:
                    if is_music_request(question): await run_play(ctx, a_arg, play_now=now_intent)
                elif a_type == "PLAY_NOW" and a_arg:
                    if is_music_request(question): await run_play(ctx, a_arg, play_now=True)
                elif a_type == "SKIP":
                    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                        ctx.voice_client.stop()
                        await ctx.send("⏭️ Musique passée par mini-NGR !")
                elif a_type == "PAUSE":
                    if ctx.voice_client and ctx.voice_client.is_playing():
                        ctx.voice_client.pause()
                        now_playing[ctx.guild.id]['pause_start'] = datetime.datetime.now()
                        await ctx.send("⏸️ Musique mise en pause par mini-NGR.")
                elif a_type == "RESUME":
                    if ctx.voice_client and ctx.voice_client.is_paused():
                        ctx.voice_client.resume()
                        song = now_playing[ctx.guild.id]
                        if 'pause_start' in song:
                            song['paused_duration'] = song.get('paused_duration', 0) + (datetime.datetime.now() - song['pause_start']).total_seconds()
                            del song['pause_start']
                        await ctx.send("▶️ Lecture reprise par mini-NGR.")
                elif a_type == "STOP":
                    if ctx.voice_client:
                        get_queue(ctx.guild.id).clear()
                        now_playing[ctx.guild.id] = None
                        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused(): ctx.voice_client.stop()
                        await ctx.voice_client.disconnect()
                        await ctx.send("🛑 Lecture arrêtée par mini-NGR.")
                elif a_type == "CLEARQUEUE":
                    get_queue(ctx.guild.id).clear()
                    await (bot.get_channel(MUSIC_CHANNEL_ID) or ctx.channel).send("🧹 La file d'attente a été vidée !")
                elif a_type == "QUEUE": await show_queue(ctx)
        except Exception as e:
            print(f"[ASK ERREUR] {e}", flush=True)
            await ctx.send(f"❌ mini-NGR a bugué : `{e}`")

# ============================================================
# Commandes Discord standard
# ============================================================
@bot.command(name="ask")
async def ask(ctx, *, question: str): await run_ask(ctx, question)

@bot.command(name="trigger_hourly")
@commands.has_permissions(administrator=True)
async def trigger_hourly(ctx):
    await ctx.send("⚡ Lancement manuel...")
    if not (hourly_events["games"] or hourly_events["songs"] or hourly_events["chatters"]):
        hourly_events["chatters"].add(ctx.author.name)
        hourly_events["games"].add("Dev")
    await process_hourly_summary()

@bot.command(name="clear", aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear_messages(ctx, limit: int):
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=limit)
    alert = await ctx.send(f"🧹 **{len(deleted)} messages** supprimés !")
    await asyncio.sleep(4)
    await alert.delete()

@bot.command(name="vmove")
@commands.has_permissions(move_members=True)
async def voice_move(ctx, member: discord.Member, *, channel_name: str):
    target = discord.utils.get(ctx.guild.voice_channels, name=channel_name) or next((c for c in ctx.guild.voice_channels if channel_name.lower() in c.name.lower()), None)
    if not target or not member.voice: return await ctx.send("❌ Action impossible (salon introuvable ou membre déconnecté).")
    await member.move_to(target)
    await ctx.send(f"🚀 {member.mention} déplacé vers **{target.name}** !")

@bot.command(name="vmute")
@commands.has_permissions(mute_members=True)
async def voice_mute(ctx, member: discord.Member):
    if member.voice: await member.edit(mute=True); await ctx.send(f"🔇 {member.mention} réduit au silence.")

@bot.command(name="vunmute")
@commands.has_permissions(mute_members=True)
async def voice_unmute(ctx, member: discord.Member):
    if member.voice: await member.edit(mute=False); await ctx.send(f"🔊 {member.mention} peut parler.")

@bot.command(name="timer", aliases=["alarm", "remind"])
async def start_timer(ctx, duration: str, *, reminder: str = "Le temps est écoulé !"):
    m = re.match(r"^(\d+)([smh])$", duration.lower())
    if not m: return await ctx.send("❌ Format invalide (ex: 10s, 5m, 1h).")
    val, unit = int(m.group(1)), m.group(2)
    sec = val if unit == "s" else val * 60 if unit == "m" else val * 3600
    await ctx.send(f"⏳ Minuteur lancé pour **{duration}**.")
    await asyncio.sleep(sec)
    await ctx.send(f"⏰ {ctx.author.mention} **Alarme !** {reminder}")

@bot.command(name="poll")
async def create_poll(ctx, *, args: str):
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 3: return await ctx.send("❌ Syntaxe : `!poll Question | Choix 1 | Choix 2...`")
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    desc = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(parts[1:10]))
    poll = await ctx.send(embed=discord.Embed(title=f"📊 {parts[0]}", description=desc, color=0x5865F2))
    for i in range(len(parts[1:10])): await poll.add_reaction(emojis[i])

@bot.command(name="userinfo")
async def user_info(ctx, member: discord.Member = None):
    m = member or ctx.author
    act = m.activity.name if m.activity else "Aucune"
    e = discord.Embed(title=f"👤 {m.name}", color=m.color)
    e.set_thumbnail(url=m.display_avatar.url)
    e.add_field(name="Activité", value=act, inline=True)
    e.add_field(name="Création", value=m.created_at.strftime("%d/%m/%Y"), inline=True)
    e.add_field(name="Rejoint", value=m.joined_at.strftime("%d/%m/%Y"), inline=True)
    await ctx.send(embed=e)

@bot.command(name="serverinfo")
async def server_info(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"🏰 {g.name}", color=0x5865F2)
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Membres", value=str(g.member_count), inline=True)
    e.add_field(name="Création", value=g.created_at.strftime("%d/%m/%Y"), inline=True)
    await ctx.send(embed=e)

@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
    async with ctx.typing(): await run_play(ctx, query)

@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        if ctx.guild.id in now_playing: now_playing[ctx.guild.id]['pause_start'] = datetime.datetime.now()
        await ctx.send("⏸️ En pause. Tapez `!resume` pour reprendre.")

@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        if ctx.guild.id in now_playing:
            s = now_playing[ctx.guild.id]
            if 'pause_start' in s:
                s['paused_duration'] = s.get('paused_duration', 0) + (datetime.datetime.now() - s['pause_start']).total_seconds()
                del s['pause_start']
        await ctx.send("▶️ Lecture reprise.")

@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Musique passée !")

@bot.command(name="stop")
async def stop(ctx):
    if not ctx.voice_client: return await ctx.send("❌ Bot déconnecté.")
    get_queue(ctx.guild.id).clear()
    now_playing[ctx.guild.id] = None
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused(): ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Lecture arrêtée et déconnexion.")

@bot.command(name="queue", aliases=["q"])
async def queue_cmd(ctx): await show_queue(ctx)

@bot.command(name="clearqueue", aliases=["cq", "clean", "empty"])
async def clear_queue_cmd(ctx):
    q = get_queue(ctx.guild.id)
    if not q: return await ctx.send("❌ La file d'attente est déjà vide.")
    q.clear()
    await ctx.send("🧹 File d'attente vidée !")

@bot.command(name="volume", aliases=["vol"])
async def volume(ctx, level: int):
    if not ctx.voice_client: return await ctx.send("❌ Bot déconnecté.")
    if not (0 <= level <= 100): return await ctx.send("❌ Entre 0 et 100.")
    v = level / 100
    volumes[ctx.guild.id] = v
    if ctx.voice_client.source and hasattr(ctx.voice_client.source, 'volume'): ctx.voice_client.source.volume = v
    await ctx.send(f"🔊 Volume : **{level}%**")

bot.run(TOKEN)
