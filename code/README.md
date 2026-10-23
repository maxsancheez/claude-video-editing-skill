# code/

A minimal, working version of a "Claude edits my reel" skill.

```
reel-editor/
  SKILL.md              # the instructions Claude reads when the skill triggers
  scripts/plan_edit.py  # cuts silence, builds captions, writes the ffmpeg render script
demo_render.py          # end-to-end test on a fake clip
```

Python 3 standard library only. Rendering needs `ffmpeg` built with libass
(`brew install ffmpeg` on a Mac).

## Run it

Dry run on built-in sample data (no ffmpeg needed):

```bash
python3 reel-editor/scripts/plan_edit.py --demo --out-dir edit
```

Full pipeline on a generated 12 s test clip (needs ffmpeg):

```bash
python3 demo_render.py demo_work
```

On your own clip:

```bash
ffmpeg -i raw.mov -af silencedetect=noise=-30dB:d=0.4 -f null - 2> silence.log
python3 reel-editor/scripts/plan_edit.py --video raw.mov --silence-log silence.log --words words.json --platform reels --out-dir edit --music music.mp3
sh edit/render.sh
```

`words.json` is a list of `{"word", "start", "end"}` objects. Whisper's
`--word_timestamps True` output has them under `segments[].words[]`.

## Use it as a Claude Code skill

Copy `reel-editor/` to `~/.claude/skills/reel-editor/`. Then, in Claude Code,
drop a raw clip in and ask Claude to edit it for TikTok.
