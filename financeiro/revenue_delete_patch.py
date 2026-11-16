"""Opção de exclusão individual para lançamentos de faturamento.

A exclusão ocorre apenas após confirmação na tela de receitas e sempre atua
sobre o registro selecionado pelo seu identificador.
"""
import contas_pagar_app as core

app = core.app
db = core.db
Revenue = core.Revenue
login_required = core.login_required


@app.route("/receitas/<int:revenue_id>/excluir", methods=["POST"])
@login_required
def delete_revenue(revenue_id):
    revenue = Revenue.query.get_or_404(revenue_id)
    month = core.request.form.get("month", "").strip()
    store = core.request.form.get("store", "").strip()

    try:
        db.session.delete(revenue)
        db.session.commit()
        core.flash("Lançamento de faturamento excluído.", "success")
    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao excluir lançamento de faturamento %s", revenue_id)
        core.flash("Não foi possível excluir o lançamento. Tente novamente.", "danger")

    return core.redirect(core.url_for("revenues", month=month or None, store=store or None))
