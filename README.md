# CRM Cervejeiros Completo

Versão ampliada para expansão e qualificação de leads.

## Inclui
- CRM multiusuário: administrador, gerente e vendedor
- Distribuição automática round-robin
- Qualificação automática por score
- Pipeline Kanban
- IA comercial via OpenAI Responses API
- Resposta automática por regras caso a IA não esteja configurada
- WhatsApp: link pronto + integração preparada para WhatsApp Business Cloud
- Webhook para mensagens recebidas do WhatsApp
- Auto-resposta opcional
- Agenda, reuniões e follow-ups
- Página pública `/captura`
- API `/api/lead` para formulário/site
- Importação e exportação CSV
- Relatórios por origem, UF, etapa, temperatura e vendedor
- Conversão e valor fechado por vendedor
- Histórico de contatos e logs de automação
- PWA instalável no celular

## Acesso inicial
admin@cervejeiros.com.br
senha: 1234

## Produção
Use PostgreSQL no Render e configure as variáveis do `.env.example`.

## WhatsApp
Para envio automático, use conta WhatsApp Business Cloud oficial e configure:
WHATSAPP_TOKEN
WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_VERIFY_TOKEN

AUTO_REPLY_WHATSAPP=1 ativa a resposta automática a mensagens recebidas.

## IA
Configure OPENAI_API_KEY. O projeto usa a Responses API e o modelo é configurável por OPENAI_MODEL.
