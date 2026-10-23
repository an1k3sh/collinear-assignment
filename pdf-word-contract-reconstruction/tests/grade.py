import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import traceback
from zipfile import BadZipFile

from lxml.etree import XMLSyntaxError

from evidence import pdf_text,render,structure
from judge import grade,WEIGHTS

ROOT=Path("/app")
LOG=Path("/logs/verifier")
OUTPUT=ROOT/"submission"


def main():
    LOG.mkdir(parents=True,exist_ok=True)
    for name,sha in json.loads(Path("/tests/protected.json").read_text()).items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:
            raise AssertionError("Protected source modified: "+name)
    for name in ("agreement.docx","rebuild.py","verification.md"):
        if not (OUTPUT/name).is_file() or not (OUTPUT/name).stat().st_size:
            raise AssertionError("Missing deliverable: "+name)
    candidate=LOG/"submitted.docx"
    shutil.copyfile(OUTPUT/"agreement.docx",candidate)
    try:
        submitted_structure=structure(candidate)
    except (BadZipFile,KeyError,XMLSyntaxError) as exc:
        raise AssertionError("Submitted file is not a readable Word document") from exc
    submitted_pdf=render(candidate,LOG/"submitted-render")
    (OUTPUT/"agreement.docx").unlink()
    try:
        try:
            result=subprocess.run(["python",str(OUTPUT/"rebuild.py")],cwd=OUTPUT,
                                  capture_output=True,text=True,timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("Rebuild exceeded the published 180-second limit") from exc
        (LOG/"rebuild.txt").write_text(result.stdout+"\n"+result.stderr)
        if result.returncode or not (OUTPUT/"agreement.docx").exists():
            raise AssertionError("Rebuild did not recreate agreement.docx; see rebuild.txt")
        rebuilt=LOG/"rebuilt.docx"
        shutil.copyfile(OUTPUT/"agreement.docx",rebuilt)
        rebuilt_pdf=render(rebuilt,LOG/"rebuilt-render")
        rebuilt_structure=structure(rebuilt)
        before=" ".join(" ".join(p["text"].split()) for p in pdf_text(submitted_pdf))
        after=" ".join(" ".join(p["text"].split()) for p in pdf_text(rebuilt_pdf))
        before_tables=[item["rows"] for item in submitted_structure["body"] if item["type"]=="table"]
        after_tables=[item["rows"] for item in rebuilt_structure["body"] if item["type"]=="table"]
        if before!=after or before_tables!=after_tables:
            raise AssertionError("Rebuild changed document content/structure/rendered text")
    finally:
        shutil.copyfile(candidate,OUTPUT/"agreement.docx")
    judgment=grade("/tests/reference/original.docx",candidate,LOG/"judge")
    reward={key:judgment["scores"][key]/4 for key in WEIGHTS}
    reward.update(artifact_validity=1.0,weighted_quality=judgment["weighted_score"],
                  overall=float(judgment["accepted"]))
    (LOG/"reward.json").write_text(json.dumps(reward,indent=2)+"\n")
    (LOG/"status.json").write_text(json.dumps({"status":"graded","judge_reviews":judgment["review_count"]},indent=2)+"\n")
    print(json.dumps(reward,indent=2))


if __name__=="__main__":
    try:
        main()
    except AssertionError:
        LOG.mkdir(parents=True,exist_ok=True)
        (LOG/"status.json").write_text(json.dumps({"status":"artifact_failure","error":traceback.format_exc()},indent=2))
        (LOG/"reward.json").write_text('{"overall":0.0,"artifact_validity":0.0}\n')
        raise
    except Exception:
        LOG.mkdir(parents=True,exist_ok=True)
        (LOG/"status.json").write_text(json.dumps({"status":"infrastructure_error","error":traceback.format_exc()},indent=2))
        # No reward is emitted: model/provider/renderer faults are not candidate failures.
        raise
