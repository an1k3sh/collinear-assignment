import numpy as np
from PIL import Image

def glyphs(crop, dark):
    c = crop.astype(int)
    if dark:
        ink = c.mean(2) < 150
    else:
        ink = (c[:, :, 2] - c[:, :, 0] >= 40) & (c.mean(2) < 200)
    cols = ink.any(0)
    out = []
    x = 0
    n = len(cols)
    while x < n:
        if cols[x]:
            s = x
            while x < n and cols[x]:
                x += 1
            g = ink[:, s:x]
            rows = np.where(g.any(1))[0]
            g = g[rows.min():rows.max() + 1]
            out.append(g)
        else:
            x += 1
    return out

def norm(g):
    h, w = g.shape
    im = Image.fromarray((g * 255).astype(np.uint8)).resize((12, 18), Image.BILINEAR)
    return np.array(im).astype(float) / 255, (h, w)


class TemplateOCR:
    def __init__(self, path):
        import json
        self.T = [(t['char'], t['dark'], np.array(t['v'])) for t in json.load(open(path))]
        self.worst_margin = 1e9

    def __call__(self, crop, dark):
        s = ''
        for g in glyphs(crop, dark):
            v, _ = norm(g)
            ds = sorted((np.abs(tv - v).mean(), ch) for ch, td, tv in self.T if td == dark)
            self.worst_margin = min(self.worst_margin, ds[1][0] - ds[0][0])
            if ds[0][0] > 0.08:
                raise ValueError('unrecognised glyph (distance %.3f)' % ds[0][0])
            s += ds[0][1]
        return s
