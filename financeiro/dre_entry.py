import dre_detalhado as detailed

app = detailed.app

# O módulo detalhado substitui a rota de exportação do DRE. Reaplica a proteção
# de login no endpoint final para manter o mesmo nível de acesso do Financeiro.
_current_export = app.view_functions.get("export_report")
if _current_export is not None:
    app.view_functions["export_report"] = detailed.login_required(_current_export)
