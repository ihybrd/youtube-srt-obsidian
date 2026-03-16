import argparse
import html
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import requests


DEFAULT_TIMEOUT = 15
INVALID_FILENAME_CHARS = r'<>:"/\|?*'
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
PLAYER_API_URL = "https://www.youtube.com/youtubei/v1/player?key={api_key}"
ANDROID_CONTEXT = {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}}


class SubtitleDownloadError(RuntimeError):
    pass


@dataclass
class SubtitleEntry:
    start: float
    duration: float
    text: str


@dataclass
class VideoMetadata:
    title: str
    author: str
    thumbnail_url: str
    source_url: str
    source_id: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download YouTube subtitles and render them as Markdown."
    )
    parser.add_argument("youtube_link", help="YouTube video URL or 11-character video id")
    parser.add_argument("output_dir", help="Output directory for the generated Markdown file")
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help="Preferred subtitle language code. Repeat or use comma-separated values.",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        default=10,
        help="How many caption fragments to merge into one Markdown section. Default: 10.",
    )
    parser.add_argument("--proxy-https", help="HTTPS proxy URL")
    return parser


def normalize_languages(raw_languages: Sequence[str]) -> List[str]:
    result: List[str] = []
    for raw in raw_languages:
        for item in raw.split(","):
            language = item.strip()
            if language and language not in result:
                result.append(language)
    return result


def build_session(proxy_https: Optional[str]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    if proxy_https:
        session.proxies.update({"http": proxy_https, "https": proxy_https})
    return session


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(text: str) -> str:
    text = html.unescape(text.replace("\n", " "))
    text = collapse_whitespace(text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


def sanitize_filename(name: str) -> str:
    sanitized = "".join("_" if char in INVALID_FILENAME_CHARS else char for char in name)
    sanitized = collapse_whitespace(sanitized).rstrip(". ")
    return sanitized or "subtitle"


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    total_seconds, milliseconds = divmod(total_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def format_timestamp_label(seconds: float) -> str:
    return format_timestamp(seconds).replace(",", ".")


def build_timestamp_url(source_url: str, seconds: float) -> str:
    start_seconds = max(0, int(seconds))
    parsed = urllib.parse.urlparse(source_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["t"] = [str(start_seconds)]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def build_frontmatter(metadata: VideoMetadata, subtitle_language: Optional[str]) -> str:
    fields = {
        "title": metadata.title,
        "platform": "youtube",
        "source_url": metadata.source_url,
        "source_id": metadata.source_id,
        "author": metadata.author,
    }
    if metadata.thumbnail_url:
        fields["thumbnail_url"] = metadata.thumbnail_url
    if subtitle_language:
        fields["subtitle_language"] = subtitle_language

    lines = ["---"]
    for key, value in fields.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


def chunk_entries(entries: Sequence[SubtitleEntry], group_size: int) -> Iterable[List[SubtitleEntry]]:
    safe_group_size = max(1, group_size)
    current_chunk: List[SubtitleEntry] = []
    for entry in entries:
        if not entry.text:
            continue
        current_chunk.append(entry)
        if len(current_chunk) >= safe_group_size:
            yield current_chunk
            current_chunk = []
    if current_chunk:
        yield current_chunk


def render_markdown(
    metadata: VideoMetadata,
    entries: Sequence[SubtitleEntry],
    subtitle_language: Optional[str],
    group_size: int,
) -> str:
    frontmatter = build_frontmatter(metadata, subtitle_language)
    lines = [frontmatter, "", f"# {metadata.title}", ""]

    if metadata.thumbnail_url:
        lines.append(f"![]({metadata.thumbnail_url})")
        lines.append("")

    lines.append(f"Source: [{metadata.source_url}]({metadata.source_url})")
    lines.append(f"Author: {metadata.author}")
    if subtitle_language:
        lines.append(f"Subtitle language: {subtitle_language}")
    lines.append("")

    for chunk in chunk_entries(entries, group_size):
        start_seconds = chunk[0].start
        timestamp_label = format_timestamp_label(start_seconds)
        timestamp_url = build_timestamp_url(metadata.source_url, start_seconds)
        merged_text = normalize_text(" ".join(entry.text for entry in chunk))
        if not merged_text:
            continue

        lines.append(f"## [{timestamp_label}]({timestamp_url})")
        lines.append(merged_text)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def extract_youtube_video_id(youtube_link: str) -> str:
    direct_id = youtube_link.strip()
    if re.fullmatch(r"[\w-]{11}", direct_id):
        return direct_id

    parsed = urllib.parse.urlparse(youtube_link)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    query = urllib.parse.parse_qs(parsed.query)

    if host == "youtu.be":
        candidate = path.split("/")[0]
        if re.fullmatch(r"[\w-]{11}", candidate):
            return candidate

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if "v" in query and re.fullmatch(r"[\w-]{11}", query["v"][0]):
            return query["v"][0]
        path_parts = [part for part in path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live", "v"}:
            candidate = path_parts[1]
            if re.fullmatch(r"[\w-]{11}", candidate):
                return candidate

    raise SubtitleDownloadError(f"Could not extract YouTube video id from: {youtube_link}")


def extract_innertube_api_key(watch_html: str) -> str:
    match = re.search(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"', watch_html)
    if match is None:
        raise SubtitleDownloadError("Could not extract INNERTUBE_API_KEY from the YouTube watch page.")
    return match.group(1)


def create_consent_cookie(session: requests.Session, watch_html: str) -> None:
    match = re.search(r'name="v" value="(.*?)"', watch_html)
    if match is None:
        raise SubtitleDownloadError("YouTube returned a consent page and the consent token could not be extracted.")
    session.cookies.set("CONSENT", "YES+" + match.group(1), domain=".youtube.com")


def fetch_watch_html(session: requests.Session, video_id: str) -> str:
    response = session.get(WATCH_URL.format(video_id=video_id), timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    watch_html = html.unescape(response.text)

    if 'action="https://consent.youtube.com/s"' in watch_html:
        create_consent_cookie(session, watch_html)
        response = session.get(WATCH_URL.format(video_id=video_id), timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        watch_html = html.unescape(response.text)
        if 'action="https://consent.youtube.com/s"' in watch_html:
            raise SubtitleDownloadError("YouTube consent page could not be bypassed.")

    return watch_html


def fetch_player_response(session: requests.Session, video_id: str) -> dict:
    watch_html = fetch_watch_html(session, video_id)
    api_key = extract_innertube_api_key(watch_html)
    response = session.post(
        PLAYER_API_URL.format(api_key=api_key),
        json={"context": ANDROID_CONTEXT, "videoId": video_id},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def flatten_runs(runs: Sequence[dict]) -> str:
    return "".join(str(run.get("text", "")) for run in runs)


def get_text_value(value) -> str:
    if isinstance(value, dict):
        if "simpleText" in value:
            return str(value["simpleText"])
        if "runs" in value:
            return flatten_runs(value["runs"])
    return str(value or "")


def get_thumbnail_url(video_details: dict) -> str:
    thumbnails = (((video_details.get("thumbnail") or {}).get("thumbnails")) or [])
    if not thumbnails:
        return ""
    return str(thumbnails[-1].get("url", ""))


def get_youtube_metadata(player_response: dict, video_id: str) -> VideoMetadata:
    video_details = player_response.get("videoDetails") or {}
    microformat = ((player_response.get("microformat") or {}).get("playerMicroformatRenderer")) or {}
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    title = video_details.get("title") or microformat.get("title") or video_id
    author = video_details.get("author") or microformat.get("ownerChannelName") or "Unknown"
    thumbnail_url = get_thumbnail_url(video_details)

    if not thumbnail_url:
        thumbnails = microformat.get("thumbnail", {}).get("thumbnails", [])
        if thumbnails:
            thumbnail_url = str(thumbnails[-1].get("url", ""))

    return VideoMetadata(
        title=str(title),
        author=str(author),
        thumbnail_url=thumbnail_url,
        source_url=source_url,
        source_id=video_id,
    )


def get_caption_tracks(player_response: dict) -> List[dict]:
    captions = player_response.get("captions") or {}
    renderer = captions.get("playerCaptionsTracklistRenderer") or {}
    tracks = renderer.get("captionTracks") or []
    if not tracks:
        raise SubtitleDownloadError("No subtitles are available for this YouTube video.")
    return list(tracks)


def choose_caption_track(tracks: Sequence[dict], languages: Sequence[str]) -> dict:
    if not languages:
        ordered_tracks = sorted(tracks, key=lambda track: track.get("kind") == "asr")
        return ordered_tracks[0]

    normalized_languages = {language.lower() for language in languages}
    for language in normalized_languages:
        for track in tracks:
            language_code = str(track.get("languageCode", "")).lower()
            name = get_text_value(track.get("name")).lower()
            vss_id = str(track.get("vssId", "")).lower()
            if (
                language == language_code
                or language == vss_id.lstrip(".")
                or language in name
                or language_code.startswith(language + "-")
            ):
                return track

    available = ", ".join(
        f"{track.get('languageCode', 'unknown')} ({get_text_value(track.get('name')) or 'unnamed'})"
        for track in tracks
    )
    raise SubtitleDownloadError(
        f"Requested subtitle language was not found. Available tracks: {available}"
    )


def build_caption_download_url(base_url: str) -> str:
    return base_url.replace("&fmt=srv3", "")


def parse_caption_xml(xml_text: str) -> List[SubtitleEntry]:
    root = ET.fromstring(xml_text)
    entries: List[SubtitleEntry] = []
    for node in root.findall(".//text") + root.findall(".//p"):
        text = normalize_text("".join(node.itertext()))
        if not text:
            continue
        if "start" in node.attrib:
            start = float(node.attrib.get("start", "0") or 0.0)
            duration = float(node.attrib.get("dur", "0") or 0.0)
        else:
            start = float(node.attrib.get("t", "0") or 0.0) / 1000.0
            duration = float(node.attrib.get("d", "0") or 0.0) / 1000.0
        entries.append(SubtitleEntry(start=start, duration=duration, text=text))
    return entries


def fetch_caption_entries(session: requests.Session, track: dict) -> List[SubtitleEntry]:
    caption_url = build_caption_download_url(str(track.get("baseUrl", "")))
    if not caption_url:
        raise SubtitleDownloadError("YouTube returned a subtitle track without baseUrl.")

    response = session.get(caption_url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if not response.text.strip():
        raise SubtitleDownloadError("YouTube returned an empty subtitle response for the selected track.")
    return parse_caption_xml(response.text)


def fetch_youtube_data(
    session: requests.Session,
    youtube_link: str,
    languages: Sequence[str],
) -> tuple[VideoMetadata, List[SubtitleEntry], Optional[str]]:
    video_id = extract_youtube_video_id(youtube_link)
    player_response = fetch_player_response(session, video_id)
    metadata = get_youtube_metadata(player_response, video_id)
    tracks = get_caption_tracks(player_response)
    selected_track = choose_caption_track(tracks, languages)
    subtitle_language = str(selected_track.get("languageCode") or "") or None
    entries = fetch_caption_entries(session, selected_track)
    return metadata, entries, subtitle_language


def write_output(output_dir: str, metadata: VideoMetadata, markdown: str) -> Path:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    filename = sanitize_filename(f"SRT - {metadata.title}.md")
    output_path = destination / filename
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    languages = normalize_languages(args.language)
    session = build_session(args.proxy_https)

    try:
        metadata, entries, subtitle_language = fetch_youtube_data(
            session=session,
            youtube_link=args.youtube_link,
            languages=languages,
        )
        if not entries:
            raise SubtitleDownloadError("Subtitle track was found, but it contains no usable text.")
        markdown = render_markdown(
            metadata=metadata,
            entries=entries,
            subtitle_language=subtitle_language,
            group_size=args.group_size,
        )
        output_path = write_output(args.output_dir, metadata, markdown)
    except SubtitleDownloadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1

    print(f"Finished: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
