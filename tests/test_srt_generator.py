import unittest

from srt_generator import (
    SubtitleEntry,
    VideoMetadata,
    build_caption_download_url,
    choose_caption_track,
    extract_innertube_api_key,
    extract_youtube_video_id,
    normalize_languages,
    parse_caption_xml,
    render_markdown,
)


class SrtGeneratorTests(unittest.TestCase):
    def test_extract_youtube_video_id_supports_multiple_url_shapes(self):
        self.assertEqual(extract_youtube_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(
            extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ?si=test"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_innertube_api_key_reads_watch_html(self):
        html = '<script>var ytcfg = {"INNERTUBE_API_KEY":"abc_123-xyz"};</script>'
        self.assertEqual(extract_innertube_api_key(html), "abc_123-xyz")

    def test_normalize_languages_deduplicates_values(self):
        self.assertEqual(
            normalize_languages(["en, zh-CN", "en", "ja"]),
            ["en", "zh-CN", "ja"],
        )

    def test_choose_caption_track_prefers_manual_when_no_language_requested(self):
        tracks = [
            {"languageCode": "en", "kind": "asr", "name": {"simpleText": "English"}},
            {"languageCode": "en", "name": {"simpleText": "English"}},
        ]
        chosen = choose_caption_track(tracks, [])
        self.assertNotEqual(chosen.get("kind"), "asr")

    def test_choose_caption_track_matches_language_code_or_name(self):
        tracks = [
            {"languageCode": "en", "name": {"simpleText": "English"}},
            {"languageCode": "zh-Hans", "name": {"simpleText": "Chinese (Simplified)"}},
        ]
        self.assertEqual(choose_caption_track(tracks, ["zh-Hans"])["languageCode"], "zh-Hans")
        self.assertEqual(choose_caption_track(tracks, ["simplified"])["languageCode"], "zh-Hans")

    def test_build_caption_download_url_removes_srv3_format(self):
        url = "https://www.youtube.com/api/timedtext?lang=en&fmt=srv3&v=test"
        self.assertEqual(
            build_caption_download_url(url),
            "https://www.youtube.com/api/timedtext?lang=en&v=test",
        )

    def test_parse_caption_xml_supports_text_and_p_nodes(self):
        xml_text = (
            "<timedtext>"
            "<text start='1.2' dur='3.4'>hello &amp; world</text>"
            "<body><p t='5000' d='1200'>line one\nline two</p></body>"
            "</timedtext>"
        )
        entries = parse_caption_xml(xml_text)
        self.assertEqual(
            entries,
            [
                SubtitleEntry(start=1.2, duration=3.4, text="hello & world"),
                SubtitleEntry(start=5.0, duration=1.2, text="line one line two"),
            ],
        )

    def test_render_markdown_groups_entries(self):
        metadata = VideoMetadata(
            title="Test Video",
            author="Author",
            thumbnail_url="https://example.com/thumb.jpg",
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            source_id="dQw4w9WgXcQ",
        )
        entries = [
            SubtitleEntry(0.0, 1.0, "hello"),
            SubtitleEntry(1.0, 1.0, "world"),
            SubtitleEntry(10.0, 1.0, "second"),
        ]

        output = render_markdown(
            metadata=metadata,
            entries=entries,
            subtitle_language="en",
            group_size=2,
        )

        self.assertIn('title: "Test Video"', output)
        self.assertIn("## [00:00:00.000](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=0)", output)
        self.assertIn("hello world", output)
        self.assertIn("## [00:00:10.000](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10)", output)


if __name__ == "__main__":
    unittest.main()
