from datetime import date, timedelta

from sqlalchemy import case, func
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
# 2) Painel otimizado.
#    - por padrão mostra somente o mês financeiro escolhido;
#    - pagina 50 contas por vez;
#    - calcula totais no banco, sem carregar todo o histórico;
#    - carrega pagamentos somente das contas visíveis na página;
#    - mantém filtros, DRE, gráficos e totais gerais do período.
# ---------------------------------------------------------------------------
def _sum_scalar(query):
    value = query.scalar()
    return float(value or 0)


def _status_predicate(status, paid, balance, today):
    if not status:
        return None
    if status == "Pago":
        return balance <= 0.009
    if status == "Parcial vencido":
        return core.db.and_(balance > 0.009, paid > 0, Payable.due_date < today)
    if status == "Parcial":
        return core.db.and_(balance > 0.009, paid > 0, Payable.due_date >= today)
    if status == "Vencido":
        return core.db.and_(balance > 0.009, paid <= 0.009, Payable.due_date < today)
    if status == "Vence em 3 dias":
        return core.db.and_(
            balance > 0.009,
            paid <= 0.009,
            Payable.due_date >= today,
            Payable.due_date <= today + timedelta(days=3),
        )
    if status == "Vence em 7 dias":
        return core.db.and_(
            balance > 0.009,
            paid <= 0.009,
            Payable.due_date > today + timedelta(days=3),
            Payable.due_date <= today + timedelta(days=7),
        )
    if status == "A vencer":
        return core.db.and_(
            balance > 0.009,
            paid <= 0.009,
            Payable.due_date > today + timedelta(days=7),
        )
    return None


def _apply_account_filters(query, selected_stores, search, date_from, date_to):
    if search:
        like = f"%{search}%"
        query = query.filter(core.db.or_(
            Payable.supplier.ilike(like),
            Payable.description.ilike(like),
            Payable.category.ilike(like),
            Payable.store.ilike(like),
        ))
    if selected_stores:
        query = query.filter(Payable.store.in_(selected_stores))
    if date_from:
        query = query.filter(Payable.due_date >= date_from)
    if date_to:
        query = query.filter(Payable.due_date <= date_to)
    return query


def _dashboard_fast():
    today = date.today()
    status_filter = core.request.args.get("status", "")
    selected_stores = multi._selected_stores()
    search = core.request.args.get("q", "").strip()
    month_raw = core.request.args.get("month", today.strftime("%Y-%m"))
    month_start, month_end = core.parse_month(month_raw)

    # Se o usuário não informar um intervalo manual, a lista abre somente no mês escolhido.
    date_from_raw = core.request.args.get("date_from", "").strip()
    date_to_raw = core.request.args.get("date_to", "").strip()
    if not date_from_raw and not date_to_raw:
        date_from = month_start
        date_to = month_end - timedelta(days=1)
        date_from_display = date_from.isoformat()
        date_to_display = date_to.isoformat()
    else:
        date_from = core.parse_date(date_from_raw)
        date_to = core.parse_date(date_to_raw)
        date_from_display = date_from_raw
        date_to_display = date_to_raw

    try:
        page = max(int(core.request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    per_page = 50

    payment_totals = core.db.session.query(
        PayablePayment.payable_id.label("payable_id"),
        func.coalesce(func.sum(PayablePayment.amount), 0).label("paid_amount"),
    ).group_by(PayablePayment.payable_id).subquery()

    paid = func.coalesce(payment_totals.c.paid_amount, 0.0)
    raw_balance = Payable.total_amount - paid
    balance = case((raw_balance > 0, raw_balance), else_=0.0)

    base_q = core.db.session.query(Payable).outerjoin(
        payment_totals, payment_totals.c.payable_id == Payable.id
    )
    base_q = _apply_account_filters(base_q, selected_stores, search, date_from, date_to)
    status_pred = _status_predicate(status_filter, paid, balance, today)
    if status_pred is not None:
        base_q = base_q.filter(status_pred)

    total_count = base_q.with_entities(func.count(Payable.id)).scalar() or 0
    total_pages = max((total_count + per_page - 1) // per_page, 1)
    if page > total_pages:
        page = total_pages

    page_ids = [row[0] for row in (
        base_q.with_entities(Payable.id)
        .order_by(Payable.due_date.asc(), Payable.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )]

    if page_ids:
        visible = Payable.query.options(selectinload(Payable.payments)).filter(Payable.id.in_(page_ids)).all()
        order_map = {account_id: idx for idx, account_id in enumerate(page_ids)}
        accounts = sorted(visible, key=lambda a: order_map.get(a.id, 999999))
    else:
        accounts = []

    # Totais do filtro calculados no banco, sem carregar todas as contas.
    aggregate_q = core.db.session.query(
        func.coalesce(func.sum(Payable.total_amount), 0),
        func.coalesce(func.sum(paid), 0),
        func.coalesce(func.sum(balance), 0),
        func.coalesce(func.sum(case((
            core.db.and_(balance > 0.009, Payable.due_date < today), balance
        ), else_=0.0)), 0),
        func.coalesce(func.sum(case((
            core.db.and_(
                balance > 0.009,
                paid <= 0.009,
                Payable.due_date >= today,
                Payable.due_date <= today + timedelta(days=7),
            ), balance
        ), else_=0.0)), 0),
        func.coalesce(func.sum(case((
            core.db.and_(balance > 0.009, Payable.due_date < today), 1
        ), else_=0)), 0),
    ).select_from(Payable).outerjoin(
        payment_totals, payment_totals.c.payable_id == Payable.id
    )
    aggregate_q = _apply_account_filters(aggregate_q, selected_stores, search, date_from, date_to)
    if status_pred is not None:
        aggregate_q = aggregate_q.filter(status_pred)

    agg = aggregate_q.one()
    filtered_total = float(agg[0] or 0)
    filtered_paid = float(agg[1] or 0)
    filtered_balance = float(agg[2] or 0)
    overdue_total = float(agg[3] or 0)
    due_7_total = float(agg[4] or 0)
    overdue_count = int(agg[5] or 0)

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

    def _page_url(target_page):
        args = core.request.args.to_dict()
        args["page"] = target_page
        args.setdefault("month", month_raw)
        return core.url_for("dashboard", **args)

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
        date_from=date_from_display,
        date_to=date_to_display,
        today=today,
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
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_pages=total_pages,
        prev_url=_page_url(page - 1) if page > 1 else None,
        next_url=_page_url(page + 1) if page < total_pages else None,
    )


app.view_functions["dashboard"] = login_required(_dashboard_fast)
