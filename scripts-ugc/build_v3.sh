#!/bin/bash
# Chroma Loop UGC reel v3 — "kids gaming edit": rapid flash hook, punch-in zooms,
# screen shake, speed ramps, 120fps slow-mo, glitch transitions, emoji captions.
# Timeline: 0-2 hook (3 flashes + white frames) | 2-7.5 lvl3 2x | 7.5-12.5 lvl4 2x
#           12.5-14.5 slow-mo 0.4x | 14.5-17.5 ocean closure 1x | 17.5-20 win screen
set -euo pipefail
cd "$(dirname "$0")"

SAT="eq=saturation=1.25:contrast=1.03"
VOUT="-c:v libx264 -profile:v high -preset medium -crf 18 -r 30 -pix_fmt yuv420p"
AOUT="-c:a aac -b:a 192k -ar 48000 -ac 2"

# --- Stage 1: segments -------------------------------------------------------

# A: rapid hook — three win flashes with white flash-frames between
ffmpeg -y -v error -i gp_forest.mp4 -i gameplay_v1.mp4 \
 -filter_complex "\
[0:v]trim=10.2:10.8,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.06/2)*2':'trunc(ih/1.06/2)*2',scale=1080:1920,setsar=1[p1];\
[1:v]trim=11.5:12.1,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.10/2)*2':'trunc(ih/1.10/2)*2',scale=1080:1920,setsar=1[p2];\
[0:v]trim=30.1:30.7667,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.08/2)*2':'trunc(ih/1.08/2)*2',scale=1080:1920,setsar=1[p3];\
color=white:s=1080x1920:d=0.0667:r=30,format=yuv420p,setsar=1[w1];\
color=white:s=1080x1920:d=0.0667:r=30,format=yuv420p,setsar=1[w2];\
[0:a]atrim=10.2:10.8,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q1];\
[1:a]atrim=11.5:12.1,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q2];\
[0:a]atrim=30.1:30.7667,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q3];\
anullsrc=r=48000:cl=stereo:d=0.0667[s1];anullsrc=r=48000:cl=stereo:d=0.0667[s2];\
[p1][q1][w1][s1][p2][q2][w2][s2][p3][q3]concat=n=5:v=1:a=1[v][a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 2.0 segA.mp4

# B: forest lvl3 at 2x with zoom drift, punch+shake on the flash (local t=5.25)
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=0.2:11.2,setpts=(PTS-STARTPTS)/2,fps=30,${SAT},\
scale=w='trunc(1080*(1+0.10*t/5.5+0.15*exp(-100*(t-5.25)*(t-5.25)))/2)*2':h='trunc(1920*(1+0.10*t/5.5+0.15*exp(-100*(t-5.25)*(t-5.25)))/2)*2':eval=frame,crop=1080:1920:x='(iw-ow)/2+if(between(t,5.25,5.6),12*sin(85*t),0)':y='(ih-oh)/2+if(between(t,5.25,5.6),9*sin(97*t),0)',setsar=1[v];\
[0:a]atrim=0.2:11.2,asetpts=PTS-STARTPTS,atempo=2,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 5.5 segB.mp4

# C: forest lvl4 at 2x with zoom drift
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=19.4:29.4,setpts=(PTS-STARTPTS)/2,fps=30,${SAT},\
scale=w='trunc(1080*(1+0.10*t/5)/2)*2':h='trunc(1920*(1+0.10*t/5)/2)*2':eval=frame,crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v];\
[0:a]atrim=19.4:29.4,asetpts=PTS-STARTPTS,atempo=2,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 5.0 segC.mp4

# D: slow-mo 0.4x of the last rotation before the forest lvl4 flash, cut from the
# raw 120 fps recording for smooth motion
ffmpeg -y -v error -ss 29.6 -to 30.6 -i screenrec.mp4 -filter_complex "\
[0:v]setpts=(PTS-STARTPTS)*2.5,fps=30,crop=1012:1800:34:400,scale=1080:1920,${SAT},\
scale=w='trunc(1080*(1.06+0.08*t/2)/2)*2':h='trunc(1920*(1.06+0.08*t/2)/2)*2':eval=frame,crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v];\
[0:a]asetpts=PTS-STARTPTS,atempo=0.5,atempo=0.8,volume=0.4,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 2.0 segD.mp4

# E: ocean closure at 1x, punch+shake at the flash (local t=1.3)
ffmpeg -y -v error -i gameplay_v1.mp4 -filter_complex "\
[0:v]trim=10.4:13.4,setpts=PTS-STARTPTS,${SAT},\
scale=w='trunc(1080*(1.04+0.18*exp(-90*(t-1.3)*(t-1.3)))/2)*2':h='trunc(1920*(1.04+0.18*exp(-90*(t-1.3)*(t-1.3)))/2)*2':eval=frame,crop=1080:1920:x='(iw-ow)/2+if(between(t,1.3,1.7),14*sin(80*t),0)':y='(ih-oh)/2+if(between(t,1.3,1.7),10*sin(93*t),0)',setsar=1[v];\
[0:a]atrim=10.4:13.4,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 3.0 segE.mp4

# F: win-screen freeze frame with slow push-in (recording jumps to the next
# level too fast, so the popup is held as a still)
ffmpeg -y -v error -loop 1 -t 2.5 -i winframe.png -f lavfi -t 2.5 -i anullsrc=r=48000:cl=stereo -filter_complex "\
[0:v]fps=30,${SAT},\
scale=w='trunc(1080*(1+0.12*t/2.5)/2)*2':h='trunc(1920*(1+0.12*t/2.5)/2)*2':eval=frame,crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v]" \
 -map "[v]" -map 1:a $VOUT $AOUT -t 2.5 segF.mp4

# --- Stage 2: concat + glitch transitions + emoji captions + SFX -------------

ffmpeg -y -v error \
 -i segA.mp4 -i segB.mp4 -i segC.mp4 -i segD.mp4 -i segE.mp4 -i segF.mp4 \
 -loop 1 -t 1.95  -i cap_hook.png   -loop 1 -t 7.0  -i cap_loop.png \
 -loop 1 -t 12.3  -i cap_sneaky.png -loop 1 -t 14.4 -i cap_wait.png \
 -loop 1 -t 17.3  -i cap_ohh.png    -loop 1 -t 20.0 -i cap_cta1.png \
 -loop 1 -t 20.0  -i cap_cta2.png \
 -filter_complex "\
[0:v][0:a][1:v][1:a][2:v][2:a][3:v][3:a][4:v][4:a][5:v][5:a]concat=n=6:v=1:a=1[vc][ac];\
[vc]rgbashift=rh=10:bh=-10:gv=6:enable='between(t,7.44,7.56)+between(t,14.44,14.56)'[vg];\
[6:v]format=rgba,fade=in:st=0.10:d=0.12:alpha=1,fade=out:st=1.85:d=0.10:alpha=1[c1];\
[7:v]format=rgba,fade=in:st=2.30:d=0.15:alpha=1,fade=out:st=6.85:d=0.15:alpha=1[c2];\
[8:v]format=rgba,fade=in:st=7.80:d=0.15:alpha=1,fade=out:st=12.15:d=0.15:alpha=1[c3];\
[9:v]format=rgba,fade=in:st=12.60:d=0.15:alpha=1,fade=out:st=14.25:d=0.15:alpha=1[c4];\
[10:v]format=rgba,fade=in:st=15.85:d=0.10:alpha=1,fade=out:st=17.15:d=0.15:alpha=1[c5];\
[11:v]format=rgba,fade=in:st=17.55:d=0.15:alpha=1[c6];\
[12:v]format=rgba,fade=in:st=17.75:d=0.15:alpha=1[c7];\
[vg][c1]overlay=x=0:y='430+50*exp(-14*(t-0.10))':enable='between(t,0.10,1.95)'[o1];\
[o1][c2]overlay=x=0:y='430+50*exp(-14*(t-2.30))':enable='between(t,2.30,7.00)'[o2];\
[o2][c3]overlay=x=0:y='430+50*exp(-14*(t-7.80))':enable='between(t,7.80,12.30)'[o3];\
[o3][c4]overlay=x=0:y='470+50*exp(-14*(t-12.60))':enable='between(t,12.60,14.40)'[o4];\
[o4][c5]overlay=x=0:y='430+70*exp(-14*(t-15.85))':enable='between(t,15.85,17.30)'[o5];\
[o5][c6]overlay=x=0:y='420+50*exp(-14*(t-17.55))':enable='between(t,17.55,20)'[o6];\
[o6][c7]overlay=x=0:y='545+50*exp(-14*(t-17.75))':enable='between(t,17.75,20)'[vt];\
sine=frequency=1200:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=50|50[d1];\
sine=frequency=1200:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=720|720[d2];\
sine=frequency=1200:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=1400|1400[d3];\
anoisesrc=d=0.25:color=pink:amplitude=0.22:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=600|600[w1];\
anoisesrc=d=0.25:color=pink:amplitude=0.22:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=1270|1270[w2];\
anoisesrc=d=0.3:color=pink:amplitude=0.26:sample_rate=48000,afade=t=in:st=0:d=0.06,afade=t=out:st=0.1:d=0.2,aformat=channel_layouts=stereo,adelay=14380|14380[w3];\
sine=frequency=1200:duration=0.5:sample_rate=48000,afade=t=out:st=0.02:d=0.48:curve=exp,volume=0.5,aformat=channel_layouts=stereo,adelay=7250|7250[d4];\
aevalsrc='0.2*sin(2*PI*(170*t+190*t*t))':d=1.8:s=48000,afade=t=in:st=0:d=0.4,aformat=channel_layouts=stereo,adelay=12700|12700[riser];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.9,aformat=channel_layouts=stereo[bd];\
sine=frequency=60:duration=0.35:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.06:d=0.29:curve=qsin,volume=1.7,aformat=channel_layouts=stereo[bb];\
[bd][bb]amix=inputs=2:duration=longest:normalize=0,adelay=15800|15800[big];\
sine=frequency=900:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.4,aformat=channel_layouts=stereo,adelay=17600|17600[d5];\
[ac][d1][d2][d3][w1][w2][w3][d4][riser][big][d5]amix=inputs=11:duration=first:normalize=0[am]" \
 -map "[vt]" -map "[am]" $VOUT $AOUT assembled_pre3.mp4

# --- Loudness: two-pass to -14 LUFS -----------------------------------------
ffmpeg -y -i assembled_pre3.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 \
  | sed -n '/^{/,/^}/p' > loudnorm3.json
II=$(grep '"input_i"' loudnorm3.json | sed 's/[^0-9.-]*//g')
TP=$(grep '"input_tp"' loudnorm3.json | sed 's/[^0-9.-]*//g')
LRA=$(grep '"input_lra"' loudnorm3.json | sed 's/[^0-9.-]*//g')
TH=$(grep '"input_thresh"' loudnorm3.json | sed 's/[^0-9.-]*//g')
OFF=$(grep '"target_offset"' loudnorm3.json | sed 's/[^0-9.-]*//g')
ffmpeg -y -v error -i assembled_pre3.mp4 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=${II}:measured_TP=${TP}:measured_LRA=${LRA}:measured_thresh=${TH}:offset=${OFF}:linear=true,aresample=48000" \
  -c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart -t 20.0 \
  chroma_ugc_reels_v3.mp4

ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,profile,width,height,r_frame_rate -of default=noprint_wrappers=1 chroma_ugc_reels_v3.mp4
ffmpeg -i chroma_ugc_reels_v3.mp4 -af loudnorm=print_format=json -f null - 2>&1 | grep -E '"input_i"|"input_tp"'
