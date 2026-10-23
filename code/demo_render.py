#!/usr/bin/env python3
"""End-to-end check: build a fake 12 s vertical clip with gaps, run the skill's pipeline on it.

Needs ffmpeg with libass. Usage: python3 demo_render.py [work_dir]
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(HERE, "reel-editor", "scripts", "plan_edit.py")
# Same "speech" windows as the --demo data: tone plays here, silence elsewhere.
SPEECH = [(0.9, 3.1), (4.6, 7.2), (7.9, 10.8)]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def duration(path):
    # Parse ffmpeg's banner so we don't also need ffprobe installed.
    err = subprocess.run(["ffmpeg", "-i", path], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    work = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo_work")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "raw.mp4")
    music = os.path.join(work, "music.wav")

    gate = "+".join(f"between(t,{s},{e})" for s, e in SPEECH)
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=12",
         "-f", "lavfi", "-i", f"aevalsrc='({gate})*0.5*sin(2*PI*220*t)':s=48000:d=12",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", raw])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=4", music])

    det = subprocess.run(["ffmpeg", "-i", raw, "-af", "silencedetect=noise=-30dB:d=0.4",
                          "-f", "null", "-"], capture_output=True, text=True)
    log_path = os.path.join(work, "silence.log")
    with open(log_path, "w") as f:
        f.write(det.stderr)

    words = [{"word": w, "start": s, "end": s + 0.3} for w, s in
             [("Fake", 1.0), ("words", 1.5), ("here.", 2.2), ("More", 5.0),
              ("fake", 5.6), ("words.", 6.4), ("Last", 8.2), ("line", 9.0), ("now.", 10.0)]]
    words_path = os.path.join(work, "words.json")
    with open(words_path, "w") as f:
        json.dump(words, f)

    edit = os.path.join(work, "edit")
    plan = run([sys.executable, PLAN, "--video", raw, "--silence-log", log_path,
                "--words", words_path, "--music", music, "--out-dir", edit])
    print(plan.stdout.split("caption cards")[0].rstrip())
    run(["sh", os.path.join(edit, "render.sh")])

    out = os.path.join(edit, "out.mp4")
    print(f"rendered       {duration(raw):.2f}s -> {duration(out):.2f}s  ({out})")


if __name__ == "__main__":
    main()
