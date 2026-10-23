"""Original author data and renderer; never copied into the agent environment."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/"environment/app"
ERRORS = {
    "AS":[1000,2000,3000,4000], "AI":[400,600,800,1000],
    "BS":[3000,6000,4000,7000], "BI":[2500,4500,3500,5500],
    "CS":[700,900,800,1000], "CI":[4500,5500,6500,7500],
    "DS":[2000,3000,4000,5000], "DI":[1500,9000,1800,2200]}
HIST = {
    "AS":[[600,250,100,50],[500,300,150,50],[500,350,100,50],[550,250,150,50]],
    "AI":[[1400,560,30,10]]*4,
    "BS":[[500,300,150,50],[1000,500,350,150],[700,400,300,100],[1400,800,600,200]],
    "BI":[[600,200,150,50],[900,600,300,200],[800,400,250,50],[1800,1000,900,300]],
    "CS":[[600,300,80,20]]*3+[[7000,2990,10,0]],
    "CI":[[500,300,150,50],[600,300,200,100],[700,300,250,150],[900,500,400,200]],
    "DS":[[600,250,100,50],[600,200,1000,200],[800,300,300,100],[1200,500,200,100]],
    "DI":[[1400,560,30,10],[100,100,600,200],[1400,560,30,10],[1400,560,30,10]]}


def save(fig, path):
    fig.savefig(path, dpi=120, facecolor="white")
    plt.close(fig)
    with Image.open(path) as image:
        Image.fromarray(np.asarray(image.convert("RGB"))).save(path)


def main():
    manifest = json.loads((APP/"export-manifest.json").read_text())
    operations = json.loads((APP/"operations.json").read_text())
    registry = {r["target"]:r for r in csv.DictReader((APP/"registry.csv").open())}
    resets = {(r["target"],r["window"],r["metric"]):r["baseline"] for r in operations["resets"]}
    readings = {"units":"base-counts","counters":[],"histograms":[]}
    counters = {}
    for index, target in enumerate(ERRORS):
        for metric in ("requests","errors"):
            value = 500000 + index*70000 if metric == "requests" else 20000+index*3000
            levels = [value]
            for i in range(4):
                value = resets.get((target,f"W{i+1}",metric),value)
                delta = (100000+index*20000)*(1 if i%2 == 0 else 2) if metric == "requests" else ERRORS[target][i]
                value += delta
                levels.append(value)
            if target == "DS":
                levels[2] = None
            counters[target,metric] = levels
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":13,"axes.titlesize":16})
    report = APP/"report"
    report.mkdir(exist_ok=True)
    for page in manifest["pages"]:
        if page["kind"] == "counters":
            fig, axes = plt.subplots(2,2,figsize=(16,10),layout="constrained")
            for row,target in enumerate(page["targets"]):
                for col,metric in enumerate(("requests","errors")):
                    values = list(counters[target,metric])
                    if page["id"] == "C2.r1" and metric == "errors":
                        values = [v+2000*i for i,v in enumerate(values)]
                    ax = axes[row,col]
                    shown = [np.nan if v is None else v/1000 for v in values]
                    ax.plot(range(5),shown,"o-",color="#1c5a92" if col == 0 else "#a64b18",lw=2,ms=8)
                    for i,v in enumerate(shown):
                        if np.isnan(v):
                            ax.text(i,.45,"UNKNOWN",transform=ax.get_xaxis_transform(),ha="center",
                                    bbox={"facecolor":"#eee","edgecolor":"#888"})
                        else:
                            ax.annotate(f"{v:g}",(i,v),xytext=(0,12),textcoords="offset points",
                                        ha="center",fontsize=13)
                    ax.set_title(registry[target]["display_name"]+" | "+metric)
                    ax.set_ylabel(f"Cumulative {metric} (thousands)")
                    ax.set_xticks(range(5),["B0\n08:00","B1\n08:30","B2\n09:30","B3\n10:00","B4\n11:00"])
                    ax.set_ylim(bottom=0,top=max(v for v in shown if not np.isnan(v))*1.22)
                    ax.grid(alpha=.25)
                for i in range(5):
                    readings["counters"].append({"page":page["id"],"target":target,"boundary":f"B{i}",
                        **{m:(None if counters[target,m][i] is None else
                             counters[target,m][i]+(2000*i if page["id"]=="C2.r1" and m=="errors" else 0))
                           for m in ("requests","errors")}})
            fig.suptitle(f"{page['id']} | Exported counter levels\n21 September 2026 | UTC | labels in thousands",
                         fontsize=22)
            fig.supxlabel("Boundary samples are old-epoch final readings; consult operations log for subsequent resets.")
        else:
            fig, axes = plt.subplots(2,1,figsize=(16,11),layout="constrained")
            colors = ["#23699e","#53a6a6","#db8c22","#a83c55"]
            labels = ["<=100 ms","(100,300] ms","(300,1000] ms",">1000 ms"]
            for ax,target in zip(axes,page["targets"]):
                for b in range(4):
                    x = np.arange(4)+(b-1.5)*.2
                    vals = [row[b] for row in HIST[target]]
                    bars = ax.bar(x,vals,.18,color=colors[b],label=labels[b])
                    ax.bar_label(bars,padding=4,fontsize=12,rotation=90)
                ax.set_xticks(range(4),["W1\n08:00-08:30","W2\n08:30-09:30","W3\n09:30-10:00","W4\n10:00-11:00"])
                ax.set_ylim(0,max(max(row) for row in HIST[target])*1.28)
                ax.set_ylabel("Sampled request count (not thousands)")
                ax.set_title(registry[target]["display_name"])
                ax.grid(axis="y",alpha=.2)
                ax.set_axisbelow(True)
                ax.legend(loc="upper left",ncol=4,fontsize=11)
                for i,row in enumerate(HIST[target]):
                    readings["histograms"].append({"page":page["id"],"target":target,"window":f"W{i+1}","bins":row})
            fig.suptitle(f"{page['id']} | Disjoint latency-bin counts\n21 September 2026 | UTC | labelled sample counts",
                         fontsize=22)
            fig.supxlabel("Sampling volumes differ across windows. Pool counts, not percentages or percentiles.")
        save(fig,report/page["file"])
    (ROOT/"tests").mkdir(exist_ok=True)
    (ROOT/"tests/truth.json").write_text(json.dumps(readings,indent=2)+"\n")
    links = "\n".join(f'<a href="#{p["id"]}">{p["id"]}</a>' for p in manifest["pages"])
    figures = "\n".join(f'<figure id="{p["id"]}"><img src="{p["file"]}" alt="{p["id"]}: {p["kind"]} chart"><figcaption>{p["id"]} - {p["kind"]}</figcaption></figure>' for p in manifest["pages"])
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Rollout evidence packet</title>'
            '<style>body{font:18px system-ui;margin:24px;color:#172332}nav{position:sticky;top:0;background:white;padding:16px;z-index:2}'
            'a,button{margin-right:14px;font-size:18px}figure{margin:30px 0;overflow:auto}img{width:100%;height:auto}'
            'body.zoom img{width:1920px;max-width:none}</style>'
            '<h1>Rollout evidence packet</h1><p>Consult the export manifest and corrections before selecting authoritative pages.</p>'
            f'<nav>{links}<button onclick="document.body.classList.toggle(\'zoom\')">Toggle full-resolution zoom</button></nav>{figures}</html>')
    (report/"index.html").write_text(html)


if __name__ == "__main__":
    main()
