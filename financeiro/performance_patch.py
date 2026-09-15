from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import selectinload

import multi_store_filter_patch as multi

app = multi.app
base = multi.base
core = multi.core
detailed = multi.detailed
Payable = multi.Payable
PayablePayment = multi.PayablePayment
Revenue = multi.Revenue
login_required = multi.login_required


# ---------------------------------------------------------------------------
# 1) Evita rotinas pesadas de inicialização a cada clique/requisição.
#    Elas continuam existindo, mas rodam apenas quando necessário.
# ---------------------------------------------------------------------------
_original_bootstrap = core.bootstrap
_original_sync_legacy_units = base.sync_legacy_units
_bootstrap_done = False
_last_daily_sync = None


def _optimized_bootstrap():
    global _bootstrap_done
    if _bootstrap_done:
        return None
    result = _original_bootstrap()
    _bootstrap_done = True
    return result


def _optimized_sync_legacy_units():
    global _last_daily_sync
    today = date.today()
    if _last_daily_sync == today:
        return None
    result = _original_sync_legacy_units()
    _last_daily_sync = today
    return result


_before = list(app.before_request_funcs.get(None, []))
app.before_request_funcs[None] = [
    _optimized_bootstrap if fn is _original_bootstrap else
    _optimized_sync_legacy_units if fn is _original_sync_legacy_units else
    fn
    for fn in _before
]


# ---------------------------------------------------------------------------
# 2) Painel/Contas a pagar otimizado.
#    - carrega os pagamentos das contas em lote (elimina N+1 queries);
#    - usa SUM no banco para receitas/despesas do mês;
#    - monta resumo por unidade com GROUP BY, em vez de 2 consultas por loja.
#    Nenhum lançamento ou regra financeira é alterado.
# ---------------------------------------------------------------------------
def _sum_scalar(query):
    value = query.scalar()
    return float(value or 0)


def _dashboard_fast():
    status_filter = core.request.args.get("status", "")
    selected_stores = multi._selected_stores()
    search = core.request.args.get("q", "").strip()
    date_from_raw = core.request.args.get("date_from", "")
    date_to_raw = core.request.args.get("date_to", "")
    date_from = core.parse_date(date_from_raw)
    date_to = core.parse_date(date_to_raw)
    month_raw = core.request.args.get("month", date.today().strftime("%Y-%m"))
    month_start, month_end = core.parse_month(month_raw)

    q = Payable.query.options(selectinload(Payable.payments))
    if search:
        like = f"%{search}%"
        q = q.filter(core.db.or_(
            Payable.supplier.ilike(like),
            Payable.description.ilike(like),
            Payable.category.ilike(like),
            Payable.store.ilike(like),
        ))
    if selected_stores:
        q = q.filter(Payable.store.in_(selected_stores))
    if date_from:
        q = q.filter(Payable.due_date >= date_from)
    if date_to:
        q = q.filter(Payable.due_date <= date_to)

    accounts = q.order_by(Payable.due_date.asc(), Payable.id.desc()).all()
    if status_filter:
        accounts = [a for a in accounts if a.status == status_filter]

    filtered_total = sum(a.total_amount or 0 for a in accounts)
    filtered_paid = sum(a.paid_amount for a in accounts)
    filtered_balance = sum(a.balance for a in accounts)
    overdue_total = sum(a.balance for a in accounts if a.status in ("Vencido", "Parcial vencido"))
    due_7_total = sum(a.balance for a in accounts if a.status in ("Vence em 3 dias", "Vence em 7 dias"))
    overdue_count = sum(1 for a in accounts if a.status in ("Vencido", "Parcial vencido"))

    revenue_q = core.db.session.query(func.coalesce(func.sum(Revenue.amount), 0)).filter(
        Revenue.revenue_date >= month_start,
        Revenue.revenue_date < month_end,
    )
    expense_q = core.db.session.query(func.coalesce(func.sum(PayablePayment.amount), 0)).join(Payable).filter(
        PayablePayment.paid_date >= month_start,
        PayablePayment.paid_date < month_end,
    )
    if selected_stores:
        revenue_q = revenue_q.filter(Revenue.store.in_(selected_stores))
        expense_q = expense_q.filter(Payable.store.in_(selected_stores))

    revenue_month = _sum_scalar(revenue_q)
    expense_month = _sum_scalar(expense_q)
    result_month = revenue_month - expense_month

    # Mantém exatamente os indicadores gerenciais existentes.
    if selected_stores:
        dre_rows = [detailed.compute_detailed_dre(month_raw, store) for store in selected_stores]
        cmv_month = sum(row.get("cmv", 0) or 0 for row in dre_rows)
    else:
        consolidated_dre = detailed.compute_detailed_dre(month_raw, "")
        cmv_month = consolidated_dre.get("cmv", 0) or 0

    gross_profit_month = revenue_month - cmv_month
    cmv_pct = (cmv_month / revenue_month * 100) if revenue_month else 0
    gross_margin_pct = (gross_profit_month / revenue_month * 100) if revenue_month else 0
    net_profit_month = result_month
    net_margin_pct = (net_profit_month / revenue_month * 100) if revenue_month else 0

    stores = base.managed_stores(active_only=False)
    visible_stores = selected_stores or stores

    rev_rows = core.db.session.query(
        Revenue.store,
        func.coalesce(func.sum(Revenue.amount), 0),
    ).filter(
        Revenue.revenue_date >= month_start,
        Revenue.revenue_date < month_end,
    )
    exp_rows = core.db.session.query(
        Payable.store,
        func.coalesce(func.sum(PayablePayment.amount), 0),
    ).join(Payable).filter(
        PayablePayment.paid_date >= month_start,
        PayablePayment.paid_date < month_end,
    )

    if visible_stores:
        rev_rows = rev_rows.filter(Revenue.store.in_(visible_stores))
        exp_rows = exp_rows.filter(Payable.store.in_(visible_stores))

    rev_map = {store: float(total or 0) for store, total in rev_rows.group_by(Revenue.store).all()}
    exp_map = {store: float(total or 0) for store, total in exp_rows.group_by(Payable.store).all()}

    unit_rows = []
    for store in visible_stores:
        rev = rev_map.get(store, 0.0)
        exp = exp_map.get(store, 0.0)
        unit_rows.append({
            "store": store,
            "revenue": round(rev, 2),
            "expense": round(exp, 2),
            "result": round(rev - exp, 2),
        })

    return core.render_template(
        "dashboard.html",
        accounts=accounts,
        filtered_total=filtered_total,
        filtered_paid=filtered_paid,
        filtered_balance=filtered_balance,
        overdue_total=overdue_total,
        due_7_total=due_7_total,
        overdue_count=overdue_count,
        status_filter=status_filter,
        store_filter="",
        selected_stores=selected_stores,
        stores=stores,
        search=search,
        date_from=date_from_raw,
        date_to=date_to_raw,
        today=date.today(),
        month=month_start.strftime("%Y-%m"),
        revenue_month=revenue_month,
        expense_month=expense_month,
        result_month=result_month,
        cmv_month=cmv_month,
        cmv_pct=cmv_pct,
        gross_profit_month=gross_profit_month,
        gross_margin_pct=gross_margin_pct,
        net_profit_month=net_profit_month,
        net_margin_pct=net_margin_pct,
        unit_rows=unit_rows,
    )


app.view_functions["dashboard"] = login_required(_dashboard_fast)
