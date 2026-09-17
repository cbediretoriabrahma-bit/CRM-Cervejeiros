import dre_hotfix as fixed

app = fixed.app

# Mantém a proteção de login no endpoint final de exportação do DRE.
_current_export = app.view_functions.get("export_report")
if _current_export is not None:
    app.view_functions["export_report"] = fixed.login_required(_current_export)

# Permite selecionar várias unidades ao mesmo tempo no Painel, DRE e Saúde Financeira.
# Este patch altera apenas filtros e consultas; não modifica nem apaga lançamentos existentes.
import multi_store_filter_patch  # noqa: F401,E402

# Classificações detalhadas do DRE e separação das despesas pessoais.
import dre_categories_patch  # noqa: F401,E402

# Reativa os comandos de Categoria / Recorrência e suas rotas no painel.
import dashboard_quick_edit_patch  # noqa: F401,E402

# Exclusão de uma conta somente na competência selecionada, sem cancelar
# a recorrência nem apagar os demais meses.
import monthly_delete_patch  # noqa: F401,E402

# Reativa as otimizações de desempenho do painel.
# Evita consultas repetidas, carrega pagamentos em lote e reduz o custo da abertura da página.
import performance_patch  # noqa: F401,E402
