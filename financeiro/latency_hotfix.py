import performance_patch as perf

app = perf.app
core = perf.core
detailed = perf.detailed

# A rotina de suporte do DRE fazia varreduras completas em contas e recorrencias
# antes de toda requisicao. Isso deixava cada clique mais lento conforme a base crescia.
_original_dre_support = detailed.ensure_dre_support
_dre_support_done = False


def _dre_support_once_per_process():
    global _dre_support_done
    if _dre_support_done:
        return None
    result = _original_dre_support()
    _dre_support_done = True
    return result


_before = list(app.before_request_funcs.get(None, []))
app.before_request_funcs[None] = [
    _dre_support_once_per_process if fn is _original_dre_support else fn
    for fn in _before
]
