#!/usr/bin/env python3
"""Pixel-level wire tracer for the Meridian as-built drawings.

Wires are crisp 5 px axis-aligned strokes of a single colour. The tracer
extracts horizontal and vertical stroke segments, joins them only where a
segment END meets another segment END (right-angle bend) or where a
collinear gap is bridged by a printed cable label, and terminates a chain
where a segment end touches a node box. Crossings (interior/interior) are
never joined. Text (box names and cable labels) is read with a small
glyph-template OCR whose templates are stored in glyph_templates.json.
"""
import json, sys, os
import numpy as np
from PIL import Image

WIRE = (32, 49, 62)


def runs_1d(row, minlen):
    p = np.concatenate(([0], row.astype(np.int8), [0]))
    d = np.diff(p)
    s = np.where(d == 1)[0]
    e = np.where(d == -1)[0]
    return [(a, b - 1) for a, b in zip(s, e) if b - a >= minlen]


def segments(M, minlen=12):
    """Return list of (c, lo, hi, t0, t1) for horizontal strokes of mask M
    (c = centre row, lo/hi = column extent, t0/t1 = row extent)."""
    parent = {}
    rowruns = []
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    prev = []
    for y in range(M.shape[0]):
        cur = []
        for (a, b) in runs_1d(M[y], minlen):
            key = (y, a, b)
            parent[key] = key
            for (py, pa, pb) in prev:
                if abs(pa - a) <= 2 and abs(pb - b) <= 2:
                    parent[find(key)] = find((py, pa, pb))
            cur.append(key)
        prev = cur
    groups = {}
    for k in parent:
        groups.setdefault(find(k), []).append(k)
    out = []
    for g in groups.values():
        ys = [k[0] for k in g]
        lo = min(k[1] for k in g); hi = max(k[2] for k in g)
        out.append(((min(ys) + max(ys)) / 2, lo, hi, min(ys), max(ys)))
    return out


def find_boxes(im):
    K = (im == 0).all(2)
    hs = [s for s in segments(K, 120)]
    boxes = []
    # pair top and bottom edges with same x extent
    hs.sort(key=lambda s: (s[1], s[0]))
    used = set()
    for i, a in enumerate(hs):
        if i in used:
            continue
        for j, b in enumerate(hs):
            if j <= i or j in used:
                continue
            if abs(a[1] - b[1]) <= 3 and abs(a[2] - b[2]) <= 3 and b[0] - a[0] > 60:
                x0, x1, y0, y1 = a[1], a[2], a[3], b[4]
                if K[y0:y1, x0:x0 + 3].mean() > 0.9:
                    boxes.append((x0, y0, x1, y1))
                    used.update({i, j})
                    break
    return boxes


def trace_sheet(path, ocr):
    im = np.array(Image.open(path).convert('RGB')).astype(int)
    W = (im == WIRE).all(2)
    H = segments(W)
    V = [(c, lo, hi, t0, t1) for (c, lo, hi, t0, t1) in segments(W.T)]
    boxes = find_boxes(im)
    blue = (im[:, :, 2] - im[:, :, 0] >= 40)
    names = {}
    for bx in boxes:
        x0, y0, x1, y1 = bx
        names[bx] = ocr(im[y0 + 6:y1 - 5, x0 + 6:x1 - 5], dark=True)

    # endpoints: (kind, idx, end) -> point
    ends = []
    for i, (y, lo, hi, _, _) in enumerate(H):
        ends.append((('H', i, 0), (lo, y)))
        ends.append((('H', i, 1), (hi, y)))
    for i, (x, lo, hi, _, _) in enumerate(V):
        ends.append((('V', i, 0), (x, lo)))
        ends.append((('V', i, 1), (x, hi)))
    links = {}
    problems = []
    def add(a, b, info=None):
        links.setdefault(a, []).append((b, info))
        links.setdefault(b, []).append((a, info))
    # corners: H end meets V end
    for (ka, pa) in ends:
        if ka[0] != 'H':
            continue
        for (kb, pb) in ends:
            if kb[0] != 'V':
                continue
            if abs(pa[0] - pb[0]) <= 4 and abs(pa[1] - pb[1]) <= 4:
                add(ka, kb)
    # label gaps between collinear H segments
    labels = []
    for i, a in enumerate(H):
        for j, b in enumerate(H):
            if i == j or abs(a[0] - b[0]) > 1 or not (a[2] < b[1]):
                continue
            gap = b[1] - a[2]
            if gap > 200:
                continue
            yc = int(a[0])
            reg = blue[yc - 20:yc + 21, a[2] + 1:b[1]]
            if reg.sum() > 20:
                ys, xs = np.where(reg)
                crop = im[yc - 20 + ys.min():yc - 20 + ys.max() + 1,
                          a[2] + 1 + xs.min():a[2] + 1 + xs.max() + 1]
                text = ocr(crop, dark=False)
                add(('H', i, 1), ('H', j, 0), text)
                labels.append((text, (a[2] + b[1]) // 2, yc))
                blue[yc - 20:yc + 21, a[2] + 1:b[1]] = False
    # box terminations
    term = {}
    for (k, p) in ends:
        for bx in boxes:
            x0, y0, x1, y1 = bx
            if y0 - 2 <= p[1] <= y1 + 2 and (abs(p[0] - x0) <= 6 or abs(p[0] - x1) <= 6) and k[0] == 'H':
                term[k] = names[bx]
            if x0 - 2 <= p[0] <= x1 + 2 and (abs(p[1] - y0) <= 6 or abs(p[1] - y1) <= 6) and k[0] == 'V':
                term[k] = names[bx]
    for (k, p) in ends:
        n = len(links.get(k, [])) + (1 if k in term else 0)
        if n != 1:
            problems.append(('endpoint degree %d' % n, k, p))
    # walk chains
    seen = set()
    cables = []
    for (k, p) in ends:
        if k not in term or k in seen:
            continue
        chain_labels = []
        cur = k
        while True:
            seen.add(cur)
            other = (cur[0], cur[1], 1 - cur[2])
            seen.add(other)
            if other in term:
                break
            nxt = links.get(other, [])
            if len(nxt) != 1:
                problems.append(('dangling', other))
                break
            nk, info = nxt[0]
            if info:
                chain_labels.append(info)
            cur = nk
        cables.append({'a': term[k], 'b': term[other], 'labels': chain_labels})
    # every blue (label) pixel must have been consumed by an in-line label gap
    if blue.sum() > 0:
        problems.append(('unassigned label ink pixels', int(blue.sum())))
    return {'boxes': [(names[b], b) for b in boxes], 'cables': cables,
            'problems': problems, 'labels': labels, 'nH': len(H), 'nV': len(V)}


def main():
    import argparse, csv
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='/app')
    ap.add_argument('--output', default='/app/submission/topology.json')
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    from ocr_lib import TemplateOCR
    ocr = TemplateOCR(os.path.join(here, 'glyph_templates.json'))
    nodes = {r['node']: r['room'] for r in csv.DictReader(open(os.path.join(args.root, 'data/nodes.csv')))}
    inv = {r['cable'] for r in csv.DictReader(open(os.path.join(args.root, 'data/cable_versions.csv')))}
    links, errors = [], []
    for reg in csv.DictReader(open(os.path.join(args.root, 'data/drawing_register.csv'))):
        r = trace_sheet(os.path.join(args.root, reg['file']), ocr)
        errors += [(reg['sheet'],) + tuple(p) for p in r['problems']]
        for name, bx in r['boxes']:
            if name not in nodes:
                errors.append((reg['sheet'], 'unknown node box', name))
        for c in r['cables']:
            if len(c['labels']) != 1:
                errors.append((reg['sheet'], 'cable chain with labels', c))
                continue
            ra, rb = nodes.get(c['a']), nodes.get(c['b'])
            backbone = reg['sheet'].startswith('spine')
            if c['a'] == c['b'] or (ra == rb) == backbone:
                errors.append((reg['sheet'], 'room rule violated', c))
            links.append({'cable': c['labels'][0], 'a': c['a'], 'b': c['b'], 'sheet': reg['sheet']})
    ids = [l['cable'] for l in links]
    if len(set(ids)) != len(ids):
        errors.append(('duplicate cable labels',))
    if set(ids) != inv:
        errors.append(('inventory mismatch', sorted(inv - set(ids)), sorted(set(ids) - inv)))
    print('cables traced:', len(links), ' worst OCR margin: %.3f' % ocr.worst_margin)
    for e in errors:
        print('ERROR', e)
    links.sort(key=lambda l: l['cable'])
    with open(args.output, 'w') as f:
        json.dump({'links': links}, f, indent=1)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
