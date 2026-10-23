from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
import fitz
from PIL import Image, ImageDraw

NS={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def render(source,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        process=subprocess.run(
            ["libreoffice","-env:UserInstallation="+Path(profile).as_uri(),
             "--headless","--convert-to","pdf","--outdir",str(output),str(source)],
            capture_output=True,text=True,timeout=120)
    target=output/(Path(source).stem+".pdf")
    if process.returncode or not target.exists():
        raise RuntimeError("LibreOffice conversion failed: "+process.stdout+process.stderr)
    with fitz.open(target) as pdf:
        if not 1<=len(pdf)<=40:
            raise ValueError("Document must render to 1-40 readable pages")
    return target


def structure(path):
    with ZipFile(path) as archive:
        root=etree.fromstring(archive.read("word/document.xml"))
        styles=etree.fromstring(archive.read("word/styles.xml"))
        style_info={}
        for style in styles:
            id_=style.get(qn("w:styleId"))
            style_info[id_]={
                "name":style.xpath("string(w:name/@w:val)",namespaces=NS),
                "based_on":style.xpath("string(w:basedOn/@w:val)",namespaces=NS),
                "outline":style.xpath("string(w:pPr/w:outlineLvl/@w:val)",namespaces=NS),
                "numbering":style.xpath("string(w:pPr/w:numPr/w:numId/@w:val)",namespaces=NS),
            }
        body=[]
        for node in root.find("w:body",NS):
            if node.tag==qn("w:p"):
                text="".join(node.xpath(".//w:t/text()",namespaces=NS))
                body.append({
                    "type":"paragraph","text":text,
                    "style":node.xpath("string(w:pPr/w:pStyle/@w:val)",namespaces=NS),
                    "numbering_id":node.xpath("string(w:pPr/w:numPr/w:numId/@w:val)",namespaces=NS),
                    "numbering_level":node.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)",namespaces=NS),
                    "footnote_refs":node.xpath(".//w:footnoteReference/@w:id",namespaces=NS),
                    "drawings":len(node.xpath(".//w:drawing|.//w:pict",namespaces=NS)),
                })
            elif node.tag==qn("w:tbl"):
                rows=[]
                for row in node.findall("w:tr",NS):
                    cells=[]
                    for cell in row.findall("w:tc",NS):
                        cells.append({
                            "text":"\n".join("".join(p.xpath(".//w:t/text()",namespaces=NS))
                                             for p in cell.findall("w:p",NS)),
                            "span":cell.xpath("string(w:tcPr/w:gridSpan/@w:val)",namespaces=NS) or "1",
                            "vertical_merge":cell.xpath("string(w:tcPr/w:vMerge/@w:val)",namespaces=NS)
                                if cell.find("w:tcPr/w:vMerge",NS) is not None else None,
                        })
                    rows.append({"repeat_header":row.find("w:trPr/w:tblHeader",NS) is not None,"cells":cells})
                body.append({"type":"table","rows":rows})
        furniture={}
        for name in archive.namelist():
            if name.startswith(("word/header","word/footer")) and name.endswith(".xml") or name=="word/footnotes.xml":
                node=etree.fromstring(archive.read(name))
                furniture[name]={
                    "text":node.xpath(".//w:t/text()",namespaces=NS),
                    "fields":node.xpath(".//w:instrText/text()|.//w:fldSimple/@w:instr",namespaces=NS),
                }
        return {
            "body":body,"styles":style_info,"furniture":furniture,
            "numbering_xml":archive.read("word/numbering.xml").decode() if "word/numbering.xml" in archive.namelist() else None,
            "sections":[{
                "orientation":s.xpath("string(w:pgSz/@w:orient)",namespaces=NS) or "portrait",
                "width":s.xpath("string(w:pgSz/@w:w)",namespaces=NS),
                "height":s.xpath("string(w:pgSz/@w:h)",namespaces=NS),
                "columns":s.xpath("string(w:cols/@w:num)",namespaces=NS) or "1",
            } for s in root.findall(".//w:sectPr",NS)],
        }


def edit_copy(source,target):
    doc=Document(source)
    changes=[]
    for para in doc.paragraphs:
        if "Access readiness." in para.text:
            para.add_run(" For the next service period, the escort must also confirm "
                         "the accessible entrance, identify temporary obstructions and "
                         "record an alternative route before the operative arrives. "
                         "The dispatcher records that confirmation with the job reference.")
            changes.append("Extended the Access readiness clause as ordinary paragraph text.")
            break
    for table in doc.tables:
        found=False
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip()=="Remote sensor calibration":
                    cell.paragraphs[0].add_run(
                        " including a documented comparison with the portable reference "
                        "instrument, a second reading after stabilisation, a recorded "
                        "ambient-temperature check and confirmation by the site escort")
                    changes.append("Extended the Remote sensor calibration table description.")
                    found=True;break
            if found:break
        if found:break
    doc.save(target)
    return changes


def pdf_text(path):
    with fitz.open(path) as doc:
        return [{"page":i+1,"width":round(p.rect.width,2),"height":round(p.rect.height,2),
                 "text":p.get_text(sort=True)} for i,p in enumerate(doc)]


def comparison_images(reference,candidate,folder,prefix):
    paths=[]
    with fitz.open(reference) as left,fitz.open(candidate) as right:
        for i in range(max(len(left),len(right))):
            panels=[]
            for doc in (left,right):
                if i>=len(doc):
                    panels.append(Image.new("RGB",(850,1200),"#eeeeee"));continue
                page=doc[i]
                pix=page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False)
                image=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                panels.append(image)
            width=max(p.width for p in panels)
            height=max(p.height for p in panels)
            sheet=Image.new("RGB",(2*width+30,height+50),"white")
            draw=ImageDraw.Draw(sheet)
            draw.text((10,12),f"REFERENCE - {prefix} page {i+1}",fill="black")
            draw.text((width+30,12),f"CANDIDATE - {prefix} page {i+1}",fill="black")
            for j,image in enumerate(panels):sheet.paste(image,(j*(width+30),45))
            path=folder/f"{prefix}-{i+1:02d}.png";sheet.save(path)
            paths.append(path)
    return paths


def prepare(reference,candidate,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    ref_pdf=render(reference,folder/"ref-render")
    cand_pdf=render(candidate,folder/"candidate-render")
    ref_edit=folder/"reference-edited.docx";cand_edit=folder/"candidate-edited.docx"
    reference_changes=edit_copy(reference,ref_edit)
    candidate_changes=edit_copy(candidate,cand_edit)
    ref_edit_pdf=render(ref_edit,folder/"ref-edited-render")
    cand_edit_pdf=render(cand_edit,folder/"candidate-edited-render")
    pictures=comparison_images(ref_pdf,cand_pdf,folder,"original")
    edit_pictures=comparison_images(ref_edit_pdf,cand_edit_pdf,folder,"edited")
    # All pages remain available; prioritize the pages affected by the published probes.
    selected_edits=[p for p in edit_pictures if p.name in ("edited-02.png","edited-04.png","edited-05.png")]
    report={
        "reference":structure(reference),"candidate":structure(candidate),
        "reference_render":pdf_text(ref_pdf),"candidate_render":pdf_text(cand_pdf),
        "edit_probe":{"reference_actions":reference_changes,"candidate_actions":candidate_changes,
                      "reference_render":pdf_text(ref_edit_pdf),"candidate_render":pdf_text(cand_edit_pdf)},
    }
    (folder/"structure.json").write_text(json.dumps(report,ensure_ascii=True,indent=2))
    return pictures+selected_edits,report
