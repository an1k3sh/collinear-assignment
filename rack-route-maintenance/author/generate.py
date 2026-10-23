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
    im=Image.new("RGB",(3200,2600),"white")
    draw=ImageDraw.Draw(im)
    draw.text((70,25),f"MERIDIAN | {name} | Routed rack wiring | revision 3",font=font(42),fill="black")
    draw.text((70,90),"Follow right-angle turns. Crossings are NOT connections. Only labelled boxes are nodes.",font=font(34),fill="black")
    count=(len(nodes)+1)//2
    levels=[400+i*1800/max(1,count-1) for i in range(count)]
    positions={n:(130 if i<count else 3070,levels[i if i<count else i-count]) for i,n in enumerate(nodes)}
    lanes=[450+i*2300/(2*len(edges)-1) for i in range(2*len(edges))]
    # Rendering has its own PRNG so drawing style cannot change the scenario.
    layout=random.Random(sum(ord(c) for c in name)+2026)
    layout.shuffle(lanes)
    paths=[]
    occupied_y=set()
    for i,e in enumerate(edges):
        offset=(i-(len(edges)-1)/2)*38
        a,b=positions[e["a"]],positions[e["b"]]
        ay,by=a[1]+offset,b[1]+offset
        occupied_y.update((ay,by))
        ax=220 if a[0]<1600 else 2980
        bx=220 if b[0]<1600 else 2980
        x1,x2=lanes[2*i:2*i+2]
        if ay==by:
            x1,x2=sorted((x1,x2),reverse=ax>bx)
        paths.append(dict(edge=e,ax=ax,ay=ay,bx=bx,by=by,x1=x1,x2=x2))
    for i,path in enumerate(paths):
        ay,by=path["ay"],path["by"]
        low,high=sorted((ay,by))
        if low==high:
            low,high=(low-270,low-70) if low>2200 else (low+70,min(2450,low+270))
        else:
            low,high=low+45,high-45
        choices=[low+(high-low)*j/101 for j in range(1,101)]
        middle=max(choices,key=lambda y:min(abs(y-other) for other in occupied_y))
        if min(abs(middle-other) for other in occupied_y)<10:
            raise RuntimeError("Not enough independent drawing space for routed wires")
        occupied_y.add(middle)
        path["points"]=[(path["ax"],ay),(path["x1"],ay),(path["x1"],middle),
                        (path["x2"],middle),(path["x2"],by),(path["bx"],by)]
        draw.line(path["points"],fill=(32,49,62),width=5,joint="curve")
    for path in paths:
        x=335 if path["ax"]<1600 else 2865
        y=path["ay"]
        label=path["edge"]["cable"]
        draw.rectangle((x-54,y-21,x+54,y+21),fill="white")
        draw.text((x,y),label,font=font(32),fill=(0,65,128),anchor="mm")
    for n,(x,y) in positions.items():
        half_height=max(110,(len(edges)-1)*19+16)
        draw.rectangle((x-90,y-half_height,x+90,y+half_height),fill="white",outline="black",width=5)
        draw.text((x,y),n,font=font(39),anchor="mm",fill="black")
    draw.text((70,2500),"Each unbranched cable terminates on two labelled node boxes. Geometry is not distance.",font=font(32),fill="black")
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
