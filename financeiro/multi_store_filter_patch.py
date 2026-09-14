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


def _selected_stores():
    stores = [s.strip() for s in core.request.args.getlist("store") if (s or "").strip()]
    valid = set(base.managed_stores(active_only=False))
    return [s for s in stores if s in valid]


def _dashboard_multi_store():
    status_filter = core.request.args.get("status", "")
    selected_stores = _selected_stores()
    search = core.request.args.get("q", "").strip()
    date_from_raw = core.request.args.get("date_from", "")
    date_to_raw = core.request.args.get("date_to", "")
    date_from = core.parse_date(date_from_raw)
    date_to = core.parse_date(date_to_raw)
    month_raw = core.request.args.get("month", date.today().strftime("%Y-%m"))
    month_start, month_end = core.parse_month(month_raw)

    q = Payable.query
    if search:
        like = f"%{search}%"
        q = q.filter(core.db.or_(Payable.supplier.ilike(like), Payable.description.ilike(like), Payable.category.ilike(like), Payable.store.ilike(like)))
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

    rq = Revenue.query.filter(Revenue.revenue_date >= month_start, Revenue.revenue_date < month_end)
    pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= month_start, PayablePayment.paid_date < month_end)
    if selected_stores:
        rq = rq.filter(Revenue.store.in_(selected_stores))
        pq = pq.filter(Payable.store.in_(selected_stores))
    revenue_month = sum(r.amount or 0 for r in rq.all())
    expense_month = sum(p.amount or 0 for p in pq.all())
    result_month = revenue_month - expense_month

    # Indicadores gerenciais do DRE para o mesmo mês e para as mesmas unidades do painel.
    # O CMV usa a classificação já existente no DRE, sem alterar lançamentos financeiros.
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
    unit_rows = []
    for s in visible_stores:
        rev = sum(r.amount or 0 for r in Revenue.query.filter(Revenue.store == s, Revenue.revenue_date >= month_start, Revenue.revenue_date < month_end).all())
        exp = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(Payable.store == s, PayablePayment.paid_date >= month_start, PayablePayment.paid_date < month_end).all())
        unit_rows.append({"store": s, "revenue": round(rev, 2), "expense": round(exp, 2), "result": round(rev-exp, 2)})

    return core.render_template(
        "dashboard.html", accounts=accounts, filtered_total=filtered_total, filtered_paid=filtered_paid,
        filtered_balance=filtered_balance, overdue_total=overdue_total, due_7_total=due_7_total,
        overdue_count=overdue_count, status_filter=status_filter, store_filter="",
        selected_stores=selected_stores, stores=stores, search=search, date_from=date_from_raw,
        date_to=date_to_raw, today=date.today(), month=month_start.strftime("%Y-%m"),
        revenue_month=revenue_month, expense_month=expense_month, result_month=result_month,
        cmv_month=cmv_month, cmv_pct=cmv_pct, gross_profit_month=gross_profit_month,
        gross_margin_pct=gross_margin_pct, net_profit_month=net_profit_month,
        net_margin_pct=net_margin_pct, unit_rows=unit_rows,
    )


def _financial_health_multi_store():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    selected_stores = _selected_stores()
    start, end = core.parse_month(month)
    stores = base.managed_stores(active_only=False)
    visible_stores = selected_stores or stores
    rows = []
    for store in visible_stores:
        revenue = sum(r.amount or 0 for r in Revenue.query.filter(Revenue.store == store, Revenue.revenue_date >= start, Revenue.revenue_date < end).all())
        expense = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(Payable.store == store, PayablePayment.paid_date >= start, PayablePayment.paid_date < end).all())
        overdue = sum(a.balance for a in Payable.query.filter(Payable.store == store).all() if a.balance > 0 and a.due_date < date.today())
        item = base.health_diagnosis(revenue, expense, overdue)
        item["store"] = store
        rows.append(item)
    consolidated = base.health_diagnosis(sum(r["revenue"] for r in rows), sum(r["expense"] for r in rows), sum(r["overdue"] for r in rows))
    consolidated["store"] = "Lojas selecionadas" if selected_stores else "Consolidado do Grupo"
    return core.render_template("financial_health.html", month=month, stores=stores, selected_stores=selected_stores, store_filter="", rows=rows, consolidated=consolidated)


def _dre_multi_store():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    selected_stores = _selected_stores()
    stores = base.managed_stores(active_only=False)

    if not selected_stores:
        data = detailed.compute_detailed_dre(month, "")
    elif len(selected_stores) == 1:
        data = detailed.compute_detailed_dre(month, selected_stores[0])
    else:
        start, end = core.parse_month(month)
        rq = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end, Revenue.store.in_(selected_stores))
        pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= start, PayablePayment.paid_date < end, Payable.store.in_(selected_stores))
        revenues = rq.all(); payments = pq.all()
        revenue_by_category = {}; expense_by_category = {}
        for r in revenues:
            category = r.category or "Outros"
            revenue_by_category[category] = revenue_by_category.get(category, 0) + (r.amount or 0)
        payable_ids = list({p.payable_id for p in payments})
        classes = detailed._class_map(payable_ids)
        class_totals = {key: 0.0 for key in detailed.DRE_CLASS_LABELS}
        for p in payments:
            category = p.payable.category or "Outros"; amount = p.amount or 0
            expense_by_category[category] = expense_by_category.get(category, 0) + amount
            class_totals[classes.get(p.payable_id, "nao_classificado")] += amount
        total_revenue = sum(revenue_by_category.values()); total_expense = sum(expense_by_category.values())
        cmv = class_totals["cmv"]; gross_profit = total_revenue - cmv
        gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
        net_result = total_revenue - total_expense; net_margin = (net_result / total_revenue * 100) if total_revenue else 0
        variable = class_totals["cmv"] + class_totals["variavel"] + class_totals["impostos"]
        contribution = total_revenue - variable; contribution_margin = (contribution / total_revenue * 100) if total_revenue else 0
        fixed = class_totals["fixa"] + class_totals["financeira"] + class_totals["nao_classificado"]
        ratio = contribution / total_revenue if total_revenue else 0; breakeven = (fixed / ratio) if ratio > 0 else 0
        classified = total_expense - class_totals["nao_classificado"]; coverage = (classified / total_expense * 100) if total_expense else 100
        expense_rows = [{"category": c, "amount": a, "pct_revenue": (a/total_revenue*100) if total_revenue else 0, "pct_expense": (a/total_expense*100) if total_expense else 0} for c,a in sorted(expense_by_category.items(), key=lambda x:x[1], reverse=True)]
        class_rows = [{"key": k, "label": label, "amount": class_totals[k], "pct_revenue": (class_totals[k]/total_revenue*100) if total_revenue else 0, "pct_expense": (class_totals[k]/total_expense*100) if total_expense else 0} for k,label in detailed.DRE_CLASS_LABELS.items()]
        data = {"revenue_by_category": revenue_by_category, "expense_by_category": expense_by_category, "expense_rows": expense_rows, "class_rows": class_rows, "class_totals": class_totals, "total_revenue": total_revenue, "total_expense": total_expense, "cmv": cmv, "gross_profit": gross_profit, "gross_margin": gross_margin, "net_result": net_result, "net_margin": net_margin, "contribution": contribution, "contribution_margin": contribution_margin, "fixed_for_breakeven": fixed, "breakeven": breakeven, "classification_coverage": coverage, "unclassified": class_totals["nao_classificado"]}

    visible_stores = selected_stores or stores
    unit_rows = []
    for store in visible_stores:
        unit = detailed.compute_detailed_dre(month, store)
        unit_rows.append({"store": store, "revenue": unit["total_revenue"], "gross_profit": unit["gross_profit"], "gross_margin": unit["gross_margin"], "expense": unit["total_expense"], "result": unit["net_result"], "net_margin": unit["net_margin"], "breakeven": unit["breakeven"]})
    context = dict(data)
    context.update({"stores": stores, "selected_stores": selected_stores, "store_filter": "", "month": month, "unit_rows": unit_rows})
    return core.render_template("dre.html", **context)


app.view_functions["dashboard"] = login_required(_dashboard_multi_store)
app.view_functions["financial_health"] = login_required(_financial_health_multi_store)
app.view_functions["dre"] = login_required(_dre_multi_store)
