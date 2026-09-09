from sqlalchemy import func
import contas_pagar_app as core

app = core.app
db = core.db
Payable = core.Payable
PayablePayment = core.PayablePayment
Revenue = core.Revenue
login_required = core.login_required

class StoreUnit(db.Model):
    __tablename__ = "finance_store_unit"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    city = db.Column(db.String(120))
    state = db.Column(db.String(20))
    code = db.Column(db.String(40), unique=True)
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=core.datetime.utcnow)

def ensure_unit(name):
    name = (name or "").strip()
    if not name:
        return None
    unit = StoreUnit.query.filter(func.lower(StoreUnit.name) == name.lower()).first()
    if not unit:
        unit = StoreUnit(name=name, active=True)
        db.session.add(unit)
    return unit

def managed_stores(active_only=True):
    q = StoreUnit.query
    if active_only:
        q = q.filter_by(active=True)
    names = {u.name for u in q.order_by(StoreUnit.name).all()}
    if not names:
        names.update(r[0] for r in db.session.query(Payable.store).filter(Payable.store.isnot(None), Payable.store != "").all())
        names.update(r[0] for r in db.session.query(Revenue.store).filter(Revenue.store.isnot(None), Revenue.store != "").all())
    return sorted(names)

core.all_stores = managed_stores

@app.before_request
def sync_legacy_units():
    db.create_all()
    try:
        names = set()
        names.update(r[0] for r in db.session.query(Payable.store).filter(Payable.store.isnot(None), Payable.store != "").distinct().all())
        names.update(r[0] for r in db.session.query(Revenue.store).filter(Revenue.store.isnot(None), Revenue.store != "").distinct().all())
        changed = False
        for name in names:
            if not StoreUnit.query.filter(func.lower(StoreUnit.name) == name.lower()).first():
                db.session.add(StoreUnit(name=name, active=True)); changed = True
        if changed:
            db.session.commit()
    except Exception:
        db.session.rollback()

@app.route("/unidades", methods=["GET", "POST"])
@login_required
def units():
    if core.request.method == "POST":
        name = core.request.form.get("name", "").strip()
        if not name:
            core.flash("Informe o nome da unidade.", "danger")
        elif StoreUnit.query.filter(func.lower(StoreUnit.name) == name.lower()).first():
            core.flash("Já existe uma unidade com esse nome.", "danger")
        else:
            unit = StoreUnit(
                name=name,
                city=core.request.form.get("city", "").strip(),
                state=core.request.form.get("state", "").strip().upper(),
                code=core.request.form.get("code", "").strip() or None,
                notes=core.request.form.get("notes", "").strip(),
                active=True,
            )
            db.session.add(unit); db.session.commit()
            core.flash("Unidade cadastrada com sucesso.", "success")
        return core.redirect(core.url_for("units"))
    rows = StoreUnit.query.order_by(StoreUnit.active.desc(), StoreUnit.name).all()
    return core.render_template("units.html", units=rows)

@app.route("/unidades/<int:unit_id>/editar", methods=["POST"])
@login_required
def edit_unit(unit_id):
    unit = StoreUnit.query.get_or_404(unit_id)
    old_name = unit.name
    new_name = core.request.form.get("name", "").strip()
    if not new_name:
        core.flash("Informe o nome da unidade.", "danger")
        return core.redirect(core.url_for("units"))
    duplicate = StoreUnit.query.filter(func.lower(StoreUnit.name) == new_name.lower(), StoreUnit.id != unit.id).first()
    if duplicate:
        core.flash("Já existe outra unidade com esse nome.", "danger")
        return core.redirect(core.url_for("units"))
    unit.name = new_name
    unit.city = core.request.form.get("city", "").strip()
    unit.state = core.request.form.get("state", "").strip().upper()
    unit.code = core.request.form.get("code", "").strip() or None
    unit.notes = core.request.form.get("notes", "").strip()
    if old_name != new_name:
        Payable.query.filter_by(store=old_name).update({Payable.store: new_name}, synchronize_session=False)
        Revenue.query.filter_by(store=old_name).update({Revenue.store: new_name}, synchronize_session=False)
    db.session.commit()
    core.flash("Unidade atualizada.", "success")
    return core.redirect(core.url_for("units"))

@app.route("/unidades/<int:unit_id>/status", methods=["POST"])
@login_required
def toggle_unit(unit_id):
    unit = StoreUnit.query.get_or_404(unit_id)
    unit.active = not unit.active
    db.session.commit()
    core.flash("Unidade ativada." if unit.active else "Unidade desativada. Os históricos foram preservados.", "success")
    return core.redirect(core.url_for("units"))

def health_diagnosis(revenue, expense, overdue):
    result = revenue - expense
    margin = (result / revenue * 100) if revenue else 0
    cost_ratio = (expense / revenue * 100) if revenue else (100 if expense else 0)
    breakeven = expense
    gap = revenue - breakeven

    if revenue <= 0 and expense > 0:
        health, color, focus = "Crítica", "red", "Receitas"
        diagnosis = "A unidade teve despesas, mas não registrou receita no período. A prioridade é recuperar faturamento e revisar imediatamente os gastos indispensáveis."
    elif result < 0:
        health, color = "Crítica", "red"
        if revenue < expense * 0.85:
            focus = "Receitas"
            diagnosis = "A receita ficou significativamente abaixo do ponto de equilíbrio. O foco principal deve ser aumentar faturamento, sem deixar de revisar despesas que possam ser reduzidas."
        else:
            focus = "Custos"
            diagnosis = "A receita está próxima do necessário para equilibrar a operação, mas os custos estão consumindo o resultado. O foco principal deve ser redução e renegociação de despesas."
    elif margin < 10:
        health, color, focus = "Atenção", "yellow", "Custos"
        diagnosis = "A unidade está positiva, porém com margem apertada. Os custos estão consumindo grande parte da receita; revise fornecedores, despesas fixas e gastos operacionais."
    elif margin < 20:
        health, color, focus = "Saudável", "blue", "Margem"
        diagnosis = "A unidade está saudável e acima do ponto de equilíbrio, mas ainda há espaço para melhorar margem e eficiência dos custos."
    else:
        health, color, focus = "Excelente", "green", "Manter desempenho"
        diagnosis = "A unidade apresenta resultado e margem fortes. Mantenha controle de custos, crescimento de receita e disciplina de pagamentos."

    if overdue > 0:
        diagnosis += " Há contas vencidas em aberto, que também exigem atenção para preservar o caixa e evitar encargos."

    return {
        "revenue": round(revenue, 2), "expense": round(expense, 2), "result": round(result, 2),
        "margin": round(margin, 1), "cost_ratio": round(cost_ratio, 1), "breakeven": round(breakeven, 2),
        "gap": round(gap, 2), "overdue": round(overdue, 2), "health": health, "color": color,
        "focus": focus, "diagnosis": diagnosis,
    }

@app.route("/saude-financeira")
@login_required
def financial_health():
    month = core.request.args.get("month", core.date.today().strftime("%Y-%m"))
    store_filter = core.request.args.get("store", "").strip()
    start, end = core.parse_month(month)
    stores = managed_stores(active_only=False)
    selected = [store_filter] if store_filter else stores
    rows = []

    for store in selected:
        revenue = sum(r.amount or 0 for r in Revenue.query.filter(
            Revenue.store == store, Revenue.revenue_date >= start, Revenue.revenue_date < end).all())
        expense = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(
            Payable.store == store, PayablePayment.paid_date >= start, PayablePayment.paid_date < end).all())
        overdue = sum(a.balance for a in Payable.query.filter(Payable.store == store).all()
                      if a.balance > 0 and a.due_date < core.date.today())
        item = health_diagnosis(revenue, expense, overdue)
        item["store"] = store
        rows.append(item)

    total_revenue = sum(r["revenue"] for r in rows)
    total_expense = sum(r["expense"] for r in rows)
    total_overdue = sum(r["overdue"] for r in rows)
    consolidated = health_diagnosis(total_revenue, total_expense, total_overdue)
    consolidated["store"] = store_filter or "Consolidado do Grupo"

    return core.render_template("financial_health.html", month=month, stores=stores,
                                store_filter=store_filter, rows=rows, consolidated=consolidated)
