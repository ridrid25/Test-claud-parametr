# Сборка: чёрный кадр 1080x1920 → титры → «архивная плёнка» (дрейф, зерно, мерцание, виньетка).
import json, subprocess

tl = json.load(open("timeline.json"))
M = tl["meta"]; T = M["total"]; HOOK_END = M["hook_end"]; CTA = M["cta_start"]

inputs = ["-f","lavfi","-i",f"color=c=0x0a0a0d:s=1080x1920:r=30:d={T}"]
files = ["hook.png","hooksub.png","cta.png"]
word_items = [w for w in tl["words"] if w["s"] >= HOOK_END]
uniq = []
for w in word_items:
    if w["png"] not in files and w["png"] not in uniq: uniq.append(w["png"])
files += uniq
for f in files:
    inputs += ["-loop","1","-i",f]
idx = {f: i+1 for i, f in enumerate(files)}

fc = []
# заставка с фейдом
fc.append(f"[{idx['hook.png']}:v]format=rgba,fade=in:st=0:d=0.35:alpha=1,fade=out:st={HOOK_END-0.3:.2f}:d=0.3:alpha=1[hook]")
fc.append(f"[{idx['hooksub.png']}:v]format=rgba,fade=in:st=0.6:d=0.4:alpha=1,fade=out:st={HOOK_END-0.3:.2f}:d=0.3:alpha=1[hsub]")
fc.append(f"[{idx['cta.png']}:v]format=rgba,fade=in:st={CTA:.2f}:d=0.4:alpha=1[cta]")
cur = "0:v"
fc.append(f"[{cur}][hook]overlay=(W-w)/2:770:shortest=1[v1]")
fc.append("[v1][hsub]overlay=(W-w)/2:1160:shortest=1[v2]")
cur = "v2"; n = 3
for w in word_items:
    out = f"v{n}"; n += 1
    fc.append(f"[{cur}][{idx[w['png']]}:v]overlay=(W-w)/2:(H-h)/2:shortest=1:enable='between(t,{w['s']},{w['e']})'[{out}]")
    cur = out
fc.append(f"[{cur}][cta]overlay=(W-w)/2:(H-h)/2:shortest=1[vc]")
# плёнка: наезд + дрейф/качание, зерно по яркости, мерцание, виньетка
fc.append(
    f"[vc]scale=w='trunc((1080*(1.06+0.0024*t))/2)*2':h=-2:eval=frame,"
    "crop=1080:1920:x='(iw-1080)/2+7*sin(2.1*t)+3*sin(5.7*t)':y='(ih-1920)/2+9*sin(0.9*t)+4*sin(3.3*t)',"
    "noise=c0s=11:c0f=t+u,"
    "eq=brightness='0.022*sin(16.7*t)+0.014*sin(6.1*t)':eval=frame,"
    "vignette=PI/4.6,format=yuv420p[vout]"
)
cmd = ["ffmpeg","-y","-v","error"] + inputs + ["-filter_complex",";".join(fc),
       "-map","[vout]","-t",str(T),"-r","30","-c:v","libx264","-preset","medium","-crf","18","video_silent.mp4"]
print("overlays:", len(word_items)+3)
subprocess.run(cmd, check=True)
print("video ok")

# аудио: фразы по своим стартам, тишина вокруг
ai = []
for p in ["p0","p1","p2","p3","p4"]:
    ai += ["-i", f"../tts/{p}.wav"]
delays = [int(M["phrase_start"][p]*1000) for p in ["p0","p1","p2","p3","p4"]]
af = []
for i, d in enumerate(delays):
    af.append(f"[{i}:a]aresample=48000,adelay={d}|{d}[a{i}]")
af.append("[a0][a1][a2][a3][a4]amix=inputs=5:normalize=0,apad[aout]")
subprocess.run(["ffmpeg","-y","-v","error"] + ai + ["-filter_complex",";".join(af),
    "-map","[aout]","-t",str(T),"-c:a","pcm_s16le","voice_raw.wav"], check=True)
print("audio ok")
