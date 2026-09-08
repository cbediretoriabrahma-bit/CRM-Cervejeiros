import os
from datetime import date, datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, inspect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.getenv("FINANCE_SECRET_KEY", os.getenv("SECRET_KEY", "troque-esta-chave"))
db_url = os.getenv("DATABASE_URL", "sqlite:///contas_pagar.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class FinanceUser(db.Model):
    __tablename__ = "finance_user"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Administrador")
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Payable(db.Model):
    __tablename__ = "payable"
    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(120), nullable=False, default="Geral")
    supplier = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(220), nullable=False)
    category = db.Column(db.String(100), default="Outros")
    total_amount = db.Column(db.Float, nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=False)
    document = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    payments = db.relationship("PayablePayment", backref="payable", lazy=True, cascade="all, delete-orphan")

    @property
    def paid_amount(self):
        return round(sum((p.amount or 0) for p in self.payments), 2)

    @property
    def balance(self):
        return max(round((self.total_amount or 0) - self.paid_amount, 2), 0)

    @property
    def status(self):
        if self.balance <= 0.009: return "Pago"
        if self.paid_amount > 0:
            return "Parcial vencido" if self.due_date < date.today() else "Parcial"
        days = (self.due_date - date.today()).days
        if days < 0: return "Vencido"
        if days <= 3: return "Vence em 3 dias"
        if days <= 7: return "Vence em 7 dias"
        return "A vencer"

    @property
    def color_class(self):
        return {"Pago":"green","Vence em 3 dias":"yellow","Vence em 7 dias":"orange","Vencido":"red","Parcial vencido":"red","Parcial":"purple","A vencer":"blue"}.get(self.status,"blue")

class PayablePayment(db.Model):
    __tablename__ = "payable_payment"
    id = db.Column(db.Integer, primary_key=True)
    payable_id = db.Column(db.Integer, db.ForeignKey("payable.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    paid_date = db.Column(db.Date, nullable=False, default=date.today)
    payment_method = db.Column(db.String(80), default="PIX")
    note = db.Column(db.String(220))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Revenue(db.Model):
    __tablename__ = "finance_revenue"
    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(120), nullable=False, default="Geral")
    revenue_date = db.Column(db.Date, nullable=False, default=date.today)
    category = db.Column(db.String(100), nullable=False, default="Vendas")
    description = db.Column(db.String(220), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    payment_method = db.Column(db.String(80), default="PIX")
    document = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def brl(value):
    value = float(value or 0)
    return "R$ {:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")
app.jinja_env.filters["brl"] = brl

def login_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get("finance_user_id"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return inner

def parse_money(raw):
    raw = (raw or "0").replace("R$", "").replace(" ", "")
    if "," in raw: raw = raw.replace(".", "").replace(",", ".")
    try: return float(raw)
    except Exception: return 0.0

def parse_date(value):
    if not value: return None
    try: return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError: return None

def parse_month(value):
    try: start = datetime.strptime(value, "%Y-%m").date()
    except Exception: start = date.today().replace(day=1)
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, end

def all_stores():
    stores = set()
    stores.update(r[0] for r in db.session.query(Payable.store).filter(Payable.store.isnot(None), Payable.store != "").all())
    stores.update(r[0] for r in db.session.query(Revenue.store).filter(Revenue.store.isnot(None), Revenue.store != "").all())
    return sorted(stores)

@app.before_request
def bootstrap():
    db.create_all()
    try:
        cols = {c["name"] for c in inspect(db.engine).get_columns("payable")}
        if "store" not in cols:
            db.session.execute(text("ALTER TABLE payable ADD COLUMN store VARCHAR(120) DEFAULT 'Geral'")); db.session.commit()
    except Exception:
        db.session.rollback()
    if not FinanceUser.query.first():
        email = os.getenv("FINANCE_ADMIN_EMAIL", "financeiro@cervejeiros.com.br")
        password = os.getenv("FINANCE_ADMIN_PASSWORD", "1234")
        db.session.add(FinanceUser(name="Administrador", email=email, password_hash=generate_password_hash(password)))
        db.session.commit()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        user = FinanceUser.query.filter(func.lower(FinanceUser.email) == email).first()
        if user and user.active and check_password_hash(user.password_hash, password):
            session["finance_user_id"] = user.id; session["finance_user_name"] = user.name
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    status_filter = request.args.get("status", "")
    store_filter = request.args.get("store", "").strip()
    search = request.args.get("q", "").strip()
    date_from_raw = request.args.get("date_from", "")
    date_to_raw = request.args.get("date_to", "")
    date_from = parse_date(date_from_raw); date_to = parse_date(date_to_raw)
    month_raw = request.args.get("month", date.today().strftime("%Y-%m"))
    month_start, month_end = parse_month(month_raw)

    q = Payable.query
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Payable.supplier.ilike(like), Payable.description.ilike(like), Payable.category.ilike(like), Payable.store.ilike(like)))
    if store_filter: q = q.filter(Payable.store == store_filter)
    if date_from: q = q.filter(Payable.due_date >= date_from)
    if date_to: q = q.filter(Payable.due_date <= date_to)
    accounts = q.order_by(Payable.due_date.asc(), Payable.id.desc()).all()
    if status_filter: accounts = [a for a in accounts if a.status == status_filter]

    filtered_total = sum(a.total_amount or 0 for a in accounts)
    filtered_paid = sum(a.paid_amount for a in accounts)
    filtered_balance = sum(a.balance for a in accounts)
    overdue_total = sum(a.balance for a in accounts if a.status in ("Vencido", "Parcial vencido"))
    due_7_total = sum(a.balance for a in accounts if a.status in ("Vence em 3 dias", "Vence em 7 dias"))
    overdue_count = sum(1 for a in accounts if a.status in ("Vencido", "Parcial vencido"))

    rq = Revenue.query.filter(Revenue.revenue_date >= month_start, Revenue.revenue_date < month_end)
    pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= month_start, PayablePayment.paid_date < month_end)
    if store_filter:
        rq = rq.filter(Revenue.store == store_filter); pq = pq.filter(Payable.store == store_filter)
    revenue_month = sum(r.amount or 0 for r in rq.all())
    expense_month = sum(p.amount or 0 for p in pq.all())
    result_month = revenue_month - expense_month

    stores = all_stores(); unit_rows = []
    for s in stores:
        rev = sum(r.amount or 0 for r in Revenue.query.filter(Revenue.store == s, Revenue.revenue_date >= month_start, Revenue.revenue_date < month_end).all())
        exp = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(Payable.store == s, PayablePayment.paid_date >= month_start, PayablePayment.paid_date < month_end).all())
        unit_rows.append({"store":s,"revenue":round(rev,2),"expense":round(exp,2),"result":round(rev-exp,2)})

    return render_template("dashboard.html", accounts=accounts, filtered_total=filtered_total, filtered_paid=filtered_paid,
        filtered_balance=filtered_balance, overdue_total=overdue_total, due_7_total=due_7_total,
        overdue_count=overdue_count, status_filter=status_filter, store_filter=store_filter,
        stores=stores, search=search, date_from=date_from_raw, date_to=date_to_raw, today=date.today(),
        month=month_start.strftime("%Y-%m"), revenue_month=revenue_month, expense_month=expense_month,
        result_month=result_month, unit_rows=unit_rows)

@app.route("/nova", methods=["GET", "POST"])
@login_required
def new_payable():
    stores = all_stores()
    if request.method == "POST":
        supplier = request.form.get("supplier", "").strip(); description = request.form.get("description", "").strip()
        store = request.form.get("store", "").strip() or request.form.get("new_store", "").strip() or "Geral"
        total_amount = parse_money(request.form.get("total_amount")); due_date_raw = request.form.get("due_date", "")
        if not supplier or not description or total_amount <= 0 or not due_date_raw:
            flash("Preencha loja, fornecedor, descrição, valor e vencimento.", "danger")
            return render_template("form.html", account=None, stores=stores, today=date.today())
        account = Payable(store=store, supplier=supplier, description=description,
            category=request.form.get("category", "Outros").strip() or "Outros", total_amount=total_amount,
            due_date=datetime.strptime(due_date_raw, "%Y-%m-%d").date(), document=request.form.get("document", "").strip(),
            notes=request.form.get("notes", "").strip())
        db.session.add(account); db.session.flush()
        entry = parse_money(request.form.get("entry_amount"))
        if entry > 0:
            entry = min(entry, total_amount); paid_date_raw = request.form.get("entry_date") or date.today().isoformat()
            db.session.add(PayablePayment(payable_id=account.id, amount=entry,
                paid_date=datetime.strptime(paid_date_raw, "%Y-%m-%d").date(), payment_method=request.form.get("entry_method", "PIX"),
                note="Entrada / pagamento inicial"))
        db.session.commit(); flash("Conta cadastrada com sucesso.", "success"); return redirect(url_for("dashboard"))
    return render_template("form.html", account=None, stores=stores, today=date.today())

@app.route("/receitas/nova", methods=["GET", "POST"])
@login_required
def new_revenue():
    stores = all_stores()
    if request.method == "POST":
        store = request.form.get("store", "").strip() or request.form.get("new_store", "").strip() or "Geral"
        amount = parse_money(request.form.get("amount")); revenue_date = parse_date(request.form.get("revenue_date"))
        description = request.form.get("description", "").strip()
        if amount <= 0 or not revenue_date or not description:
            flash("Preencha unidade, data, descrição e valor da receita.", "danger")
            return render_template("revenue_form.html", stores=stores, today=date.today())
        db.session.add(Revenue(store=store, revenue_date=revenue_date,
            category=request.form.get("category", "Vendas").strip() or "Vendas", description=description, amount=amount,
            payment_method=request.form.get("payment_method", "PIX"), document=request.form.get("document", "").strip(),
            notes=request.form.get("notes", "").strip()))
        db.session.commit(); flash("Receita registrada com sucesso.", "success"); return redirect(url_for("dashboard"))
    return render_template("revenue_form.html", stores=stores, today=date.today())

@app.route("/receitas")
@login_required
def revenues():
    store = request.args.get("store", "").strip(); month = request.args.get("month", date.today().strftime("%Y-%m"))
    start, end = parse_month(month)
    q = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end)
    if store: q = q.filter(Revenue.store == store)
    rows = q.order_by(Revenue.revenue_date.desc(), Revenue.id.desc()).all()
    return render_template("revenues.html", rows=rows, stores=all_stores(), store_filter=store, month=month, total=sum(r.amount or 0 for r in rows))

@app.route("/dre")
@login_required
def dre():
    store = request.args.get("store", "").strip(); month = request.args.get("month", date.today().strftime("%Y-%m"))
    start, end = parse_month(month)
    rq = Revenue.query.filter(Revenue.revenue_date >= start, Revenue.revenue_date < end)
    pq = PayablePayment.query.join(Payable).filter(PayablePayment.paid_date >= start, PayablePayment.paid_date < end)
    if store:
        rq = rq.filter(Revenue.store == store); pq = pq.filter(Payable.store == store)
    revenue_by_category = {}; expense_by_category = {}
    for r in rq.all(): revenue_by_category[r.category] = revenue_by_category.get(r.category, 0) + (r.amount or 0)
    for p in pq.all():
        cat = p.payable.category or "Outros"; expense_by_category[cat] = expense_by_category.get(cat, 0) + (p.amount or 0)
    total_revenue = sum(revenue_by_category.values()); total_expense = sum(expense_by_category.values())
    result = total_revenue - total_expense; margin = (result / total_revenue * 100) if total_revenue else 0
    unit_rows = []
    for s in all_stores():
        rev = sum(r.amount or 0 for r in Revenue.query.filter(Revenue.store == s, Revenue.revenue_date >= start, Revenue.revenue_date < end).all())
        exp = sum(p.amount or 0 for p in PayablePayment.query.join(Payable).filter(Payable.store == s, PayablePayment.paid_date >= start, PayablePayment.paid_date < end).all())
        unit_rows.append({"store":s,"revenue":rev,"expense":exp,"result":rev-exp})
    return render_template("dre.html", stores=all_stores(), store_filter=store, month=month,
        revenue_by_category=revenue_by_category, expense_by_category=expense_by_category,
        total_revenue=total_revenue, total_expense=total_expense, result=result, margin=margin, unit_rows=unit_rows)

@app.route("/conta/<int:account_id>")
@login_required
def detail(account_id):
    return render_template("detail.html", account=Payable.query.get_or_404(account_id))

@app.route("/conta/<int:account_id>/editar", methods=["GET", "POST"])
@login_required
def edit_payable(account_id):
    account = Payable.query.get_or_404(account_id); stores = all_stores()
    if request.method == "POST":
        account.store = request.form.get("store", "").strip() or request.form.get("new_store", "").strip() or "Geral"
        account.supplier = request.form.get("supplier", "").strip(); account.description = request.form.get("description", "").strip()
        account.category = request.form.get("category", "Outros").strip() or "Outros"
        account.total_amount = parse_money(request.form.get("total_amount")); account.due_date = datetime.strptime(request.form.get("due_date"), "%Y-%m-%d").date()
        account.document = request.form.get("document", "").strip(); account.notes = request.form.get("notes", "").strip()
        db.session.commit(); flash("Conta atualizada.", "success"); return redirect(url_for("detail", account_id=account.id))
    return render_template("form.html", account=account, stores=stores, today=date.today())

@app.route("/conta/<int:account_id>/pagar", methods=["POST"])
@login_required
def add_payment(account_id):
    account = Payable.query.get_or_404(account_id); amount = parse_money(request.form.get("amount"))
    if amount <= 0:
        flash("Informe um valor de pagamento válido.", "danger"); return redirect(url_for("detail", account_id=account.id))
    amount = min(amount, account.balance); paid_date_raw = request.form.get("paid_date") or date.today().isoformat()
    db.session.add(PayablePayment(payable_id=account.id, amount=amount,
        paid_date=datetime.strptime(paid_date_raw, "%Y-%m-%d").date(), payment_method=request.form.get("payment_method", "PIX"),
        note=request.form.get("note", "").strip()))
    db.session.commit(); flash("Pagamento registrado e saldo atualizado.", "success"); return redirect(url_for("detail", account_id=account.id))

@app.route("/conta/<int:account_id>/baixar", methods=["POST"])
@login_required
def settle(account_id):
    account = Payable.query.get_or_404(account_id)
    if account.balance > 0:
        db.session.add(PayablePayment(payable_id=account.id, amount=account.balance, paid_date=date.today(),
            payment_method=request.form.get("payment_method", "PIX"), note="Baixa total"))
        db.session.commit(); flash("Conta baixada como paga.", "success")
    return redirect(url_for("detail", account_id=account.id))

@app.route("/conta/<int:account_id>/excluir", methods=["POST"])
@login_required
def delete_payable(account_id):
    account = Payable.query.get_or_404(account_id); db.session.delete(account); db.session.commit()
    flash("Conta excluída.", "success"); return redirect(url_for("dashboard"))

@app.route("/alertas")
@login_required
def alerts():
    accounts = Payable.query.order_by(Payable.due_date.asc()).all()
    alerts = [a for a in accounts if a.balance > 0 and a.status in ("Vencido","Parcial vencido","Vence em 3 dias","Vence em 7 dias")]
    return render_template("alerts.html", accounts=alerts, today=date.today())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
