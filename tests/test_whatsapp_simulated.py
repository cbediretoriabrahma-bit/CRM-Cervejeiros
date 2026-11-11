"""Simula mensagens da Meta/WhatsApp usando banco SQLite isolado.

Nenhuma requisicao real e enviada a Meta ou OpenAI; as respostas enviadas
sao interceptadas. O CRM de producao nao e acessado.
"""
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch
from datetime import datetime

from homologacao_entry import app, crm
import ai_whatsapp_patch as wa


class WhatsappWebhookSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.appctx = app.app_context()
        cls.appctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.appctx.pop()

    def setUp(self):
        crm.db.session.remove()
        crm.db.drop_all()
        crm.db.create_all()
        self.phone = "5511999001234"
        self.sent = []

        def fake_send(number, message):
            self.sent.append((number, message))
            return True, "SIMULATED"

        self.send_patch = patch.object(crm, "send_whatsapp_cloud", side_effect=fake_send)
        self.send_patch.start()
        self.env_patch = patch.dict(os.environ, {
            "AI_WHATSAPP_ENABLED": "1",
            "AI_MEETING_ENABLED": "1",
            "AUTO_REPLY_WHATSAPP": "1",
            "META_APP_SECRET": "somente-teste-integracao",
        })
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.send_patch.stop()
        crm.db.session.remove()

    def receive(self, text, identifier):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"profile": {"name": "Cliente Ficticio"}}],
                        "messages": [{
                            "from": self.phone,
                            "id": identifier,
                            "type": "text",
                            "text": {"body": text}
                        }]
                    }
                }]
            }]
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        signature = "sha256=" + hmac.new(
            b"somente-teste-integracao", body, hashlib.sha256
        ).hexdigest()
        with app.test_request_context(
            "/webhooks/whatsapp", method="POST", data=body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature}
        ):
            # Invoca a rota diretamente para nao abrir a web publica de testes.
            return app.view_functions["whatsapp_webhook"]()

    def test_cliente_agenda_primeira_reuniao(self):
        status = self.receive("Quero agendar uma reunião", "teste-001")
        self.assertEqual(status[1], 200)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("horários disponíveis", self.sent[0][1])
        lead = crm.Lead.query.filter_by(phone=self.phone).one()
        self.assertEqual(lead.stage, "Novo Lead")
        self.assertIsNone(crm.Task.query.filter_by(task_type="Reunião").first())

        response = self.receive("1", "teste-002")
        self.assertEqual(response[1], 200)
        crm.db.session.expire_all()
        lead = crm.Lead.query.filter_by(phone=self.phone).one()
        tasks = crm.Task.query.filter_by(
            lead_id=lead.id, task_type="Reunião", status="Pendente"
        ).all()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(lead.stage, "Reunião Agendada")
        self.assertEqual(len(self.sent), 2)
        self.assertIn("foi agendada", self.sent[1][1])

        # Um segundo "1" nao pode criar mais uma reuniao.
        self.receive("1", "teste-003")
        tasks = crm.Task.query.filter_by(
            lead_id=lead.id, task_type="Reunião"
        ).all()
        self.assertEqual(len(tasks), 1)

    def test_assinatura_invalida_recusada(self):
        with app.test_request_context(
            "/webhooks/whatsapp", method="POST",
            data=b"{}", content_type="application/json",
            headers={"X-Hub-Signature-256": "sha256=invalida"}
        ):
            reply = app.view_functions["whatsapp_webhook"]()
        self.assertEqual(reply[1], 403)
        self.assertEqual(len(self.sent), 0)


if __name__ == "__main__":
    unittest.main()
