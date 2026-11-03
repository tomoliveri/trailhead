#!/usr/bin/env python3
"""Raw simulator captures -> one transparent PNG per distinct screen: build/renders/<device>/s<k>.png."""
import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2] / 'build' / 'renders'
for dev in sys.argv[1:]:
    seen, n = set(), 0
    for f in sorted((ROOT / dev).glob('t*.png')):
        im = Image.open(f).convert('RGBA')
        w, h = im.size
        im = im.crop((6, 60, w - 6, h - 64))      # drop the 2x-scale title bar, status bar and window border
        flat = Image.new('RGBA', im.size, (255, 255, 255, 255))
        flat.alpha_composite(im)                   # the window's rounded corners are transparent: make them white
        im = flat
        key = hashlib.md5(im.resize((64, 64)).tobytes()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        # white backdrop -> transparent (flood from the corners only, so white text on the watch stays)
        mask = Image.new('L', im.size, 0)
        rgb = im.convert('RGB')
        for corner in ((8, 8), (im.width - 9, 8), (8, im.height - 9), (im.width - 9, im.height - 9)):
            ImageDraw.floodfill(rgb, corner, (255, 0, 255), thresh=18)
        px, mp = rgb.load(), mask.load()
        for y in range(im.height):
            for x in range(im.width):
                if px[x, y] == (255, 0, 255):
                    mp[x, y] = 255
        im.putalpha(Image.eval(mask, lambda v: 255 - v))
        bbox = im.getbbox()
        im = im.crop(bbox)
        im.save(ROOT / dev / f's{n}.png')
        n += 1
    print(dev, n, 'distinct screens')
