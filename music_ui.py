"""Antigravity V3 — Module d'interface musique premium (embeds Discord)"""
import discord, datetime

# Palette de couleurs premium
VIOLET = 0x7C3AED
BLUE   = 0x3B82F6
GREEN  = 0x10B981
RED    = 0xEF4444
PINK   = 0xEC4899
GOLD   = 0xF59E0B

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

def playing_embed(song):
    em = discord.Embed(title="🎵 Lecture en cours",
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**", color=PINK)
    if song.get('thumbnail'): em.set_image(url=song['thumbnail'])
    em.add_field(name="🎤 Artiste", value=song.get('uploader', 'Inconnu'), inline=True)
    em.add_field(name="⏱️ Durée", value=fmt_dur(song.get('duration', 0)), inline=True)
    if song.get('requester'):
        em.add_field(name="👤 Par", value=song['requester'], inline=True)
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
