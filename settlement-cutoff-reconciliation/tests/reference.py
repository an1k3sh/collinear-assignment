"""Independent relational reference: SQL version selection, joins and date arithmetic."""
import csv
import json
from pathlib import Path
import sqlite3


def expected(root):
    root = Path(root)
    cutoff = json.loads((root / "cutoff.json").read_text())["cutoff"]
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for file in root.glob("*.csv"):
        with file.open() as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            db.execute(f'CREATE TABLE "{file.stem}" ({",".join(fields)})')
            db.executemany(f'INSERT INTO "{file.stem}" VALUES ({",".join("?" for _ in fields)})',
                           ([r[k] for k in fields] for r in reader))
    for table, key in (("events", "event_id"), ("allocations", "allocation_id")):
        db.execute(f"""CREATE TEMP TABLE active_{table} AS
          SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
              PARTITION BY merchant,{key} ORDER BY CAST(version AS INTEGER) DESC) position
            FROM {table} WHERE recorded_at<=?
          ) WHERE position=1 AND status='posted' AND effective_at<=?""", (cutoff, cutoff))
    settlements = [dict(r) for r in db.execute("""
      WITH activity AS (
        SELECT merchant,batch,currency,
          SUM(CASE WHEN kind='sale' THEN amount_cents ELSE 0 END) sales_cents,
          SUM(CASE WHEN kind='refund' THEN amount_cents ELSE 0 END) refunds_cents,
          SUM(CASE WHEN kind='fee' THEN amount_cents ELSE 0 END) fees_cents,
          SUM(CASE WHEN kind IN ('reserve_hold','reserve_release') THEN amount_cents ELSE 0 END) reserve_net_cents,
          SUM(amount_cents) expected_cents FROM active_events GROUP BY merchant,batch,currency
      ), deposits AS (
        SELECT merchant,batch,currency,SUM(amount_cents) bank_cents FROM bank
        WHERE status='posted' AND recorded_at<=? AND effective_at<=?
        GROUP BY merchant,batch,currency
      ), combined AS (
        SELECT b.merchant,b.batch,b.currency,b.due_date,
          COALESCE(a.sales_cents,0) sales_cents, COALESCE(a.refunds_cents,0) refunds_cents,
          COALESCE(a.fees_cents,0) fees_cents, COALESCE(a.reserve_net_cents,0) reserve_net_cents,
          COALESCE(a.expected_cents,0) expected_cents, COALESCE(d.bank_cents,0) bank_cents
        FROM batches b LEFT JOIN activity a USING(merchant,batch,currency)
        LEFT JOIN deposits d USING(merchant,batch,currency)
      )
      SELECT merchant,batch,currency,sales_cents,refunds_cents,fees_cents,reserve_net_cents,
        expected_cents,bank_cents,bank_cents-expected_cents difference_cents,
        CASE WHEN bank_cents=expected_cents THEN 'matched'
          WHEN bank_cents=0 AND due_date>substr(?,1,10) THEN 'pending'
          ELSE 'exception' END status
      FROM combined ORDER BY merchant,batch,currency
    """, (cutoff, cutoff, cutoff))]
    aging = [dict(r) for r in db.execute("""
      WITH applied AS (
        SELECT merchant,invoice_id,SUM(amount_cents) total FROM active_allocations GROUP BY merchant,invoice_id
      ), balances AS (
        SELECT i.merchant,i.invoice_id,CAST(i.amount_cents AS INTEGER) amount_cents,
          COALESCE(a.total,0) applied_cents, i.amount_cents-COALESCE(a.total,0) open_cents,
          date(i.accepted,'+'||i.terms_days||' days') due_date
        FROM invoices i LEFT JOIN applied a USING(merchant,invoice_id)
      ), aged AS (
        SELECT *,CASE WHEN open_cents>0 THEN MAX(0,CAST(julianday(substr(?,1,10))-julianday(due_date) AS INTEGER))
          ELSE 0 END days_overdue FROM balances
      )
      SELECT *,CASE WHEN open_cents=0 THEN 'closed' WHEN days_overdue=0 THEN 'current'
        WHEN days_overdue<=30 THEN '1-30' WHEN days_overdue<=60 THEN '31-60' ELSE '61+' END bucket
      FROM aged ORDER BY merchant,invoice_id
    """, (cutoff,))]
    reserves = [dict(r) for r in db.execute("""
      SELECT o.merchant,o.currency,CAST(o.opening_cents AS INTEGER) opening_cents,
        -COALESCE(SUM(e.amount_cents),0) movement_cents,
        o.opening_cents-COALESCE(SUM(e.amount_cents),0) closing_cents
      FROM opening_reserves o LEFT JOIN active_events e
        ON e.merchant=o.merchant AND e.currency=o.currency
        AND e.kind IN ('reserve_hold','reserve_release')
      GROUP BY o.merchant,o.currency,o.opening_cents ORDER BY o.merchant,o.currency
    """)]
    db.close()
    summary = {"cutoff": cutoff, "reserves": reserves,
               "expected_deposits_cents": sum(r["expected_cents"] for r in settlements),
               "bank_cents": sum(r["bank_cents"] for r in settlements),
               "difference_cents": sum(r["difference_cents"] for r in settlements),
               "open_receivables_cents": sum(r["open_cents"] for r in aging),
               "overdue_receivables_cents": sum(r["open_cents"] for r in aging if r["days_overdue"])}
    return {"settlements": settlements, "aging": aging, "summary": summary}
