from datetime import date

import dre_categories_patch as categories

app = categories.app
base = categories.base
core = categories.core
detailed = categories.detailed
Payable = categories.Payable
PayablePayment = base.PayablePayment
RecurringCost = base.RecurringCost
RecurringOccurrence = base.RecurringOccurrence
login_required = categories.login_required


class RecurringOccurrenceSkip(core.db.Model):
    """Marca uma competência recorrente que foi excluída manualmente.

    A marca impede que o materializador recrie a conta no próximo request,
    preservando normalmente as demais competências da recorrência.
    """

    __tablename__ = "finance_recurring_occurrence_skip"
    id = core.db.Column(core.db.Integer, primary_key=True)
    recurring_cost_id = core.db.Column(
        core.db.Integer,
        core.db.ForeignKey("finance_recurring_cost.id"),
        nullable=False,
    )
    due_date = core.db.Column(core.db.Date, nullable=False)
    created_at = core.db.Column(core.db.DateTime, default=core.datetime.utcnow)
    __table_args__ = (
        core.db.UniqueConstraint(
            "recurring_cost_id",
            "due_date",
            name="uq_recurring_skip_due_date",
        ),
    )


def materialize_recurring_costs_with_skips():
    today = date.today()
    horizon = base.add_months(today.replace(day=1), 12)
    changed = False

    for rule in RecurringCost.query.filter_by(active=True).all():
        cursor = rule.start_date.replace(day=1)
        final = rule.end_date if rule.end_date else horizon

        while cursor <= horizon and cursor <= final:
            due = base.due_for_month(cursor.year, cursor.month, rule.due_day)
            if due >= rule.start_date and (not rule.end_date or due <= rule.end_date):
                skipped = RecurringOccurrenceSkip.query.filter_by(
                    recurring_cost_id=rule.id,
                    due_date=due,
                ).first()
                exists = RecurringOccurrence.query.filter_by(
                    recurring_cost_id=rule.id,
                    due_date=due,
                ).first()

                if not skipped and not exists:
                    payable = Payable(
                        store=rule.store,
                        supplier=rule.supplier,
                        description=rule.description,
                        category=rule.category,
                        total_amount=rule.total_amount,
                        due_date=due,
                        document=rule.document,
                        notes=rule.notes,
                    )
                    core.db.session.add(payable)
                    core.db.session.flush()
                    core.db.session.add(
                        RecurringOccurrence(
                            recurring_cost_id=rule.id,
                            payable_id=payable.id,
                            due_date=due,
                        )
                    )
                    changed = True
            cursor = base.add_months(cursor, 1)

    if changed:
        core.db.session.commit()


# O before_request de financeiro_app resolve esse nome em tempo de execução.
# Assim, as competências apagadas permanecem apagadas sem cancelar a recorrência.
base.materialize_recurring_costs = materialize_recurring_costs_with_skips


@app.route("/conta/<int:account_id>/excluir-mes", methods=["POST"])
@login_required
def delete_account_month(account_id):
    account = Payable.query.get_or_404(account_id)
    reference_date = account.due_date
    occurrence = RecurringOccurrence.query.filter_by(payable_id=account.id).first()

    try:
        if occurrence:
            skip = RecurringOccurrenceSkip.query.filter_by(
                recurring_cost_id=occurrence.recurring_cost_id,
                due_date=occurrence.due_date,
            ).first()
            if not skip:
                core.db.session.add(
                    RecurringOccurrenceSkip(
                        recurring_cost_id=occurrence.recurring_cost_id,
                        due_date=occurrence.due_date,
                    )
                )

            # Remove somente o vínculo desta competência. A regra recorrente continua ativa.
            core.db.session.delete(occurrence)

        # Remove classificação específica da conta, quando existir.
        detailed.CostDreClass.query.filter_by(payable_id=account.id).delete(
            synchronize_session=False
        )

        # Remove eventuais pagamentos desta conta/competência.
        PayablePayment.query.filter_by(payable_id=account.id).delete(
            synchronize_session=False
        )

        core.db.session.delete(account)
        core.db.session.commit()
    except Exception:
        core.db.session.rollback()
        return core.jsonify({"ok": False, "error": "Não foi possível excluir esta conta."}), 500

    return core.jsonify(
        {
            "ok": True,
            "message": "Conta excluída somente desta competência.",
            "reference_month": reference_date.strftime("%m/%Y"),
        }
    )
