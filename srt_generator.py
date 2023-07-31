from youtube_transcript_api import YouTubeTranscriptApi
from deepmultilingualpunctuation import PunctuationModel
import requests
import json
import argparse
import urllib.parse


parser = argparse.ArgumentParser(description="")
parser.add_argument("youtube_link", help="youtube link")
parser.add_argument("output_dir", help="output directory")
parser.add_argument("--proxy-https", help="https proxy")
args = parser.parse_args()

youtube_link = args.youtube_link
output_dir = args.output_dir
proxies = {"https": args.proxy_https} if args.proxy_https is not None else {}

if "?" not in youtube_link:  # short link
    youtube_id = youtube_link.split("/")[-1]
else:
    youtube_id = urllib.parse.parse_qs(youtube_link.split("?")[1])['v'][0]

# download caption
srt = YouTubeTranscriptApi.get_transcript(youtube_id, proxies=proxies)
model = PunctuationModel()


def convert_seconds_to_hhmmss(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def get_youtube_video_info(id):
    url = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=%s" % id
    r = requests.get(url, proxies=proxies)
    j = json.loads(r.content)
    return j

header = get_youtube_video_info(youtube_id)

tmp = None
tmp_t = None
output = ""
for subtitle_id, line in enumerate(srt):
    t = line['start']
    subtitle = line['text']

    if (subtitle_id) % 10 == 0:
        if tmp is not None:
            tmp = tmp_t + model.restore_punctuation(tmp)
            tmp = tmp[:-1] if tmp.endswith(".") or tmp.endswith("?") else tmp
            _tmp = ""
            for block in tmp.split("."):
                if block.startswith(" "):
                    _tmp += ". " + block[1].upper() + block[2:]
                else:
                    dot = "." if _tmp else ""
                    _tmp += dot + block
            tmp = _tmp
            print(tmp)
            title = "# %s\n" % tmp_t.split("]")[0][1:]
            output += title + tmp + "\n"
        tmp = subtitle
        tmp_t = "[%s](%s&#t=%s)" % (convert_seconds_to_hhmmss(int(t)), youtube_link, str(t))
    else:
        tmp += " " + subtitle

header['title'] = header['title'].replace(":", " - ").replace("/", "-")
header_info = "\n".join(["%s: %s" % (k, header[k]) for k in header if k != 'html'])
thumbnail_url = "![](%s)" % header['thumbnail_url']
output = "---\n%s\n---\n%s\n" % (header_info, thumbnail_url) + output
print("The output content is ready")

output_file = output_dir + '/SRT - %s.md' % header['title']
with open(output_file, "w") as f:
    f.write(output)

print("Finished: " + output_file)