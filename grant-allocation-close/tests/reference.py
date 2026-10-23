from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def cents(value):
    return int((Decimal(str(value))*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))


def expected(wb):
    cutoff=wb["Control"]["B2"].value
    rates={wb["Rates"].cell(r,1).value:Decimal(str(wb["Rates"].cell(r,2).value)) for r in range(2,5)}
    latest={}
    for r in range(2,502):
        row=[wb["Ledger"].cell(r,c).value for c in range(1,9)]
        if row[0] is None:
            continue
        program,item,revision,recorded,effective,status,currency,amount=row
        if recorded>cutoff:
            continue
        key=program,item
        if key not in latest or revision>latest[key][2]:
            latest[key]=row
    balances={}
    for program,item,revision,recorded,effective,status,currency,amount in latest.values():
        if status=="posted" and effective<=cutoff:
            converted=Decimal(str(amount))*rates[currency]*100
            balances[program]=balances.get(program,0)+int(converted.quantize(Decimal(1),rounding=ROUND_HALF_UP))
    results={}
    for r in range(2,10):
        key,name,weight,maximum,approval,rank=[wb["Programs"].cell(r,c).value for c in range(1,7)]
        balance=balances.get(key,0)
        cap=max(0,min(balance,cents(maximum))) if approval=="approved" else 0
        results[key]=dict(name=name,balance=balance,cap=cap,weight=weight,rank=rank,quota=Fraction(0))
    total=min(cents(wb["Control"]["B3"].value),sum(v["cap"] for v in results.values()))
    remaining=total
    active={k for k,v in results.items() if v["cap"]>0}
    while active and remaining:
        level=Fraction(remaining,sum(results[k]["weight"] for k in active))
        saturated={k for k in active if results[k]["cap"]<=level*results[k]["weight"]}
        if not saturated:
            for k in active:
                results[k]["quota"]=level*results[k]["weight"]
            break
        for k in saturated:
            results[k]["quota"]=Fraction(results[k]["cap"])
            remaining-=results[k]["cap"]
        active-=saturated
    for row in results.values():
        row["award"]=row["quota"].numerator//row["quota"].denominator
    residual=total-sum(r["award"] for r in results.values())
    ordered=sorted(results,key=lambda k:(-(results[k]["quota"]-results[k]["award"]),results[k]["rank"]))
    for k in ordered[:residual]:
        results[k]["award"]+=1
    return results,total,cents(wb["Control"]["B3"].value)-total


def variant(wb,number):
    if number==0:
        return
    if number==1:
        wb["Control"]["B3"]=423.17
    elif number==2:
        wb["Control"]["B3"]=1030.99
        for r in range(2,10):
            wb["Programs"].cell(r,3,[100,1,40,2,90,3,70,4][r-2])
    elif number==3:
        wb["Programs"]["E2"]="hold"
        wb["Programs"]["E5"]="hold"
        wb["Programs"]["D7"]=1.03
    elif number==4:
        row=["001","LATE-ROW",1,datetime(2026,4,29),datetime(2026,4,29),"posted","EUR",73.335]
        for c,value in enumerate(row,1):
            wb["Ledger"].cell(501,c,value)
        wb["Ledger"].row_dimensions[501].hidden=True
        wb["Programs"]["D2"]=190
    elif number==5:
        wb["Control"]["B2"]=datetime(2026,6,2)
        wb["Control"]["B3"]=670.23
    elif number==6:
        rows=[[wb["Rates"].cell(r,c).value for c in range(1,3)] for r in range(2,5)]
        rows.reverse()
        for r,row in enumerate(rows,2):
            row[1]={"GBP":1.2749,"EUR":0.9945,"USD":1}[row[0]]
            for c,value in enumerate(row,1):
                wb["Rates"].cell(r,c,value)
        wb["Programs"]["B2"]="Renamed food program"
    elif number==7:
        wb["Control"]["B3"]=0.05
        for r in range(2,10):
            wb["Programs"].cell(r,3,1)
        for r in range(2,502):
            for c in range(1,9):
                wb["Ledger"].cell(r,c).value=None
        for r in range(2,10):
            row=[wb["Programs"].cell(r,1).value,"001",1,datetime(2026,4,20),
                 datetime(2026,4,20),"posted","USD",10000]
            for c,value in enumerate(row,1):
                wb["Ledger"].cell(r,c,value)
    elif number==8:
        for r in range(2,10):
            wb["Programs"].cell(r,4,0)
    elif number==9:
        records=[[wb["Ledger"].cell(r,c).value for c in range(1,9)] for r in range(2,32)]
        records.reverse()
        for r,row in enumerate(records,2):
            for c,value in enumerate(row,1):
                wb["Ledger"].cell(r,c).value=value
        extra=[
            ["001","01",2,datetime(2026,4,30),datetime(2026,4,30),"void","EUR",24],
            ["01","REFUND",1,datetime(2026,4,30),datetime(2026,4,30),"posted","USD",-500.005],
            ["1","01",2,datetime(2026,4,30),datetime(2026,6,3),"posted","EUR",16],
        ]
        for r,row in enumerate(extra,499):
            for c,value in enumerate(row,1):
                wb["Ledger"].cell(r,c,value)
    elif number==10:
        wb["Control"]["B3"]=0
    else:
        raise ValueError(number)
