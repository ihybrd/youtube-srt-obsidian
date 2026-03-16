# youtube-srt-obsidian

A small Python script that downloads YouTube subtitles with `requests` only and renders them as clickable Markdown for Obsidian.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Usage

```bash
python3 srt_generator.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" ./output
```

Useful options:

- `--language en,zh-CN` prefers one or more subtitle languages.
- `--group-size 10` controls how many subtitle fragments are merged into one Markdown section.
- `--proxy-https http://127.0.0.1:7890` sets an HTTPS proxy for network requests.

## Notes

- The script only supports YouTube now.
- Third-party runtime dependency is only `requests`.
- It reads subtitle track metadata from the YouTube watch page and then downloads the selected caption track directly.
