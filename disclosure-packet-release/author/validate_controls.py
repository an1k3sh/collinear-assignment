from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import fitz
import pikepdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))
from check_packet import Packet,attachments

BASE=Path(sys.argv[1])
results=[]


def rewrite(path,edit):
    other=path.with_suffix(".new.pdf")
    with pikepdf.open(path) as pdf:
        edit(pdf)
        pdf.save(other)
    other.replace(path)


def fitz_edit(path,edit):
    other=path.with_suffix(".new.pdf")
    with fitz.open(path) as pdf:
        edit(pdf)
        pdf.save(other,garbage=4,deflate=True)
    other.replace(path)


def workbook(path,part,edit):
    files,_=attachments(path)
    output=BytesIO()
    with ZipFile(BytesIO(files["statement.xlsx"])) as source,ZipFile(output,"w") as target:
        for info in source.infolist():
            data=source.read(info.filename)
            if info.filename==part:
                root=ET.fromstring(data)
                edit(root)
                data=ET.tostring(root,encoding="utf-8",xml_declaration=True)
            target.writestr(info,data)
    def replace(pdf):
        names=pdf.Root.Names.EmbeddedFiles.Names
        for i in range(0,len(names),2):
            if str(names[i])=="statement.xlsx":
                stream=names[i+1].EF.F
                stream.write(output.getvalue())
                stream.Params.Size=len(output.getvalue())
                return
        raise AssertionError("Missing workbook control source")
    rewrite(path,replace)


def run(name,edit,method=None,valid=False):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"release.pdf"
        shutil.copyfile(BASE,path)
        edit(path)
        packet=Packet(ROOT/"environment/app",path)
        checks=[method] if method else ["privacy","document","navigation","supporting","recalculation"]
        error=None
        try:
            for check in checks:
                getattr(packet,check)()
        except AssertionError as exc:
            error=str(exc)
        matched=(error is None)==valid
        results.append(dict(name=name,expected_valid=valid,correctly_classified=matched,error=error))
        assert matched,results[-1]


run("oracle",lambda path:None,valid=True)


def recompress(path):
    other=path.with_suffix(".new.pdf")
    with pikepdf.open(path) as pdf:
        pdf.save(other,linearize=True,compress_streams=False)
    other.replace(path)


run("valid-linearized-uncompressed",recompress,valid=True)
run("original-private-packet",lambda path:shutil.copyfile(ROOT/"environment/app/input/packet.pdf",path),"privacy")
run("private-document-info",lambda path:rewrite(path,lambda pdf:pdf.docinfo.__setitem__("/Author","Arden Vale")),"privacy")
run("off-page-private-text",lambda path:fitz_edit(path,lambda pdf:pdf[1].insert_text((-900,-120),"Arden Vale")),"privacy")


def private_page_file(path):
    files,_=attachments(ROOT/"environment/app/input/packet.pdf")
    def change(pdf):
        page=pdf[2]
        for annot in page.annots():
            if annot.type[0]==fitz.PDF_ANNOT_FILE_ATTACHMENT:
                annot.update_file(buffer_=files[annot.file_info["filename"]])
                return
        raise AssertionError("Missing control source annotation")
    fitz_edit(path,change)


run("private-page-associated-file",private_page_file,"privacy")
run("private-workbook-properties",lambda path:workbook(path,"docProps/core.xml",lambda root:
    setattr(root.find("{http://purl.org/dc/elements/1.1/}creator"),"text","Arden Vale")),"privacy")


def fixed_total(root):
    cell=root.find(".//{*}c[@r='C6']")
    cell.find("{*}f").text="1387.4"


run("cached-but-nonrecalculating-total",lambda path:workbook(path,"xl/worksheets/sheet1.xml",fixed_total),"recalculation")
run("lost-document-attachment",lambda path:fitz_edit(path,lambda pdf:pdf.embfile_del("transactions.csv")),"navigation")


def lost_page_attachment(pdf):
    page=pdf[2]
    annot=next(a for a in page.annots() if a.type[0]==fitz.PDF_ANNOT_FILE_ATTACHMENT)
    page.delete_annot(annot)


run("lost-page-attachment",lambda path:fitz_edit(path,lost_page_attachment),"navigation")
run("removed-public-diagram",lambda path:fitz_edit(path,lambda pdf:
    pdf[1].draw_rect(fitz.Rect(155,225,455,260),color=None,fill=(1,1,1))),"document")


def old_revision(path):
    fitz_edit(path,lambda pdf:pdf[1].insert_text((-900,-120),"Arden Vale"))
    with fitz.open(path) as pdf:
        pdf.update_stream(pdf[1].get_contents()[-1],b"")
        pdf.saveIncr()
    with fitz.open(path) as pdf:
        assert "Arden Vale" not in pdf[1].get_text(clip=fitz.INFINITE_RECT()), "Invalid control: current text remains"


run("private-text-in-prior-revision",old_revision,"privacy")
output=ROOT/"evidence"
output.mkdir(exist_ok=True)
(output/"control-validation.json").write_text(json.dumps(results,indent=2)+"\n")
print(json.dumps(results,indent=2))
