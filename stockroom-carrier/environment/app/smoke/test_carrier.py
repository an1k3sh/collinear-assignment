import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from carrier_service import Carrier, initialize


class CarrierSmoke(unittest.TestCase):
    def test_carrier_acceptance_survives_local_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed.json"
            database = root / "carrier.sqlite"
            source, incoming, output = root / "program.stock", root / "inventory.json", root / "out.json"
            seed.write_text('{"service_id":"public-smoke","policies":{"order":"accept_then_timeout_once"}}')
            initialize(seed, database)
            incoming.write_text('{"warehouses":{"east":{"gear":10,"seal":10}}}')
            source.write_text('''
proc main() {
 transaction {
   reserve("order.a","east","gear",2);
   let receipt:string=carrier_send("order","east","gear",2,"seal",1);
 } recover(e) {emit "caught" {reason:code(e);};}
 emit "receipt" {found:len(carrier_receipt("order"))>0;};
}
''')
            process = subprocess.run(
                [sys.executable, "-m", "stockroom", str(source), "--inventory", str(incoming),
                 "--out", str(output), "--carrier", str(database)],
                capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["holds"], {})
            self.assertEqual(result["deliveries"], {})
            self.assertEqual(result["warehouses"]["east"]["gear"], 10)
            self.assertEqual(result["events"], [
                {"id":1,"name":"caught","data":{"reason":"CARRIER_TIMEOUT"}},
                {"id":2,"name":"receipt","data":{"found":True}}])
            self.assertIsNotNone(Carrier(database).lookup("order"))


if __name__ == "__main__":
    unittest.main()
