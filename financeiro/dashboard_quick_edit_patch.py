from datetime import date

import dre_categories_patch as categories

app = categories.app
base = categories.base
core = categories.core
detailed = categories.detailed
Payable = categories.Payable
RecurringCost = base.RecurringCost
RecurringOccurrence = base.RecurringOccurrence
login_required = categories.login_required

CATEGORY_SHORTCUTS = [
    ("CMV", ["CMV: Custo de mercadorias", "CMV: Custo de geladeiras"]),
    ("Despesas com pessoal", ["Pessoal empresa: Salários", "Pessoal empresa: Freelancer", "Pessoal empresa: Horas extras", "Pessoal empresa: Comissões", "Pessoal empresa: INSS", "Pessoal empresa: FGTS", "Pessoal empresa: Refeições"]),
    ("Despesas de ocupação", ["Ocupação: Aluguel", "Ocupação: Condomínio", "Ocupação: IPTU", "Ocupação: Energia elétrica", "Ocupação: Água", "Ocupação: Internet", "Ocupação: Telefone", "Ocupação: Segurança", "Ocupação: Limpeza"]),
    ("Despesas comerciais", ["Comercial: Marketing", "Comercial: Taxa de cartão", "Comercial: Propaganda", "Comercial: Ação de divulgação", "Comercial: Combustível", "Comercial: Manutenção de veículo", "Comercial: Manutenção de loja"]),
    ("Despesas administrativas", ["Administrativa: Contabilidade", "Administrativa: Sistema ERP", "Administrativa: Material de escritório", "Administrativa: Honorários advocatícios", "Administrativa: Licenças e alvarás"]),
    ("Despesas financeiras", ["Financeira: Juros", "Financeira: Antecipação de cartão"]),
    ("Impostos sobre vendas", ["Impostos: Simples Nacional", "Impostos: ICMS", "Impostos: ISS", "Impostos: PIS/COFINS", "Impostos: Outros impostos sobre vendas"]),
    ("Despesas pessoais", ["Despesa pessoal: Mercado", "Despesa pessoal: Farmácia", "Despesa pessoal: Passeio", "Despesa pessoal: Viagens", "Despesa pessoal: Escola", "Despesa pessoal: Pet Shop", "Despesa pessoal: Empregada", "Despesa pessoal: Compra na loja", "Despesa pessoal: Saúde", "Despesa pessoal: Unimed", "Despesa pessoal: Dentista", "Despesa pessoal: Parcelamento de imposto", "Despesa pessoal: Financiamento", "Despesa pessoal: Karina", "Despesa pessoal: iFood", "Despesa pessoal: Piscina", "Despesa pessoal: Cartão de crédito", "Despesa pessoal: Combustível", "Despesa pessoal: Energia elétrica", "Despesa pessoal: Água", "Despesa pessoal: Condomínio", "Despesa pessoal: Telefone", "Despesa pessoal: Internet"]),
]


def _dre_row(payable_id):
    return detailed.CostDreClass.query.filter_by(payable_id=payable_id).first()


def _occurrence(payable_id):
    return RecurringOccurrence.query.filter_by(payable_id=payable_id).first()


def dre_class_for(payable_id):
    row = _dre_row(payable_id)
    return categories.normalize_dre_class(row.dre_class if row else "nao_classificado")


def recurring_for(payable_id):
    occurrence = _occurrence(payable_id)
    if not occurrence:
        return False
    rule = RecurringCost.query.get(occurrence.recurring_cost_id)
    return bool(rule and rule.active)


@app.context_processor
def dashboard_edit_context():
    return {
        "dre_class_for": dre_class_for,
        "recurring_for": recurring_for,
        "dre_labels_quick": categories.NEW_DRE_CLASS_LABELS,
        "category_shortcuts": CATEGORY_SHORTCUTS,
    }


@app.route("/conta/<int:account_id>/categoria-rapida", methods=["POST"])
@login_required
def quick_update_category(account_id):
    account = Payable.query.get_or_404(account_id)
    category = core.request.form.get("category", "").strip()
    if not category:
        core.flash("Selecione uma categoria.", "danger")
        return core.redirect(core.request.referrer or core.url_for("dashboard"))
    account.category = category
    # Mantém a classificação do DRE sincronizada com o atalho escolhido.
    inferred = categories.infer_dre_class(category, account.description, account.supplier, account.notes)
    if inferred != "nao_classificado":
        row = _dre_row(account.id)
        if row:
            row.dre_class = inferred
        else:
            core.db.session.add(detailed.CostDreClass(payable_id=account.id, dre_class=inferred))
    occurrence = _occurrence(account.id)
    if occurrence:
        rule = RecurringCost.query.get(occurrence.recurring_cost_id)
        if rule:
            rule.category = category
            rclass = detailed.RecurringDreClass.query.filter_by(recurring_cost_id=rule.id).first()
            if inferred != "nao_classificado":
                if rclass:
                    rclass.dre_class = inferred
                else:
                    core.db.session.add(detailed.RecurringDreClass(recurring_cost_id=rule.id, dre_class=inferred))
    core.db.session.commit()
    core.flash("Categoria atualizada.", "success")
    return core.redirect(core.request.referrer or core.url_for("dashboard"))


@app.route("/conta/<int:account_id>/dre-rapido", methods=["POST"])
@login_required
def quick_update_dre(account_id):
    Payable.query.get_or_404(account_id)
    dre_class = categories.normalize_dre_class(core.request.form.get("dre_class"))
    row = _dre_row(account_id)
    if row:
        row.dre_class = dre_class
    else:
        core.db.session.add(detailed.CostDreClass(payable_id=account_id, dre_class=dre_class))
    occurrence = _occurrence(account_id)
    if occurrence:
        rclass = detailed.RecurringDreClass.query.filter_by(recurring_cost_id=occurrence.recurring_cost_id).first()
        if rclass:
            rclass.dre_class = dre_class
        else:
            core.db.session.add(detailed.RecurringDreClass(recurring_cost_id=occurrence.recurring_cost_id, dre_class=dre_class))
    core.db.session.commit()
    core.flash("Classificação do DRE atualizada.", "success")
    return core.redirect(core.request.referrer or core.url_for("dashboard"))


@app.route("/conta/<int:account_id>/recorrencia-rapida", methods=["POST"])
@login_required
def quick_toggle_recurring(account_id):
    account = Payable.query.get_or_404(account_id)
    occurrence = _occurrence(account.id)
    if occurrence:
        rule = RecurringCost.query.get(occurrence.recurring_cost_id)
        if rule and rule.active:
            rule.active = False
            core.db.session.commit()
            core.flash("Recorrência desativada. As contas já lançadas foram preservadas.", "success")
            return core.redirect(core.request.referrer or core.url_for("dashboard"))
        if rule:
            rule.active = True
            core.db.session.commit()
            base.materialize_recurring_costs()
            core.flash("Recorrência reativada.", "success")
            return core.redirect(core.request.referrer or core.url_for("dashboard"))

    rule = RecurringCost(
        store=account.store or "Geral",
        supplier=account.supplier,
        description=account.description,
        category=account.category or "Outros",
        total_amount=account.total_amount,
        due_day=account.due_date.day,
        document=account.document,
        notes=account.notes,
        start_date=account.due_date,
        end_date=None,
        active=True,
    )
    core.db.session.add(rule)
    core.db.session.flush()
    core.db.session.add(RecurringOccurrence(recurring_cost_id=rule.id, payable_id=account.id, due_date=account.due_date))
    current_class = dre_class_for(account.id)
    core.db.session.add(detailed.RecurringDreClass(recurring_cost_id=rule.id, dre_class=current_class))
    core.db.session.commit()
    base.materialize_recurring_costs()
    detailed.sync_recurring_dre_classes()
    core.flash("Conta marcada como recorrente. Os próximos vencimentos serão criados automaticamente.", "success")
    return core.redirect(core.request.referrer or core.url_for("dashboard"))
