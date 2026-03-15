import unittest

from srt_generator import (
    SubtitleDownloadError,
    SubtitleEntry,
    VideoMetadata,
    extract_youtube_video_id,
    normalize_languages,
    parse_bilibili_reference,
    render_markdown,
    transcript_item_to_entry,
)


class Snippet:
    def __init__(self, start, duration, text):
        self.start = start
        self.duration = duration
        self.text = text


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

    def test_parse_bilibili_reference_supports_bv_and_av(self):
        self.assertEqual(
            parse_bilibili_reference("https://www.bilibili.com/video/BV1xx411c7mD?p=2"),
            ({"bvid": "BV1xx411c7mD"}, 2),
        )
        self.assertEqual(
            parse_bilibili_reference("https://www.bilibili.com/video/av170001"),
            ({"aid": "170001"}, 1),
        )

    def test_parse_bilibili_reference_rejects_bad_page_number(self):
        with self.assertRaises(SubtitleDownloadError):
            parse_bilibili_reference("https://www.bilibili.com/video/BV1xx411c7mD?p=abc")

    def test_normalize_languages_deduplicates_values(self):
        self.assertEqual(
            normalize_languages(["en, zh-CN", "en", "ja"]),
            ["en", "zh-CN", "ja"],
        )

    def test_transcript_item_to_entry_supports_dict_and_objects(self):
        entry_from_dict = transcript_item_to_entry(
            {"start": 1.5, "duration": 2.0, "text": "hello world"}
        )
        entry_from_object = transcript_item_to_entry(Snippet(3.0, 1.2, "foo bar"))

        self.assertEqual(entry_from_dict, SubtitleEntry(1.5, 2.0, "hello world"))
        self.assertEqual(entry_from_object, SubtitleEntry(3.0, 1.2, "foo bar"))

    def test_render_markdown_groups_entries(self):
        metadata = VideoMetadata(
            platform="youtube",
            title="Test Video",
            author="Author",
            thumbnail_url="https://example.com/thumb.jpg",
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            source_id="dQw4w9WgXcQ",
            extra={},
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
            punctuation_model=None,
        )

        self.assertIn('title: "Test Video"', output)
        self.assertIn("## [00:00:00.000](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=0)", output)
        self.assertIn("hello world", output)
        self.assertIn("## [00:00:10.000](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10)", output)


if __name__ == "__main__":
    unittest.main()
