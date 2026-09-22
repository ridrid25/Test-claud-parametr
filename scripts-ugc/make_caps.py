# Renders caption PNGs: Montserrat ExtraBold text + color emoji, transparent bg.
from PIL import Image, ImageDraw, ImageFont

MONT = "/usr/share/fonts/opentype/montserrat/Montserrat-ExtraBold.otf"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

def render(name, text, emoji=None, size=64, color=(255,255,255,255)):
    font = ImageFont.truetype(MONT, size)
    stroke = 6
    d = ImageDraw.Draw(Image.new("RGBA", (8,8)))
    bbox = d.textbbox((0,0), text, font=font, stroke_width=stroke)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    em_target = int(size*1.25)
    gap = int(size*0.28) if emoji else 0
    W, H = 1080, max(th, em_target) + 24
    img = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    total_w = tw + (gap + em_target if emoji else 0)
    x = (W - total_w)//2 - bbox[0]
    y = (H - th)//2 - bbox[1]
    draw.text((x, y), text, font=font, fill=color, stroke_width=stroke, stroke_fill=(0,0,0,255))
    if emoji:
        # NotoColorEmoji is a bitmap font; render at its native strike then resize.
        for strike in (137, 109, 128):
            try:
                efont = ImageFont.truetype(EMOJI, strike)
                eimg = Image.new("RGBA", (strike+40, strike+40), (0,0,0,0))
                ed = ImageDraw.Draw(eimg)
                ed.text((10, 10), emoji, font=efont, embedded_color=True)
                ebox = eimg.getbbox()
                if not ebox:
                    continue
                eimg = eimg.crop(ebox).resize((em_target, em_target), Image.LANCZOS)
                img.alpha_composite(eimg, (x + bbox[0] + tw + gap, (H - em_target)//2))
                break
            except OSError:
                continue
    img.save(f"cap_{name}.png")
    print(name, img.size)

render("hook",  "this game hits DIFFERENT", "\U0001F525")          # fire
render("loop",  "rotate → connect → LOOP", "\U0001F300", size=56)  # cyclone
render("sneaky","level 40 is SNEAKY", "\U0001F624")                 # 😤
render("wait",  "wait for it...", "\U0001F440")                     # eyes
render("ohh",   "OHHHH", "\U0001F92F", size=96)                     # 🤯
render("cta1",  "Chroma Loop", "⚡", color=(255,255,255,255))   # zap
render("cta2",  "FREE on Google Play", None, size=56, color=(120,255,150,255))
