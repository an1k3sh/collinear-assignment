"""Author QA: recover segment counts from pixels and manually read row totals."""
import json
from pathlib import Path
import sys
import os
import shutil
import subprocess
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))
from grade import extraction
from reference import intervals_from_truth

TOTALS = {
    "H1.r1":[1000,1000,1000,1000,2000,2000,2000,2000],
    "H2.r1":[1000,2000,1500,3000,1000,2000,1500,4000],
    "H3.r1":[1000,1000,1000,10000,1000,1200,1400,2000],
    "H4.r1":[1000,2000,1500,2000,2000,1000,2000,2000],
}
COLORS = [(35,105,158),(83,166,166),(219,140,34),(168,60,85)]


def main():
    app = ROOT/"environment/app"
    manifest = json.loads((app/"export-manifest.json").read_text())
    operations = json.loads((app/"operations.json").read_text())
    truth = json.loads((ROOT/"tests/truth.json").read_text())
    readings = intervals_from_truth(truth)
    estimates = {}
    for page in manifest["pages"]:
        if page["kind"] != "histograms":
            continue
        image = Image.open(app/"report"/page["file"]).convert("RGB")
        rows = []
        for y in range(image.height):
            counts = [0]*4
            for x in range(image.width):
                pixel = image.getpixel((x,y))
                if pixel in COLORS:
                    counts[COLORS.index(pixel)] += 1
            if sum(counts) > 1000:
                if not rows or y != rows[-1][-1]+1:
                    rows.append([])
                rows[-1].append(y)
        assert len(rows) == 8
        for i,ys in enumerate(rows):
            y = ys[len(ys)//2]
            counts = [0]*4
            for x in range(image.width):
                pixel = image.getpixel((x,y))
                if pixel in COLORS:
                    counts[COLORS.index(pixel)] += 1
            n = TOTALS[page["id"]][i]
            estimates[page["id"],page["targets"][i//4],f"W{i%4+1}"] = [v/sum(counts)*n for v in counts]
    maximum_error = 0
    for row,exact in zip(readings["histograms"],truth["histograms"]):
        key = row["page"],row["target"],row["window"]
        radius = max(20,.005*sum(exact["bins"]))/4
        row["bins"] = [[max(0,v-radius),v,v+radius] for v in estimates[key]]
        maximum_error = max(maximum_error,max(abs(a-b) for a,b in zip(estimates[key],exact["bins"])))
    checks,missing = extraction(readings,truth,manifest,operations)
    assert all(checks) and missing
    output = Path(sys.argv[1])
    output.mkdir(parents=True,exist_ok=True)
    (output/"raster-readings.json").write_text(json.dumps(readings,indent=2)+"\n")
    report = {"histogram_bins":128,"accepted_observations":sum(checks),
              "total_observations":len(checks),"maximum_count_error":maximum_error,
              "interval_width_fraction_of_allowance":.5}
    (output/"raster-check.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
    with tempfile.TemporaryDirectory(prefix="chart-v5-raster-") as temp:
        work = Path(temp)/"app"
        shutil.copytree(app,work)
        sub = work/"submission"
        shutil.copytree(ROOT/"solution",sub)
        (sub/"readings.json").write_text(json.dumps(readings))
        command = [sys.executable,str(sub/"analyze.py")]
        for key,name in (("readings","submission/readings.json"),("manifest","export-manifest.json"),
                         ("operations","operations.json"),("planning","planning.json"),
                         ("registry","registry.csv"),("out","submission/analysis.json")):
            command.extend(["--"+key,str(work/name)])
        subprocess.run(command,check=True,timeout=90)
        subprocess.run([sys.executable,str(ROOT/"tests/grade.py")],check=True,timeout=1800,
                       env=dict(os.environ,APP_ROOT=str(work),VERIFIER_LOG=str(output.resolve()/"raster-full")))


if __name__ == "__main__":
    main()
