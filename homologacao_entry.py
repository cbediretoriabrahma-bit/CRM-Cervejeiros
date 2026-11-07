"""Ambiente de homologacao isolado: sem dados reais e sem envio externo.

Executa o mesmo codigo do CRM, mas usa uma base SQLite temporaria,
desativa integracoes de envio e deixa acessivel apenas /homologacao/status.
Nao usar como aplicativo comercial ou com dados de clientes.
"""
import os

from flask import jsonify, request

# Protecao antes de importar qualquer arquivo do CRM.
os.environ["DATABASE_URL"] = "sqlite:////tmp/cervejeiros_homologacao_isolada.db"
os.environ["AUTO_REPLY_WHATSAPP"] = "0"
os.environ["AUTO_REPLY_INSTAGRAM"] = "0"
os.environ["AI_WHATSAPP_ENABLED"] = "0"
os.environ["AI_MEETING_ENABLED"] = "0"
for key in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "INSTAGRAM_ACCESS_TOKEN",
            "INSTAGRAM_ACCESS_TOKEN_GELADEIRA", "INSTAGRAM_ACCESS_TOKEN_CERVEJEIROS",
            "OPENAI_API_KEY"):
    os.environ.pop(key, None)

from crm_entry import app, crm  # noqa: E402

with app.app_context():
    crm.db.create_all()


@app.before_request
def _block_everything_except_status():
    if request.path != "/homologacao/status" or request.method != "GET":
        return "Serviço de homologação: rota bloqueada", 404


@app.get("/homologacao/status")
def homologacao_status():
    from sqlalchemy import text
    with crm.db.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return jsonify(
        ambiente="homologacao",
        banco="sqlite_temporario_isolado",
        status="ok",
        integracoes_externas="desativadas",
        whatsapp="desativado",
        ia="desativada",
    ), 200
