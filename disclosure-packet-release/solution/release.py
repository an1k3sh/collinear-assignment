import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pikepdf

mapping=json.loads(Path("/app/input/release-map.json").read_text())


def text(value):
    for row in mapping:
        value=value.replace(row["private"],row["public"])
    return value


def payload(data):
    if data.startswith(b"PK"):
        output=BytesIO()
        with ZipFile(BytesIO(data)) as source,ZipFile(output,"w",ZIP_DEFLATED) as target:
            for entry in source.infolist():
                content=source.read(entry.filename)
                if entry.filename.endswith((".xml",".rels")):
                    content=text(content.decode("utf-8")).encode("utf-8")
                target.writestr(entry,content)
        return output.getvalue()
    return text(data.decode("utf-8")).encode("utf-8")


def operand(value):
    if isinstance(value,pikepdf.String):
        original=str(value)
        replacement=text(original)
        return pikepdf.String(replacement) if replacement!=original else value
    if isinstance(value,pikepdf.Array):
        return pikepdf.Array([operand(item) for item in value])
    return value


def content_stream(page_or_stream):
    instructions=[]
    for instruction in pikepdf.parse_content_stream(page_or_stream):
        instructions.append(([operand(v) for v in instruction.operands],instruction.operator))
    return pikepdf.unparse_content_stream(instructions)


with pikepdf.open("/app/input/packet.pdf") as pdf:
    embedded=set()
    for page in pdf.pages:
        page.Contents=pdf.make_stream(content_stream(page))
    seen=set()

    def visit(obj):
        if isinstance(obj,pikepdf.String):
            original=str(obj)
            replacement=text(original)
            return pikepdf.String(replacement) if replacement!=original else obj
        if not isinstance(obj,(pikepdf.Dictionary,pikepdf.Array,pikepdf.Stream)):
            return obj
        if obj.is_indirect:
            if obj.objgen in seen:
                return obj
            seen.add(obj.objgen)
        if isinstance(obj,pikepdf.Array):
            for i in range(len(obj)):
                obj[i]=visit(obj[i])
            return obj
        if "/EF" in obj:
            embedded.update(stream.objgen for key,stream in obj.EF.items()
                            if isinstance(stream,pikepdf.Stream))
        if isinstance(obj,pikepdf.Stream):
            if obj.objgen in embedded or obj.get("/Type")==pikepdf.Name("/EmbeddedFile"):
                data=payload(obj.read_bytes())
                obj.write(data)
                obj.Params=pikepdf.Dictionary(Size=len(data),CheckSum=pikepdf.String(hashlib.md5(data).digest()))
                if "/DL" in obj:
                    obj.DL=len(data)
            elif obj.get("/Type")==pikepdf.Name("/Metadata"):
                obj.write(text(obj.read_bytes().decode("utf-8")).encode("utf-8"))
            elif obj.get("/Subtype")==pikepdf.Name("/Form"):
                obj.write(content_stream(obj))
        for key,value in list(obj.items()):
            if key not in ("/Length","/Filter","/DecodeParms"):
                obj[key]=visit(value)
        return obj

    visit(pdf.Root)
    visit(pdf.docinfo)
    output=Path("/app/submission")
    output.mkdir(parents=True,exist_ok=True)
    pdf.save(output/"release.pdf",compress_streams=True)
print(output/"release.pdf")
