#!/bin/bash
# Мастеринг: 2-проходный loudnorm → точная коррекция → лимитер (level=false!) → один AAC-энкод.
set -e
T=$(python3 -c "import json;print(json.load(open('timeline.json'))['meta']['total'])")
J=$(ffmpeg -i voice_raw.wav -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | tail -12)
II=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['input_i'],d['input_tp'],d['input_lra'],d['input_thresh'])")
read -r MI MTP MLRA MTH <<< "$II"
echo "measured I=$MI TP=$MTP LRA=$MLRA"
ffmpeg -y -v error -i voice_raw.wav -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=$MI:measured_TP=$MTP:measured_LRA=$MLRA:measured_thresh=$MTH:linear=true,alimiter=limit=0.794:level=false" -c:a pcm_s16le voice_norm.wav
ffmpeg -y -v error -i video_silent.mp4 -i voice_norm.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -movflags +faststart -t "$T" out.mp4
echo "=== проверка ==="
ffmpeg -i out.mp4 -af loudnorm=I=-14:TP=-1.5:print_format=summary -f null - 2>&1 | grep -E "Input Integrated|Input True Peak"
ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,width,height,r_frame_rate -of default=noprint_wrappers=1 out.mp4
