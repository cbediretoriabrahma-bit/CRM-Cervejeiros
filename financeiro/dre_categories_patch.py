from datetime import date

import dre_hotfix as fixed

app = fixed.app
detailed = fixed.detailed
base = detailed.base
core = detailed.core
Payable = base.Payable
PayablePayment = base.PayablePayment
Revenue = base.Revenue
login_required = detailed.login_required

# Estrutura gerencial solicitada para o DRE.
NEW_DRE_CLASS_LABELS = {
    "cmv": "CMV",
    "pessoal_empresa": "Despesas com pessoal",
    "ocupacao": "Despesas de ocupação",
    "comercial": "Despesas comerciais",
    "administrativa": "Despesas administrativas",
    "financeira": "Despesas financeiras",
    "impostos": "Impostos sobre vendas",
    "pessoal": "Despesas pessoais (fora do DRE operacional)",
    "nao_classificado": "Não classificado",
}

# Compatibilidade com lançamentos antigos. Nada é apagado ou regravado no banco.
LEGACY_CLASS_MAP = {
    "fixa": "administrativa",
    "variavel": "comercial",
}

detailed.DRE_CLASS_LABELS.clear()
detailed.DRE_CLASS_LABELS.update(NEW_DRE_CLASS_LABELS)


def normalize_dre_class(value):
    value = (value or "").strip()
    value = LEGACY_CLASS_MAP.get(value, value)
    return value if value in NEW_DRE_CLASS_LABELS else "nao_classificado"


def infer_dre_class(category="", description="", supplier="", notes=""):
    text = detailed._plain(" ".join([category or "", description or "", supplier or "", notes or ""]))
    category_plain = detailed._plain(category or "")

    # Prefixos usados nos atalhos do cadastro dão prioridade e evitam ambiguidade.
    prefix_map = {
        "cmv:": "cmv",
        "pessoal empresa:": "pessoal_empresa",
        "ocupacao:": "ocupacao",
        "comercial:": "comercial",
        "administrativa:": "administrativa",
        "financeira:": "financeira",
        "impostos:": "impostos",
        "despesa pessoal:": "pessoal",
    }
    for prefix, dre_class in prefix_map.items():
        if category_plain.startswith(prefix):
            return dre_class

    personal_terms = [
        "mercado", "farmacia", "passeio", "viagem pessoal", "escola", "pet shop",
        "empregada", "compra pessoal", "saude pessoal", "unimed", "dentista",
        "parcelamento de imposto pessoal", "financiamento pessoal", "karina", "ifood",
        "piscina", "cartao de credito pessoal",
    ]
    if any(term in text for term in personal_terms):
        return "pessoal"

    cmv_terms = [
        "chopp", "chope", "cerveja", "barril", "bebida", "mercadoria", "estoque",
        "insumo", "materia prima", "co2", "gas carbonico", "copo", "growler",
        "gelo", "embalagem", "produto para revenda", "compra produto", "custo de geladeira",
    ]
    if any(term in text for term in cmv_terms):
        return "cmv"

    personnel_terms = [
        "salario", "folha", "freelancer", "hora extra", "comissao", "inss", "fgts",
        "refeicao", "vale refeicao", "vale alimentacao", "pro labore",
    ]
    if any(term in text for term in personnel_terms):
        return "pessoal_empresa"

    occupancy_terms = [
        "aluguel", "condominio", "iptu", "energia", "eletricidade", "agua", "internet",
        "telefone", "celular", "seguranca", "limpeza",
    ]
    if any(term in text for term in occupancy_terms):
        return "ocupacao"

    commercial_terms = [
        "marketing", "propaganda", "acao de divulgacao", "taxa cartao", "taxa de cartao",
        "maquininha", "adquirente", "taxa pix", "combustivel", "manutencao de veiculo",
        "manutencao veiculo", "manutencao de loja", "manutencao loja", "frete", "entrega", "motoboy",
    ]
    if any(term in text for term in commercial_terms):
        return "comercial"

    admin_terms = [
        "contabilidade", "contador", "sistema erp", "software", "material de escritorio",
        "honorario advocaticio", "advogado", "licenca", "alvara", "royalty", "royalties",
        "mensalidade", "administrativo",
    ]
    if any(term in text for term in admin_terms):
        return "administrativa"

    financial_terms = [
        "juros", "tarifa bancaria", "tarifa banco", "taxa bancaria", "antecipacao",
        "emprestimo", "multa bancaria", "encargo financeiro",
    ]
    if any(term in text for term in financial_terms):
        return "financeira"

    tax_terms = [
        "imposto sobre venda", "simples nacional", " das ", "darf", "icms", "iss",
        "ipi", "pis", "cofins", "irpj", "csll", "tributo sobre venda",
    ]
    padded = f" {text} "
    if any(term in padded for term in tax_terms):
        return "impostos"

    return "nao_classificado"


detailed.normalize_dre_class = normalize_dre_class
detailed.infer_dre_class = infer_dre_class


def _class_map(payable_ids):
    if not payable_ids:
        return {}
    rows = detailed.CostDreClass.query.filter(detailed.CostDreClass.payable_id.in_(payable_ids)).all()
    return {row.payable_id: normalize_dre_class(row.dre_class) for row in rows}


detailed._class_map = _class_map


def compute_detailed_dre(month, store=""):
    start, end = core.parse_month(month)
    rq = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end)
    pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= start, PayablePayment.paid_date < end)
    if store:
        rq = rq.filter(Revenue.store == store)
        pq = pq.filter(Payable.store == store)

    revenues = rq.all()
    payments = pq.all()
    revenue_by_category = {}
    expense_by_category = {}
    personal_by_category = {}
    for r in revenues:
        category = r.category or "Outros"
        revenue_by_category[category] = revenue_by_category.get(category, 0) + (r.amount or 0)

    payable_ids = list({p.payable_id for p in payments})
    classes = _class_map(payable_ids)
    class_totals = {key: 0.0 for key in NEW_DRE_CLASS_LABELS}

    for p in payments:
        category = p.payable.category or "Outros"
        amount = p.amount or 0
        dre_class = classes.get(p.payable_id, "nao_classificado")
        class_totals[dre_class] += amount
        if dre_class == "pessoal":
            personal_by_category[category] = personal_by_category.get(category, 0) + amount
        else:
            expense_by_category[category] = expense_by_category.get(category, 0) + amount

    total_revenue = sum(revenue_by_category.values())
    total_expense = sum(expense_by_category.values())
    personal_expense = class_totals["pessoal"]
    cash_outflow = total_expense + personal_expense
    cmv = class_totals["cmv"]
    gross_profit = total_revenue - cmv
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    net_result = total_revenue - total_expense
    net_margin = (net_result / total_revenue * 100) if total_revenue else 0

    # Para ponto de equilíbrio, CMV + comercial + impostos são tratados como variáveis.
    variable_for_contribution = class_totals["cmv"] + class_totals["comercial"] + class_totals["impostos"]
    contribution = total_revenue - variable_for_contribution
    contribution_margin = (contribution / total_revenue * 100) if total_revenue else 0
    fixed_for_breakeven = (
        class_totals["pessoal_empresa"] + class_totals["ocupacao"] +
        class_totals["administrativa"] + class_totals["financeira"] +
        class_totals["nao_classificado"]
    )
    contribution_ratio = contribution / total_revenue if total_revenue else 0
    breakeven = (fixed_for_breakeven / contribution_ratio) if contribution_ratio > 0 else 0
    classified_amount = total_expense - class_totals["nao_classificado"]
    classification_coverage = (classified_amount / total_expense * 100) if total_expense else 100

    expense_rows = [{
        "category": category,
        "amount": amount,
        "pct_revenue": (amount / total_revenue * 100) if total_revenue else 0,
        "pct_expense": (amount / total_expense * 100) if total_expense else 0,
    } for category, amount in sorted(expense_by_category.items(), key=lambda item: item[1], reverse=True)]

    class_rows = [{
        "key": key,
        "label": label,
        "amount": class_totals[key],
        "pct_revenue": (class_totals[key] / total_revenue * 100) if total_revenue else 0,
        "pct_expense": (class_totals[key] / total_expense * 100) if total_expense and key != "pessoal" else 0,
    } for key, label in NEW_DRE_CLASS_LABELS.items()]

    return {
        "revenue_by_category": revenue_by_category,
        "expense_by_category": expense_by_category,
        "personal_by_category": personal_by_category,
        "expense_rows": expense_rows,
        "class_rows": class_rows,
        "class_totals": class_totals,
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "personal_expense": personal_expense,
        "cash_outflow": cash_outflow,
        "cmv": cmv,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "net_result": net_result,
        "net_margin": net_margin,
        "contribution": contribution,
        "contribution_margin": contribution_margin,
        "fixed_for_breakeven": fixed_for_breakeven,
        "breakeven": breakeven,
        "classification_coverage": classification_coverage,
        "unclassified": class_totals["nao_classificado"],
    }


detailed.compute_detailed_dre = compute_detailed_dre


def _merge_dre_rows(rows):
    revenue_by_category = {}
    expense_by_category = {}
    personal_by_category = {}
    class_totals = {key: 0.0 for key in NEW_DRE_CLASS_LABELS}
    for row in rows:
        for key, value in row["revenue_by_category"].items():
            revenue_by_category[key] = revenue_by_category.get(key, 0) + value
        for key, value in row["expense_by_category"].items():
            expense_by_category[key] = expense_by_category.get(key, 0) + value
        for key, value in row.get("personal_by_category", {}).items():
            personal_by_category[key] = personal_by_category.get(key, 0) + value
        for key in class_totals:
            class_totals[key] += row["class_totals"].get(key, 0)

    total_revenue = sum(revenue_by_category.values())
    total_expense = sum(expense_by_category.values())
    personal_expense = class_totals["pessoal"]
    cmv = class_totals["cmv"]
    gross_profit = total_revenue - cmv
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    net_result = total_revenue - total_expense
    net_margin = (net_result / total_revenue * 100) if total_revenue else 0
    variable = class_totals["cmv"] + class_totals["comercial"] + class_totals["impostos"]
    contribution = total_revenue - variable
    contribution_margin = (contribution / total_revenue * 100) if total_revenue else 0
    fixed = class_totals["pessoal_empresa"] + class_totals["ocupacao"] + class_totals["administrativa"] + class_totals["financeira"] + class_totals["nao_classificado"]
    ratio = contribution / total_revenue if total_revenue else 0
    breakeven = (fixed / ratio) if ratio > 0 else 0
    classified = total_expense - class_totals["nao_classificado"]
    coverage = (classified / total_expense * 100) if total_expense else 100
    expense_rows = [{"category": c, "amount": a, "pct_revenue": (a / total_revenue * 100) if total_revenue else 0, "pct_expense": (a / total_expense * 100) if total_expense else 0} for c, a in sorted(expense_by_category.items(), key=lambda x: x[1], reverse=True)]
    class_rows = [{"key": k, "label": label, "amount": class_totals[k], "pct_revenue": (class_totals[k] / total_revenue * 100) if total_revenue else 0, "pct_expense": (class_totals[k] / total_expense * 100) if total_expense and k != "pessoal" else 0} for k, label in NEW_DRE_CLASS_LABELS.items()]
    return {"revenue_by_category": revenue_by_category, "expense_by_category": expense_by_category, "personal_by_category": personal_by_category, "expense_rows": expense_rows, "class_rows": class_rows, "class_totals": class_totals, "total_revenue": total_revenue, "total_expense": total_expense, "personal_expense": personal_expense, "cash_outflow": total_expense + personal_expense, "cmv": cmv, "gross_profit": gross_profit, "gross_margin": gross_margin, "net_result": net_result, "net_margin": net_margin, "contribution": contribution, "contribution_margin": contribution_margin, "fixed_for_breakeven": fixed, "breakeven": breakeven, "classification_coverage": coverage, "unclassified": class_totals["nao_classificado"]}


def dre_multi_store_updated():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    selected = [s.strip() for s in core.request.args.getlist("store") if (s or "").strip()]
    stores = base.managed_stores(active_only=False)
    valid = set(stores)
    selected = [s for s in selected if s in valid]

    if not selected:
        data = compute_detailed_dre(month, "")
    elif len(selected) == 1:
        data = compute_detailed_dre(month, selected[0])
    else:
        data = _merge_dre_rows([compute_detailed_dre(month, store) for store in selected])

    visible_stores = selected or stores
    unit_rows = []
    for store in visible_stores:
        unit = compute_detailed_dre(month, store)
        unit_rows.append({"store": store, "revenue": unit["total_revenue"], "gross_profit": unit["gross_profit"], "gross_margin": unit["gross_margin"], "expense": unit["total_expense"], "result": unit["net_result"], "net_margin": unit["net_margin"], "breakeven": unit["breakeven"]})

    context = dict(data)
    context.update({"stores": stores, "selected_stores": selected, "store_filter": "", "month": month, "unit_rows": unit_rows})
    return core.render_template("dre.html", **context)


app.view_functions["dre"] = login_required(dre_multi_store_updated)
