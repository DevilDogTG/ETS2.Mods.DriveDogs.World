#!/usr/bin/env python3
"""
Generates the mod's cover/thumbnail image for the ETS2 Mod Manager listing (src/cover.jpg). The megapack
build copies it into the archive, where manifest.sii's `icon:` field references it. SCS requires a 276x162
JPEG.

Same layout and gold/amber palette as the other DriveDogs covers (logo left, title block right, road, amber
version badge); the World motif is a stormy night: a storm cloud with a lightning bolt, rain, pine treelines
against a horizon glow, and a train with lit windows approaching a level crossing whose lamps reflect on the
wet road.

Composited at 4x (1104x648) then downscaled for anti-aliasing. The version badge is read from megapack.yaml's
package.version, so rerun this before every build that bumps the version.
"""
import random
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = ROOT / "logo.png"
OUT_PATH = ROOT / "src" / "cover.jpg"
CONFIG_PATH = ROOT / "megapack.yaml"

SCALE = 4
FINAL_SIZE = (276, 162)
CANVAS_SIZE = (FINAL_SIZE[0] * SCALE, FINAL_SIZE[1] * SCALE)

FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
FONT_REG = r"C:\Windows\Fonts\arial.ttf"

BG_TOP = (8, 12, 22)
BG_BOTTOM = (24, 20, 14)
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (255, 196, 84)
STAR_COLOR = (255, 236, 200)
HORIZON_GLOW = (90, 105, 140)
CLOUD_COLOR = (40, 44, 58)
CLOUD_RIM = (255, 196, 84)
BOLT_COLOR = (255, 236, 190)
HILL_FAR = (30, 30, 40)
HILL_NEAR = (19, 19, 26)
TREE_COLOR = (12, 14, 18)
TRAIN_COLOR = (44, 44, 54)
WINDOW_COLOR = (255, 196, 84)
RAIL_COLOR = (255, 170, 70)
LAMP_COLOR = (255, 150, 60)
RAIN_COLOR = (180, 190, 210)
BADGE_COLOR = (255, 196, 84)
BADGE_TEXT_COLOR = (20, 16, 10)

HORIZON = 0.78  # fraction of height where the rail line runs (crossing the road: a level crossing)


def read_version():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    version = (cfg.get("package") or {}).get("version")
    if not version:
        raise SystemExit(f"No package.version in {CONFIG_PATH}")
    return str(version)


def composite(img, *layers):
    base = img.convert("RGBA")
    for layer in layers:
        base = Image.alpha_composite(base, layer)
    return base.convert("RGB")


def make_background(size):
    w, h = size
    img = Image.new("RGB", size, BG_BOTTOM)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def add_stars(img):
    """A few stars between the clouds (fixed seed, so the cover is reproducible)."""
    w, h = img.size
    rng = random.Random(1061306287)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(40):
        x, y = rng.uniform(0, w), rng.uniform(0, h * HORIZON * 0.8)
        r = rng.choice((1, 1, 1, 2, 2, 3))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*STAR_COLOR, rng.randint(50, 150)))
    return composite(img, layer)


def add_horizon_glow(img):
    """Soft glow along the horizon so the pine silhouettes read against the sky."""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([-w * 0.1, h * (HORIZON - 0.16), w * 1.1, h * (HORIZON + 0.06)],
                                  fill=(*HORIZON_GLOW, 110))
    return composite(img, layer.filter(ImageFilter.GaussianBlur(radius=h * 0.07)))


def puff_layer(size, puffs, color, alpha=255):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for cx, cy, r in puffs:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, alpha))
    return layer


def add_storm(img):
    """Storm cloud top-centre, clear of the logo on the left and the version badge on the right, lit amber from
    below, with a lightning bolt dropping from its right side and the bolt's flash."""
    w, h = img.size
    cx, cy, s = w * 0.63, h * 0.10, h * 0.075
    puffs = [(cx - s * 1.6, cy + s * 0.3, s * 0.8), (cx - s * 0.6, cy - s * 0.2, s * 1.1),
             (cx + s * 0.7, cy - s * 0.1, s * 1.0), (cx + s * 1.8, cy + s * 0.35, s * 0.75),
             (cx, cy + s * 0.5, s * 0.9)]
    rim = puff_layer(img.size, [(x, y + s * 0.12, r) for x, y, r in puffs], CLOUD_RIM, 200)
    body = puff_layer(img.size, puffs, CLOUD_COLOR)

    bx, by, k = cx + s * 1.5, cy + s * 0.8, s * 1.5
    bolt = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(bolt).polygon([(bx, by), (bx - k * 0.45, by + k * 0.9), (bx + k * 0.05, by + k * 0.95),
                                  (bx - k * 0.35, by + k * 2.0), (bx + k * 0.55, by + k * 0.7),
                                  (bx + k * 0.05, by + k * 0.65), (bx + k * 0.4, by)],
                                 fill=(*BOLT_COLOR, 255))
    flash = bolt.filter(ImageFilter.GaussianBlur(radius=h * 0.06))
    return composite(img, flash, flash, rim.filter(ImageFilter.GaussianBlur(radius=h * 0.02)), rim, body,
                     bolt.filter(ImageFilter.GaussianBlur(radius=h * 0.008)), bolt)


def add_hills(img):
    w, h = img.size
    draw = ImageDraw.Draw(img)
    for color, y0, amp, phase in ((HILL_FAR, HORIZON - 0.05, 0.05, 0.0), (HILL_NEAR, HORIZON + 0.02, 0.035, 1.7)):
        pts = [(0, h)]
        for i in range(0, 101):
            x = w * i / 100
            t = i / 100
            y = h * (y0 - amp * (0.6 * abs(((t * 2.3 + phase) % 2) - 1) + 0.4 * abs(((t * 5.1 + phase) % 2) - 1)))
            pts.append((x, y))
        pts.append((w, h))
        draw.polygon(pts, fill=color)
    return img


def draw_pine(draw, x, base_y, height):
    width = height * 0.42
    for k in range(3):
        top = base_y - height * (1 - k * 0.25)
        bottom = base_y - height * (0.35 - k * 0.12)
        hw = width * (0.55 + k * 0.22) / 2
        draw.polygon([(x, top), (x - hw, bottom), (x + hw, bottom)], fill=(*TREE_COLOR, 255))
    draw.rectangle([x - width * 0.05, base_y - height * 0.15, x + width * 0.05, base_y], fill=(*TREE_COLOR, 255))


def add_trees(img):
    """Pine treelines on both flanks of the road, smaller next to it, standing on the rail line."""
    w, h = img.size
    rng = random.Random(4)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    base_y = h * (HORIZON + 0.005)
    for x0, x1 in ((0.0, 0.40), (0.60, 1.02)):
        x = w * x0
        while x < w * x1:
            near_road = min(abs(x - w * 0.40), abs(x - w * 0.60)) < w * 0.04
            draw_pine(draw, x, base_y, h * rng.uniform(0.15, 0.24) * (0.6 if near_road else 1.0))
            x += w * rng.uniform(0.022, 0.035)
    return composite(img, layer)


def add_train(img):
    """Rail line with a glowing amber edge crossing the road, and a locomotive plus cars with lit windows on
    the right, heading for the crossing (below the title block, so it reads as scenery)."""
    w, h = img.size
    rail_y = h * HORIZON
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.line([(0, rail_y), (w, rail_y)], fill=(*RAIL_COLOR, 200), width=max(2, int(h * 0.006)))
    glow = layer.filter(ImageFilter.GaussianBlur(radius=h * 0.01))

    train = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(train)
    car_h, car_w, gap = h * 0.06, w * 0.075, w * 0.005
    x = w * 0.62
    for i in range(5):
        top = rail_y - car_h - h * 0.006
        if i == 0:  # locomotive: sloped nose, headlight
            td.polygon([(x, rail_y - h * 0.006), (x + car_w * 0.18, top), (x + car_w, top),
                        (x + car_w, rail_y - h * 0.006)], fill=(*TRAIN_COLOR, 255))
            hx, hy = x + car_w * 0.07, rail_y - car_h * 0.35
            td.ellipse([hx - h * 0.008, hy - h * 0.008, hx + h * 0.008, hy + h * 0.008], fill=(255, 238, 200, 255))
        else:
            td.rectangle([x, top, x + car_w, rail_y - h * 0.006], fill=(*TRAIN_COLOR, 255))
            ww = car_w / 7
            for k in range(3):
                wx = x + ww * (1 + k * 2)
                td.rectangle([wx, top + car_h * 0.25, wx + ww, top + car_h * 0.55], fill=(*WINDOW_COLOR, 230))
        x += car_w + gap
    window_glow = train.filter(ImageFilter.GaussianBlur(radius=h * 0.008))
    return composite(img, glow, layer, window_glow, train)


def add_crossing_lamps(img):
    """Two amber level-crossing lamps on posts either side of the road at the rail line."""
    w, h = img.size
    rail_y = h * HORIZON
    posts = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lamps = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dp, dl = ImageDraw.Draw(posts), ImageDraw.Draw(lamps)
    r = h * 0.011
    for xf in (0.43, 0.57):
        x, lamp_y = w * xf, rail_y - h * 0.085
        dp.rectangle([x - w * 0.002, rail_y - h * 0.08, x + w * 0.002, rail_y + h * 0.01], fill=(10, 10, 12, 255))
        dl.ellipse([x - r, lamp_y - r, x + r, lamp_y + r], fill=(*LAMP_COLOR, 255))
    return composite(img, posts, lamps.filter(ImageFilter.GaussianBlur(radius=h * 0.02)), lamps)


def add_road(img):
    """Road with a dashed centre line and the crossing lamps' amber reflections on the wet asphalt."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    road_top_y = int(h * 0.72)
    draw.polygon([(w * 0.30, h), (w * 0.70, h), (w * 0.56, road_top_y), (w * 0.44, road_top_y)], fill=(28, 30, 36))
    dash_w = w * 0.01
    for i in range(4):
        t0, t1 = i / 4, (i + 0.5) / 4
        y0, y1 = int(h - (h - road_top_y) * t0), int(h - (h - road_top_y) * t1)
        x0, x1 = w * 0.50 - dash_w * (1 - t0) * 0.5, w * 0.50 + dash_w * (1 - t0) * 0.5
        draw.rectangle([x0, y1, x1, y0], fill=(120, 110, 90))

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for xf in (0.465, 0.535):
        ld.rectangle([w * xf - w * 0.004, h * 0.74, w * xf + w * 0.004, h * 0.97], fill=(*RAIL_COLOR, 120))
    return composite(img, layer.filter(ImageFilter.GaussianBlur(radius=h * 0.012)))


def add_rain(img):
    """Faint slanted rain streaks over the whole scene (under the logo and text)."""
    w, h = img.size
    rng = random.Random(270)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(160):
        x, y = rng.uniform(0, w * 1.1), rng.uniform(h * 0.12, h)
        length = rng.uniform(h * 0.035, h * 0.07)
        draw.line([(x, y), (x - 0.25 * length, y + length)], fill=(*RAIN_COLOR, rng.randint(35, 80)), width=2)
    return composite(img, layer)


def paste_logo(img):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    target_h = int(img.height * 0.62)
    logo = logo.resize((int(logo.width * target_h / logo.height), target_h), Image.LANCZOS)
    pad = int(img.height * 0.06)
    pos = (pad, pad)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_logo = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    shadow_logo.putalpha(logo.split()[3].point(lambda a: a * 160 // 255))
    shadow.paste(shadow_logo, (pos[0] + 6, pos[1] + 6), shadow_logo)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    base = Image.alpha_composite(img.convert("RGBA"), shadow)
    base.paste(logo, pos, logo)
    return base.convert("RGB")


def fit_font(draw, text, font_path, max_width, start_size, min_size=10):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, min_size)


def draw_with_outline(draw, pos, text, font, fill, outline=(0, 0, 0), width=2):
    x, y = pos
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def add_text(img):
    draw = ImageDraw.Draw(img)
    w, h = img.size
    x_start = w * 0.40
    max_width = w * 0.97 - x_start
    title_lines = ["DriveDogs:", "World"]
    subtitle = "Graphics, Weather & Trains"

    title_size = int(h * 0.135)
    for line in title_lines:
        title_size = min(title_size, fit_font(draw, line, FONT_BOLD, max_width, title_size).size)
    title_font = ImageFont.truetype(FONT_BOLD, title_size)
    subtitle_font = fit_font(draw, subtitle, FONT_REG, max_width, int(h * 0.06))

    line_bbox = draw.textbbox((0, 0), "Ag", font=title_font)
    line_h = (line_bbox[3] - line_bbox[1]) * 1.15
    y = h * 0.44 - (line_h * len(title_lines) + line_h * 0.9) / 2
    for line in title_lines:
        draw_with_outline(draw, (x_start, y), line, title_font, TITLE_COLOR, width=3)
        y += line_h
    y += line_h * 0.15
    draw_with_outline(draw, (x_start, y), subtitle, subtitle_font, SUBTITLE_COLOR, width=2)
    return img


def add_version_badge(img, version):
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    text = f"v{version}"
    font = ImageFont.truetype(FONT_BOLD, int(h * 0.06))
    bbox = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = h * 0.02, h * 0.015
    x1, y0 = w - h * 0.03, h * 0.03
    x0 = x1 - (bbox[2] - bbox[0]) - 2 * pad_x
    y1 = y0 + (bbox[3] - bbox[1]) + 2 * pad_y
    draw.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=(*BADGE_COLOR, 235))
    draw.text((x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]), text, font=font, fill=BADGE_TEXT_COLOR)
    return img


def main():
    version = read_version()
    img = make_background(CANVAS_SIZE)
    img = add_stars(img)
    img = add_horizon_glow(img)
    img = add_storm(img)
    img = add_hills(img)
    img = add_trees(img)
    img = add_train(img)
    img = add_crossing_lamps(img)
    img = add_road(img)
    img = add_rain(img)
    img = paste_logo(img)
    img = add_text(img)
    img = add_version_badge(img, version)
    img = img.resize(FINAL_SIZE, Image.LANCZOS)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, "JPEG", quality=92)
    print(f"Wrote {OUT_PATH} ({img.size[0]}x{img.size[1]}, v{version})")


if __name__ == "__main__":
    main()
