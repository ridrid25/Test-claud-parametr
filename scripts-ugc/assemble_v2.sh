#!/bin/bash
# Chroma Loop UGC reel v2 — gameplay-first, 20.0 s, 1080x1920, 30 fps.
# Timeline:
#   0-2   ocean flash hook        (gameplay_v1 10.5-12.5, 1x; closure lands at 1.2)
#   2-8   forest lvl3 solve, 2x   (gp_forest 0-12; flash lands ~7.35)
#   8-14  forest lvl4 solve, 2x   (gp_forest 19-31; flash lands ~13.75)
#   14-20 ocean finale, 1x        (gameplay_v1 9-15; closure 16.7, win screen 17.5+)
set -euo pipefail
cd "$(dirname "$0")"

FONT=/usr/share/fonts/opentype/montserrat/Montserrat-ExtraBold.otf
DT="fontfile=${FONT}:fontsize=64:fontcolor=white:borderw=6:bordercolor=black:x=(w-text_w)/2"

ffmpeg -y -v error \
  -i gameplay_v1.mp4 -i gp_forest.mp4 \
  -filter_complex "\
[0:v]trim=10.5:12.5,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[v0];\
[1:v]trim=0:12,setpts=(PTS-STARTPTS)/2,fps=30,setsar=1,format=yuv420p[v1];\
[1:v]trim=19:31,setpts=(PTS-STARTPTS)/2,fps=30,setsar=1,format=yuv420p[v2];\
[0:v]trim=9:15,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[v3];\
[0:a]atrim=10.5:12.5,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a0];\
[1:a]atrim=0:12,asetpts=PTS-STARTPTS,atempo=2,aresample=48000,aformat=channel_layouts=stereo[a1];\
[1:a]atrim=19:31,asetpts=PTS-STARTPTS,atempo=2,aresample=48000,aformat=channel_layouts=stereo[a2];\
[0:a]atrim=9:15,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a3];\
[v0][a0][v1][a1][v2][a2][v3][a3]concat=n=4:v=1:a=1[vc][ac];\
[vc]drawtext=${DT}:textfile=c1.txt:y=520:enable='between(t,0,2)',\
drawtext=${DT}:textfile=c2a.txt:y=440:enable='between(t,2.3,7)',\
drawtext=${DT}:textfile=c2b.txt:y=524:enable='between(t,2.3,7)',\
drawtext=${DT}:textfile=c3.txt:y=480:enable='between(t,8.3,13.3)',\
drawtext=${DT}:textfile=c4a.txt:y=440:enable='between(t,14.6,20)',\
drawtext=${DT}:textfile=c4b.txt:y=524:enable='between(t,14.6,20)'[vt];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.85,aformat=channel_layouts=stereo[dingA];\
sine=frequency=60:duration=0.3:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.05:d=0.25:curve=qsin,volume=1.6,aformat=channel_layouts=stereo[bassA];\
[dingA][bassA]amix=inputs=2:duration=longest:normalize=0,adelay=1200|1200[sfx1];\
sine=frequency=1200:duration=0.5:sample_rate=48000,afade=t=out:st=0.02:d=0.48:curve=exp,volume=0.4,aformat=channel_layouts=stereo,adelay=7350|7350[sfx2];\
sine=frequency=1200:duration=0.5:sample_rate=48000,afade=t=out:st=0.02:d=0.48:curve=exp,volume=0.4,aformat=channel_layouts=stereo,adelay=13750|13750[sfx3];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.85,aformat=channel_layouts=stereo[dingB];\
sine=frequency=60:duration=0.3:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.05:d=0.25:curve=qsin,volume=1.6,aformat=channel_layouts=stereo[bassB];\
[dingB][bassB]amix=inputs=2:duration=longest:normalize=0,adelay=16700|16700[sfx4];\
[ac][sfx1][sfx2][sfx3][sfx4]amix=inputs=5:duration=first:normalize=0[am]" \
  -map "[vt]" -map "[am]" \
  -c:v libx264 -profile:v high -preset medium -crf 18 -r 30 \
  -c:a aac -b:a 192k -ar 48000 \
  assembled_pre2.mp4

ffmpeg -y -i assembled_pre2.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 \
  | sed -n '/^{/,/^}/p' > loudnorm2.json
II=$(grep '"input_i"' loudnorm2.json | sed 's/[^0-9.-]*//g')
TP=$(grep '"input_tp"' loudnorm2.json | sed 's/[^0-9.-]*//g')
LRA=$(grep '"input_lra"' loudnorm2.json | sed 's/[^0-9.-]*//g')
TH=$(grep '"input_thresh"' loudnorm2.json | sed 's/[^0-9.-]*//g')
OFF=$(grep '"target_offset"' loudnorm2.json | sed 's/[^0-9.-]*//g')

ffmpeg -y -v error -i assembled_pre2.mp4 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=${II}:measured_TP=${TP}:measured_LRA=${LRA}:measured_thresh=${TH}:offset=${OFF}:linear=true,volume=-0.68dB,aresample=48000" \
  -c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart -t 20.0 \
  chroma_ugc_reels_v2.mp4

ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,profile,width,height,r_frame_rate -of default=noprint_wrappers=1 chroma_ugc_reels_v2.mp4
ffmpeg -i chroma_ugc_reels_v2.mp4 -af loudnorm=print_format=json -f null - 2>&1 | grep -E '"input_i"|"input_tp"'
