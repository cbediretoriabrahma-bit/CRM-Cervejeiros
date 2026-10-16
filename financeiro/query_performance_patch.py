from datetime import date

from sqlalchemy import case, func, text

import performance_patch as perf
import dre_categories_patch as categories

app = perf.app
base = perf.base
core = perf.core
detailed = perf.detailed
Payable = perf.Payable
PayablePayment = perf.PayablePayment
Revenue = perf.Revenue
login_required = perf.login_required
CostDreClass = detailed.CostDreClass


# ---------------------------------------------------------------------------
# Consultas agregadas do DRE
# ---------------------------------------------------------------------------
def _normalize_stores(stores):
    if stores is None:
        return None
    if isinstance(stores, str):
        stores = [stores] if stores.strip() else []
    cleaned = [str(store).strip() for store in stores if str(store or "").strip()]
    return cleaned or None


def _build_dre_data(revenue_by_category, expense_by_category, personal_by_category, class_totals):
    total_revenue = float(sum(revenue_by_category.values()))
    total_expense = float(sum(expense_by_category.values()))
    personal_expense = float(class_totals.get("pessoal", 0) or 0)
    cmv = float(class_totals.get("cmv", 0) or 0)
    gross_profit = total_revenue - cmv
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    net_result = total_revenue - total_expense
    net_margin = (net_result / total_revenue * 100) if total_revenue else 0

    variable_for_contribution = (
        float(class_totals.get("cmv", 0) or 0)
        + float(class_totals.get("comercial", 0) or 0)
        + float(class_totals.get("impostos", 0) or 0)
    )
    contribution = total_revenue - variable_for_contribution
    contribution_margin = (contribution / total_revenue * 100) if total_revenue else 0
    fixed_for_breakeven = (
        float(class_totals.get("pessoal_empresa", 0) or 0)
        + float(class_totals.get("ocupacao", 0) or 0)
        + float(class_totals.get("administrativa", 0) or 0)
        + float(class_totals.get("financeira", 0) or 0)
        + float(class_totals.get("nao_classificado", 0) or 0)
    )
    contribution_ratio = contribution / total_revenue if total_revenue else 0
    breakeven = (fixed_for_breakeven / contribution_ratio) if contribution_ratio > 0 else 0
    classified_amount = total_expense - float(class_totals.get("nao_classificado", 0) or 0)
    classification_coverage = (classified_amount / total_expense * 100) if total_expense else 100

    expense_rows = [
        {
            "category": category,
            "amount": amount,
            "pct_revenue": (amount / total_revenue * 100) if total_revenue else 0,
            "pct_expense": (amount / total_expense * 100) if total_expense else 0,
        }
        for category, amount in sorted(expense_by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    class_rows = [
        {
            "key": key,
            "label": label,
            "amount": float(class_totals.get(key, 0) or 0),
            "pct_revenue": (float(class_totals.get(key, 0) or 0) / total_revenue * 100) if total_revenue else 0,
            "pct_expense": (
                float(class_totals.get(key, 0) or 0) / total_expense * 100
                if total_expense and key != "pessoal"
                else 0
            ),
        }
        for key, label in categories.NEW_DRE_CLASS_LABELS.items()
    ]

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
        "cash_outflow": total_expense + personal_expense,
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
        "unclassified": float(class_totals.get("nao_classificado", 0) or 0),
    }


def _compute_detailed_dre_fast(month, stores=None):
    start, end = core.parse_month(month)
    stores = _normalize_stores(stores)

    revenue_query = core.db.session.query(
        Revenue.category,
        func.coalesce(func.sum(Revenue.amount), 0),
    ).filter(
        Revenue.revenue_date >= start,
        Revenue.revenue_date < end,
    )
    if stores:
        revenue_query = revenue_query.filter(Revenue.store.in_(stores))
    revenue_rows = revenue_query.group_by(Revenue.category).all()
    revenue_by_category = {
        (category or "Outros"): float(amount or 0)
        for category, amount in revenue_rows
    }

    class_expr = func.coalesce(CostDreClass.dre_class, "nao_classificado")
    expense_query = core.db.session.query(
        Payable.category,
        class_expr.label("dre_class"),
        func.coalesce(func.sum(PayablePayment.amount), 0),
    ).join(
        Payable, Payable.id == PayablePayment.payable_id
    ).outerjoin(
        CostDreClass, CostDreClass.payable_id == Payable.id
    ).filter(
        PayablePayment.paid_date >= start,
        PayablePayment.paid_date < end,
    )
    if stores:
        expense_query = expense_query.filter(Payable.store.in_(stores))
    expense_rows_raw = expense_query.group_by(Payable.category, class_expr).all()

    expense_by_category = {}
    personal_by_category = {}
    class_totals = {key: 0.0 for key in categories.NEW_DRE_CLASS_LABELS}
    for category, dre_class, amount in expense_rows_raw:
        category = category or "Outros"
        amount = float(amount or 0)
        dre_class = categories.normalize_dre_class(dre_class)
        class_totals[dre_class] = class_totals.get(dre_class, 0.0) + amount
        if dre_class == "pessoal":
            personal_by_category[category] = personal_by_category.get(category, 0.0) + amount
        else:
            expense_by_category[category] = expense_by_category.get(category, 0.0) + amount

    return _build_dre_data(
        revenue_by_category,
        expense_by_category,
        personal_by_category,
        class_totals,
    )


def compute_detailed_dre_fast(month, store=""):
    return _compute_detailed_dre_fast(month, [store] if store else None)


# O painel otimizado consulta detailed.compute_detailed_dre em tempo de execução.
# Ao substituir aqui, ele deixa de carregar todos os pagamentos e contas em memória.
detailed.compute_detailed_dre = compute_detailed_dre_fast
detailed._compute_detailed_dre_for_stores = _compute_detailed_dre_fast


def _selected_stores(stores):
    selected = [s.strip() for s in core.request.args.getlist("store") if (s or "").strip()]
    valid = set(stores)
    return [store for store in selected if store in valid]


def _unit_summary_rows(month, stores):
    if not stores:
        return []
    start, end = core.parse_month(month)

    revenue_rows = core.db.session.query(
        Revenue.store,
        func.coalesce(func.sum(Revenue.amount), 0),
    ).filter(
        Revenue.revenue_date >= start,
        Revenue.revenue_date < end,
        Revenue.store.in_(stores),
    ).group_by(Revenue.store).all()
    revenue_map = {store: float(amount or 0) for store, amount in revenue_rows}

    class_expr = func.coalesce(CostDreClass.dre_class, "nao_classificado")
    expense_rows = core.db.session.query(
        Payable.store,
        class_expr.label("dre_class"),
        func.coalesce(func.sum(PayablePayment.amount), 0),
    ).join(
        Payable, Payable.id == PayablePayment.payable_id
    ).outerjoin(
        CostDreClass, CostDreClass.payable_id == Payable.id
    ).filter(
        PayablePayment.paid_date >= start,
        PayablePayment.paid_date < end,
        Payable.store.in_(stores),
    ).group_by(Payable.store, class_expr).all()

    class_by_store = {
        store: {key: 0.0 for key in categories.NEW_DRE_CLASS_LABELS}
        for store in stores
    }
    for store, dre_class, amount in expense_rows:
        if store not in class_by_store:
            continue
        normalized = categories.normalize_dre_class(dre_class)
        class_by_store[store][normalized] += float(amount or 0)

    rows = []
    for store in stores:
        revenue = revenue_map.get(store, 0.0)
        classes = class_by_store.get(store, {})
        personal = float(classes.get("pessoal", 0) or 0)
        total_paid = sum(float(value or 0) for value in classes.values())
        expense = total_paid - personal
        cmv = float(classes.get("cmv", 0) or 0)
        gross_profit = revenue - cmv
        gross_margin = (gross_profit / revenue * 100) if revenue else 0
        result = revenue - expense
        net_margin = (result / revenue * 100) if revenue else 0
        variable = cmv + float(classes.get("comercial", 0) or 0) + float(classes.get("impostos", 0) or 0)
        contribution = revenue - variable
        ratio = contribution / revenue if revenue else 0
        fixed = (
            float(classes.get("pessoal_empresa", 0) or 0)
            + float(classes.get("ocupacao", 0) or 0)
            + float(classes.get("administrativa", 0) or 0)
            + float(classes.get("financeira", 0) or 0)
            + float(classes.get("nao_classificado", 0) or 0)
        )
        breakeven = (fixed / ratio) if ratio > 0 else 0
        rows.append({
            "store": store,
            "revenue": revenue,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "expense": expense,
            "result": result,
            "net_margin": net_margin,
            "breakeven": breakeven,
        })
    return rows


def _dre_fast():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    stores = base.managed_stores(active_only=False)
    selected = _selected_stores(stores)
    data = _compute_detailed_dre_fast(month, selected or None)
    visible_stores = selected or stores
    unit_rows = _unit_summary_rows(month, visible_stores)
    context = dict(data)
    context.update({
        "stores": stores,
        "selected_stores": selected,
        "store_filter": "",
        "month": month,
        "unit_rows": unit_rows,
    })
    return core.render_template("dre.html", **context)


app.view_functions["dre"] = login_required(_dre_fast)


# ---------------------------------------------------------------------------
# Saúde financeira sem N+1 de contas/pagamentos por unidade.
# ---------------------------------------------------------------------------
def _financial_health_fast():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    start, end = core.parse_month(month)
    stores = base.managed_stores(active_only=False)
    selected = _selected_stores(stores)
    visible_stores = selected or stores

    if visible_stores:
        revenue_rows = core.db.session.query(
            Revenue.store,
            func.coalesce(func.sum(Revenue.amount), 0),
        ).filter(
            Revenue.revenue_date >= start,
            Revenue.revenue_date < end,
            Revenue.store.in_(visible_stores),
        ).group_by(Revenue.store).all()
        expense_rows = core.db.session.query(
            Payable.store,
            func.coalesce(func.sum(PayablePayment.amount), 0),
        ).join(
            Payable, Payable.id == PayablePayment.payable_id
        ).filter(
            PayablePayment.paid_date >= start,
            PayablePayment.paid_date < end,
            Payable.store.in_(visible_stores),
        ).group_by(Payable.store).all()
    else:
        revenue_rows = []
        expense_rows = []

    revenue_map = {store: float(amount or 0) for store, amount in revenue_rows}
    expense_map = {store: float(amount or 0) for store, amount in expense_rows}

    payment_totals = core.db.session.query(
        PayablePayment.payable_id.label("payable_id"),
        func.coalesce(func.sum(PayablePayment.amount), 0).label("paid_amount"),
    ).group_by(PayablePayment.payable_id).subquery()
    paid = func.coalesce(payment_totals.c.paid_amount, 0.0)
    raw_balance = Payable.total_amount - paid
    balance = case((raw_balance > 0, raw_balance), else_=0.0)

    overdue_query = core.db.session.query(
        Payable.store,
        func.coalesce(func.sum(balance), 0),
    ).outerjoin(
        payment_totals, payment_totals.c.payable_id == Payable.id
    ).filter(
        Payable.due_date < date.today(),
        raw_balance > 0.009,
    )
    if visible_stores:
        overdue_query = overdue_query.filter(Payable.store.in_(visible_stores))
    overdue_rows = overdue_query.group_by(Payable.store).all()
    overdue_map = {store: float(amount or 0) for store, amount in overdue_rows}

    rows = []
    for store in visible_stores:
        item = base.health_diagnosis(
            revenue_map.get(store, 0.0),
            expense_map.get(store, 0.0),
            overdue_map.get(store, 0.0),
        )
        item["store"] = store
        rows.append(item)

    consolidated = base.health_diagnosis(
        sum(row["revenue"] for row in rows),
        sum(row["expense"] for row in rows),
        sum(row["overdue"] for row in rows),
    )
    consolidated["store"] = "Lojas selecionadas" if selected else "Consolidado do Grupo"
    return core.render_template(
        "financial_health.html",
        month=month,
        stores=stores,
        selected_stores=selected,
        store_filter="",
        rows=rows,
        consolidated=consolidated,
    )


app.view_functions["financial_health"] = login_required(_financial_health_fast)


# ---------------------------------------------------------------------------
# Rotinas auxiliares pesadas apenas uma vez por processo.
# ---------------------------------------------------------------------------
_original_sync_wrapper = perf._optimized_sync_legacy_units
_sync_done = False


def _sync_once_per_process():
    global _sync_done
    if _sync_done:
        return None
    try:
        return _original_sync_wrapper()
    finally:
        _sync_done = True


_before = list(app.before_request_funcs.get(None, []))
app.before_request_funcs[None] = [
    _sync_once_per_process if fn is _original_sync_wrapper else fn
    for fn in _before
]


# ---------------------------------------------------------------------------
# Índices para os filtros que o Financeiro usa o tempo todo.
# São criados uma única vez e não alteram nenhum lançamento.
# ---------------------------------------------------------------------------
_indexes_checked = False


@app.before_request
def ensure_finance_indexes():
    global _indexes_checked
    if _indexes_checked:
        return None
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_payable_store_due_date ON payable (store, due_date)",
        "CREATE INDEX IF NOT EXISTS idx_payable_payment_paid_date_payable_id ON payable_payment (paid_date, payable_id)",
        "CREATE INDEX IF NOT EXISTS idx_finance_revenue_store_date ON finance_revenue (store, revenue_date)",
        "CREATE INDEX IF NOT EXISTS idx_finance_cost_dre_class_payable_id ON finance_cost_dre_class (payable_id)",
    ]
    try:
        with core.db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except Exception:
        # A aplicação continua funcionando mesmo se o banco não permitir DDL neste momento.
        pass
    _indexes_checked = True
    return None
