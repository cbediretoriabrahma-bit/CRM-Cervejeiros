"""Ambiente de homologacao isolado do CRM Cervejeiros.

Por padrao bloqueia todas as rotas, exceto /homologacao/status.
Para uma integracao real com NUMERO DE TESTE DA META:
- configurar no Render as variaveis HOMOLOGACAO_* e META_APP_SECRET;
- manter banco separado SQLite (nunca carregar DATABASE_URL da producao);
- ligar HOMOLOGACAO_LIVE_TEST=1 apenas depois de configurar TUDO;
- apenas 1 remetente/destinatario explicitamente permitido.
"""
import os
import hmac

from flask import jsonify, request

os.environ["DATABASE_URL"] = "sqlite:////tmp/cervejeiros_homologacao_isolada.db"
os.environ["AUTO_REPLY_INSTAGRAM"] = "0"
os.environ["AUTO_REPLY_WHATSAPP"] = "0"
os.environ["AI_WHATSAPP_ENABLED"] = "0"
os.environ["AI_MEETING_ENABLED"] = "0"

def _digits(value):
    return "".join(c for c in (value or "") if c.isdigit())


def _credentials_ready():
    needed = (
        "HOMOLOGACAO_META_TEST_TOKEN",
        "HOMOLOGACAO_META_TEST_PHONE_ID",
        "HOMOLOGACAO_ALLOWED_NUMBER",
        "META_APP_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
        "OPENAI_API_KEY",
    )
    return all(os.getenv(k, "").strip() for k in needed)


LIVE = os.getenv("HOMOLOGACAO_LIVE_TEST") == "1" and _credentials_ready()

# A homologacao NUNCA usa as credenciais oficiais compartilhadas com producao.
# Se faltar algum item, qualquer envio permanece desligado.
if LIVE:
    os.environ["WHATSAPP_TOKEN"] = os.environ["HOMOLOGACAO_META_TEST_TOKEN"]
    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = os.environ["HOMOLOGACAO_META_TEST_PHONE_ID"]
    os.environ["AUTO_REPLY_WHATSAPP"] = "1"
    os.environ["AI_WHATSAPP_ENABLED"] = "1"
    os.environ["AI_MEETING_ENABLED"] = "1"
else:
    for key in (
        "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "OPENAI_API_KEY",
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN_GELADEIRA",
        "INSTAGRAM_ACCESS_TOKEN_CERVEJEIROS",
    ):
        os.environ.pop(key, None)

from crm_entry import app, crm  # noqa: E402

with app.app_context():
    crm.db.create_all()

# Dupla protecao: mesmo que o webhook seja chamado internamente,
# nenhum envio sai do ambiente exceto para o numero permitido.
_original_send = crm.send_whatsapp_cloud


def _send_only_to_test_number(phone, message):
    allowed = _digits(os.getenv("HOMOLOGACAO_ALLOWED_NUMBER"))
    if not LIVE or not allowed or _digits(phone) != allowed:
        app.logger.warning("Homologacao bloqueou envio para destinatario nao permitido")
        return False, "Destinatario nao autorizado"
    return _original_send(phone, message)


crm.send_whatsapp_cloud = _send_only_to_test_number


@app.before_request
def _isolation_guard():
    if request.method == "GET" and request.path == "/homologacao/status":
        return None
    # Validar a URL na Meta nao habilita recebimento nem envios.
    if request.path == "/webhooks/whatsapp" and request.method == "GET":
        expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
        provided = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        if (expected and provided and challenge
                and request.args.get("hub.mode") == "subscribe"
                and hmac.compare_digest(provided.encode(), expected.encode())):
            return challenge, 200
        return "verification failed", 403
    if request.path != "/webhooks/whatsapp" or not LIVE:
        return "Servico de homologacao: rota bloqueada", 404
    if request.method == "GET":
        return None  # desafio de verificacao gerido pelo webhook do CRM
    if request.method != "POST":
        return "Metodo nao autorizado", 405

    # Nao permitir que esta URL seja usada como webhook de producao.
    # A assinatura HMAC sera validada pela rota _verified_webhook.
    value = (
        ((request.get_json(silent=True) or {}).get("entry") or [{}])[0]
        .get("changes", [{}])[0].get("value") or {}
    )
    meta = value.get("metadata") or {}
    if _digits(meta.get("phone_number_id")) != _digits(
        os.getenv("HOMOLOGACAO_META_TEST_PHONE_ID")
    ):
        return "Numero Meta nao autorizado", 403
    messages = value.get("messages") or []
    if not messages or any(
        _digits(m.get("from")) != _digits(os.getenv("HOMOLOGACAO_ALLOWED_NUMBER"))
        for m in messages
    ):
        return "Remetente nao autorizado", 403
    return None


@app.get("/homologacao/status")
def homologacao_status():
    from sqlalchemy import text
    with crm.db.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return jsonify(
        ambiente="homologacao",
        banco="sqlite_temporario_isolado",
        status="ok",
        whatsapp_teste="habilitado" if LIVE else "desativado",
        ia_teste="habilitada" if LIVE else "desativada",
        credenciais_teste="completas" if _credentials_ready() else "pendentes",
        rotas_comerciais="bloqueadas",
    ), 200
