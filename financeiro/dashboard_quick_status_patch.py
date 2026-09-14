from flask import jsonify
import dashboard_quick_edit_patch as quick

app = quick.app
core = quick.core
Payable = quick.Payable
login_required = quick.login_required


def _status_payload(account):
    return {
        'id': account.id,
        'category': account.category or '',
        'dre_class': quick.dre_class_for(account.id),
        'recurring': quick.recurring_for(account.id),
        'description': account.description or '',
        'supplier': account.supplier or '',
    }


@app.route('/conta/<int:account_id>/edicao-rapida-status')
@login_required
def quick_edit_status(account_id):
    account = Payable.query.get_or_404(account_id)
    return jsonify(_status_payload(account))


@app.route('/contas/edicao-rapida-status')
@login_required
def quick_edit_status_batch():
    raw_ids = core.request.args.get('ids', '')
    ids = []
    for value in raw_ids.split(','):
        value = value.strip()
        if value.isdigit():
            ids.append(int(value))
    ids = list(dict.fromkeys(ids))[:500]
    if not ids:
        return jsonify({})

    accounts = Payable.query.filter(Payable.id.in_(ids)).all()

    dre_rows = quick.detailed.CostDreClass.query.filter(
        quick.detailed.CostDreClass.payable_id.in_(ids)
    ).all()
    dre_map = {
        row.payable_id: quick.categories.normalize_dre_class(row.dre_class)
        for row in dre_rows
    }

    occurrences = quick.RecurringOccurrence.query.filter(
        quick.RecurringOccurrence.payable_id.in_(ids)
    ).all()
    occurrence_map = {row.payable_id: row.recurring_cost_id for row in occurrences}
    recurring_ids = list(set(occurrence_map.values()))
    recurring_map = {}
    if recurring_ids:
        rules = quick.RecurringCost.query.filter(quick.RecurringCost.id.in_(recurring_ids)).all()
        active_by_rule = {rule.id: bool(rule.active) for rule in rules}
        recurring_map = {
            payable_id: active_by_rule.get(rule_id, False)
            for payable_id, rule_id in occurrence_map.items()
        }

    result = {}
    for account in accounts:
        result[str(account.id)] = {
            'id': account.id,
            'category': account.category or '',
            'dre_class': dre_map.get(account.id, 'nao_classificado'),
            'recurring': recurring_map.get(account.id, False),
            'description': account.description or '',
            'supplier': account.supplier or '',
        }
    return jsonify(result)
