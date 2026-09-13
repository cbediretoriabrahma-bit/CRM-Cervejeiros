from datetime import date

import dre_detalhado as detailed

app = detailed.app
core = detailed.core
login_required = detailed.login_required


def fixed_dre():
    month = core.request.args.get("month", date.today().strftime("%Y-%m"))
    store_filter = core.request.args.get("store", "").strip()
    data = detailed.compute_detailed_dre(month, store_filter)
    unit_rows = []
    for store in detailed.base.managed_stores(active_only=False):
        unit = detailed.compute_detailed_dre(month, store)
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

    context = dict(data)
    context.update({
        "stores": detailed.base.managed_stores(active_only=False),
        "store_filter": store_filter,
        "unit_rows": unit_rows,
    })
    return core.render_template("dre.html", **context)


app.view_functions["dre"] = login_required(fixed_dre)
