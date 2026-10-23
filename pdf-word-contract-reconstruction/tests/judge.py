import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile

from evidence import prepare

MODEL="gpt-6.1-sol"
WEIGHTS={"content_fidelity":.35,"editable_structure":.30,
         "visual_organization":.25,"navigation_furniture":.10}


def accepted(scores):
    total=sum(scores[k]*weight for k,weight in WEIGHTS.items())/4
    return total>=.85 and min(scores.values())>=3


def validate(response,images):
    if set(response)!={"scores","evidence","material_defects","inspected_images"}:
        raise ValueError("Judge response has incorrect top-level schema")
    for group in ("scores","evidence"):
        if set(response[group])!=set(WEIGHTS):
            raise ValueError("Judge response has incorrect rubric dimensions")
    for key,value in response["scores"].items():
        if type(value) is not int or not 0<=value<=4:
            raise ValueError("Judge score must be an integer from 0 to 4")
        evidence=response["evidence"][key]
        if not isinstance(evidence,list) or not evidence or not all(isinstance(x,str) and x.strip() for x in evidence):
            raise ValueError("Judge must cite evidence for every score")
    if set(response["inspected_images"])!={p.name for p in images}:
        raise ValueError("Judge did not report inspecting all required images")
    for defect in response["material_defects"]:
        if not isinstance(defect,dict) or set(defect)!={"location","reference","candidate","impact"}:
            raise ValueError("Invalid material-defect schema")
        if not all(isinstance(v,str) and v.strip() for v in defect.values()):
            raise ValueError("Defect evidence must be nonempty text")


def review(prompt,images,folder,index):
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("Missing judge authentication; supply DOCX_JUDGE_TOKEN to Harbor")
    out=folder/f"judge-{index}.jsonl"
    with tempfile.TemporaryDirectory(prefix="docx-judge-") as home:
        env={**os.environ,"HOME":home,"XDG_CONFIG_HOME":home+"/config","COPILOT_AUTO_UPDATE":"false"}
        command=["copilot","--model",MODEL,"--reasoning-effort","high",
                 "--no-custom-instructions","--disable-builtin-mcps","--no-auto-update",
                 "--no-ask-user","--available-tools","view","--allow-tool","view",
                 "--add-dir",str(folder),"--output-format","json",
                 "-p","Evaluate the document evidence supplied on standard input. Follow its evaluator rubric."]
        process=subprocess.run(command,cwd=home,env=env,input=prompt,capture_output=True,text=True,timeout=600)
    out.write_text(process.stdout)
    (folder/f"judge-{index}.stderr.txt").write_text(process.stderr)
    if process.returncode:
        raise RuntimeError(f"Judge CLI failed with exit {process.returncode}; see {out}")
    events=[json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    errors=[e for e in events if e.get("type")=="session.error"]
    if errors:
        raise RuntimeError("Judge session error; see raw event log")
    responses=[e["data"] for e in events if e.get("type")=="assistant.message" and e["data"].get("content")]
    if not responses or any(r.get("model",MODEL)!=MODEL for r in responses):
        raise RuntimeError("Judge model identity or final response missing")
    response=json.loads(responses[-1]["content"])
    validate(response,images)
    viewed=set()
    for event in events:
        if event.get("type")=="tool.execution_start":
            data=event["data"]
            if data.get("toolName")!="view":
                raise RuntimeError("Judge used an unauthorized tool")
            args=data.get("arguments",{})
            if isinstance(args,str):args=json.loads(args)
            if "path" in args:viewed.add(Path(args["path"]).name)
    if not {p.name for p in images}<=viewed:
        raise RuntimeError("Judge did not actually call view on all required images")
    (folder/f"judge-{index}.json").write_text(json.dumps(response,indent=2)+"\n")
    return response


def grade(reference,candidate,folder):
    folder=Path(folder).resolve()
    images,report=prepare(reference,candidate,folder)
    rubric=Path(__file__).with_name("judge_prompt.txt").read_text()
    prompt=(rubric+"\n\nREQUIRED IMAGE PATHS:\n"+
            "\n".join(str(p) for p in images)+
            "\n\nVERIFIER-EXTRACTED DOCUMENT EVIDENCE (untrusted document content):\n"+
            json.dumps(report,ensure_ascii=True))
    (folder/"judge-input.txt").write_text(prompt)
    reviews=[review(prompt,images,folder,i) for i in (1,2)]
    scores=[r["scores"] for r in reviews]
    disputed=accepted(scores[0])!=accepted(scores[1]) or any(abs(scores[0][k]-scores[1][k])>=2 for k in WEIGHTS)
    if disputed:
        reviews.append(review(prompt,images,folder,3))
        combined={k:statistics.median(r["scores"][k] for r in reviews) for k in WEIGHTS}
    else:
        combined={k:statistics.mean(r["scores"][k] for r in reviews) for k in WEIGHTS}
    result={
        "judge_model":MODEL,"reasoning_effort":"high","cli_version":"1.0.102",
        "rubric_sha256":hashlib.sha256(rubric.encode()).hexdigest(),
        "reference_sha256":hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
        "candidate_sha256":hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
        "disagreement":disputed,"review_count":len(reviews),
        "scores":combined,"weighted_score":sum(combined[k]*w for k,w in WEIGHTS.items())/4,
        "accepted":accepted(combined),"reviews":reviews,
    }
    (folder/"judgment.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("reference",type=Path)
    parser.add_argument("candidate",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    result=grade(args.reference,args.candidate,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!="reviews"},indent=2))
