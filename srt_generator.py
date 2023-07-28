from youtube_transcript_api import YouTubeTranscriptApi
from deepmultilingualpunctuation import PunctuationModel
import requests
import json
import sys

# arg1: script.py, arg2: youtube_link, arg3: output_dir
if len(sys.argv) == 3:
    ytb_link = sys.argv[1]
    output_dir = sys.argv[2]
else:
    ytb_link = input("YouTube link:")
    output_dir = input("Output Directory:")

if "?" not in ytb_link: # short link
    ytb_id = ytb_link.split("/")[-1]
else:
    ytb_id = ytb_link.split("?")[1].split("&")[0].split("=")[1]

# download caption
srt = YouTubeTranscriptApi.get_transcript(ytb_id)
model = PunctuationModel()

def convert_seconds_to_HHMMSS(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def get_youtube_video_title(id):
    url = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=%s" % id
    r = requests.get(url)
    j = json.loads(r.content)
    return j['title'].replace(":", " - ").replace("/", "-")


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
            print(tmp)
            title = "# " + tmp_t.split("]")[0][1:] + "\n"
            output += title + tmp + "\n"
        tmp = subtitle
        tmp_t = "[" + convert_seconds_to_HHMMSS(int(t)) + "](" + ytb_link + "&#t=" + str(t) + ")"
    else:
        tmp += " " + subtitle

# print(output)
print("The output content is ready")
output_file = output_dir + '/SRT - %s.md' % get_youtube_video_title(ytb_id)
with open(output_file , "w") as f:
    f.write(output)
print("Finished: " + output_file)