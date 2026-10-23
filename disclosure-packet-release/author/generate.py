import csv
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile

import fitz
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.workbook.defined_name import DefinedName

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"environment/app/input"
TARGET.mkdir(parents=True,exist_ok=True)
mapping=[
    dict(private="Arden Vale",public="CLIENT-07"),
    dict(private="arden.vale@example.invalid",public="EMAIL-REMOVED"),
    dict(private="TEST-ACCT-8471-9920",public="ACCOUNT-REMOVED"),
    dict(private="PRIVATE-CASE-004271",public="PUBLIC-CASE-071"),
]
(TARGET/"release-map.json").write_text(json.dumps(mapping,indent=2)+"\n")
wb=Workbook()
sheet=wb.active
sheet.title="Statement"
sheet.append(["Line","Description","Amount"])
for row in [("S-01","Services",1200.00),("S-02","Materials",347.40),("S-03","Credit",-160.00)]:
    sheet.append(row)
sheet["B6"]="Net"
sheet["C6"]="=SUM(C2:C4)"
sheet["B7"]="Tax"
sheet["C7"]="=ROUND(C6*0.08,2)"
sheet["B8"]="Total"
sheet["C8"]="=C6+C7"
sheet["A10"]="Public case"
sheet["B10"]="PUBLIC-CASE-071"
sheet["A11"]="Customer"
sheet["B11"]="Arden Vale"
sheet["A12"]="Email"
sheet["B12"]="arden.vale@example.invalid"
sheet["A13"]="Payment account"
sheet["B13"]="TEST-ACCT-8471-9920"
sheet["B2"].comment=Comment("Audit note: services approved. Contact Arden Vale.","Arden Vale")
sheet.oddHeader.center.text="Arden Vale - PRIVATE-CASE-004271"
sheet.oddFooter.left.text="arden.vale@example.invalid"
wb.properties.creator="Arden Vale"
wb.properties.lastModifiedBy="arden.vale@example.invalid"
wb.properties.description="Account TEST-ACCT-8471-9920"
wb.defined_names.add(DefinedName("ClientLabel",attr_text='"Arden Vale"'))
audit=wb.create_sheet("Audit")
audit.append(["Public approval","Customer","Private case"])
audit.append(["APPROVAL-2026-118","Arden Vale","PRIVATE-CASE-004271"])
audit.sheet_state="hidden"
with tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp)
    source=folder/"source";out=folder/"out"
    source.mkdir();out.mkdir()
    wb.save(source/"statement.xlsx")
    process=subprocess.run(["libreoffice","-env:UserInstallation="+(folder/"profile").as_uri(),
                            "--headless","--convert-to","xlsx","--outdir",str(out),str(source/"statement.xlsx")],
                           capture_output=True,text=True,timeout=60)
    if process.returncode or not (out/"statement.xlsx").exists():
        raise RuntimeError(process.stdout+process.stderr)
    workbook=(out/"statement.xlsx").read_bytes()
stream=StringIO()
writer=csv.writer(stream,lineterminator="\r\n")
writer.writerow(["transaction","customer","email","account","amount"])
writer.writerow(["TX-8471","Arden Vale","arden.vale@example.invalid","TEST-ACCT-8471-9920","1200.00"])
writer.writerow(["TX-9920","Arden Vale","arden.vale@example.invalid","TEST-ACCT-8471-9920","187.40"])
csv_bytes=stream.getvalue().encode()
approval=("Approval reference: APPROVAL-2026-118\nDecision: APPROVED\nAmount: 1498.39 USD\n"
          "Customer: Arden Vale\nContact: arden.vale@example.invalid\nPrivate case: PRIVATE-CASE-004271\n").encode()
contact=(b'<?xml version="1.0" encoding="UTF-8"?>\n'
         b'<contact><case>PUBLIC-CASE-071</case><release>AUTHORIZED</release>'
         b'<name>Arden Vale</name><email>arden.vale@example.invalid</email>'
         b'<account>TEST-ACCT-8471-9920</account></contact>')
doc=fitz.open()
private_regions={}
public_rects={}
pages=[]
for i in range(3):
    page=doc.new_page(width=612,height=792)
    pages.append(page.number)
    page.insert_text((42,40),["Financial statement","Operational detail","Supporting material"][i],fontsize=20)
    page.insert_text((42,72),"PUBLIC-CASE-071 | Meridian Community Services | June 2026",fontsize=10)
    page.insert_text((42,770),f"Public disclosure packet | page {i+1}",fontsize=9)
page=doc[0]
private_regions["0"]=[]
for y,text in [(110,"Customer: Arden Vale"),(134,"Email: arden.vale@example.invalid"),
               (158,"Account: TEST-ACCT-8471-9920"),(182,"Legacy case: PRIVATE-CASE-004271")]:
    page.insert_text((42,y),text,fontsize=11)
    private_regions["0"].append([40,y-14,550,y+5])
page.draw_rect(fitz.Rect(40,220,570,430),color=(0.15,0.2,0.3),width=1)
for y,left,right in [(247,"Line / Description","USD"),(279,"S-01 Services","1200.00"),
                     (311,"S-02 Materials","347.40"),(343,"S-03 Credit","-160.00"),
                     (375,"Net","1387.40"),(399,"Tax (8%)","110.99"),(423,"Total","1498.39")]:
    page.insert_text((52,y),left,fontsize=11)
    page.insert_text((490,y),right,fontsize=11)
page.insert_text((42,480),"Supporting files and approval are on page 3.",fontsize=11)
page.insert_link({"kind":fitz.LINK_GOTO,"from":fitz.Rect(40,462,370,486),"page":2})
page=doc[1]
page.insert_text((42,115),"Public transaction references: TX-8471 and TX-9920",fontsize=12)
page.insert_text((42,145),"Approved work: three service stages, credit applied after reconciliation.",fontsize=11)
for i,(label,value) in enumerate([("Services",1200),("Materials",347.4),("Credit",160)]):
    y=225+i*90
    page.insert_text((45,y+20),label,fontsize=12)
    page.draw_rect(fitz.Rect(155,y,155+value/4,y+35),color=None,fill=(0.15,0.4+0.1*i,0.65))
    page.insert_text((475,y+24),str(value),fontsize=10)
page.insert_text((42,565),"The diagram reports public statement line amounts; it is not customer identity.",fontsize=10)
note=page.add_text_annot((500,610),"Public audit note: net 1387.40 USD and approval APPROVAL-2026-118. Contact Arden Vale.")
note.set_info(title="Arden Vale",subject="PRIVATE-CASE-004271")
note.update()
# Old print-template text displaced outside the page survives in the source file.
page.insert_text((-900,-120),"Arden Vale | arden.vale@example.invalid | TEST-ACCT-8471-9920",fontsize=11)
page=doc[2]
page.insert_text((42,115),"Document attachments: statement.xlsx and transactions.csv",fontsize=12)
page.insert_text((42,145),"Page attachments: approval.txt and contact-card.xml",fontsize=12)
page.insert_text((42,190),"Release authorization: APPROVAL-2026-118. Total authorized: 1498.39 USD.",fontsize=11)
first=page.add_file_annot((90,260),approval,"approval.txt",desc="Approval for Arden Vale")
first.set_info(title="Arden Vale",subject="PRIVATE-CASE-004271")
first.update()
second=page.add_file_annot((300,260),contact,"contact-card.xml",desc="Contact arden.vale@example.invalid")
second.set_info(title="Arden Vale")
second.update()
doc.embfile_add("statement.xlsx",workbook,filename="statement.xlsx",desc="Statement for Arden Vale")
doc.embfile_add("transactions.csv",csv_bytes,filename="transactions.csv",desc="Account TEST-ACCT-8471-9920")
doc.set_metadata(dict(title="Arden Vale financial statement",author="arden.vale@example.invalid",
                      subject="PRIVATE-CASE-004271",keywords="TEST-ACCT-8471-9920"))
doc.set_xml_metadata('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
                     '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                     '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" '
                     'dc:creator="Arden Vale" dc:description="PRIVATE-CASE-004271"/>'
                     '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>')
doc.set_toc([[1,"Arden Vale - Statement",1],[1,"Operational detail",2],[1,"Supporting material",3]])
doc.save(TARGET/"packet.pdf")
doc.close()
(ROOT/"tests/visual-regions.json").write_text(json.dumps({
    "0":[[40,220,570,430],[40,460,570,490]],
    "1":[[40,110,570,150],[40,210,550,500],[40,555,580,580]],
    "2":[[40,105,580,200]]},indent=2)+"\n")
print(TARGET/"packet.pdf")
