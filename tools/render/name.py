#!/usr/bin/env python3
"""Name each device's 8 distinct screens. The demo cycles screens in a fixed order, so captures are a rotation of it;
pick the rotation whose watch faces best match the reference device's (checked by eye; REF_ORDER maps its s0..s7)."""
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

NAMES = ['home', 'session', 'week', 'hud', 'pacer', 'zones', 'turn', 'pair']   # DemoView shot order
REF, REF_START = 'fr265', 3       # fr265 s0 is shot 3 (hud)
OVERRIDE = {d: 3 for d in ('fr265', 'fr165', 'vivoactive5', 'fenix7', 'fr255s')}   # checked by eye on the contact sheet (s0 = hud)
ROOT = Path(__file__).resolve().parents[2] / 'build' / 'renders'


def face(p):
    im = Image.open(p).convert('L')
    w, h = im.size
    side = min(w, h) * 0.42
    c = im.crop((int(w / 2 - side / 2), int(h / 2 - side / 2), int(w / 2 + side / 2), int(h / 2 + side / 2)))
    a = np.asarray(c.resize((48, 48)), float)
    return (a - a.mean()) / (a.std() + 1e-6)


ref = [face(ROOT / REF / f's{(k - REF_START) % 8}.png') for k in range(8)]   # ref[k] = shot k
for dev in sys.argv[1:]:
    f = [face(ROOT / dev / f's{i}.png') for i in range(8)]
    best = OVERRIDE.get(dev) if dev in OVERRIDE else max(range(8), key=lambda r: sum((f[i] * ref[(i + r) % 8]).mean() for i in range(8)))
    for i in range(8):
        shutil.copy(ROOT / dev / f's{i}.png', ROOT / dev / f'{NAMES[(i + best) % 8]}.png')
    print(dev, 's0 is', NAMES[best])
