# Титры: Montserrat ExtraBold, белый + золото #d8b25e (палитра razbor), мягкая тень.
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import json

EB = "/usr/share/fonts/opentype/montserrat/Montserrat-ExtraBold.otf"
SB = "/usr/share/fonts/opentype/montserrat/Montserrat-SemiBold.otf"
WHITE = (242, 242, 242, 255); GOLD = (216, 178, 94, 255); DIM = (168, 168, 168, 255)

def text_img(lines, pad=40):
    # lines: [(text, font, color)]
    imgs = []
    for text, font, color in lines:
        bbox = font.getbbox(text)
        w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
        im = Image.new("RGBA", (w+2*pad, h+2*pad), (0,0,0,0))
        d = ImageDraw.Draw(im)
        # тень
        d.text((pad+3-bbox[0], pad+5-bbox[1]), text, font=font, fill=(0,0,0,200))
        im = im.filter(ImageFilter.GaussianBlur(4))
        d = ImageDraw.Draw(im)
        d.text((pad-bbox[0], pad-bbox[1]), text, font=font, fill=color)
        imgs.append(im)
    W = max(i.width for i in imgs)
    gap = 18
    H = sum(i.height for i in imgs) + gap*(len(imgs)-1)
    out = Image.new("RGBA", (W, H), (0,0,0,0))
    y = 0
    for i in imgs:
        out.paste(i, ((W-i.width)//2, y), i); y += i.height + gap
    return out

def fit_font(path, text, size, maxw=980):
    f = ImageFont.truetype(path, size)
    while f.getbbox(text)[2] - f.getbbox(text)[0] > maxw and size > 40:
        size -= 4; f = ImageFont.truetype(path, size)
    return f

tl = json.load(open("timeline.json"))
seen = {}
for i, w in enumerate(tl["words"]):
    if w["s"] < tl["meta"]["hook_end"]: continue  # p0 закрыт заставкой
    key = (w["w"], w["acc"])
    if key in seen:
        w["png"] = seen[key]; continue
    size = 132 if w["acc"] else 96
    f = fit_font(EB, w["w"], size)
    img = text_img([(w["w"], f, GOLD if w["acc"] else WHITE)])
    name = f"w{len(seen):03d}.png"
    img.save(name); seen[key] = name; w["png"] = name
json.dump(tl, open("timeline.json","w"), ensure_ascii=False, indent=1)

# Заставка
hook = text_img([
    ("Селлер покупает", ImageFont.truetype(EB, 92), WHITE),
    ("только эти 3 вещи", ImageFont.truetype(EB, 92), GOLD),
])
sub = text_img([("Удели всего 45 секунд", ImageFont.truetype(SB, 50), DIM)])
hook.save("hook.png"); sub.save("hooksub.png")

# Финальная карта
cta = text_img([
    ("mp.ridfinance.ru", fit_font(EB, "mp.ridfinance.ru", 96, maxw=760), GOLD),
    ("бесплатно · без заявки", fit_font(SB, "бесплатно · без заявки", 54, maxw=700), WHITE),
])
cta.save("cta.png")
print("pngs:", len(seen)+3)
