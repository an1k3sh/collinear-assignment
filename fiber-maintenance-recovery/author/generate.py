import csv
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont

TASK = Path(__file__).resolve().parents[1]
APP = TASK / "environment/app"
DATA, DRAWINGS = APP / "data", APP / "drawings"
for folder in (DATA,DRAWINGS):
    folder.mkdir(parents=True,exist_ok=True)
RNG = random.Random(450019)
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"]
font_path = next((p for p in FONT_PATHS if Path(p).exists()),None)
if font_path is None:
    raise RuntimeError("A legible TrueType font is required to render drawings")


def font(size):
    return ImageFont.truetype(font_path,size)


def write(name,rows):
    with (DATA/name).open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)


def render(name,nodes,edges):
    im=Image.new("RGB",(1800,1700),"white")
    draw=ImageDraw.Draw(im)
    draw.text((70,30),f"MERIDIAN | {name} | As-built revision 3",font=font(38),fill="black")
    draw.text((70,88),"Only labelled circles are nodes. Line crossings are NOT connections.",font=font(27),fill="black")
    positions={n:(900+640*math.cos(2*math.pi*i/len(nodes)-math.pi/2),
                  860+640*math.sin(2*math.pi*i/len(nodes)-math.pi/2)) for i,n in enumerate(nodes)}
    segments=[(positions[e["a"]],positions[e["b"]]) for e in edges]
    for a,b in segments:
        draw.line([a,b],fill=(32,49,62),width=4)
    boxes=[]
    for e,(a,b) in zip(edges,segments):
        candidates=[]
        for t in (0.23,0.77,0.34,0.66,0.45,0.55,0.15,0.85):
            p=(a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
            proximity=min([distance(p,c,d) for c,d in segments if (c,d)!=(a,b)]+[999])
            clear=min([math.hypot(p[0]-x,p[1]-y) for x,y in positions.values()]+[999])
            label_gap=min([math.hypot(p[0]-x,p[1]-y) for x,y in boxes]+[999])
            candidates.append((min(proximity,clear-60,label_gap-100),p))
        score,p=max(candidates)
        if score<18:
            raise RuntimeError(f"Label {e['cable']} needs a clearer drawing position: {score}")
        boxes.append(p)
        box=draw.textbbox((0,0),e["cable"],font=font(27))
        w,h=box[2]-box[0],box[3]-box[1]
        draw.rectangle((p[0]-w/2-7,p[1]-h/2-6,p[0]+w/2+7,p[1]+h/2+6),fill="white")
        draw.text(p,e["cable"],font=font(27),fill=(0,65,128),anchor="mm")
    for n,(x,y) in positions.items():
        draw.ellipse((x-51,y-36,x+51,y+36),fill="white",outline="black",width=4)
        draw.text((x,y),n,font=font(28),anchor="mm",fill="black")
    draw.text((70,1590),"Cable labels identify entire lines between their two terminations.",font=font(27),fill="black")
    draw.text((70,1632),"Diagram is schematic, not to scale. Inventory does not imply endpoint numbering.",font=font(25),fill="black")
    im.save(DRAWINGS/(name+".png"))


ids=list(range(101,188))
RNG.shuffle(ids)
links=[]
local={}
for site in "ABCDEF":
    nodes=[f"{site}{i:02}" for i in range(1,9)]
    ring=[(nodes[i],nodes[(i+1)%8]) for i in range(8)]
    possibilities=[(nodes[i],nodes[j]) for i in range(8) for j in range(i+2,8)
                   if (i,j)!=(0,7)]
    chords=RNG.sample(possibilities,4)
    edges=[]
    for index,(a,b) in enumerate(ring+chords):
        e=dict(cable=f"L{ids.pop()}",a=a,b=b)
        edges.append(e)
        links.append(e)
    local[site]=edges
    # Physical positions differ between rooms; identifiers do not imply geometry.
    RNG.shuffle(nodes)
    render("room-"+site,nodes,edges)
backbone_pairs=[]
sites="ABCDEF"
for i,site in enumerate(sites):
    backbone_pairs.append((site+"08",sites[(i+1)%6]+"01"))
backbone_pairs += [(a+"04",b+"04") for a,b in [("A","D"),("B","E"),("C","F")]]
backbone_pairs += [(a+"06",b+"02") for a,b in [("A","C"),("C","E"),("E","A"),("B","D"),("D","F"),("F","B")]]
backbone=[]
for a,b in backbone_pairs:
    e=dict(cable=f"L{ids.pop()}",a=a,b=b)
    backbone.append(e)
    links.append(e)
# Separate spine sheets keep node and cable labels legible.
for index in range(3):
    edges=backbone[index*5:(index+1)*5]
    nodes=sorted({e[f] for e in edges for f in ("a","b")})
    render(f"spine-{index+1}",nodes,edges)
(TASK/"author/topology.json").write_text(json.dumps(dict(links=links),indent=2)+"\n")
versions=[]
for index,e in enumerate(links):
    local_edge=e["a"][0]==e["b"][0]
    position=next((i for i,x in enumerate(local.get(e["a"][0],[])) if x==e),-1)
    risk=(e["a"][0]+"-tray-"+str(position%4) if local_edge else "corridor-"+str((index-72)%7))
    dark=(local_edge and position>=8) or (not local_edge and index>=81)
    row=dict(cable=e["cable"],recorded_at="2026-06-15T06:00:00Z",
             status="dark" if dark else "lit",capacity=10 if local_edge else 12,
             risk_group=risk,activation_cents=1500+100*(index%5))
    versions.append(row)
    if index in (5,19,47):
        versions.append(dict(row,recorded_at="2026-06-15T07:30:00Z",status="blocked"))
    if index in (8,24,36):
        versions.append(dict(row,recorded_at="2026-06-15T09:00:00Z",capacity=1,status="blocked"))
    if index in (14,39,58):
        versions.append(dict(row,recorded_at="2026-06-15T07:20:00Z",capacity=6))
RNG.shuffle(versions)
write("cable_versions.csv",versions)
write("nodes.csv",[dict(node=f"{s}{i:02}",room=s) for s in sites for i in range(1,9)])
write("drawing_register.csv",[dict(sheet=p.stem,file="drawings/"+p.name,revision=3)
                              for p in sorted(DRAWINGS.glob("*.png"))])
write("phases.csv",[dict(phase=f"P{i}",description=d) for i,d in enumerate(
    ["West corridor enclosure work","Central splice enclosure work","East corridor enclosure work"],1)])
outages=[]
for phase,offset in [("P1",0),("P2",2),("P3",4)]:
    for index in (offset,offset+7):
        outages.append(dict(phase=phase,cable=backbone[index]["cable"]))
write("outages.csv",outages)
write("services.csv",[
    dict(service="S1",source="A03",target="D05",units=3,protection="1+1"),
    dict(service="S2",source="B03",target="E05",units=3,protection="1+1"),
    dict(service="S3",source="C03",target="F05",units=2,protection="1+1"),
    dict(service="S4",source="A07",target="C07",units=2,protection="none"),
    dict(service="S5",source="D07",target="F07",units=2,protection="none"),
])
(DATA/"settings.json").write_text(json.dumps(dict(planning_cutoff="2026-06-15T08:00:00Z",
                                                   budget_cents=36000),indent=2)+"\n")
print(f"Generated {len(links)} cables on nine readable drawings")
