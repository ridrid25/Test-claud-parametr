# Ролик «Селлер покупает только 3 вещи»: тайминги слов по речевым отрезкам piper.
# Голос: piper (GitHub rhasspy/piper, релиз 2023.11.14-2) + voice-ru-irinia-medium (релиз v0.0.2).
# Слова фразы распределяются по ВСЕМ речевым отрезкам (silencedetect -32dB/0.18s)
# пропорционально длине слова; паузы держат предыдущее слово.
import subprocess, json, re

TTS = "../tts"  # p0..p4.wav, синтез: ./piper/piper --model ru-irinia-medium.onnx --length_scale 1.08
PHRASES = {
  "p0": "Селлер покупает только три вещи.",
  "p1": "Первое — время. Отчёт о реализации съедает вечер. Дашборд читает его за минуту: загрузили файл — и цифры на экране.",
  "p2": "Второе — ясность. Продажи есть, а на счёт пришло непонятно сколько. Комиссия, логистика, возвраты — видно, куда ушёл каждый рубль.",
  "p3": "Третье — точность. Всё сходится с отчётом кабинета до рубля. Расхождение — это ошибка, а не «примерно».",
  "p4": "Это бесплатно и без заявки. Откройте дашборд и посмотрите свои цифры сами.",
}
SHOW = {"Первое": "1-е", "Второе": "2-е", "Третье": "3-е"}
ACCENT = {"время","ясность","точность","1-е","2-е","3-е","рубля","бесплатно"}

def sil(wav):
    r = subprocess.run(["ffmpeg","-i",wav,"-af","silencedetect=n=-32dB:d=0.18","-f","null","-"],
                       capture_output=True,text=True).stderr
    out, st = [], None
    for line in r.splitlines():
        m=re.search(r"silence_start: ([\d.]+)",line)
        if m: st=float(m.group(1))
        m=re.search(r"silence_end: ([\d.]+)",line)
        if m and st is not None: out.append((st,float(m.group(1)))); st=None
    return out
def dur(wav):
    return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","csv=p=0",wav],capture_output=True,text=True).stdout.strip())

order=["p0","p1","p2","p3","p4"]
durs={p:dur(f"{TTS}/{p}.wav") for p in order}
gap=0.45; t=0.35; ps={}
for p in order: ps[p]=t; t+=durs[p]+gap
speech_end=ps["p4"]+durs["p4"]

words_tl=[]
for p in order:
    D=durs[p]
    segs, cur = [], 0.0
    for s0,s1 in sil(f"{TTS}/{p}.wav"):
        if s0-cur>0.10: segs.append([cur,s0])
        cur=s1
    if D-cur>0.10: segs.append([cur,D])
    if not segs: segs=[[0,D]]
    total_speech=sum(b-a for a,b in segs)
    ws=[]
    for w in PHRASES[p].split():
        c=w.strip("—–.,:«»!?")
        if c: ws.append(SHOW.get(c,c))
    weights=[len(w)+2.2 for w in ws]; wsum=sum(weights)
    def map_t(sp):
        acc=0
        for a,b in segs:
            if sp<=acc+(b-a): return a+(sp-acc)
            acc+=b-a
        return segs[-1][1]
    sp=0.0
    for w,wt in zip(ws,weights):
        d=total_speech*wt/wsum
        words_tl.append({"w":w,"s":round(ps[p]+map_t(sp),3),
                         "e":round(ps[p]+map_t(sp+d),3),"acc":w in ACCENT})
        sp+=d
cta=round(speech_end+0.15,3)
for i in range(len(words_tl)-1):
    words_tl[i]["e"]=words_tl[i+1]["s"]
words_tl[-1]["e"]=round(cta-0.15,3)
meta={"phrase_start":ps,"durs":durs,"hook_end":round(ps["p1"]-0.05,3),
      "cta_start":cta,"total":round(cta+3.2,2)}
json.dump({"meta":meta,"words":words_tl},open("timeline.json","w"),ensure_ascii=False,indent=1)
print("total",meta["total"],"words",len(words_tl))
