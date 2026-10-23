import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.set_int_max_str_digits(0)
mode=sys.argv[1]
sys.path.insert(0,"/solution")

if mode=="durable":
    from stockroom.durable import Machine
    mapping={"$fault":{"$fault":17,"$token":23},"$token":[True,None,"scalar"]}
    assert Machine.decode(Machine.encode(mapping))==mapping

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    inventory=root/"inventory.json"
    huge=10**5000
    inventory.write_text(json.dumps({"warehouses":{"$fault":{"$fault":huge,"$token":1}}}))
    program=root/"test.stock"
    program.write_text('proc main(){'+('pause "checkpoint";' if mode=="durable" else '')+'}')
    output=root/"result.json"
    command=[sys.executable,"-m","stockroom",str(program),
             "--inventory",str(inventory),"--out",str(output)]
    if mode=="durable":
        checkpoint=root/"checkpoint.json"
        command.extend(["--checkpoint",str(checkpoint)])
    first=subprocess.run(command,cwd="/solution",capture_output=True,text=True,timeout=20)
    assert first.returncode==(10 if mode=="durable" else 0),(first.returncode,first.stderr)
    if mode=="durable":
        second=subprocess.run(command+["--resume",str(checkpoint)],cwd="/solution",
                              capture_output=True,text=True,timeout=20)
        assert second.returncode==0,(second.returncode,second.stderr)
    assert json.loads(output.read_text())["warehouses"]["$fault"]["$fault"]==huge
print(json.dumps({"mode":mode,"huge_integer_cli":True,
                  "typed_mapping_roundtrip":mode=="durable",
                  "fresh_process_resume":mode=="durable"}))
