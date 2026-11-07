"""Testes isolados: agendamento da primeira reuniao sem acessar Meta/Render."""
import importlib
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


class Lead:
    def __init__(self):
        self.id = 7
        self.owner_id = 3
        self.name = "Teste"
        self.stage = "Qualificado"
        self.notes = ""
        self.meeting_interest = None
        self.next_followup = None


def create_module():
    p = types.ModuleType("patched_app")
    p._apply_answer_to_lead = lambda lead, msg: None
    p._reply_for_message = lambda lead, msg: "legado"
    crm = MagicMock()
    crm.db.session.get_bind.return_value.dialect.name = "sqlite"
    crm.Task.query.filter.return_value.first.return_value = None
    crm.Task.side_effect = lambda **kw: kw
    crm.AutomationLog.side_effect = lambda **kw: kw
    p.crm = crm

    sc = types.ModuleType("sitecustomize")
    def tag(lead, key):
        for row in (lead.notes or "").splitlines():
            if row.startswith(f"[{key}]="):
                return row.split("=", 1)[1]
        return ""
    def save(lead, key, value):
        lines = [row for row in (lead.notes or "").splitlines()
                 if not row.startswith(f"[{key}]=")]
        lines.append(f"[{key}]={value}")
        lead.notes = "\n".join(lines)
    sc._tag_value = tag
    sc._set_tag = save

    with patch.dict(sys.modules, {"patched_app": p, "sitecustomize": sc}):
        if "ai_meeting_patch" in sys.modules:
            del sys.modules["ai_meeting_patch"]
        module = importlib.import_module("ai_meeting_patch")
    return module, crm, sc


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        self.m, self.crm, self.sc = create_module()
        self.lead = Lead()

    def test_numbered_options(self):
        self.assertEqual(self.m._chosen_index("opção 2"), 1)
        self.assertEqual(self.m._chosen_index("4"), 3)
        self.assertIsNone(self.m._chosen_index("Quero investimento"))

    def test_meeting_intent(self):
        self.assertTrue(self.m._is_meeting_request("Podemos agendar uma reunião?"))
        self.assertFalse(self.m._is_meeting_request("Qual o investimento?"))

    def test_offered_slots_are_persisted(self):
        first = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=3)
        first = first.replace(hour=10, minute=0, second=0, microsecond=0)
        with patch.dict(os.environ, {"AI_WHATSAPP_ENABLED": "1", "AI_MEETING_ENABLED": "1"}):
            self.sc._set_tag(self.lead, "AI_MTG_RESPONSE", "offer")
            with patch.object(self.m, "_new_options", return_value=[first]):
                answer = self.m._reply(self.lead, "Quero agendar")
            self.assertIn("primeira reunião", answer)
            self.assertEqual(self.sc._tag_value(self.lead, "AI_MTG_PENDING"), "choose")
            self.assertTrue(self.sc._tag_value(self.lead, "AI_MTG_SLOT_1"))
            self.crm.db.session.commit.assert_called_once()

    def test_confirm_creates_a_real_task(self):
        slot = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=3)
        slot = slot.replace(hour=10, minute=0, second=0, microsecond=0)
        with patch.object(self.m, "_available", return_value=True):
            self.assertTrue(self.m._book(self.lead, slot))
        self.assertEqual(self.lead.stage, "Reunião Agendada")
        self.assertEqual(self.lead.meeting_interest, "Sim")
        self.crm.db.session.add.assert_called()
        self.assertEqual(self.sc._tag_value(self.lead, "AI_MTG_PENDING"), "")

    def test_existing_meeting_prevents_double_booking(self):
        self.crm.Task.query.filter.return_value.first.return_value = object()
        slot = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=3)
        self.assertFalse(self.m._book(self.lead, slot))
        self.crm.db.session.add.assert_not_called()

    def test_conflicting_meeting_blocks_availability(self):
        slot = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=3)
        while slot.weekday() >= 5:
            slot += timedelta(days=1)
        slot = slot.replace(hour=10, minute=0, second=0, microsecond=0)
        self.crm.Task.query.filter.return_value.first.return_value = object()
        self.crm.Task.due_at.__gt__.return_value = True
        self.crm.Task.due_at.__lt__.return_value = True
        self.assertFalse(self.m._available(slot))

    def test_past_slot_is_not_available(self):
        slot = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(hours=1)
        self.assertFalse(self.m._available(slot))

    def test_manual_handoff_skips_meeting_offer(self):
        self.lead.notes = "[AI_HANDOFF]=1"
        with patch.dict(os.environ, {"AI_WHATSAPP_ENABLED": "1", "AI_MEETING_ENABLED": "1"}):
            self.sc._set_tag(self.lead, "AI_MTG_RESPONSE", "offer")
            self.assertEqual(self.m._reply(self.lead, "quero reunião"), "legado")
            self.assertFalse(self.sc._tag_value(self.lead, "AI_MTG_SLOT_1"))

    def test_booking_is_not_confirmed_when_slot_taken(self):
        slot = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=3)
        with patch.object(self.m, "_available", return_value=False):
            self.assertFalse(self.m._book(self.lead, slot))
        self.assertEqual(self.lead.stage, "Qualificado")
        self.crm.db.session.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
