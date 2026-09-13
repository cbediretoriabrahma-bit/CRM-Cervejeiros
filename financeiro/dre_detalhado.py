import io
import json
import zipfile
from datetime import date, datetime

from flask import send_file
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import financeiro_app as base

app = base.app
db = base.db
core = base.core
Payable = base.Payable
PayablePayment = base.PayablePayment
Revenue = base.Revenue
RecurringCost = base.RecurringCost
RecurringOccurrence = base.RecurringOccurrence
login_required = base.login_required

DRE_CLASS_LABELS = {
    "cmv": "Custo direto / CMV",
    "fixa": "Despesa operacional fixa",
    "variavel": "Despesa operacional variável",
    "impostos": "Impostos e taxas",
    "financeira": "Despesa financeira",
    "nao_classificado": "Não classificado",
}


class CostDreClass(db.Model):
    __tablename__ = "finance_cost_dre_class"
    id = db.Column(db.Integer, primary_key=True)
    payable_id = db.Column(db.Integer, db.ForeignKey("payable.id"), unique=True, nullable=False)
    dre_class = db.Column(db.String(40), nullable=False, default="nao_classificado")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecurringDreClass(db.Model):
    __tablename__ = "finance_recurring_dre_class"
    id = db.Column(db.Integer, primary_key=True)
    recurring_cost_id = db.Column(db.Integer, db.ForeignKey("finance_recurring_cost.id"), unique=True, nullable=False)
    dre_class = db.Column(db.String(40), nullable=False, default="nao_classificado")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def normalize_dre_class(value):
    return value if value in DRE_CLASS_LABELS else "nao_classificado"


def sync_recurring_dre_classes():
    """Replica a classificação DRE da regra recorrente para cada ocorrência criada."""
    rules = {r.recurring_cost_id: r.dre_class for r in RecurringDreClass.query.all()}
    if not rules:
        return
    changed = False
    for occurrence in RecurringOccurrence.query.all():
        dre_class = rules.get(occurrence.recurring_cost_id)
        if not dre_class:
            continue
        existing = CostDreClass.query.filter_by(payable_id=occurrence.payable_id).first()
        if not existing:
            db.session.add(CostDreClass(payable_id=occurrence.payable_id, dre_class=dre_class))
            changed = True
    if changed:
        db.session.commit()


@app.before_request
def ensure_dre_support():
    try:
        db.create_all()
        sync_recurring_dre_classes()
    except Exception:
        db.session.rollback()


def save_cost_with_dre():
    supplier = core.request.form.get("supplier", "").strip()
    description = core.request.form.get("description", "").strip()
    store = core.request.form.get("store", "").strip() or core.request.form.get("new_store", "").strip() or "Geral"
    total_amount = core.parse_money(core.request.form.get("total_amount"))
    due_date = core.parse_date(core.request.form.get("due_date"))
    dre_class = normalize_dre_class(core.request.form.get("dre_class"))
    if not supplier or not description or total_amount <= 0 or not due_date:
        core.flash("Preencha loja, fornecedor, descrição, valor e vencimento.", "danger")
        return core.redirect(core.url_for("new_payable"))

    base.ensure_unit(store)
    common = dict(
        store=store,
        supplier=supplier,
        description=description,
        category=core.request.form.get("category", "Outros").strip() or "Outros",
        total_amount=total_amount,
        document=core.request.form.get("document", "").strip(),
        notes=core.request.form.get("notes", "").strip(),
    )
    recurring = core.request.form.get("is_recurring") == "1"

    if recurring:
        end_date = core.parse_date(core.request.form.get("recurrence_end"))
        rule = RecurringCost(**common, due_day=due_date.day, start_date=due_date, end_date=end_date, active=True)
        db.session.add(rule)
        db.session.flush()
        db.session.add(RecurringDreClass(recurring_cost_id=rule.id, dre_class=dre_class))

        payable = Payable(**common, due_date=due_date)
        db.session.add(payable)
        db.session.flush()
        db.session.add(CostDreClass(payable_id=payable.id, dre_class=dre_class))
        db.session.add(RecurringOccurrence(recurring_cost_id=rule.id, payable_id=payable.id, due_date=due_date))
        db.session.commit()
        base.materialize_recurring_costs()
        sync_recurring_dre_classes()
        core.flash("Custo recorrente cadastrado e classificado para o DRE.", "success")
    else:
        payable = Payable(**common, due_date=due_date)
        db.session.add(payable)
        db.session.flush()
        db.session.add(CostDreClass(payable_id=payable.id, dre_class=dre_class))
        entry = core.parse_money(core.request.form.get("entry_amount"))
        if entry > 0:
            entry = min(entry, total_amount)
            paid_date = core.parse_date(core.request.form.get("entry_date")) or date.today()
            db.session.add(PayablePayment(
                payable_id=payable.id,
                amount=entry,
                paid_date=paid_date,
                payment_method=core.request.form.get("entry_method", "PIX"),
                note="Entrada / pagamento inicial",
            ))
        db.session.commit()
        core.flash("Conta cadastrada com sucesso.", "success")
    return core.redirect(core.url_for("dashboard"))


save_cost_with_dre.__name__ = "save_cost_with_dre"
app.view_functions["save_cost"] = login_required(save_cost_with_dre)


@app.route("/conta/<int:account_id>/classificacao-dre", methods=["POST"])
@login_required
def update_dre_class(account_id):
    Payable.query.get_or_404(account_id)
    dre_class = normalize_dre_class(core.request.form.get("dre_class"))
    row = CostDreClass.query.filter_by(payable_id=account_id).first()
    if row:
        row.dre_class = dre_class
    else:
        db.session.add(CostDreClass(payable_id=account_id, dre_class=dre_class))
    db.session.commit()
    core.flash("Classificação do DRE atualizada.", "success")
    return core.redirect(core.url_for("detail", account_id=account_id))


def detail_with_dre(account_id):
    account = Payable.query.get_or_404(account_id)
    row = CostDreClass.query.filter_by(payable_id=account_id).first()
    return core.render_template(
        "detail.html",
        account=account,
        today=date.today(),
        dre_class=(row.dre_class if row else "nao_classificado"),
        dre_labels=DRE_CLASS_LABELS,
    )


app.view_functions["detail"] = login_required(detail_with_dre)


def _class_map(payable_ids):
    if not payable_ids:
        return {}
    rows = CostDreClass.query.filter(CostDreClass.payable_id.in_(payable_ids)).all()
    return {row.payable_id: normalize_dre_class(row.dre_class) for row in rows}


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
    for r in revenues:
        category = r.category or "Outros"
        revenue_by_category[category] = revenue_by_category.get(category, 0) + (r.amount or 0)
    payable_ids = list({p.payable_id for p in payments})
    classes = _class_map(payable_ids)
    class_totals = {key: 0.0 for key in DRE_CLASS_LABELS}
    for p in payments:
        category = p.payable.category or "Outros"
        amount = p.amount or 0
        expense_by_category[category] = expense_by_category.get(category, 0) + amount
        dre_class = classes.get(p.payable_id, "nao_classificado")
        class_totals[dre_class] += amount

    total_revenue = sum(revenue_by_category.values())
    total_expense = sum(expense_by_category.values())
    cmv = class_totals["cmv"]
    gross_profit = total_revenue - cmv
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    net_result = total_revenue - total_expense
    net_margin = (net_result / total_revenue * 100) if total_revenue else 0

    variable_for_contribution = class_totals["cmv"] + class_totals["variavel"] + class_totals["impostos"]
    contribution = total_revenue - variable_for_contribution
    contribution_margin = (contribution / total_revenue * 100) if total_revenue else 0
    fixed_for_breakeven = class_totals["fixa"] + class_totals["financeira"] + class_totals["nao_classificado"]
    contribution_ratio = contribution / total_revenue if total_revenue else 0
    breakeven = (fixed_for_breakeven / contribution_ratio) if contribution_ratio > 0 else 0

    classified_amount = total_expense - class_totals["nao_classificado"]
    classification_coverage = (classified_amount / total_expense * 100) if total_expense else 100

    expense_rows = []
    for category, amount in sorted(expense_by_category.items(), key=lambda item: item[1], reverse=True):
        expense_rows.append({
            "category": category,
            "amount": amount,
            "pct_revenue": (amount / total_revenue * 100) if total_revenue else 0,
            "pct_expense": (amount / total_expense * 100) if total_expense else 0,
        })

    class_rows = []
    for key, label in DRE_CLASS_LABELS.items():
        amount = class_totals[key]
        class_rows.append({
            "key": key,
            "label": label,
            "amount": amount,
            "pct_revenue": (amount / total_revenue * 100) if total_revenue else 0,
            "pct_expense": (amount / total_expense * 100) if total_expense else 0,
        })

    return {
        "store": store,
        "month": month,
        "revenue_by_category": revenue_by_category,
        "expense_by_category": expense_by_category,
        "expense_rows": expense_rows,
        "class_rows": class_rows,
        "class_totals": class_totals,
        "total_revenue": total_revenue,
        "total_expense": total_expense,
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


def detailed_dre():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    store_filter = core.request.args.get("store", "").strip()
    data = compute_detailed_dre(month, store_filter)
    unit_rows = []
    for store in base.managed_stores(active_only=False):
        unit = compute_detailed_dre(month, store)
        unit_rows.append({
            "store": store,
            "revenue": unit["total_revenue"],
            "gross_profit": unit["gross_profit"],
            "gross_margin": unit["gross_margin"],
            "expense": unit["total_expense"],
            "result": unit["net_result"],
            "net_margin": unit["net_margin"],
            "breakeven": unit["breakeven"],
        })
    return core.render_template(
        "dre.html",
        stores=base.managed_stores(active_only=False),
        store_filter=store_filter,
        month=month,
        unit_rows=unit_rows,
        **data,
    )


app.view_functions["dre"] = login_required(detailed_dre)


def detailed_dre_export(fmt):
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    store = core.request.args.get("store", "").strip()
    d = compute_detailed_dre(month, store)
    scope = store or "Consolidado"
    summary = [
        ["Receita total", d["total_revenue"], 100.0 if d["total_revenue"] else 0],
        ["(-) Custo direto / CMV", d["cmv"], (d["cmv"] / d["total_revenue"] * 100) if d["total_revenue"] else 0],
        ["Lucro bruto", d["gross_profit"], d["gross_margin"]],
        ["Margem bruta", d["gross_margin"], None],
        ["Margem de contribuição", d["contribution"], d["contribution_margin"]],
        ["Despesas totais", d["total_expense"], (d["total_expense"] / d["total_revenue"] * 100) if d["total_revenue"] else 0],
        ["Resultado líquido", d["net_result"], d["net_margin"]],
        ["Margem líquida", d["net_margin"], None],
        ["Ponto de equilíbrio estimado", d["breakeven"], None],
    ]

    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "DRE Detalhado"
        ws.append(["DRE Detalhado", scope, month])
        ws.append(["Indicador", "Valor", "% da receita"])
        for item, value, pct in summary:
            ws.append([item, value, pct])
        ws.append([])
        ws.append(["Gastos por categoria", "Valor", "% da receita", "% dos gastos"])
        for row in d["expense_rows"]:
            ws.append([row["category"], row["amount"], row["pct_revenue"], row["pct_expense"]])
        ws.append([])
        ws.append(["Classificação DRE", "Valor", "% da receita", "% dos gastos"])
        for row in d["class_rows"]:
            ws.append([row["label"], row["amount"], row["pct_revenue"], row["pct_expense"]])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 45)
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return send_file(out, as_attachment=True, download_name=f"dre_detalhado_{month}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=22, rightMargin=22, topMargin=22, bottomMargin=22)
    styles = getSampleStyleSheet()
    story = [Paragraph(f"DRE Detalhado - {scope} - {month}", styles["Title"]), Spacer(1, 8)]
    rows = [["Indicador", "Valor", "% da receita"]]
    for item, value, pct in summary:
        if "Margem " in item and isinstance(value, (int, float)) and pct is None:
            value_text = f"{value:.1f}%"
        else:
            value_text = core.brl(value) if isinstance(value, (int, float)) else str(value)
        rows.append([item, value_text, "" if pct is None else f"{pct:.1f}%"])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.lightgrey), ("GRID", (0,0), (-1,-1), .4, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story += [table, Spacer(1, 12), Paragraph("Gastos por categoria", styles["Heading2"])]
    expense_rows = [["Categoria", "Valor", "% receita", "% gastos"]] + [[r["category"], core.brl(r["amount"]), f"{r['pct_revenue']:.1f}%", f"{r['pct_expense']:.1f}%"] for r in d["expense_rows"]]
    t2 = Table(expense_rows, repeatRows=1)
    t2.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.lightgrey), ("GRID", (0,0), (-1,-1), .4, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story.append(t2)
    doc.build(story)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name=f"dre_detalhado_{month}.pdf", mimetype="application/pdf")


_original_export_report = app.view_functions["export_report"]


def export_report_with_detailed_dre(kind, fmt):
    if kind == "dre" and fmt in {"xlsx", "pdf"}:
        return detailed_dre_export(fmt)
    return _original_export_report(kind, fmt)


app.view_functions["export_report"] = export_report_with_detailed_dre


def backup_financeiro_extended():
    finance_tables = [
        "finance_user", "finance_store_unit", "payable", "payable_payment", "finance_revenue",
        "finance_recurring_cost", "finance_recurring_occurrence", "finance_cost_dre_class", "finance_recurring_dre_class",
    ]
    inspector = base.inspect(db.engine)
    available = set(inspector.get_table_names())
    selected = [name for name in finance_tables if name in available]
    memory = io.BytesIO()
    manifest = {
        "backup_type": "financeiro-cervejeiros",
        "created_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tables": {},
        "format_version": 3,
    }
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table_name in selected:
            columns = inspector.get_columns(table_name)
            result = db.session.execute(base.text(f'SELECT * FROM "{table_name}"'))
            rows = [{key: base._backup_value(value) for key, value in row.items()} for row in result.mappings().all()]
            manifest["tables"][table_name] = {
                "row_count": len(rows),
                "columns": [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True))} for c in columns],
            }
            archive.writestr(f"{table_name}.json", json.dumps(rows, ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    memory.seek(0)
    return send_file(memory, mimetype="application/zip", as_attachment=True,
                     download_name=f"backup_financeiro_cervejeiros_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.zip", max_age=0)


app.view_functions["backup_financeiro"] = login_required(backup_financeiro_extended)
