import re, zipfile, shutil, os
from xml.sax.saxutils import escape

SEED = '/app/seeds/Northstar_Forecast_Starter.xlsx'
OUT = '/app/output/Northstar_Forecast_Completed.xlsx'
COLS = [chr(c) for c in range(ord('E'), ord('P') + 1)]


def prev(c):
    return chr(ord(c) - 1)


F = {}  # sheet xml -> {cell: formula}


def put(sheet, cell, formula):
    F.setdefault(sheet, {})[cell] = formula


DRV, COH, REV, PL, WC, CF, CHK = 'sheet3', 'sheet5', 'sheet6', 'sheet7', 'sheet8', 'sheet9', 'sheet10'

for i, c in enumerate(COLS):
    p = prev(c)
    # A. Drivers
    for r in range(6, 26):
        put(DRV, f'{c}{r}', f'Assumptions!{c}{r}')

    # D. Cohort customers
    put(COH, f'{c}8', f'Drivers!{c}12*(1-Drivers!{c}10)' if i == 0 else f'{p}8*(1-Drivers!{c}10)')
    for k in range(12):
        r = 9 + k
        if i < k:
            f = '0'
        elif i == k:
            f = f'Drivers!{c}9'
        else:
            f = f'{p}{r}*(1-Drivers!{c}11)'
        put(COH, f'{c}{r}', f)

    # E. Cohort MRR
    put(COH, f'{c}25', f'{c}8*Drivers!{c}13*(1+Drivers!{c}15)' if i == 0
        else f'{p}25*(1-Drivers!{c}10)*(1+Drivers!{c}15)')
    for k in range(12):
        r = 26 + k
        if i < k:
            f = '0'
        elif i == k:
            f = f'{c}{r - 17}*Drivers!{c}14*(1+Drivers!{c}15)'
        else:
            f = f'{p}{r}*(1-Drivers!{c}11)*(1+Drivers!{c}15)'
        put(COH, f'{c}{r}', f)

    # Revenue
    put(REV, f'{c}6', f'Cohorts!{c}38')
    put(REV, f'{c}7', f'{c}6/{p}6-1')
    put(REV, f'{c}8', f'Cohorts!{c}38')
    put(REV, f'{c}9', f'Cohorts!{c}21')
    put(REV, f'{c}10', f'{c}6/{c}9')

    # C. P&L
    put(PL, f'{c}7', f'{c}6*Drivers!{c}7')
    put(PL, f'{c}8', f'{c}6-{c}7')
    put(PL, f'{c}9', f'{p}9*(1+Drivers!{c}18)')
    put(PL, f'{c}10', f'{c}6*Drivers!{c}19')
    put(PL, f'{c}11', f'{p}11*(1+Drivers!{c}20)')
    put(PL, f'{c}12', f'{c}8-{c}9-{c}10-{c}11')
    put(PL, f'{c}13', f'Drivers!{c}21')
    put(PL, f'{c}14', f'{c}12-{c}13')
    put(PL, f'{c}15', f"'Cash Flow'!{c}13*Drivers!{c}24/12")
    put(PL, f'{c}16', f'MAX({c}14-{c}15,0)*Drivers!{c}8')
    put(PL, f'{c}17', f'{c}14-{c}15-{c}16')

    # A. Working capital
    put(WC, f'{c}6', f"'P&L'!{c}6/Drivers!{c}25*Drivers!{c}16")
    put(WC, f'{c}7', f"'P&L'!{c}7/Drivers!{c}25*Drivers!{c}17")
    put(WC, f'{c}8', f'{c}6-{c}7')
    put(WC, f'{c}10', f'{c}6-{p}6')
    put(WC, f'{c}11', f'{c}7-{p}7')
    put(WC, f'{c}12', f'-{c}10+{c}11')

    # C. Cash flow
    put(CF, f'{c}10', f'{c}7+{c}8+{c}9')
    put(CF, f'{c}12', f'{c}6+{c}10-{c}11')
    put(CF, f'{c}14', f'MAX(Drivers!{c}23-{c}12,0)')
    put(CF, f'{c}15', f'MIN({c}13,MAX({c}12-Drivers!{c}23,0))')
    put(CF, f'{c}16', f'{c}14-{c}15')
    put(CF, f'{c}17', f'{c}12+{c}16')
    put(CF, f'{c}18', f'{c}13+{c}16')

    # Checks
    put(CHK, f'{c}6', f"'P&L'!{c}6-Revenue!{c}6")
    put(CHK, f'{c}7', f"'Working Capital'!{c}6/'P&L'!{c}6*Drivers!{c}25-Drivers!{c}16")
    put(CHK, f'{c}8', f"'Working Capital'!{c}7/'P&L'!{c}7*Drivers!{c}25-Drivers!{c}17")
    put(CHK, f'{c}9', f"'P&L'!{c}17-('P&L'!{c}14-'P&L'!{c}15-'P&L'!{c}16)")
    put(CHK, f'{c}10', f"'Cash Flow'!{c}17-('Cash Flow'!{c}6+'Cash Flow'!{c}10-'Cash Flow'!{c}11"
                       f"+'Cash Flow'!{c}14-'Cash Flow'!{c}15)")
    put(CHK, f'{c}11', f"'Cash Flow'!{c}18-('Cash Flow'!{c}13+'Cash Flow'!{c}14-'Cash Flow'!{c}15)")
    put(CHK, f'{c}12', f"MAX(Drivers!{c}23-'Cash Flow'!{c}17,0)")
    put(CHK, f'{c}13', f"MIN('Cash Flow'!{c}14,'Cash Flow'!{c}15)")
    put(CHK, f'{c}14', f'Revenue!{c}6-Cohorts!{c}38')
    put(CHK, f'{c}15', f'Revenue!{c}9-Cohorts!{c}21')

total = sum(len(v) for v in F.values())
assert total == 1020, total

os.makedirs('/app/output', exist_ok=True)
zin = zipfile.ZipFile(SEED)
tmp = OUT + '.tmp'
with zipfile.ZipFile(tmp, 'w') as zout:
    for info in zin.infolist():
        data = zin.read(info.filename)
        m = re.fullmatch(r'xl/worksheets/(sheet\d+)\.xml', info.filename)
        if m and m.group(1) in F:
            xml = data.decode('utf-8')
            for cell, formula in F[m.group(1)].items():
                pat = re.compile(r'<c r="%s"((?: [a-z]+="[^"]*")*?)(?:/>|>(.*?)</c>)' % cell, re.S)
                mm = pat.search(xml)
                assert mm, cell
                assert not mm.group(2), (cell, mm.group(2))  # target must be empty
                attrs = re.sub(r' t="[^"]*"', '', mm.group(1))
                xml = xml[:mm.start()] + f'<c r="{cell}"{attrs}><f>{escape(formula)}</f></c>' + xml[mm.end():]
            data = xml.encode('utf-8')
        zout.writestr(info, data)
os.replace(tmp, OUT)
print('wrote', OUT, total)
