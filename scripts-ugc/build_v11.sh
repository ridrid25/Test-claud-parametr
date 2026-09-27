#!/bin/bash
# Chroma Loop UGC reel v6 = v5 без врезок с актрисой (только игра), звук записи
# телефона не тронут. Эффекты v4/v5 сохранены: хук, зумы, встряска, слоумо,
# спидлайны, конфетти, глитчи, freeze.
# Timeline (s): 0-2 hook | 2-6.4 lvl3 2.5x | 6.4-6.93 lvl3 flash 1x |
#   6.93-11.33 lvl4 2.5x | 11.33-13.33 slow-mo | 13.33-14.47 flash2+popup 1x |
#   14.47-17.47 ocean | 17.47-20 freeze. 600 frames.
set -euo pipefail
cd "$(dirname "$0")"

SAT="eq=saturation=1.25:contrast=1.03"
VOUT="-c:v libx264 -profile:v high -preset medium -crf 18 -r 30 -pix_fmt yuv420p"
AOUT="-c:a aac -b:a 192k -ar 48000 -ac 2"

# A: fail-hook (1.0 s: почти замкнутая петля с неправильной трубой) +
# rapid flash montage (1.0 s: три вспышки, третья — калейдоскоп)
ffmpeg -y -v error -i gp_forest.mp4 -i gameplay_v1.mp4 \
 -filter_complex "\
[1:v]trim=10.6:11.6,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.05/2)*2':'trunc(ih/1.05/2)*2',scale=1080:1920,setsar=1[h];\
[1:a]atrim=10.6:11.6,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[ha];\
[0:v]trim=10.35:10.65,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.06/2)*2':'trunc(ih/1.06/2)*2',scale=1080:1920,setsar=1[p1];\
[1:v]trim=11.65:11.95,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.10/2)*2':'trunc(ih/1.10/2)*2',scale=1080:1920,setsar=1[p2];\
[0:v]trim=30.25:30.5167,setpts=PTS-STARTPTS,${SAT},crop='trunc(iw/1.08/2)*2':'trunc(ih/1.08/2)*2',scale=540:960,setsar=1,split=4[k1][k2][k3][k4];\
[k2]hflip[k2f];[k3]vflip[k3f];[k4]hflip,vflip[k4f];\
color=black:s=1080x1920:d=0.2667:r=30,format=yuv420p[kbg];\
[kbg][k1]overlay=0:0:shortest=1[kq1];[kq1][k2f]overlay=540:0[kq2];[kq2][k3f]overlay=0:960[kq3];[kq3][k4f]overlay=540:960,setsar=1[p3];\
color=white:s=1080x1920:d=0.0667:r=30,format=yuv420p,setsar=1[w1];\
color=white:s=1080x1920:d=0.0667:r=30,format=yuv420p,setsar=1[w2];\
[0:a]atrim=10.35:10.65,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q1];\
[1:a]atrim=11.65:11.95,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q2];\
[0:a]atrim=30.25:30.5167,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[q3];\
anullsrc=r=48000:cl=stereo:d=0.0667[s1];anullsrc=r=48000:cl=stereo:d=0.0667[s2];\
[h][ha][p1][q1][w1][s1][p2][q2][w2][s2][p3][q3]concat=n=6:v=1:a=1[v][a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 2.0 v11segA.mp4

# B: lvl3 at 2.5x, zoom drift + punch/shake/rotation jitter on the flash (local 4.2)
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=0.2:11.2,setpts=(PTS-STARTPTS)/2.5,fps=30,${SAT},\
scale=w='trunc(1080*(1.02+0.13*t/4.4+0.16*exp(-120*(t-4.2)*(t-4.2)))/2)*2':h='trunc(1920*(1.02+0.13*t/4.4+0.16*exp(-120*(t-4.2)*(t-4.2)))/2)*2':eval=frame,\
rotate=a='if(between(t,4.2,4.5),0.035*sin(50*t),0)':c=black,\
crop=1080:1920:x='(iw-ow)/2+if(between(t,4.2,4.5),12*sin(85*t),0)':y='(ih-oh)/2+if(between(t,4.2,4.5),9*sin(97*t),0)',setsar=1[v];\
[0:a]atrim=0.2:11.2,asetpts=PTS-STARTPTS,atempo=2.5,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 4.4 v11segB.mp4

# B2: lvl3 flash aftermath at 1x (glow, вместо врезки) — punch-out
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=10.75:11.2833,setpts=PTS-STARTPTS,${SAT},\
scale=w='trunc(1080*(1.10+0.12*exp(-80*(t-0.1)*(t-0.1)))/2)*2':h='trunc(1920*(1.10+0.12*exp(-80*(t-0.1)*(t-0.1)))/2)*2':eval=frame,\
crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v];\
[0:a]atrim=10.75:11.2833,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 0.5333 v11segB2.mp4

# C: lvl4 at 2.5x, zoom drift + gentle sway
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=18.4:29.4,setpts=(PTS-STARTPTS)/2.5,fps=30,${SAT},\
scale=w='trunc(1080*(1.03+0.13*t/4.4)/2)*2':h='trunc(1920*(1.03+0.13*t/4.4)/2)*2':eval=frame,\
rotate=a='0.008*sin(2*PI*0.4*t)':c=black,\
crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v];\
[0:a]atrim=18.4:29.4,asetpts=PTS-STARTPTS,atempo=2.5,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 4.4 v11segC.mp4

# D: slow-mo 0.4x from the raw 120 fps recording, own slowed audio
ffmpeg -y -v error -ss 29.6 -to 30.4 -i screenrec.mp4 -filter_complex "\
[0:v]setpts=(PTS-STARTPTS)*2.5,fps=30,crop=1012:1800:34:400,scale=1080:1920,${SAT},\
scale=w='trunc(1080*(1.06+0.10*t/2)/2)*2':h='trunc(1920*(1.06+0.10*t/2)/2)*2':eval=frame,\
crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v];\
[0:a]asetpts=PTS-STARTPTS,atempo=0.5,atempo=0.8,volume=0.6,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 2.0 v11segD.mp4

# E: forest flash2 + появление победного экрана at 1x (вместо врезки) — punch+shake
ffmpeg -y -v error -i gp_forest.mp4 -filter_complex "\
[0:v]trim=30.4:31.5333,setpts=PTS-STARTPTS,${SAT},\
scale=w='trunc(1080*(1.06+0.20*exp(-90*(t-0.15)*(t-0.15)))/2)*2':h='trunc(1920*(1.06+0.20*exp(-90*(t-0.15)*(t-0.15)))/2)*2':eval=frame,\
rotate=a='if(between(t,0.1,0.45),0.04*sin(55*t),0)':c=black,\
crop=1080:1920:x='(iw-ow)/2+if(between(t,0.1,0.45),14*sin(82*t),0)':y='(ih-oh)/2+if(between(t,0.1,0.45),10*sin(95*t),0)',setsar=1[v];\
[0:a]atrim=30.4:31.5333,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 1.1333 v11segE.mp4

# F: ocean closure at 1x — punch + shake + jitter at the flash (local 1.3)
ffmpeg -y -v error -i gameplay_v1.mp4 -filter_complex "\
[0:v]trim=10.4:13.4,setpts=PTS-STARTPTS,${SAT},\
scale=w='trunc(1080*(1.04+0.18*exp(-90*(t-1.3)*(t-1.3)))/2)*2':h='trunc(1920*(1.04+0.18*exp(-90*(t-1.3)*(t-1.3)))/2)*2':eval=frame,\
rotate=a='if(between(t,1.3,1.6),0.035*sin(52*t),0)':c=black,\
crop=1080:1920:x='(iw-ow)/2+if(between(t,1.3,1.7),14*sin(80*t),0)':y='(ih-oh)/2+if(between(t,1.3,1.7),10*sin(93*t),0)',setsar=1[v];\
[0:a]atrim=10.4:13.4,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a]" \
 -map "[v]" -map "[a]" $VOUT $AOUT -t 3.0 v11segF.mp4

# G: win-screen freeze with pulsing push-in
ffmpeg -y -v error -loop 1 -t 2.5333 -i winframe.png -f lavfi -t 2.5333 -i anullsrc=r=48000:cl=stereo -filter_complex "\
[0:v]fps=30,${SAT},\
scale=w='trunc(1080*(1.10+0.08*t/2.53+0.02*sin(2*PI*1.4*t))/2)*2':h='trunc(1920*(1.10+0.08*t/2.53+0.02*sin(2*PI*1.4*t))/2)*2':eval=frame,\
rotate=a='0.14*exp(-6*t)':c=black,\
crop=1080:1920:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[v]" \
 -map "[v]" -map 1:a $VOUT $AOUT -t 2.5333 v11segG.mp4

# --- Stage 2: concat + overlays + SFX ----------------------------------------
ffmpeg -y -v error \
 -i v11segA.mp4 -i v11segB.mp4 -i v11segB2.mp4 -i v11segC.mp4 -i v11segD.mp4 \
 -i v11segE.mp4 -i v11segF.mp4 -i v11segG.mp4 \
 -loop 1 -t 20 -i fx_speedlines.png \
 -framerate 30 -start_number 0 -i confetti/c%03d.png \
 -loop 1 -t 1.95  -i cap_hook.png   -loop 1 -t 6.2  -i cap_loop.png \
 -loop 1 -t 11.2  -i cap_sneaky.png -loop 1 -t 13.3 -i cap_wait.png \
 -loop 1 -t 17.2  -i cap_ohh.png    -loop 1 -t 20.0 -i cap_cta1.png \
 -loop 1 -t 20.0  -i cap_cta2.png \
 -loop 1 -t 0.95  -i cap_fail.png \
 -i /home/user/Test-claud-parametr/input/clip1.mp4 \
 -filter_complex "\
[0:v][0:a][1:v][1:a][2:v][2:a][3:v][3:a][4:v][4:a][5:v][5:a][6:v][6:a][7:v][7:a]concat=n=8:v=1:a=1[vc][ac];\
[vc]rgbashift=rh=10:bh=-10:gv=6:enable='between(t,6.37,6.47)+between(t,11.28,11.40)+between(t,14.42,14.52)+between(t,17.42,17.52)'[ve1];\
[ve1]hue=h='360*(t-15.9)':enable='between(t,15.9,16.7)'[ve2];\
[ve2]pixelize=width=36:height=36:enable='between(t,2.0,2.08)+between(t,6.93,7.01)+between(t,11.33,11.41)'[ve3];\
[ve3]negate=enable='between(t,13.45,13.52)+between(t,15.77,15.84)'[vgk];\
[vgk]split[vm][vkk];\
[vkk]scale=540:960,split=4[m1][m2][m3][m4];\
[m2]hflip[m2f];[m3]vflip[m3f];[m4]hflip,vflip[m4f];\
color=black:s=1080x1920:r=30[mbg];\
[mbg][m1]overlay=0:0:shortest=1[mq1];[mq1][m2f]overlay=540:0[mq2];[mq2][m3f]overlay=0:960[mq3];[mq3][m4f]overlay=540:960[kq];\
[vm][kq]overlay=0:0:enable='between(t,6.40,6.93)+between(t,9.50,10.30)+between(t,12.30,13.33)+between(t,16.05,16.58)'[vg];\
[8:v]format=rgba,colorchannelmixer=aa=0.85[sl];\
[vg][sl]overlay=x=0:y=0:enable='between(t,1.05,1.22)+between(t,1.42,1.59)+between(t,6.10,6.32)+between(t,13.42,13.68)+between(t,15.74,15.98)'[ov0];\
[9:v]format=rgba,setpts=PTS+15.77/TB[cf];\
[ov0][cf]overlay=x=0:y=0:enable='between(t,15.77,18.27)'[ov1];\
[17:v]format=rgba,fade=in:st=0.05:d=0.10:alpha=1,fade=out:st=0.85:d=0.10:alpha=1[c8];\
[10:v]format=rgba,fade=in:st=1.05:d=0.10:alpha=1,fade=out:st=2.40:d=0.10:alpha=1[c1];\
[11:v]format=rgba,fade=in:st=2.60:d=0.15:alpha=1,fade=out:st=6.05:d=0.15:alpha=1[c2];\
[12:v]format=rgba,fade=in:st=7.10:d=0.15:alpha=1,fade=out:st=11.05:d=0.15:alpha=1[c3];\
[13:v]format=rgba,fade=in:st=11.45:d=0.15:alpha=1,fade=out:st=13.15:d=0.15:alpha=1[c4];\
[14:v]format=rgba,fade=in:st=15.80:d=0.10:alpha=1,fade=out:st=17.05:d=0.15:alpha=1[c5];\
[15:v]format=rgba,fade=in:st=17.60:d=0.15:alpha=1[c6];\
[16:v]format=rgba,fade=in:st=17.75:d=0.15:alpha=1[c7];\
[ov1][c8]overlay=x=0:y='430+50*exp(-14*(t-0.05))':enable='between(t,0.05,0.95)'[o0];\
[o0][c1]overlay=x=0:y='430+50*exp(-14*(t-1.05))':enable='between(t,1.05,2.50)'[o1];\
[o1][c2]overlay=x=0:y='430+50*exp(-14*(t-2.60))':enable='between(t,2.60,6.20)'[o2];\
[o2][c3]overlay=x=0:y='430+50*exp(-14*(t-7.10))':enable='between(t,7.10,11.20)'[o3];\
[o3][c4]overlay=x=0:y='470+50*exp(-14*(t-11.45))':enable='between(t,11.45,13.30)'[o4];\
[o4][c5]overlay=x=0:y='430+70*exp(-14*(t-15.80))':enable='between(t,15.80,17.20)'[o5];\
[o5][c6]overlay=x=0:y='420+50*exp(-14*(t-17.60))':enable='between(t,17.60,20)'[o6];\
[o6][c7]overlay=x=0:y='545+50*exp(-14*(t-17.75))':enable='between(t,17.75,20)'[vt];\
aevalsrc='0.4*sin(2*PI*110*t)+0.25*sin(2*PI*220*t)':d=0.30:s=48000,afade=t=in:st=0:d=0.01,afade=t=out:st=0.2:d=0.1,aformat=channel_layouts=stereo,adelay=550|550[buzz];\
sine=frequency=1200:duration=0.3:sample_rate=48000,afade=t=out:st=0.02:d=0.28:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=1050|1050[d1];\
sine=frequency=1200:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=1420|1420[d2];\
sine=frequency=1200:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.35,aformat=channel_layouts=stereo,adelay=1780|1780[d3];\
anoisesrc=d=0.25:color=pink:amplitude=0.22:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=1350|1350[w1];\
anoisesrc=d=0.25:color=pink:amplitude=0.22:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=1720|1720[w2];\
sine=frequency=1200:duration=0.5:sample_rate=48000,afade=t=out:st=0.02:d=0.48:curve=exp,volume=0.5,aformat=channel_layouts=stereo,adelay=6200|6200[d4];\
anoisesrc=d=0.25:color=pink:amplitude=0.24:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=6900|6900[w3];\
aevalsrc='0.2*sin(2*PI*(170*t+200*t*t))':d=1.85:s=48000,afade=t=in:st=0:d=0.4,aformat=channel_layouts=stereo,adelay=11430|11430[riser];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.9,aformat=channel_layouts=stereo[bd1];\
sine=frequency=60:duration=0.35:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.06:d=0.29:curve=qsin,volume=1.7,aformat=channel_layouts=stereo[bb1];\
[bd1][bb1]amix=inputs=2:duration=longest:normalize=0,adelay=13450|13450[big1];\
anoisesrc=d=0.25:color=pink:amplitude=0.24:sample_rate=48000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.08:d=0.17,aformat=channel_layouts=stereo,adelay=14430|14430[w4];\
sine=frequency=1200:duration=0.7:sample_rate=48000,afade=t=out:st=0.03:d=0.65:curve=exp,volume=0.9,aformat=channel_layouts=stereo[bd2];\
sine=frequency=60:duration=0.35:sample_rate=48000,afade=t=in:st=0:d=0.02,afade=t=out:st=0.06:d=0.29:curve=qsin,volume=1.7,aformat=channel_layouts=stereo[bb2];\
[bd2][bb2]amix=inputs=2:duration=longest:normalize=0,adelay=15770|15770[big2];\
anoisesrc=d=0.08:color=white:amplitude=0.28:sample_rate=48000,afade=t=out:st=0.01:d=0.07,aformat=channel_layouts=stereo,adelay=15820|15820[pp1];\
anoisesrc=d=0.08:color=white:amplitude=0.24:sample_rate=48000,afade=t=out:st=0.01:d=0.07,aformat=channel_layouts=stereo,adelay=15980|15980[pp2];\
sine=frequency=900:duration=0.4:sample_rate=48000,afade=t=out:st=0.02:d=0.38:curve=exp,volume=0.4,aformat=channel_layouts=stereo,adelay=17600|17600[d5];\
sine=frequency=1500:duration=0.35:sample_rate=48000,afade=t=out:st=0.02:d=0.33:curve=exp,volume=0.3,aformat=channel_layouts=stereo,adelay=9500|9500[d6];\
sine=frequency=1500:duration=0.35:sample_rate=48000,afade=t=out:st=0.02:d=0.33:curve=exp,volume=0.3,aformat=channel_layouts=stereo,adelay=16050|16050[d7];\
[18:a]atrim=0.32:1.52,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.06,afade=t=out:st=1.12:d=0.08,aresample=48000,aformat=channel_layouts=stereo,adelay=100|100[vo1];\
[18:a]atrim=13.25:15.83,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.06,afade=t=out:st=2.48:d=0.10,aresample=48000,aformat=channel_layouts=stereo,adelay=7500|7500[vo2];\
[18:a]atrim=22.12:25.06,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.06,afade=t=out:st=2.82:d=0.12,aresample=48000,aformat=channel_layouts=stereo,adelay=15200|15200[vo3];\
[18:a]atrim=26.51:28.02,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.06,afade=t=out:st=1.39:d=0.12,aresample=48000,aformat=channel_layouts=stereo,adelay=18350|18350[vo4];\
[ac][buzz][d1][d2][d3][w1][w2][d4][w3][riser][big1][w4][big2][pp1][pp2][d5][d6][d7][vo1][vo2][vo3][vo4]amix=inputs=22:duration=first:normalize=0[am]" \
 -map "[vt]" -map "[am]" $VOUT $AOUT v11_pre.mp4

# --- Loudness -----------------------------------------------------------------
ffmpeg -y -i v11_pre.mp4 -af loudnorm=I=-14:TP=-2:LRA=11:print_format=json -f null - 2>&1 \
  | sed -n '/^{/,/^}/p' > loudnorm11.json
II=$(grep '"input_i"' loudnorm11.json | sed 's/[^0-9.-]*//g')
TP=$(grep '"input_tp"' loudnorm11.json | sed 's/[^0-9.-]*//g')
LRA=$(grep '"input_lra"' loudnorm11.json | sed 's/[^0-9.-]*//g')
TH=$(grep '"input_thresh"' loudnorm11.json | sed 's/[^0-9.-]*//g')
OFF=$(grep '"target_offset"' loudnorm11.json | sed 's/[^0-9.-]*//g')
ffmpeg -y -v error -i v11_pre.mp4 \
  -af "loudnorm=I=-14:TP=-2:LRA=11:measured_I=${II}:measured_TP=${TP}:measured_LRA=${LRA}:measured_thresh=${TH}:offset=${OFF}:linear=true,aresample=48000" \
  -c:v copy -c:a pcm_s16le -f matroska v11_ln.mkv
D=$(ffmpeg -i v11_ln.mkv -af loudnorm=print_format=json -f null - 2>&1 | grep '"input_i"' | sed 's/[^0-9.-]*//g')
CORR=$(python3 -c "print(round(-14 - ($D), 2))")
echo "post-loudnorm I=$D corr=${CORR}dB"
ffmpeg -y -v error -i v11_ln.mkv \
  -af "volume=${CORR}dB,alimiter=limit=0.794:level=false:attack=2:release=50" \
  -frames:v 600 -t 20.0 -c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart \
  chroma_ugc_reels_v11.mp4

ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 chroma_ugc_reels_v11.mp4
ffmpeg -i chroma_ugc_reels_v11.mp4 -af loudnorm=print_format=json -f null - 2>&1 | grep -E '"input_i"|"input_tp"'
