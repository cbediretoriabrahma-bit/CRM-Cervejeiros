import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from flask import render_template, request, session
from sqlalchemy import event

import patched_app as patched

crm = patched.crm
app = patched.app
db = crm.db

TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")
CONTACT_TAG = "PIPELINE_CONTACTED"


class LeadAnalytics(db.Model):
    """Registro histórico independente do Lead.

    Não possui FK propositalmente: quando o Lead é excluído do CRM, a linha
    estatística continua existindo para preservar as taxas de conversão.
    """

    __tablename__ = "lead_analytics"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    name = db.Column(db.String(160))
    source = db.Column(db.String(80), default="N/I", index=True)
    city = db.Column(db.String(120))
    state = db.Column(db.String(40), index=True)
    owner_id = db.Column(db.Integer, index=True)

    received_at = db.Column(db.DateTime, nullable=False, index=True)
    contacted_at = db.Column(db.DateTime)
    meeting1_scheduled_at = db.Column(db.DateTime)
    meeting1_done_at = db.Column(db.DateTime)
    meeting2_scheduled_at = db.Column(db.DateTime)
    meeting2_done_at = db.Column(db.DateTime)
    contract_sent_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    lost_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)

    last_stage = db.Column(db.String(80))
    last_updated_at = db.Column(db.DateTime, default=datetime.utcnow)


FUNNEL_STAGES = [
    "Reunião Agendada",
    "1ª Reunião Realizada",
    "2ª Reunião Agendada",
    "2ª Reunião Realizada",
    "Contrato Enviado",
    "Fechado",
]

# Etapas antigas são tratadas como avanço comercial equivalente para não
# perder histórico de registros criados antes do pipeline atual.
LEGACY_STAGE_MAP = {
    "Proposta Enviada": "Contrato Enviado",
    "Negociação": "Contrato Enviado",
}


def _is_contacted(lead):
    notes = lead.notes or ""
    tagged = re.search(rf"^\[{CONTACT_TAG}\]=(.*)$", notes, flags=re.MULTILINE)
    return bool(lead.last_contact or (tagged and tagged.group(1).strip() == "1"))


def _existing_dict(connection, lead_id):
    row = connection.execute(
        LeadAnalytics.__table__.select().where(LeadAnalytics.__table__.c.lead_id == lead_id)
    ).first()
    return dict(row._mapping) if row else None


def _stage_values(stage, existing, marker):
    values = {}
    stage = LEGACY_STAGE_MAP.get(stage or "", stage or "")

    if stage in FUNNEL_STAGES:
        rank = FUNNEL_STAGES.index(stage)
        milestones = [
            (0, "meeting1_scheduled_at"),
            (1, "meeting1_done_at"),
            (2, "meeting2_scheduled_at"),
            (3, "meeting2_done_at"),
            (4, "contract_sent_at"),
            (5, "closed_at"),
        ]
        for required_rank, field in milestones:
            if rank >= required_rank and not (existing or {}).get(field):
                values[field] = marker

    if stage == "Perdido" and not (existing or {}).get("lost_at"):
        values["lost_at"] = marker

    return values


def _snapshot_values(lead, existing=None, deleted=False):
    now = datetime.utcnow()
    marker = lead.updated_at or now
    values = {
        "name": lead.name,
        "source": (lead.source or "N/I").strip() or "N/I",
        "city": lead.city,
        "state": (lead.state or "").strip().upper() or None,
        "owner_id": lead.owner_id,
        "last_stage": lead.stage,
        "last_updated_at": now,
    }

    if _is_contacted(lead) and not (existing or {}).get("contacted_at"):
        values["contacted_at"] = marker

    values.update(_stage_values(lead.stage, existing, marker))

    if deleted and not (existing or {}).get("deleted_at"):
        values["deleted_at"] = now

    return values


def _upsert_snapshot(connection, lead, deleted=False):
    table = LeadAnalytics.__table__
    existing = _existing_dict(connection, lead.id)
    values = _snapshot_values(lead, existing=existing, deleted=deleted)

    if existing:
        connection.execute(table.update().where(table.c.lead_id == lead.id).values(**values))
    else:
        values.update(
            lead_id=lead.id,
            received_at=lead.created_at or datetime.utcnow(),
        )
        connection.execute(table.insert().values(**values))


@event.listens_for(crm.Lead, "after_insert")
def _lead_analytics_after_insert(mapper, connection, target):
    _upsert_snapshot(connection, target)


@event.listens_for(crm.Lead, "after_update")
def _lead_analytics_after_update(mapper, connection, target):
    _upsert_snapshot(connection, target)


@event.listens_for(crm.Lead, "after_delete")
def _lead_analytics_after_delete(mapper, connection, target):
    _upsert_snapshot(connection, target, deleted=True)


_BACKFILL_DONE = False


def _infer_backfill(lead):
    row = LeadAnalytics(
        lead_id=lead.id,
        name=lead.name,
        source=(lead.source or "N/I").strip() or "N/I",
        city=lead.city,
        state=(lead.state or "").strip().upper() or None,
        owner_id=lead.owner_id,
        received_at=lead.created_at or datetime.utcnow(),
        last_stage=lead.stage,
        last_updated_at=lead.updated_at or datetime.utcnow(),
    )

    marker = lead.updated_at or lead.created_at or datetime.utcnow()
    if _is_contacted(lead):
        row.contacted_at = marker

    stage = LEGACY_STAGE_MAP.get(lead.stage or "", lead.stage or "")
    if stage in FUNNEL_STAGES:
        rank = FUNNEL_STAGES.index(stage)
        if rank >= 0:
            row.meeting1_scheduled_at = marker
        if rank >= 1:
            row.meeting1_done_at = marker
        if rank >= 2:
            row.meeting2_scheduled_at = marker
        if rank >= 3:
            row.meeting2_done_at = marker
        if rank >= 4:
            row.contract_sent_at = marker
        if rank >= 5:
            row.closed_at = marker
    if stage == "Perdido":
        row.lost_at = marker
    return row


@app.before_request
def _backfill_lead_analytics_once():
    global _BACKFILL_DONE
    if _BACKFILL_DONE:
        return

    try:
        existing_ids = {lead_id for (lead_id,) in db.session.query(LeadAnalytics.lead_id).all()}
        missing = crm.Lead.query.filter(~crm.Lead.id.in_(existing_ids)).all() if existing_ids else crm.Lead.query.all()
        for lead in missing:
            db.session.add(_infer_backfill(lead))
        if missing:
            db.session.commit()
        _BACKFILL_DONE = True
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Falha ao preparar histórico estatístico de leads: %s", exc)


def _local_bounds(period, date_from, date_to):
    now = datetime.now(TZ)
    start_local = None
    end_local = None

    if period == "today":
        start_local = datetime.combine(now.date(), time.min, tzinfo=TZ)
        end_local = start_local + timedelta(days=1)
    elif period == "7d":
        start_local = datetime.combine(now.date() - timedelta(days=6), time.min, tzinfo=TZ)
        end_local = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=TZ)
    elif period == "month":
        start_local = datetime(now.year, now.month, 1, tzinfo=TZ)
        if now.month == 12:
            end_local = datetime(now.year + 1, 1, 1, tzinfo=TZ)
        else:
            end_local = datetime(now.year, now.month + 1, 1, tzinfo=TZ)
    elif period == "custom":
        try:
            if date_from:
                d = datetime.strptime(date_from, "%Y-%m-%d").date()
                start_local = datetime.combine(d, time.min, tzinfo=TZ)
            if date_to:
                d = datetime.strptime(date_to, "%Y-%m-%d").date()
                end_local = datetime.combine(d + timedelta(days=1), time.min, tzinfo=TZ)
        except ValueError:
            start_local = end_local = None

    def utc_naive(value):
        return value.astimezone(UTC).replace(tzinfo=None) if value else None

    return utc_naive(start_local), utc_naive(end_local)


def _rate(value, total):
    return round((value / total) * 100, 1) if total else 0.0


def _local_date(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ).date()


@app.route("/estatisticas")
@crm.login_required
def statistics_panel():
    period = (request.args.get("period") or "month").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    source = (request.args.get("source") or "").strip()
    state = (request.args.get("state") or "").strip().upper()
    owner_raw = (request.args.get("owner_id") or "").strip()

    query = LeadAnalytics.query
    if session.get("role") == "seller":
        query = query.filter(LeadAnalytics.owner_id == session.get("user_id"))

    start_utc, end_utc = _local_bounds(period, date_from, date_to)
    if start_utc:
        query = query.filter(LeadAnalytics.received_at >= start_utc)
    if end_utc:
        query = query.filter(LeadAnalytics.received_at < end_utc)
    if source:
        query = query.filter(LeadAnalytics.source == source)
    if state:
        query = query.filter(LeadAnalytics.state == state)
    if owner_raw and session.get("role") in ["admin", "manager"]:
        try:
            query = query.filter(LeadAnalytics.owner_id == int(owner_raw))
        except ValueError:
            owner_raw = ""

    rows = query.order_by(LeadAnalytics.received_at.desc()).all()
    total = len(rows)

    counts = {
        "received": total,
        "contacted": sum(bool(x.contacted_at) for x in rows),
        "meeting1_scheduled": sum(bool(x.meeting1_scheduled_at) for x in rows),
        "meeting1_done": sum(bool(x.meeting1_done_at) for x in rows),
        "meeting2_scheduled": sum(bool(x.meeting2_scheduled_at) for x in rows),
        "meeting2_done": sum(bool(x.meeting2_done_at) for x in rows),
        "contract_sent": sum(bool(x.contract_sent_at) for x in rows),
        "closed": sum(bool(x.closed_at) for x in rows),
        "lost": sum(bool(x.lost_at) for x in rows),
        "deleted": sum(bool(x.deleted_at) for x in rows),
    }

    today = datetime.now(TZ).date()
    today_count = sum(_local_date(x.received_at) == today for x in rows)

    funnel = [
        ("Leads recebidos", counts["received"]),
        ("Contatados", counts["contacted"]),
        ("1ª reunião agendada", counts["meeting1_scheduled"]),
        ("1ª reunião realizada", counts["meeting1_done"]),
        ("2ª reunião agendada", counts["meeting2_scheduled"]),
        ("2ª reunião realizada", counts["meeting2_done"]),
        ("Contrato enviado", counts["contract_sent"]),
        ("Fechados", counts["closed"]),
    ]
    funnel_rows = [
        {"label": label, "count": count, "rate": _rate(count, total)}
        for label, count in funnel
    ]

    source_groups = defaultdict(lambda: {"total": 0, "closed": 0, "meeting": 0})
    state_counter = Counter()
    owner_groups = defaultdict(lambda: {"total": 0, "closed": 0, "meeting": 0})

    for row in rows:
        src = row.source or "N/I"
        source_groups[src]["total"] += 1
        source_groups[src]["closed"] += int(bool(row.closed_at))
        source_groups[src]["meeting"] += int(bool(row.meeting1_scheduled_at))
        state_counter[row.state or "N/I"] += 1
        owner_groups[row.owner_id]["total"] += 1
        owner_groups[row.owner_id]["closed"] += int(bool(row.closed_at))
        owner_groups[row.owner_id]["meeting"] += int(bool(row.meeting1_scheduled_at))

    source_rows = []
    for name, item in sorted(source_groups.items(), key=lambda kv: kv[1]["total"], reverse=True):
        source_rows.append({
            "name": name,
            "total": item["total"],
            "meeting": item["meeting"],
            "closed": item["closed"],
            "meeting_rate": _rate(item["meeting"], item["total"]),
            "close_rate": _rate(item["closed"], item["total"]),
        })

    users = crm.User.query.order_by(crm.User.name).all()
    user_names = {u.id: u.name for u in users}
    owner_rows = []
    for owner_id, item in sorted(owner_groups.items(), key=lambda kv: kv[1]["total"], reverse=True):
        owner_rows.append({
            "name": user_names.get(owner_id, "Sem responsável"),
            "total": item["total"],
            "meeting": item["meeting"],
            "closed": item["closed"],
            "meeting_rate": _rate(item["meeting"], item["total"]),
            "close_rate": _rate(item["closed"], item["total"]),
        })

    # Série diária: até 31 dias, terminando no dia mais recente do período filtrado.
    dated = [_local_date(x.received_at) for x in rows if x.received_at]
    daily_labels = []
    daily_values = []
    if dated:
        last_day = max(dated)
        first_day = max(min(dated), last_day - timedelta(days=30))
        day_counter = Counter(dated)
        day = first_day
        while day <= last_day:
            daily_labels.append(day.strftime("%d/%m"))
            daily_values.append(day_counter.get(day, 0))
            day += timedelta(days=1)

    source_labels = [x["name"] for x in source_rows[:8]]
    source_values = [x["total"] for x in source_rows[:8]]

    filter_sources = [x[0] for x in db.session.query(LeadAnalytics.source).distinct().order_by(LeadAnalytics.source).all() if x[0]]
    filter_states = [x[0] for x in db.session.query(LeadAnalytics.state).distinct().order_by(LeadAnalytics.state).all() if x[0]]

    return render_template(
        "statistics.html",
        counts=counts,
        today_count=today_count,
        meeting_conversion=_rate(counts["meeting1_scheduled"], total),
        sales_conversion=_rate(counts["closed"], total),
        contact_conversion=_rate(counts["contacted"], total),
        funnel_rows=funnel_rows,
        source_rows=source_rows,
        owner_rows=owner_rows,
        state_rows=state_counter.most_common(),
        daily_labels=daily_labels,
        daily_values=daily_values,
        source_labels=source_labels,
        source_values=source_values,
        filter_sources=filter_sources,
        filter_states=filter_states,
        users=users,
        period=period,
        date_from=date_from,
        date_to=date_to,
        selected_source=source,
        selected_state=state,
        selected_owner=owner_raw,
    )
