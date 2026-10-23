#!/usr/bin/env python3
"""Plan a reel edit: cut silences, group words into captions, emit an ffmpeg render script.

Standard library only. ffmpeg does the actual video work.

  python3 plan_edit.py --demo
  python3 plan_edit.py --video raw.mov --silence-log silence.log --words words.json \
      --platform tiktok --out-dir edit/ [--music music.mp3]
"""
import argparse
import json
import os
import re
import shlex

W, H = 1080, 1920

# Margins in px on a 1080x1920 canvas (top, bottom, left, right).
# From orsonlord.com's 2025 overlay guide; other guides use smaller numbers,
# so these are on the conservative side.
SAFE_ZONES = {
    "tiktok": (160, 480, 120, 120),
    "reels": (250, 320, 120, 120),
    "shorts": (380, 380, 60, 120),
}

DEMO_DURATION = 12.0
DEMO_SILENCE_LOG = """\
[silencedetect @ 0x1] silence_start: 0
[silencedetect @ 0x1] silence_end: 0.9 | silence_duration: 0.9
[silencedetect @ 0x1] silence_start: 3.1
[silencedetect @ 0x1] silence_end: 4.6 | silence_duration: 1.5
[silencedetect @ 0x1] silence_start: 7.2
[silencedetect @ 0x1] silence_end: 7.9 | silence_duration: 0.7
[silencedetect @ 0x1] silence_start: 10.8
"""
DEMO_WORDS = [
    ("So", 0.95), ("I", 1.15), ("edited", 1.3), ("this", 1.7), ("whole", 1.95),
    ("video", 2.25), ("with", 2.6), ("Claude.", 2.8),
    ("Step", 4.7), ("one,", 5.0), ("get", 5.4), ("the", 5.6), ("skill.", 5.75),
    ("Step", 6.3), ("two,", 6.6), ("open", 8.0), ("the", 8.3), ("code", 8.45),
    ("tab", 8.75), ("and", 9.1), ("drop", 9.3), ("your", 9.6), ("video", 9.8),
    ("in.", 10.2),
]


def parse_silences(log, duration):
    """Turn ffmpeg silencedetect stderr into [(start, end)] pairs."""
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    if len(ends) < len(starts):  # trailing silence runs to the end of the file
        ends.append(duration)
    return list(zip(starts, ends))


def keep_segments(duration, silences, pad=0.08, min_len=0.15):
    """Everything that isn't silence, with a little breathing room on each side."""
    keep, cursor = [], 0.0
    for s, e in silences:
        cut_from = s + pad if s > 0 else 0.0
        cut_to = e - pad if e < duration else duration
        if cut_to <= cut_from:
            continue
        if cut_from - cursor >= min_len:
            keep.append((round(cursor, 3), round(cut_from, 3)))
        cursor = cut_to
    if duration - cursor >= min_len:
        keep.append((round(cursor, 3), round(duration, 3)))
    return keep


def remap_word(start, end, segments):
    """Map a word onto the cut timeline (None if it starts inside a cut).

    Whisper end times run a little long, so a word whose end spills past its
    segment gets clamped to the segment end instead of being dropped.
    """
    offset = 0.0
    for s, e in segments:
        if s <= start <= e:
            return offset + (start - s), offset + (min(end, e) - s)
        offset += e - s
    return None


def group_captions(words, max_words=3, max_gap=0.35):
    """Chunk words into 2-3 word cards. Break on punctuation or a pause."""
    cards, cur = [], []
    for i, w in enumerate(words):
        if cur and (len(cur) == max_words or w["start"] - cur[-1]["end"] > max_gap):
            cards.append(cur)
            cur = []
        cur.append(w)
        if w["word"].rstrip()[-1:] in ".,!?":
            cards.append(cur)
            cur = []
    if cur:
        cards.append(cur)
    return [(c[0]["start"], c[-1]["end"], " ".join(x["word"] for x in c)) for c in cards]


def caption_y(platform, font_size, y_frac):
    top, bottom, _, _ = SAFE_ZONES[platform]
    y = int(H * y_frac)
    if y - font_size < top or y + font_size > H - bottom:
        raise SystemExit(f"caption at y={y} leaves the {platform} safe zone "
                         f"({top}..{H - bottom}); pick another --caption-y")
    return y


def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(cards, path, platform, font_size=78, y_frac=0.58):
    _, _, left, right = SAFE_ZONES[platform]
    y = caption_y(platform, font_size, y_frac)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        f"Style: Cap,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,1,1,4,0,5,"
        f"{left},{right},0", "",
        "[Events]", "Format: Layer, Start, End, Style, Text",
    ]
    for s, e, text in cards:
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,{{\\pos({W // 2},{y})}}{text}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return y


def render_cmd(video, segments, ass_path, out, music=None, voice_gain=2.0,
               music_hi=0.25, music_lo=0.10, music_hi_secs=3.0):
    sel = "+".join(f"between(t,{s},{e})" for s, e in segments)
    vf = (f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,"
          f"subtitles={ass_path}[v]")
    af = f"[0:a]aselect='{sel}',asetpts=N/SR/TB,volume={voice_gain}[vox]"
    cmd = ["ffmpeg", "-y", "-i", video]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        af += (f";[1:a]volume='if(lt(t,{music_hi_secs}),{music_hi},{music_lo})':eval=frame[mus]"
               ";[vox][mus]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        af += ";[vox]anull[a]"
    cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "20", "-c:a", "aac", out]
    return " ".join(shlex.quote(c) for c in cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="run on built-in sample data")
    ap.add_argument("--video")
    ap.add_argument("--duration", type=float, help="clip length (s); read from the log if omitted")
    ap.add_argument("--silence-log")
    ap.add_argument("--words", help="JSON list of {word,start,end}")
    ap.add_argument("--platform", choices=SAFE_ZONES, default="tiktok")
    ap.add_argument("--music")
    ap.add_argument("--caption-y", type=float, default=0.58, help="caption height as a fraction of 1920")
    ap.add_argument("--out-dir", default="edit")
    a = ap.parse_args()

    if a.demo:
        video, duration, log = "raw.mov", DEMO_DURATION, DEMO_SILENCE_LOG
        words = [{"word": w, "start": s, "end": round(s + 0.18 + 0.03 * len(w), 2)}
                 for w, s in DEMO_WORDS]
    else:
        video = a.video
        log = open(a.silence_log).read()
        words = json.load(open(a.words))
        duration = a.duration
        if duration is None:
            m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
            if not m:
                raise SystemExit("pass --duration (no 'Duration:' line in the log)")
            duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])

    os.makedirs(a.out_dir, exist_ok=True)
    silences = parse_silences(log, duration)
    segments = keep_segments(duration, silences)
    kept = sum(e - s for s, e in segments)

    # Move every word onto the new timeline; drop any that fell inside a cut.
    moved = []
    for w in words:
        m = remap_word(w["start"], w["end"], segments)
        if m:
            moved.append({"word": w["word"], "start": m[0], "end": m[1]})
    cards = group_captions(moved)

    ass_path = os.path.join(a.out_dir, "captions.ass")
    y = write_ass(cards, ass_path, a.platform, y_frac=a.caption_y)
    cmd = render_cmd(video, segments, ass_path, os.path.join(a.out_dir, "out.mp4"), a.music)
    with open(os.path.join(a.out_dir, "render.sh"), "w") as f:
        f.write("#!/bin/sh\n" + cmd + "\n")
    with open(os.path.join(a.out_dir, "plan.json"), "w") as f:
        json.dump({"segments": segments, "captions": cards, "platform": a.platform}, f, indent=2)

    print(f"raw length     {duration:6.2f}s")
    print(f"after cuts     {kept:6.2f}s  ({100 * (1 - kept / duration):.0f}% dead air removed)")
    print(f"keep segments  {len(segments)}: " + ", ".join(f"{s}-{e}" for s, e in segments))
    print(f"words kept     {len(moved)}/{len(words)}")
    print(f"caption cards  {len(cards)} at y={y}px ({a.platform} safe zone "
          f"{SAFE_ZONES[a.platform][0]}..{H - SAFE_ZONES[a.platform][1]})")
    for s, e, t in cards:
        print(f"  {s:5.2f}-{e:5.2f}  {t}")
    print(f"wrote {ass_path}, plan.json, render.sh")


if __name__ == "__main__":
    main()
