# youtube-srt-obsidian
A Python script to download subtitles from YouTube or Bilibili and reformat them as clickable, readable Markdown for Obsidian.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Usage

```bash
python3 srt_generator.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" ./output
python3 srt_generator.py "https://www.bilibili.com/video/BV1xx411c7mD" ./output
```

Useful options:

- `--platform youtube|bilibili` forces a platform instead of auto-detecting from the URL.
- `--language en,zh-CN` prefers one or more subtitle languages.
- `--group-size 10` controls how many subtitle fragments are merged into one Markdown section.
- `--proxy-https http://127.0.0.1:7890` sets an HTTPS proxy for network requests.
- `--preserve-formatting` keeps source formatting when the adapter supports it.
- `--skip-punctuation` disables punctuation restoration if you want raw text output.

## Notes

- YouTube subtitle download depends on `youtube-transcript-api`.
- Bilibili only works when the video owner has published subtitle tracks.
- If `deepmultilingualpunctuation` is unavailable, the script still works and simply skips punctuation restoration.
