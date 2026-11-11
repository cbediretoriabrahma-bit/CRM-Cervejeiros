"""Garante que o ambiente isolado nao permita clientes nem webhooks reais."""
import unittest
from homologacao_entry import app


class IsolationTests(unittest.TestCase):
    def test_status_is_accessible_and_test_mode_disabled(self):
        client = app.test_client()
        result = client.get("/homologacao/status")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["whatsapp_teste"], "desativado")
        self.assertEqual(result.json["ia_teste"], "desativada")

    def test_commercial_routes_are_inaccessible(self):
        client = app.test_client()
        self.assertEqual(client.get("/").status_code, 404)
        self.assertEqual(client.get("/leads").status_code, 404)
        self.assertEqual(client.post("/webhooks/whatsapp", json={}).status_code, 404)
        self.assertEqual(client.get("/webhooks/whatsapp").status_code, 404)
        self.assertEqual(client.post("/webhooks/instagram", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
