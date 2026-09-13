"""Complemento de inicialização: reforça a apresentação comercial antes da reunião."""

try:
    import patched_app as p
except Exception:
    p = None

if p is not None:
    crm = p.crm
    _reply_anterior = p._qualification_reply

    def _qualification_reply_com_prova_social(lead, channel):
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel=channel, direction="in"
        ).count()
        first = (lead.name or "Olá").split()[0]

        if inbound_count == 9:
            return (
                f"{first}, antes de avançarmos, quero te mostrar rapidamente por que o modelo Cervejeiros vem crescendo tanto. 🍻\n\n"
                "Hoje já contamos com mais de 158 geladeiras instaladas em condomínios e clubes, operadas tanto pela própria Cervejeiros quanto por nossos licenciados.\n\n"
                "Já temos operações e licenciados em São Paulo, interior de São Paulo, Rio de Janeiro, Minas Gerais, Amazonas e Goiás, mostrando que o modelo pode ser replicado em diferentes regiões e perfis de mercado.\n\n"
                "A operação foi desenvolvida para ser simples, tecnológica e escalável:\n\n"
                "✅ Sem necessidade de funcionário no ponto\n"
                "✅ Operação 24 horas\n"
                "✅ Gestão de vendas e acompanhamento pelo sistema\n"
                "✅ Suporte para implantação e operação\n"
                "✅ Baixo custo operacional\n"
                "✅ Possibilidade de expansão para novas geladeiras e novos pontos\n"
                "✅ Modelo já validado em condomínios e clubes\n\n"
                "Em operações com bom desempenho, o payback pode ocorrer a partir de aproximadamente 4 meses, variando conforme localização, volume de vendas e execução da operação.\n\n"
                "É um modelo indicado para quem busca uma operação prática, escalável e com potencial de boa rentabilidade, sem a complexidade de um negócio tradicional com funcionários no local.\n\n"
                "Gostaria de falar com um de nossos consultores para conhecer os planos, valores e entender qual formato faz mais sentido para você?"
            )

        return _reply_anterior(lead, channel)

    p._qualification_reply = _qualification_reply_com_prova_social
    p._reply_for_message = lambda lead, text: _qualification_reply_com_prova_social(lead, "WhatsApp")
    p._reply_for_instagram = lambda lead: _qualification_reply_com_prova_social(lead, "Instagram")
