import os, csv, io, json, urllib.request, urllib.error
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave")
db_url = os.getenv("DATABASE_URL", "sqlite:///crm_cervejeiros.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

PIPELINE = ["Novo Lead","Em Qualificação","Qualificado","Reunião Agendada","Proposta Enviada","Negociação","Fechado","Perdido"]
TIMEFRAMES = ["Imediato","Até 30 dias","1 a 3 meses","3 a 6 meses","Mais de 6 meses","Sem prazo"]
SOURCES = ["WhatsApp","Instagram","Facebook","Google","Indicação","Site","Formulário","Evento","Outro"]

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Usuário")
    email = db.Column(db.String(180), unique=True, nullable=False)
    phone = db.Column(db.String(40))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="seller")  # admin | manager | seller
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)

class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(180))
    city = db.Column(db.String(120))
    state = db.Column(db.String(40))
    source = db.Column(db.String(80), default="WhatsApp")
    investment = db.Column(db.Float, default=0)
    timeframe = db.Column(db.String(40), default="Sem prazo")
    entrepreneur = db.Column(db.String(20), default="Não informado")
    meeting_interest = db.Column(db.String(20), default="Não informado")
    model_interest = db.Column(db.String(80), default="Ainda não definiu")
    notes = db.Column(db.Text)
    score = db.Column(db.Integer, default=0)
    temperature = db.Column(db.String(20), default="Frio")
    stage = db.Column(db.String(60), default="Novo Lead")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    owner = db.relationship("User", foreign_keys=[owner_id])
    last_contact = db.Column(db.DateTime)
    next_followup = db.Column(db.DateTime)
    lost_reason = db.Column(db.String(200))
    closed_value = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Interaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    direction = db.Column(db.String(20), default="out")
    channel = db.Column(db.String(40), default="CRM")
    message = db.Column(db.Text, nullable=False)
    ai_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lead = db.relationship("Lead", backref=db.backref("interactions", lazy=True, cascade="all, delete-orphan"))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"))
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    title = db.Column(db.String(180), nullable=False)
    task_type = db.Column(db.String(50), default="Follow-up")
    due_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), default="Pendente")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lead = db.relationship("Lead")
    owner = db.relationship("User")

class AutomationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"))
    action = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def get_setting(key, default=None):
    row = Setting.query.filter_by(key=key).first()
    return row.value if row else default

def set_setting(key, value):
    row = Setting.query.filter_by(key=key).first()
    if not row:
        row = Setting(key=key, value=str(value)); db.session.add(row)
    else:
        row.value = str(value)

def score_lead(lead):
    score = 0
    inv = lead.investment or 0
    if inv >= 55000: score += 30
    elif inv >= 35000: score += 25
    elif inv >= 24000: score += 20
    elif inv >= 17900: score += 12
    elif inv > 0: score += 5
    score += {"Imediato":25,"Até 30 dias":22,"1 a 3 meses":18,"3 a 6 meses":10,"Mais de 6 meses":5,"Sem prazo":0}.get(lead.timeframe,0)
    if lead.entrepreneur == "Sim": score += 15
    elif lead.entrepreneur == "Talvez": score += 7
    if lead.meeting_interest == "Sim": score += 20
    elif lead.meeting_interest == "Talvez": score += 8
    if lead.city and lead.state: score += 5
    if lead.email: score += 3
    if lead.model_interest and lead.model_interest != "Ainda não definiu": score += 2
    return min(score,100)

def temperature(score):
    hot = int(get_setting("hot_score","70"))
    warm = int(get_setting("warm_score","35"))
    return "Quente" if score >= hot else ("Morno" if score >= warm else "Frio")

def auto_stage(lead, preserve=True):
    if preserve and lead.stage in {"Reunião Agendada","Proposta Enviada","Negociação","Fechado","Perdido"}:
        return lead.stage
    hot = int(get_setting("hot_score","70"))
    warm = int(get_setting("warm_score","35"))
    return "Qualificado" if lead.score >= hot else ("Em Qualificação" if lead.score >= warm else "Novo Lead")

def followup_delta(lead):
    if lead.temperature=="Quente": return timedelta(hours=4)
    if lead.temperature=="Morno": return timedelta(days=1)
    return timedelta(days=3)

def ensure_followup_task(lead):
    if lead.stage in ["Fechado","Perdido"]:
        return
    due = datetime.utcnow() + followup_delta(lead)
    lead.next_followup = due
    existing = Task.query.filter_by(lead_id=lead.id, task_type="Follow-up", status="Pendente").first()
    if existing:
        existing.due_at = due
        existing.owner_id = lead.owner_id
    else:
        db.session.add(Task(lead_id=lead.id, owner_id=lead.owner_id, title=f"Follow-up com {lead.name}",
                            task_type="Follow-up", due_at=due))

def assign_round_robin(lead):
    if lead.owner_id or get_setting("auto_assign","1") != "1":
        return
    sellers = User.query.filter(User.active==True, User.role.in_(["seller","manager"])).order_by(User.id).all()
    if not sellers:
        return
    last = int(get_setting("last_assigned_user_id","0") or 0)
    idx = 0
    for i,s in enumerate(sellers):
        if s.id == last:
            idx = (i+1) % len(sellers); break
    lead.owner_id = sellers[idx].id
    set_setting("last_assigned_user_id", sellers[idx].id)
    db.session.add(AutomationLog(lead_id=lead.id, action="Distribuição automática", detail=f"Lead atribuído a {sellers[idx].name}"))

def ai_reply(lead, objective="qualificar"):
    prompt = f"""Você é o assistente comercial da Cervejeiros Auto Serviço de Chopp.
Responda em português brasileiro, curto e profissional, ideal para WhatsApp.
Objetivo: {objective}.
Conduza o lead para a próxima etapa sem inventar condições comerciais.
Nome: {lead.name}; cidade/UF: {lead.city}/{lead.state}; investimento: {lead.investment};
prazo: {lead.timeframe}; empreendedor: {lead.entrepreneur}; aceita reunião: {lead.meeting_interest};
plano: {lead.model_interest}; score: {lead.score}/100; temperatura: {lead.temperature}; etapa: {lead.stage}.
Contexto: operação de geladeiras de autoatendimento de chopp, aplicativo, dashboard de gestão, acompanhamento de vendas e suporte comercial.
Finalize com uma pergunta clara."""
    key = os.getenv("OPENAI_API_KEY")
    if key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            response = client.responses.create(
                model=os.getenv("OPENAI_MODEL","gpt-5.6"),
                input=prompt,
                max_output_tokens=260
            )
            if response.output_text:
                return response.output_text.strip()
        except Exception as e:
            app.logger.warning("Falha OpenAI: %s", e)
    first=(lead.name or "Olá").split()[0]
    if lead.temperature=="Quente":
        return f"Olá, {first}! 🍻 Seu perfil está bem alinhado à operação Cervejeiros. O próximo passo é uma reunião rápida para apresentarmos o modelo e avaliarmos a disponibilidade para {lead.city or 'sua região'}. Qual dia e horário funcionam melhor para você?"
    if lead.temperature=="Morno":
        return f"Olá, {first}! 🍻 Obrigado pelo interesse na Cervejeiros. Para avançarmos na análise do seu perfil, quero confirmar sua faixa de investimento e em quanto tempo pretende iniciar. Pode me passar essas duas informações?"
    return f"Olá, {first}! 🍻 Obrigado pelo interesse na Cervejeiros. Para começarmos sua qualificação, qual cidade você pretende operar, qual faixa de investimento tem disponível e em quanto tempo gostaria de começar?"

def normalize_phone(phone):
    digits="".join(c for c in (phone or "") if c.isdigit())
    if digits and not digits.startswith("55"): digits="55"+digits
    return digits

def send_whatsapp_cloud(phone, message):
    token=os.getenv("WHATSAPP_TOKEN")
    phone_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return False, "WhatsApp Cloud API não configurada."
    url=f"https://graph.facebook.com/v23.0/{phone_id}/messages"
    payload=json.dumps({"messaging_product":"whatsapp","to":normalize_phone(phone),"type":"text","text":{"body":message}}).encode()
    req=urllib.request.Request(url,data=payload,headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            return True, r.read().decode()
    except Exception as e:
        return False, str(e)

def current_user():
    return db.session.get(User, session.get("user_id")) if session.get("user_id") else None

def login_required(fn):
    @wraps(fn)
    def inner(*args,**kwargs):
        if not session.get("user_id"): return redirect(url_for("login"))
        return fn(*args,**kwargs)
    return inner

def admin_required(fn):
    @wraps(fn)
    def inner(*args,**kwargs):
        u=current_user()
        if not u or u.role not in ["admin","manager"]:
            flash("Acesso restrito.","danger"); return redirect(url_for("dashboard"))
        return fn(*args,**kwargs)
    return inner

def visible_leads_query():
    u=current_user()
    if u and u.role=="seller":
        return Lead.query.filter_by(owner_id=u.id)
    return Lead.query

def fill_lead(lead, form):
    lead.name=form.get("name","").strip()
    lead.phone=form.get("phone","").strip()
    lead.email=form.get("email","").strip()
    lead.city=form.get("city","").strip()
    lead.state=form.get("state","").strip().upper()
    lead.source=form.get("source","WhatsApp")
    raw=(form.get("investment") or "0").replace("R$","").replace(" ","")
    try:
        if "," in raw: raw=raw.replace(".","").replace(",",".")
        lead.investment=float(raw)
    except: lead.investment=0
    lead.timeframe=form.get("timeframe","Sem prazo")
    lead.entrepreneur=form.get("entrepreneur","Não informado")
    lead.meeting_interest=form.get("meeting_interest","Não informado")
    lead.model_interest=form.get("model_interest","Ainda não definiu")
    lead.notes=form.get("notes","").strip()

def requalify(lead, preserve=True):
    old=(lead.score,lead.temperature,lead.stage)
    lead.score=score_lead(lead)
    lead.temperature=temperature(lead.score)
    lead.stage=auto_stage(lead,preserve=preserve)
    ensure_followup_task(lead)
    if old != (lead.score,lead.temperature,lead.stage):
        db.session.add(AutomationLog(lead_id=lead.id, action="Requalificação automática",
                                     detail=f"Score {lead.score}, {lead.temperature}, etapa {lead.stage}"))

@app.before_request
def bootstrap():
    db.create_all()
    if not User.query.first():
        admin=User(name="Administrador",email=os.getenv("ADMIN_EMAIL","admin@cervejeiros.com.br"),
                   password_hash=generate_password_hash(os.getenv("ADMIN_PASSWORD","1234")),role="admin")
        db.session.add(admin)
        set_setting("auto_assign","1"); set_setting("hot_score","70"); set_setting("warm_score","35")
        db.session.commit()

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=User.query.filter_by(email=request.form["email"].strip()).first()
        if u and u.active and check_password_hash(u.password_hash,request.form["password"]):
            session["user_id"]=u.id; session["user_name"]=u.name; session["role"]=u.role
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha inválidos.","danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    leads=visible_leads_query().all()
    total=len(leads); closed=sum(l.stage=="Fechado" for l in leads)
    qualified=sum(l.score>=int(get_setting("hot_score","70")) for l in leads)
    conv=round(closed/total*100,1) if total else 0
    by_stage={s:sum(l.stage==s for l in leads) for s in PIPELINE}
    due=Task.query.filter(Task.status=="Pendente",Task.due_at<=datetime.utcnow())
    u=current_user()
    if u.role=="seller": due=due.filter_by(owner_id=u.id)
    due=due.order_by(Task.due_at).limit(10).all()
    hot=sorted([l for l in leads if l.temperature=="Quente" and l.stage not in ["Fechado","Perdido"]],key=lambda x:x.score,reverse=True)[:8]
    sellers=[]
    if u.role in ["admin","manager"]:
        for s in User.query.filter(User.active==True,User.role.in_(["seller","manager"])).all():
            ls=Lead.query.filter_by(owner_id=s.id).all()
            sellers.append({"name":s.name,"leads":len(ls),"closed":sum(x.stage=="Fechado" for x in ls),
                            "conv":round(sum(x.stage=="Fechado" for x in ls)/len(ls)*100,1) if ls else 0})
    return render_template("dashboard.html",total=total,closed=closed,qualified=qualified,conv=conv,by_stage=by_stage,due=due,hot=hot,sellers=sellers)

@app.route("/leads")
@login_required
def leads():
    q=request.args.get("q","").strip(); stage=request.args.get("stage","").strip()
    query=visible_leads_query()
    if q:
        like=f"%{q}%"; query=query.filter(db.or_(Lead.name.ilike(like),Lead.phone.ilike(like),Lead.city.ilike(like),Lead.email.ilike(like)))
    if stage: query=query.filter_by(stage=stage)
    return render_template("leads.html",leads=query.order_by(Lead.created_at.desc()).all(),pipeline=PIPELINE,q=q,stage=stage)

@app.route("/lead/new",methods=["GET","POST"])
@login_required
def lead_new():
    if request.method=="POST":
        lead=Lead(); fill_lead(lead,request.form)
        if session.get("role")=="seller": lead.owner_id=session["user_id"]
        db.session.add(lead); db.session.flush()
        assign_round_robin(lead); requalify(lead,preserve=False)
        msg=ai_reply(lead,"primeiro contato e qualificação")
        db.session.add(Interaction(lead_id=lead.id,user_id=session["user_id"],message=msg,ai_generated=True,channel="IA"))
        db.session.commit()
        flash("Lead cadastrado, distribuído e qualificado automaticamente.","success")
        return redirect(url_for("lead_detail",lead_id=lead.id))
    sellers=User.query.filter(User.active==True,User.role.in_(["seller","manager"])).all()
    return render_template("lead_form.html",lead=None,pipeline=PIPELINE,sources=SOURCES,timeframes=TIMEFRAMES,sellers=sellers)

@app.route("/lead/<int:lead_id>")
@login_required
def lead_detail(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    interactions=Interaction.query.filter_by(lead_id=lead.id).order_by(Interaction.created_at.desc()).all()
    tasks=Task.query.filter_by(lead_id=lead.id).order_by(Task.due_at).all()
    logs=AutomationLog.query.filter_by(lead_id=lead.id).order_by(AutomationLog.created_at.desc()).limit(10).all()
    latest=next((i for i in interactions if i.ai_generated),None)
    wa=None
    if latest: wa=f"https://wa.me/{normalize_phone(lead.phone)}?text={quote(latest.message)}"
    sellers=User.query.filter(User.active==True,User.role.in_(["seller","manager"])).all()
    return render_template("lead_detail.html",lead=lead,interactions=interactions,tasks=tasks,logs=logs,latest=latest,wa=wa,pipeline=PIPELINE,sellers=sellers)

@app.route("/lead/<int:lead_id>/edit",methods=["GET","POST"])
@login_required
def lead_edit(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    if request.method=="POST":
        fill_lead(lead,request.form)
        if session.get("role") in ["admin","manager"] and request.form.get("owner_id"):
            lead.owner_id=int(request.form["owner_id"])
        manual=request.form.get("stage",lead.stage)
        if manual in ["Reunião Agendada","Proposta Enviada","Negociação","Fechado","Perdido"]: lead.stage=manual
        requalify(lead,preserve=True)
        if manual in ["Reunião Agendada","Proposta Enviada","Negociação","Fechado","Perdido"]: lead.stage=manual
        if manual=="Fechado":
            try: lead.closed_value=float((request.form.get("closed_value") or "0").replace(".","").replace(",","."))
            except: pass
        if manual=="Perdido": lead.lost_reason=request.form.get("lost_reason","")
        db.session.commit(); flash("Lead atualizado.","success")
        return redirect(url_for("lead_detail",lead_id=lead.id))
    sellers=User.query.filter(User.active==True,User.role.in_(["seller","manager"])).all()
    return render_template("lead_form.html",lead=lead,pipeline=PIPELINE,sources=SOURCES,timeframes=TIMEFRAMES,sellers=sellers)

@app.route("/lead/<int:lead_id>/stage",methods=["POST"])
@login_required
def lead_stage(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    stage=request.form.get("stage")
    if stage in PIPELINE:
        lead.stage=stage
        if stage=="Perdido": lead.lost_reason=request.form.get("lost_reason","")
        ensure_followup_task(lead)
        db.session.add(AutomationLog(lead_id=lead.id,action="Movimentação de pipeline",detail=f"Movido para {stage}"))
        db.session.commit()
    return redirect(request.referrer or url_for("leads"))

@app.route("/lead/<int:lead_id>/ai",methods=["POST"])
@login_required
def lead_ai(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    msg=ai_reply(lead,request.form.get("objective","avançar para a próxima etapa"))
    db.session.add(Interaction(lead_id=lead.id,user_id=session["user_id"],message=msg,ai_generated=True,channel="IA"))
    db.session.commit(); flash("Resposta da IA gerada.","success")
    return redirect(url_for("lead_detail",lead_id=lead.id))

@app.route("/lead/<int:lead_id>/send-whatsapp",methods=["POST"])
@login_required
def lead_send_whatsapp(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    message=request.form.get("message","").strip()
    ok,detail=send_whatsapp_cloud(lead.phone,message)
    if ok:
        db.session.add(Interaction(lead_id=lead.id,user_id=session["user_id"],channel="WhatsApp",message=message,direction="out"))
        lead.last_contact=datetime.utcnow(); db.session.commit()
        flash("Mensagem enviada pelo WhatsApp Business.","success")
    else:
        flash(detail,"danger")
    return redirect(url_for("lead_detail",lead_id=lead.id))

@app.route("/lead/<int:lead_id>/interaction",methods=["POST"])
@login_required
def lead_interaction(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    msg=request.form.get("message","").strip()
    if msg:
        db.session.add(Interaction(lead_id=lead.id,user_id=session["user_id"],channel=request.form.get("channel","WhatsApp"),message=msg))
        lead.last_contact=datetime.utcnow(); ensure_followup_task(lead); db.session.commit()
    return redirect(url_for("lead_detail",lead_id=lead.id))

@app.route("/lead/<int:lead_id>/task",methods=["POST"])
@login_required
def lead_task(lead_id):
    lead=visible_leads_query().filter_by(id=lead_id).first_or_404()
    try: due=datetime.fromisoformat(request.form["due_at"])
    except: due=datetime.utcnow()+timedelta(days=1)
    db.session.add(Task(lead_id=lead.id,owner_id=lead.owner_id,title=request.form.get("title","Follow-up"),
                        task_type=request.form.get("task_type","Follow-up"),due_at=due,notes=request.form.get("notes","")))
    db.session.commit(); flash("Atividade criada.","success")
    return redirect(url_for("lead_detail",lead_id=lead.id))

@app.route("/task/<int:task_id>/done",methods=["POST"])
@login_required
def task_done(task_id):
    task=db.session.get(Task,task_id)
    if task:
        task.status="Concluída"; db.session.commit()
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/pipeline")
@login_required
def pipeline():
    q=visible_leads_query()
    cols={s:q.filter_by(stage=s).order_by(Lead.score.desc()).all() for s in PIPELINE}
    return render_template("pipeline.html",columns=cols,pipeline=PIPELINE)

@app.route("/agenda")
@login_required
def agenda():
    q=Task.query
    if session.get("role")=="seller": q=q.filter_by(owner_id=session["user_id"])
    tasks=q.order_by(Task.due_at).all()
    return render_template("agenda.html",tasks=tasks)

@app.route("/reports")
@login_required
def reports():
    leads=visible_leads_query().all()
    by_stage={s:sum(l.stage==s for l in leads) for s in PIPELINE}
    by_source={s:sum((l.source or "N/I")==s for l in leads) for s in sorted(set((l.source or "N/I") for l in leads))}
    by_state={s:sum((l.state or "N/I")==s for l in leads) for s in sorted(set((l.state or "N/I") for l in leads))}
    temps={t:sum(l.temperature==t for l in leads) for t in ["Quente","Morno","Frio"]}
    seller_data=[]
    if session.get("role") in ["admin","manager"]:
        for u in User.query.filter(User.active==True,User.role.in_(["seller","manager"])).all():
            ls=Lead.query.filter_by(owner_id=u.id).all()
            seller_data.append({"name":u.name,"leads":len(ls),"hot":sum(x.temperature=="Quente" for x in ls),
                                "closed":sum(x.stage=="Fechado" for x in ls),
                                "value":sum(x.closed_value or 0 for x in ls),
                                "conversion":round(sum(x.stage=="Fechado" for x in ls)/len(ls)*100,1) if ls else 0})
    return render_template("reports.html",leads=leads,by_stage=by_stage,by_source=by_source,by_state=by_state,temps=temps,seller_data=seller_data)

@app.route("/export/leads.csv")
@login_required
def export_leads():
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["id","nome","telefone","email","cidade","uf","origem","investimento","prazo","score","temperatura","etapa","responsavel","criado_em"])
    for l in visible_leads_query().order_by(Lead.id).all():
        w.writerow([l.id,l.name,l.phone,l.email,l.city,l.state,l.source,l.investment,l.timeframe,l.score,l.temperature,l.stage,l.owner.name if l.owner else "",l.created_at.isoformat()])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=leads_cervejeiros.csv"})

@app.route("/import",methods=["GET","POST"])
@login_required
@admin_required
def import_leads():
    if request.method=="POST":
        f=request.files.get("file")
        if not f: flash("Selecione um CSV.","danger"); return redirect(url_for("import_leads"))
        text=f.stream.read().decode("utf-8-sig",errors="ignore")
        reader=csv.DictReader(io.StringIO(text))
        count=0
        for row in reader:
            name=(row.get("nome") or row.get("name") or "").strip()
            phone=(row.get("telefone") or row.get("phone") or row.get("whatsapp") or "").strip()
            if not name or not phone: continue
            lead=Lead(name=name,phone=phone,email=row.get("email",""),city=row.get("cidade",""),state=row.get("uf",""),
                      source=row.get("origem","Importação"),timeframe=row.get("prazo","Sem prazo"))
            try: lead.investment=float((row.get("investimento") or "0").replace(".","").replace(",","."))
            except: pass
            db.session.add(lead); db.session.flush(); assign_round_robin(lead); requalify(lead,preserve=False); count+=1
        db.session.commit(); flash(f"{count} leads importados e qualificados.","success")
        return redirect(url_for("leads"))
    return render_template("import.html")

@app.route("/team")
@login_required
@admin_required
def team():
    return render_template("team.html",users=User.query.order_by(User.name).all())

@app.route("/team/new",methods=["POST"])
@login_required
@admin_required
def team_new():
    email=request.form["email"].strip()
    if User.query.filter_by(email=email).first():
        flash("E-mail já cadastrado.","danger"); return redirect(url_for("team"))
    u=User(name=request.form["name"].strip(),email=email,phone=request.form.get("phone",""),
           role=request.form.get("role","seller"),password_hash=generate_password_hash(request.form.get("password") or "1234"))
    db.session.add(u); db.session.commit(); flash("Usuário criado.","success")
    return redirect(url_for("team"))

@app.route("/settings",methods=["GET","POST"])
@login_required
@admin_required
def settings():
    if request.method=="POST":
        for key in ["auto_assign","hot_score","warm_score"]:
            set_setting(key,request.form.get(key,""))
        db.session.commit(); flash("Configurações salvas.","success")
    return render_template("settings.html",auto_assign=get_setting("auto_assign","1"),hot_score=get_setting("hot_score","70"),warm_score=get_setting("warm_score","35"),
                           openai=bool(os.getenv("OPENAI_API_KEY")),whatsapp=bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID")))

@app.route("/captura",methods=["GET","POST"])
def capture():
    if request.method=="POST":
        lead=Lead(); fill_lead(lead,request.form); lead.source=request.form.get("source","Formulário")
        db.session.add(lead); db.session.flush(); assign_round_robin(lead); requalify(lead,preserve=False)
        msg=ai_reply(lead,"agradecer o cadastro e orientar o próximo passo")
        db.session.add(Interaction(lead_id=lead.id,message=msg,ai_generated=True,channel="IA"))
        db.session.commit()
        return render_template("capture_success.html",lead=lead,message=msg)
    return render_template("capture.html",timeframes=TIMEFRAMES)

@app.route("/api/lead",methods=["POST"])
def api_lead():
    data=request.get_json(silent=True) or request.form
    if not data.get("name") or not data.get("phone"): return jsonify({"ok":False,"error":"name e phone obrigatórios"}),400
    lead=Lead(name=data.get("name"),phone=data.get("phone"),email=data.get("email",""),city=data.get("city",""),state=data.get("state",""),
              source=data.get("source","API"),timeframe=data.get("timeframe","Sem prazo"),entrepreneur=data.get("entrepreneur","Não informado"),
              meeting_interest=data.get("meeting_interest","Não informado"),model_interest=data.get("model_interest","Ainda não definiu"),notes=data.get("notes",""))
    try: lead.investment=float(data.get("investment") or 0)
    except: pass
    db.session.add(lead); db.session.flush(); assign_round_robin(lead); requalify(lead,preserve=False)
    msg=ai_reply(lead,"primeiro contato e qualificação")
    db.session.add(Interaction(lead_id=lead.id,message=msg,ai_generated=True,channel="IA")); db.session.commit()
    return jsonify({"ok":True,"lead_id":lead.id,"score":lead.score,"temperature":lead.temperature,"stage":lead.stage,"owner":lead.owner.name if lead.owner else None,"ai_reply":msg})

@app.route("/webhooks/whatsapp",methods=["GET","POST"])
def whatsapp_webhook():
    if request.method=="GET":
        if request.args.get("hub.verify_token")==os.getenv("WHATSAPP_VERIFY_TOKEN"):
            return request.args.get("hub.challenge",""),200
        return "verification failed",403
    data=request.get_json(silent=True) or {}
    try:
        value=data["entry"][0]["changes"][0]["value"]
        messages=value.get("messages",[])
        for m in messages:
            phone=m.get("from","")
            text=(m.get("text") or {}).get("body","")
            local=phone[-11:]
            lead=Lead.query.filter(Lead.phone.like(f"%{local}%")).order_by(Lead.id.desc()).first()
            if lead and text:
                db.session.add(Interaction(lead_id=lead.id,channel="WhatsApp",direction="in",message=text))
                lead.last_contact=datetime.utcnow()
                if os.getenv("AUTO_REPLY_WHATSAPP","0")=="1":
                    reply=ai_reply(lead,"responder a mensagem recebida e avançar o lead")
                    ok,_=send_whatsapp_cloud(lead.phone,reply)
                    if ok: db.session.add(Interaction(lead_id=lead.id,channel="WhatsApp",direction="out",message=reply,ai_generated=True))
                db.session.commit()
    except Exception as e:
        app.logger.warning("Webhook WhatsApp: %s",e)
    return "ok",200

if __name__=="__main__":
    with app.app_context(): db.create_all()
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=os.getenv("FLASK_DEBUG")=="1")
