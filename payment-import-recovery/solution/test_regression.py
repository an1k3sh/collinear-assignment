import unittest
from import_payments import normalized


class Money(unittest.TestCase):
    def test_exact_cents_and_invoice_id(self):
        row = {"tenant": "n", "payment_id": "p", "invoice_id": "00123",
               "paid_at": "2026-04-30T00:00:00Z", "amount": "0.29"}
        self.assertEqual(normalized(row)["cents"], 29)
        self.assertEqual(normalized(row)["invoice_id"], "00123")


if __name__ == "__main__":
    unittest.main()
