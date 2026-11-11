# Implantação da IA para WhatsApp — CRM Cervejeiros

## Situação
Módulo opcional `ai_whatsapp_patch.py` carregado por `crm_entry.py`.
Não há envio automático por padrão. Não alterar a branch principal sem homologação.

## Variáveis necessárias no Render
- `AI_WHATSAPP_ENABLED=1`: usar IA no webhook, apenas após revisão/testes.
- `AUTO_REPLY_WHATSAPP=1`: permitir o envio automático (existente no CRM).
- `AI_MEETING_ENABLED=1`: ativar o agendamento real da primeira reunião pela IA, somente após testes; padrão desligado.
- `OPENAI_API_KEY`: chave secreta da API OpenAI.
- `OPENAI_MODEL`: modelo habilitado para a conta.
- `WHATSAPP_TOKEN`: token da WhatsApp Cloud API.
- `WHATSAPP_PHONE_NUMBER_ID`: número associado à API.
- `WHATSAPP_VERIFY_TOKEN`: token de verificação do webhook.
- `META_APP_SECRET`: segredo da aplicação Meta para validar a assinatura SHA-256.

Guarde todas as credenciais exclusivamente em variáveis de ambiente; não registre segredos no GitHub.

## Comportamento da primeira versão
- Com `AI_WHATSAPP_ENABLED=0`, preserva o roteiro anterior.
- Com `AI_WHATSAPP_ENABLED=1`, responde perguntas abertas utilizando OpenAI e o histórico recente do lead.
- Evita atualizar cidade, estado e investimento com base na posição da mensagem; isso exige extração estruturada, ainda não implementada.
- Interrompe respostas automáticas após solicitação de humano ou pedido de não contato.
- Com `AI_MEETING_ENABLED=1` (além do modo IA), oferece 2 horários de manhã e 2 à tarde, considerando as tarefas de reunião pendentes do CRM, e confirma a 1ª reunião apenas quando conseguir gravá-la. O bloqueio reservado no CRM é de 1 hora, embora a apresentação comercial possa durar cerca de 5 minutos.
- Sem `AI_MEETING_ENABLED=1`, segue sem agendamento automático.
- O cliente escolhe uma das opções numeradas (1 a 4). A agenda é reconsultada na confirmação; se o horário estiver indisponível, são oferecidas novas opções.
- Para segurança contra agendamentos simultâneos da própria IA, o módulo usa bloqueio transacional PostgreSQL. Fluxos de agendamento manuais devem ser auditados para proteção equivalente.
- Caso a OpenAI falhe, não envia uma resposta improvisada.
- Verifica assinatura do webhook quando o modo IA está ativo.
- Respeita o controle já existente `AUTO_REPLY_WHATSAPP`.
- Não inclui painel de configurações, fila de mensagens ou integração com agenda externa neste primeiro passo.

## Checklist de homologação
1. Realizar backup do banco PostgreSQL e conferir restauração em ambiente de teste.
2. Criar ambiente de teste no Render, com número WhatsApp de testes.
3. Configurar Meta Cloud API e assinatura do webhook.
4. Conferir login administrativo e trocar senha inicial caso ainda exista.
5. Manter `AI_WHATSAPP_ENABLED=0` e validar CRM existente sem regressões.
6. Ativar `AI_WHATSAPP_ENABLED=1` apenas no teste; validar cenários:
   - Dúvidas livres sobre modelo/condomínios e ausência de preço aprovado.
   - Mensagens repetidas, histórico, recuperação após erro e atendimento humano.
   - Pedido de cancelamento e retomada: não responder automaticamente.
   - Assinatura inválida: receber HTTP 403.
   - Reunião: oferta de horários livres, escolha numérica e registro de `Task` pendente com estágio `Reunião Agendada`.
   - Tentar escolher horário já ocupado: oferecer novas opções sem registrar tarefa duplicada.
   - Simular dois clientes reservando a mesma hora e lead tentando confirmar reunião pela segunda vez.
   - Com `AI_MEETING_ENABLED=0`, não registrar reuniões automaticamente.
7. Conferir gastos, latência e privacidade de dados enviados à OpenAI.
8. Inspecionar logs, adaptar para tráfego concorrente, segurança e limites de envio.
9. Só após revisão e aprovação, promover branch para produção.

## Próximas melhorias
- Registrar campos estruturados com validação, sem contagem de mensagens.
- Painel de liga/desliga, assumir atendimento e revisar respostas.
- Melhorar a interpretação de datas livres e integração futura com Google Calendar, se necessário, preservando a agenda existente.
- Fila de trabalhos, idempotência transacional e tratamento resiliente de webhooks.
- Opt-out e regras de modelos aprovados fora da janela do WhatsApp.
- Auditoria de consentimento, retenção e políticas LGPD.

Observação: o webhook legado registra mensagens processadas antes de enviar resposta;
erros no envio podem exigir reprocessamento manual. Revisar na próxima etapa.
