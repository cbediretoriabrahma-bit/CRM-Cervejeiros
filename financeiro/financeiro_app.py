import io
import json
import zipfile
import calendar
from datetime import date, datetime
from flask import send_file
from sqlalchemy import func, inspect, text, UniqueConstraint
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
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

class RecurringCost(db.Model):
    __tablename__ = "finance_recurring_cost"
    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(120), nullable=False, default="Geral")
    supplier = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(220), nullable=False)
    category = db.Column(db.String(100), default="Outros")
    total_amount = db.Column(db.Float, nullable=False, default=0)
    due_day = db.Column(db.Integer, nullable=False)
    document = db.Column(db.String(100))
    notes = db.Column(db.Text)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=core.datetime.utcnow)

class RecurringOccurrence(db.Model):
    __tablename__ = "finance_recurring_occurrence"
    id = db.Column(db.Integer, primary_key=True)
    recurring_cost_id = db.Column(db.Integer, db.ForeignKey("finance_recurring_cost.id"), nullable=False)
    payable_id = db.Column(db.Integer, db.ForeignKey("payable.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    __table_args__ = (UniqueConstraint("recurring_cost_id", "due_date", name="uq_recurring_cost_due_date"),)

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

def add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def due_for_month(year, month, due_day):
    return date(year, month, min(due_day, calendar.monthrange(year, month)[1]))

def materialize_recurring_costs():
    today = date.today()
    horizon = add_months(today.replace(day=1), 12)
    changed = False
    for rule in RecurringCost.query.filter_by(active=True).all():
        cursor = rule.start_date.replace(day=1)
        final = rule.end_date if rule.end_date else horizon
        while cursor <= horizon and cursor <= final:
            due = due_for_month(cursor.year, cursor.month, rule.due_day)
            if due >= rule.start_date and (not rule.end_date or due <= rule.end_date):
                exists = RecurringOccurrence.query.filter_by(recurring_cost_id=rule.id, due_date=due).first()
                if not exists:
                    payable = Payable(store=rule.store, supplier=rule.supplier, description=rule.description,
                                      category=rule.category, total_amount=rule.total_amount, due_date=due,
                                      document=rule.document, notes=rule.notes)
                    db.session.add(payable); db.session.flush()
                    db.session.add(RecurringOccurrence(recurring_cost_id=rule.id, payable_id=payable.id, due_date=due))
                    changed = True
            cursor = add_months(cursor, 1)
    if changed:
        db.session.commit()

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
        materialize_recurring_costs()
    except Exception:
        db.session.rollback()

@app.route("/custos/salvar", methods=["POST"])
@login_required
def save_cost():
    supplier = core.request.form.get("supplier", "").strip()
    description = core.request.form.get("description", "").strip()
    store = core.request.form.get("store", "").strip() or core.request.form.get("new_store", "").strip() or "Geral"
    total_amount = core.parse_money(core.request.form.get("total_amount"))
    due_date = core.parse_date(core.request.form.get("due_date"))
    if not supplier or not description or total_amount <= 0 or not due_date:
        core.flash("Preencha loja, fornecedor, descrição, valor e vencimento.", "danger")
        return core.redirect(core.url_for("new_payable"))
    ensure_unit(store)
    common = dict(store=store, supplier=supplier, description=description,
                  category=core.request.form.get("category", "Outros").strip() or "Outros",
                  total_amount=total_amount, document=core.request.form.get("document", "").strip(),
                  notes=core.request.form.get("notes", "").strip())
    recurring = core.request.form.get("is_recurring") == "1"
    if recurring:
        end_date = core.parse_date(core.request.form.get("recurrence_end"))
        rule = RecurringCost(**common, due_day=due_date.day, start_date=due_date, end_date=end_date, active=True)
        db.session.add(rule); db.session.flush()
        payable = Payable(**common, due_date=due_date)
        db.session.add(payable); db.session.flush()
        db.session.add(RecurringOccurrence(recurring_cost_id=rule.id, payable_id=payable.id, due_date=due_date))
        db.session.commit()
        materialize_recurring_costs()
        core.flash("Custo recorrente cadastrado. Os próximos vencimentos serão criados automaticamente.", "success")
    else:
        payable = Payable(**common, due_date=due_date)
        db.session.add(payable); db.session.flush()
        entry = core.parse_money(core.request.form.get("entry_amount"))
        if entry > 0:
            entry = min(entry, total_amount)
            paid_date = core.parse_date(core.request.form.get("entry_date")) or date.today()
            db.session.add(PayablePayment(payable_id=payable.id, amount=entry, paid_date=paid_date,
                                          payment_method=core.request.form.get("entry_method", "PIX"),
                                          note="Entrada / pagamento inicial"))
        db.session.commit()
        core.flash("Conta cadastrada com sucesso.", "success")
    return core.redirect(core.url_for("dashboard"))

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
            unit = StoreUnit(name=name, city=core.request.form.get("city", "").strip(),
                             state=core.request.form.get("state", "").strip().upper(),
                             code=core.request.form.get("code", "").strip() or None,
                             notes=core.request.form.get("notes", "").strip(), active=True)
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
        core.flash("Informe o nome da unidade.", "danger"); return core.redirect(core.url_for("units"))
    duplicate = StoreUnit.query.filter(func.lower(StoreUnit.name) == new_name.lower(), StoreUnit.id != unit.id).first()
    if duplicate:
        core.flash("Já existe outra unidade com esse nome.", "danger"); return core.redirect(core.url_for("units"))
    unit.name = new_name; unit.city = core.request.form.get("city", "").strip(); unit.state = core.request.form.get("state", "").strip().upper()
    unit.code = core.request.form.get("code", "").strip() or None; unit.notes = core.request.form.get("notes", "").strip()
    if old_name != new_name:
        Payable.query.filter_by(store=old_name).update({Payable.store: new_name}, synchronize_session=False)
        Revenue.query.filter_by(store=old_name).update({Revenue.store: new_name}, synchronize_session=False)
        RecurringCost.query.filter_by(store=old_name).update({RecurringCost.store: new_name}, synchronize_session=False)
    db.session.commit(); core.flash("Unidade atualizada.", "success")
    return core.redirect(core.url_for("units"))

@app.route("/unidades/<int:unit_id>/status", methods=["POST"])
@login_required
def toggle_unit(unit_id):
    unit = StoreUnit.query.get_or_404(unit_id); unit.active = not unit.active; db.session.commit()
    core.flash("Unidade ativada." if unit.active else "Unidade desativada. Os históricos foram preservados.", "success")
    return core.redirect(core.url_for("units"))

def health_diagnosis(revenue, expense, overdue):
    result = revenue - expense; margin = (result / revenue * 100) if revenue else 0
    cost_ratio = (expense / revenue * 100) if revenue else (100 if expense else 0); breakeven = expense; gap = revenue - breakeven
    if revenue <= 0 and expense > 0:
        health, color, focus = "Crítica", "red", "Receitas"; diagnosis = "A unidade teve despesas, mas não registrou receita no período. A prioridade é recuperar faturamento e revisar imediatamente os gastos indispensáveis."
    elif result < 0:
        health, color = "Crítica", "red"
        if revenue < expense * 0.85:
            focus = "Receitas"; diagnosis = "A receita ficou significativamente abaixo do ponto de equilíbrio. O foco principal deve ser aumentar faturamento, sem deixar de revisar despesas que possam ser reduzidas."
        else:
            focus = "Custos"; diagnosis = "A receita está próxima do necessário para equilibrar a operação, mas os custos estão consumindo o resultado. O foco principal deve ser redução e renegociação de despesas."
    elif margin < 10:
        health, color, focus = "Atenção", "yellow", "Custos"; diagnosis = "A unidade está positiva, porém com margem apertada. Os custos estão consumindo grande parte da receita; revise fornecedores, despesas fixas e gastos operacionais."
    elif margin < 20:
        health, color, focus = "Saudável", "blue", "Margem"; diagnosis = "A unidade está saudável e acima do ponto de equilíbrio, mas ainda há espaço para melhorar margem e eficiência dos custos."
    else:
        health, color, focus = "Excelente", "green", "Manter desempenho"; diagnosis = "A unidade apresenta resultado e margem fortes. Mantenha controle de custos, crescimento de receita e disciplina de pagamentos."
    if overdue > 0: diagnosis += " Há contas vencidas em aberto, que também exigem atenção para preservar o caixa e evitar encargos."
    return {"revenue": round(revenue, 2), "expense": round(expense, 2), "result": round(result, 2), "margin": round(margin, 1),
            "cost_ratio": round(cost_ratio, 1), "breakeven": round(breakeven, 2), "gap": round(gap, 2), "overdue": round(overdue, 2),
            "health": health, "color": color, "focus": focus, "diagnosis": diagnosis}

@app.route("/saude-financeira")
@login_required
def financial_health():
    month = core.request.args.get("month", core.date.today().strftime("%Y-%m")); store_filter = core.request.args.get("store", "").strip()
    start, end = core.parse_month(month); stores = managed_stores(active_only=False); selected = [store_filter] if store_filter else stores; rows = []
    for store in selected:
        revenue = sum(r.amount or 0 for r in Revenue.query.filter(Revenue.store == store, Revenue.revenue_date >= start, Revenue.revenue_date < end).all())
        expense = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(Payable.store == store, PayablePayment.paid_date >= start, PayablePayment.paid_date < end).all())
        overdue = sum(a.balance for a in Payable.query.filter(Payable.store == store).all() if a.balance > 0 and a.due_date < core.date.today())
        item = health_diagnosis(revenue, expense, overdue); item["store"] = store; rows.append(item)
    consolidated = health_diagnosis(sum(r["revenue"] for r in rows), sum(r["expense"] for r in rows), sum(r["overdue"] for r in rows))
    consolidated["store"] = store_filter or "Consolidado do Grupo"
    return core.render_template("financial_health.html", month=month, stores=stores, store_filter=store_filter, rows=rows, consolidated=consolidated)

def _backup_value(value):
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if isinstance(value, (date, datetime)): return value.isoformat()
    return str(value)

@app.route("/backup-financeiro")
@login_required
def backup_financeiro():
    finance_tables = ["finance_user", "finance_store_unit", "payable", "payable_payment", "finance_revenue", "finance_recurring_cost", "finance_recurring_occurrence"]
    inspector = inspect(db.engine); available = set(inspector.get_table_names()); selected = [name for name in finance_tables if name in available]
    memory = io.BytesIO(); manifest = {"backup_type": "financeiro-cervejeiros", "created_at_utc": datetime.utcnow().replace(microsecond=0).isoformat()+"Z", "tables": {}, "format_version": 2}
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table_name in selected:
            columns = inspector.get_columns(table_name); result = db.session.execute(text(f'SELECT * FROM "{table_name}"'))
            rows = [{key: _backup_value(value) for key, value in row.items()} for row in result.mappings().all()]
            manifest["tables"][table_name] = {"row_count": len(rows), "columns": [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True))} for c in columns]}
            archive.writestr(f"{table_name}.json", json.dumps(rows, ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    memory.seek(0)
    return send_file(memory, mimetype="application/zip", as_attachment=True,
                     download_name=f"backup_financeiro_cervejeiros_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.zip", max_age=0)

def filtered_costs(args):
    q = Payable.query
    store = args.get("store", "").strip(); status = args.get("status", "").strip(); search = args.get("q", "").strip()
    date_from = core.parse_date(args.get("date_from")); date_to = core.parse_date(args.get("date_to"))
    if store: q = q.filter(Payable.store == store)
    if search:
        like = f"%{search}%"; q = q.filter(db.or_(Payable.supplier.ilike(like), Payable.description.ilike(like), Payable.category.ilike(like), Payable.store.ilike(like)))
    if date_from: q = q.filter(Payable.due_date >= date_from)
    if date_to: q = q.filter(Payable.due_date <= date_to)
    rows = q.order_by(Payable.due_date.asc(), Payable.id.desc()).all()
    return [a for a in rows if not status or a.status == status]

def report_payload(kind, args):
    store = args.get("store", "").strip(); month = args.get("month", date.today().strftime("%Y-%m"))
    if kind == "custos":
        rows = filtered_costs(args)
        headers = ["Status", "Unidade", "Vencimento", "Fornecedor", "Descrição", "Categoria", "Valor", "Pago", "Saldo"]
        data = [[a.status, a.store, a.due_date.strftime("%d/%m/%Y"), a.supplier, a.description, a.category, a.total_amount, a.paid_amount, a.balance] for a in rows]
        return "Relatório de Custos", headers, data
    start, end = core.parse_month(month)
    if kind == "receitas":
        q = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end)
        if store: q = q.filter(Revenue.store == store)
        rows = q.order_by(Revenue.revenue_date.desc()).all()
        return "Relatório de Receitas", ["Data", "Unidade", "Categoria", "Descrição", "Forma", "Valor"], [[r.revenue_date.strftime("%d/%m/%Y"), r.store, r.category, r.description, r.payment_method, r.amount] for r in rows]
    rq = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end)
    pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= start, PayablePayment.paid_date < end)
    if store: rq = rq.filter(Revenue.store == store); pq = pq.filter(Payable.store == store)
    rev = {}; exp = {}
    for r in rq.all(): rev[r.category] = rev.get(r.category, 0) + (r.amount or 0)
    for p in pq.all(): exp[p.payable.category or "Outros"] = exp.get(p.payable.category or "Outros", 0) + (p.amount or 0)
    data = [["Receita", k, v] for k, v in rev.items()] + [["Despesa", k, v] for k, v in exp.items()]
    total_r, total_e = sum(rev.values()), sum(exp.values()); data += [["Resumo", "Receita total", total_r], ["Resumo", "Despesa total", total_e], ["Resumo", "Resultado", total_r-total_e]]
    return "DRE Gerencial", ["Tipo", "Categoria", "Valor"], data

@app.route("/relatorios/<kind>/<fmt>")
@login_required
def export_report(kind, fmt):
    if kind not in {"custos", "receitas", "dre"} or fmt not in {"xlsx", "pdf"}:
        return "Relatório inválido", 404
    title, headers, rows = report_payload(kind, core.request.args)
    if fmt == "xlsx":
        wb = Workbook(); ws = wb.active; ws.title = title[:31]; ws.append([title]); ws.append(headers)
        for row in rows: ws.append(row)
        for col in ws.columns:
            letter = col[0].column_letter; ws.column_dimensions[letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 45)
        out = io.BytesIO(); wb.save(out); out.seek(0)
        return send_file(out, as_attachment=True, download_name=f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    out = io.BytesIO(); doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=22, rightMargin=22, topMargin=22, bottomMargin=22)
    styles = getSampleStyleSheet(); story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]
    pdf_rows = [headers] + [[("R$ %.2f" % v).replace(".", ",") if isinstance(v, float) else str(v) for v in row] for row in rows]
    table = Table(pdf_rows, repeatRows=1); table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.lightgrey), ("GRID", (0,0), (-1,-1), .4, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 7), ("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(table); doc.build(story); out.seek(0)
    return send_file(out, as_attachment=True, download_name=f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf", mimetype="application/pdf")
