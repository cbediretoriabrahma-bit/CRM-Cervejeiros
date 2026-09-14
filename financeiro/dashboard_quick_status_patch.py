from flask import jsonify
import dashboard_quick_edit_patch as quick

app = quick.app
core = quick.core
Payable = quick.Payable
login_required = quick.login_required


@app.route('/conta/<int:account_id>/edicao-rapida-status')
@login_required
def quick_edit_status(account_id):
    account = Payable.query.get_or_404(account_id)
    return jsonify({
        'id': account.id,
        'category': account.category or '',
        'dre_class': quick.dre_class_for(account.id),
        'recurring': quick.recurring_for(account.id),
        'description': account.description or '',
        'supplier': account.supplier or '',
    })
