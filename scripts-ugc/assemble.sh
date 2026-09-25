#!/bin/bash
# Chroma Loop UGC reel: 20.0 s, 1080x1920, 30 fps.
# Timeline (flash in gameplay_v1.mp4 at 11.5 s -> lands at reel t=11.5):
#   0-2   clip1 0:00-0:02
#   2-7   gameplay 5.0-10.0  (flash-6.5 .. flash-1.5)
#   7-11  clip2 0:00-0:04
#   11-13 gameplay 11.0-13.0 (flash-0.5 .. flash+1.5)
#   13-15 clip2 0:05-0:07
#   15-20 clip3 0:00-0:05
set -euo pipefail
cd "$(dirname "$0")"

IN=/home/user/Test-claud-parametr/input
FONT=/usr/share/fonts/opentype/montserrat/Montserrat-ExtraBold.otf
DT="fontfile=${FONT}:fontsize=64:fontcolor=white:borderw=6:bordercolor=black:x=(w-text_w)/2"

ffmpeg -y -v error \
  -i "$IN/clip1.mp4" -i gameplay_v1.mp4 -i "$IN/clip2.mp4" -i "$IN/clip3.mp4" \
  -filter_complex "\
[0:v]trim=0:2,setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,format=yuv420p[v0];\
[1:v]trim=5.2:10.2,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[v1];\
[2:v]trim=0:4,setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,format=yuv420p[v2];\
[1:v]trim=11.2:13.2,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[v3];\
[2:v]trim=5:7,setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,format=yuv420p[v4];\
[3:v]trim=0:5,setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,format=yuv420p[v5];\
[0:a]atrim=0:2,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a0];\
[1:a]atrim=5.2:10.2,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a1];\
[2:a]atrim=0:4,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a2];\
[1:a]atrim=11.2:13.2,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a3];\
[2:a]atrim=5:7,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a4];\
[3:a]atrim=0:5,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a5];\
[v0][a0][v1][a1][v2][a2][v3][a3][v4][a4][v5][a5]concat=n=6:v=1:a=1[vc][ac];\
[vc]drawtext=${DT}:textfile=cap1.txt:y=560:enable='between(t,0,2)',\
drawtext=${DT}:textfile=cap2a.txt:y=440:enable='between(t,2,7)',\
drawtext=${DT}:textfile=cap2b.txt:y=524:enable='between(t,2,7)',\
drawtext=${DT}:textfile=cap3.txt:y=560:enable='between(t,7,11)',\
drawtext=${DT}:textfile=cap4a.txt:y=440:enable='between(t,15,20)',\
drawtext=${DT}:textfile=cap4b.txt:y=524:enable='between(t,15,20)'[vt];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.85,aformat=channel_layouts=stereo[ding];\
sine=frequency=60:duration=0.3:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.05:d=0.25:curve=qsin,volume=1.6,aformat=channel_layouts=stereo[bass];\
[ding][bass]amix=inputs=2:duration=longest:normalize=0,adelay=11500|11500[sfx];\
[ac][sfx]amix=inputs=2:duration=first:normalize=0[am]" \
  -map "[vt]" -map "[am]" \
  -c:v libx264 -profile:v high -preset medium -crf 18 -r 30 \
  -c:a aac -b:a 192k -ar 48000 \
  assembled_pre.mp4

# Two-pass loudness normalization to -14 LUFS.
ffmpeg -y -i assembled_pre.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 \
  | sed -n '/^{/,/^}/p' > loudnorm1.json
II=$(grep '"input_i"' loudnorm1.json | sed 's/[^0-9.-]*//g')
TP=$(grep '"input_tp"' loudnorm1.json | sed 's/[^0-9.-]*//g')
LRA=$(grep '"input_lra"' loudnorm1.json | sed 's/[^0-9.-]*//g')
TH=$(grep '"input_thresh"' loudnorm1.json | sed 's/[^0-9.-]*//g')
OFF=$(grep '"target_offset"' loudnorm1.json | sed 's/[^0-9.-]*//g')

OUT="$1"
ffmpeg -y -v error -i assembled_pre.mp4 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=${II}:measured_TP=${TP}:measured_LRA=${LRA}:measured_thresh=${TH}:offset=${OFF}:linear=true,aresample=48000" \
  -c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart -t 20.0 \
  "$OUT"

ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,profile,width,height,r_frame_rate,sample_rate,bit_rate -of default=noprint_wrappers=1 "$OUT"
