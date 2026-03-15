import argparse
import html
import inspect
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests


DEFAULT_TIMEOUT = 15
YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
BILIBILI_DOMAINS = {
    "bilibili.com",
    "www.bilibili.com",
    "m.bilibili.com",
    "b23.tv",
    "www.b23.tv",
    "bili2233.cn",
    "www.bili2233.cn",
}
INVALID_FILENAME_CHARS = r'<>:"/\|?*'


class SubtitleDownloadError(RuntimeError):
    pass


@dataclass
class SubtitleEntry:
    start: float
    duration: float
    text: str


@dataclass
class VideoMetadata:
    platform: str
    title: str
    author: str
    thumbnail_url: str
    source_url: str
    source_id: str
    extra: Dict[str, str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download subtitles from YouTube or Bilibili and render them as Markdown."
    )
    parser.add_argument("video_link", help="YouTube or Bilibili video URL")
    parser.add_argument("output_dir", help="Output directory for the generated Markdown file")
    parser.add_argument(
        "--platform",
        choices=("auto", "youtube", "bilibili"),
        default="auto",
        help="Platform override. Default: auto detect from URL.",
    )
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
    parser.add_argument(
        "--preserve-formatting",
        action="store_true",
        help="Preserve formatting when the source adapter supports it.",
    )
    parser.add_argument(
        "--skip-punctuation",
        action="store_true",
        help="Skip punctuation restoration even if the model is installed.",
    )
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
            )
        }
    )
    if proxy_https:
        session.proxies.update({"http": proxy_https, "https": proxy_https})
    return session


def detect_platform(video_link: str) -> str:
    parsed = urllib.parse.urlparse(video_link)
    host = parsed.netloc.lower()
    if not host:
        if re.fullmatch(r"[\w-]{11}", video_link):
            return "youtube"
        raise SubtitleDownloadError(f"Cannot detect platform from input: {video_link}")

    if host in YOUTUBE_DOMAINS:
        return "youtube"
    if host in BILIBILI_DOMAINS:
        return "bilibili"
    raise SubtitleDownloadError(f"Unsupported host: {host}")


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


def build_timestamp_url(platform: str, source_url: str, seconds: float) -> str:
    start_seconds = max(0, int(seconds))
    parsed = urllib.parse.urlparse(source_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    if platform == "youtube":
        query["t"] = [str(start_seconds)]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))

    if platform == "bilibili":
        query["t"] = [str(start_seconds)]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))

    return source_url


def build_frontmatter(metadata: VideoMetadata, subtitle_language: Optional[str]) -> str:
    fields = {
        "title": metadata.title,
        "platform": metadata.platform,
        "source_url": metadata.source_url,
        "source_id": metadata.source_id,
        "author": metadata.author,
    }
    if metadata.thumbnail_url:
        fields["thumbnail_url"] = metadata.thumbnail_url
    if subtitle_language:
        fields["subtitle_language"] = subtitle_language
    fields.update({key: value for key, value in metadata.extra.items() if value})

    lines = ["---"]
    for key, value in fields.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


def load_punctuation_model(skip_punctuation: bool):
    if skip_punctuation:
        return None

    try:
        from deepmultilingualpunctuation import PunctuationModel
    except ImportError:
        return None

    try:
        return PunctuationModel()
    except Exception:
        return None


def apply_punctuation(text: str, model) -> str:
    if model is None or not text:
        return text

    try:
        punctuated = model.restore_punctuation(text)
    except Exception:
        return text

    punctuated = normalize_text(punctuated)
    if punctuated and punctuated[0].islower():
        punctuated = punctuated[0].upper() + punctuated[1:]
    return punctuated


def transcript_item_to_entry(item) -> SubtitleEntry:
    if isinstance(item, dict):
        start = item.get("start", 0.0)
        duration = item.get("duration", 0.0)
        text = item.get("text", "")
    else:
        start = getattr(item, "start", 0.0)
        duration = getattr(item, "duration", 0.0)
        text = getattr(item, "text", "")

    return SubtitleEntry(
        start=float(start or 0.0),
        duration=float(duration or 0.0),
        text=normalize_text(str(text or "")),
    )


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
    punctuation_model,
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
    for key, value in metadata.extra.items():
        if value:
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {value}")
    lines.append("")

    for chunk in chunk_entries(entries, group_size):
        start_seconds = chunk[0].start
        timestamp_label = format_timestamp_label(start_seconds)
        timestamp_url = build_timestamp_url(metadata.platform, metadata.source_url, start_seconds)
        merged_text = normalize_text(" ".join(entry.text for entry in chunk))
        merged_text = apply_punctuation(merged_text, punctuation_model)
        if not merged_text:
            continue

        lines.append(f"## [{timestamp_label}]({timestamp_url})")
        lines.append(merged_text)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def request_json(session: requests.Session, url: str, **kwargs) -> dict:
    response = session.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


def extract_youtube_video_id(video_link: str) -> str:
    direct_id = video_link.strip()
    if re.fullmatch(r"[\w-]{11}", direct_id):
        return direct_id

    parsed = urllib.parse.urlparse(video_link)
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

    raise SubtitleDownloadError(f"Could not extract YouTube video id from: {video_link}")


def get_youtube_metadata(session: requests.Session, video_id: str) -> VideoMetadata:
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    title = video_id
    author = "Unknown"
    thumbnail_url = ""

    try:
        payload = request_json(
            session,
            "https://www.youtube.com/oembed",
            params={"url": source_url, "format": "json"},
        )
        title = payload.get("title") or title
        author = payload.get("author_name") or author
        thumbnail_url = payload.get("thumbnail_url") or thumbnail_url
    except requests.RequestException:
        pass

    return VideoMetadata(
        platform="youtube",
        title=title,
        author=author,
        thumbnail_url=thumbnail_url,
        source_url=source_url,
        source_id=video_id,
        extra={},
    )


def build_youtube_client(session: requests.Session, proxy_https: Optional[str]):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise SubtitleDownloadError(
            "youtube-transcript-api is not installed. Install dependencies first."
        ) from exc

    init_signature = inspect.signature(YouTubeTranscriptApi)
    init_kwargs = {}

    if "http_client" in init_signature.parameters:
        init_kwargs["http_client"] = session

    if proxy_https and "proxy_config" in init_signature.parameters:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig
        except ImportError:
            GenericProxyConfig = None
        if GenericProxyConfig is not None:
            init_kwargs["proxy_config"] = GenericProxyConfig(
                http_url=proxy_https,
                https_url=proxy_https,
            )

    try:
        return YouTubeTranscriptApi(**init_kwargs)
    except TypeError:
        return YouTubeTranscriptApi()


def choose_youtube_transcript(transcript_list) -> object:
    transcripts = list(transcript_list)
    if not transcripts:
        raise SubtitleDownloadError("No subtitles are available for this YouTube video.")

    transcripts.sort(key=lambda item: getattr(item, "is_generated", False))
    return transcripts[0]


def fetch_youtube_legacy_transcript(client, video_id: str, kwargs: dict):
    if kwargs.get("languages"):
        legacy_api = getattr(type(client), "get_transcript", None)
        if legacy_api is None:
            raise SubtitleDownloadError("Unsupported youtube-transcript-api version.")
        return legacy_api(video_id, **kwargs), kwargs["languages"][0]

    list_transcripts = getattr(type(client), "list_transcripts", None)
    if list_transcripts is not None:
        try:
            transcript = choose_youtube_transcript(list_transcripts(video_id))
            selected_language = getattr(transcript, "language_code", None)
            return transcript.fetch(), selected_language
        except Exception as exc:
            raise SubtitleDownloadError(f"Failed to fetch YouTube subtitles: {exc}") from exc

    legacy_api = getattr(type(client), "get_transcript", None)
    if legacy_api is None:
        raise SubtitleDownloadError("Unsupported youtube-transcript-api version.")
    return legacy_api(video_id, **kwargs), None


def fetch_youtube_entries(
    session: requests.Session,
    video_id: str,
    languages: Sequence[str],
    preserve_formatting: bool,
    proxy_https: Optional[str],
) -> Tuple[List[SubtitleEntry], Optional[str]]:
    client = build_youtube_client(session, proxy_https)

    if hasattr(client, "fetch"):
        try:
            if languages:
                fetched = client.fetch(
                    video_id,
                    languages=list(languages),
                    preserve_formatting=preserve_formatting,
                )
                selected_language = languages[0]
            else:
                transcript = choose_youtube_transcript(client.list(video_id))
                selected_language = getattr(transcript, "language_code", None)
                fetched = transcript.fetch(preserve_formatting=preserve_formatting)
        except Exception as exc:
            raise SubtitleDownloadError(f"Failed to fetch YouTube subtitles: {exc}") from exc

        selected_language = getattr(fetched, "language_code", selected_language)
        entries = [transcript_item_to_entry(item) for item in fetched]
        entries = [entry for entry in entries if entry.text]
        return entries, selected_language

    kwargs = {"preserve_formatting": preserve_formatting}
    if languages:
        kwargs["languages"] = list(languages)
    if proxy_https:
        kwargs["proxies"] = {"http": proxy_https, "https": proxy_https}

    try:
        fetched, selected_language = fetch_youtube_legacy_transcript(client, video_id, kwargs)
    except Exception as exc:
        raise SubtitleDownloadError(f"Failed to fetch YouTube subtitles: {exc}") from exc

    entries = [transcript_item_to_entry(item) for item in fetched]
    entries = [entry for entry in entries if entry.text]
    return entries, selected_language


def resolve_bilibili_short_url(session: requests.Session, video_link: str) -> str:
    response = session.get(video_link, allow_redirects=True, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.url


def parse_bilibili_reference(video_link: str) -> Tuple[Dict[str, str], int]:
    parsed = urllib.parse.urlparse(video_link)
    query = urllib.parse.parse_qs(parsed.query)
    page_raw = query.get("p", ["1"])[0] or "1"
    try:
        page_number = int(page_raw)
    except ValueError as exc:
        raise SubtitleDownloadError(f"Invalid Bilibili page number: {page_raw}") from exc

    path = parsed.path
    bvid_match = re.search(r"/video/(BV[\w]+)", path, flags=re.IGNORECASE)
    if bvid_match:
        return {"bvid": bvid_match.group(1)}, page_number

    aid_match = re.search(r"/video/av(\d+)", path, flags=re.IGNORECASE)
    if aid_match:
        return {"aid": aid_match.group(1)}, page_number

    raise SubtitleDownloadError(f"Could not extract Bilibili video id from: {video_link}")


def fetch_bilibili_video_data(
    session: requests.Session,
    reference: Dict[str, str],
) -> dict:
    payload = request_json(
        session,
        "https://api.bilibili.com/x/web-interface/view",
        params=reference,
    )
    if payload.get("code") != 0 or "data" not in payload:
        raise SubtitleDownloadError(
            f"Bilibili video info request failed: {payload.get('message') or payload.get('msg') or payload}"
        )
    return payload["data"]


def select_bilibili_page(video_data: dict, page_number: int) -> dict:
    pages = video_data.get("pages") or []
    if not pages:
        raise SubtitleDownloadError("Bilibili video has no page information.")

    if page_number < 1 or page_number > len(pages):
        raise SubtitleDownloadError(
            f"Bilibili page index out of range: p={page_number}, total={len(pages)}"
        )
    return pages[page_number - 1]


def choose_bilibili_subtitle(subtitles: Sequence[dict], languages: Sequence[str]) -> dict:
    if not subtitles:
        raise SubtitleDownloadError("No published subtitles were found for this Bilibili video.")

    if not languages:
        return subtitles[0]

    normalized_languages = {language.lower() for language in languages}
    for subtitle in subtitles:
        lan = str(subtitle.get("lan", "")).lower()
        lan_doc = str(subtitle.get("lan_doc", "")).lower()
        if (
            lan in normalized_languages
            or lan_doc in normalized_languages
            or any(language in lan_doc for language in normalized_languages)
        ):
            return subtitle

    available = ", ".join(
        collapse_whitespace(f"{subtitle.get('lan')} ({subtitle.get('lan_doc', '')})")
        for subtitle in subtitles
    )
    raise SubtitleDownloadError(
        f"Requested subtitle language was not found. Available tracks: {available}"
    )


def normalize_bilibili_subtitle_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return url


def get_bilibili_metadata(video_data: dict, page: dict, page_number: int) -> VideoMetadata:
    bvid = video_data.get("bvid")
    canonical_url = f"https://www.bilibili.com/video/{bvid}"
    if page_number > 1:
        canonical_url += f"?p={page_number}"

    extra: Dict[str, str] = {}
    part = page.get("part")
    if part and part != video_data.get("title"):
        extra["part"] = str(part)

    return VideoMetadata(
        platform="bilibili",
        title=video_data.get("title") or bvid,
        author=((video_data.get("owner") or {}).get("name") or "Unknown"),
        thumbnail_url=video_data.get("pic") or "",
        source_url=canonical_url,
        source_id=bvid or str(video_data.get("aid")),
        extra=extra,
    )


def fetch_bilibili_entries(
    session: requests.Session,
    video_link: str,
    languages: Sequence[str],
) -> Tuple[VideoMetadata, List[SubtitleEntry], Optional[str]]:
    parsed = urllib.parse.urlparse(video_link)
    host = parsed.netloc.lower()
    normalized_link = (
        resolve_bilibili_short_url(session, video_link)
        if host in {"b23.tv", "www.b23.tv", "bili2233.cn", "www.bili2233.cn"}
        else video_link
    )

    reference, page_number = parse_bilibili_reference(normalized_link)
    video_data = fetch_bilibili_video_data(session, reference)
    page = select_bilibili_page(video_data, page_number)

    player_payload = request_json(
        session,
        "https://api.bilibili.com/x/player/v2",
        params={"cid": page["cid"], **reference},
    )
    if player_payload.get("code") != 0 or "data" not in player_payload:
        raise SubtitleDownloadError(
            f"Bilibili subtitle info request failed: {player_payload.get('message') or player_payload.get('msg') or player_payload}"
        )

    subtitle_info = ((player_payload.get("data") or {}).get("subtitle") or {})
    subtitle_track = choose_bilibili_subtitle(subtitle_info.get("subtitles") or [], languages)
    subtitle_language = subtitle_track.get("lan_doc") or subtitle_track.get("lan")
    subtitle_url = normalize_bilibili_subtitle_url(subtitle_track.get("subtitle_url", ""))
    if not subtitle_url:
        raise SubtitleDownloadError("Bilibili returned a subtitle track without subtitle_url.")

    subtitle_payload = request_json(session, subtitle_url)
    body = subtitle_payload.get("body") or []
    entries = [
        SubtitleEntry(
            start=float(item.get("from", 0.0)),
            duration=max(0.0, float(item.get("to", 0.0)) - float(item.get("from", 0.0))),
            text=normalize_text(str(item.get("content", ""))),
        )
        for item in body
        if item.get("content")
    ]

    metadata = get_bilibili_metadata(video_data, page, page_number)
    return metadata, entries, subtitle_language


def fetch_youtube_data(
    session: requests.Session,
    video_link: str,
    languages: Sequence[str],
    preserve_formatting: bool,
    proxy_https: Optional[str],
) -> Tuple[VideoMetadata, List[SubtitleEntry], Optional[str]]:
    video_id = extract_youtube_video_id(video_link)
    metadata = get_youtube_metadata(session, video_id)
    entries, subtitle_language = fetch_youtube_entries(
        session=session,
        video_id=video_id,
        languages=languages,
        preserve_formatting=preserve_formatting,
        proxy_https=proxy_https,
    )
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
    punctuation_model = load_punctuation_model(args.skip_punctuation)

    try:
        platform = args.platform if args.platform != "auto" else detect_platform(args.video_link)

        if platform == "youtube":
            metadata, entries, subtitle_language = fetch_youtube_data(
                session=session,
                video_link=args.video_link,
                languages=languages,
                preserve_formatting=args.preserve_formatting,
                proxy_https=args.proxy_https,
            )
        elif platform == "bilibili":
            metadata, entries, subtitle_language = fetch_bilibili_entries(
                session=session,
                video_link=args.video_link,
                languages=languages,
            )
        else:
            raise SubtitleDownloadError(f"Unsupported platform: {platform}")

        if not entries:
            raise SubtitleDownloadError("Subtitle track was found, but it contains no usable text.")

        markdown = render_markdown(
            metadata=metadata,
            entries=entries,
            subtitle_language=subtitle_language,
            group_size=args.group_size,
            punctuation_model=punctuation_model,
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
