---
name: reel-editor
description: Edit a raw talking-head video into a vertical short (TikTok, Reels, Shorts). Cuts dead air, burns 2-3 word captions inside the platform safe zone, boosts the voice and mixes in quiet music. Use when the user drops a raw .mov/.mp4 and asks to edit it, cut it, caption it, or "make it look like a reel".
compatibility: Needs ffmpeg (with libass) on PATH. Word timestamps come from Whisper or any tool that outputs word-level JSON.
---

# Reel editor

You turn one raw clip into a finished vertical reel. Do the steps in order and
don't skip the checks.

## 1. Look before you cut
- `ffprobe -v error -show_entries format=duration:stream=width,height -of json <video>`
- If it isn't 9:16, ask before cropping.

## 2. Get word timestamps
Run Whisper with word timestamps and save a JSON list of
`{"word", "start", "end"}` objects (seconds) to `words.json`. Example with
openai-whisper: `whisper <video> --word_timestamps True --output_format json`,
then flatten `segments[].words[]`.

## 3. Find dead air
`ffmpeg -i <video> -af silencedetect=noise=-30dB:d=0.4 -f null - 2> silence.log`

## 4. Plan the edit
`python3 scripts/plan_edit.py --video <video> --silence-log silence.log --words words.json --platform tiktok --out-dir edit/ [--music music.mp3]`

This writes `edit/captions.ass`, `edit/plan.json` and `edit/render.sh`, and
prints how much time it cut. It refuses to place captions outside the safe zone.

## 5. Render and check
- `sh edit/render.sh`
- Pull 6 frames from the result (`ffmpeg -i out.mp4 -vf fps=1/3 f_%02d.jpg`)
  and look at them. Captions readable? Nothing under the like/comment buttons?
- Tell the user what you cut and show the frames before calling it done.

## House style (change these to match yours)
1. Captions: 2-3 words, white, bold outline, no box, no animation.
2. Keep everything out of the platform's button zones.
3. Voice at 200%, music at 25% for the first 3 seconds, then 10%.
