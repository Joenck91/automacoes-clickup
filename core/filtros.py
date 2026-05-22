"""Sistema de filtros para tasks do ClickUp."""
import re
from .helpers import resolve_cf_display

OPERADORES = [
    "=", "≠", "contém", "não contém",
    "está vazio", "não está vazio",
    "é um de", "não é um de",
    ">", "<", ">=", "<=",
]
OPERADORES_SEM_VALOR = {"está vazio", "não está vazio"}
OPERADORES_MULTI = {"é um de", "não é um de"}
OPERADORES_NUMERICOS = {">", "<", ">=", "<="}


def _get_actual_value(task: dict, campo: str, fn2id: dict,
                      option_lookup: dict, cf_by_id: dict) -> str:
    if campo == "Status":
        return (task.get("status") or {}).get("status", "") or ""
    fid = fn2id.get(campo)
    if not fid:
        return ""
    cf = cf_by_id.get(fid)
    if not cf:
        return ""
    return resolve_cf_display(cf, option_lookup) or ""


def _filter_matches(task: dict, f: dict, fn2id: dict,
                    option_lookup: dict, cf_by_id: dict) -> bool:
    actual = _get_actual_value(task, f["campo"], fn2id, option_lookup, cf_by_id)
    op = f.get("operador", "=")
    val = f.get("valor")

    def eq(a, b):
        return str(a).strip().lower() == str(b).strip().lower()

    def contem(a, b):
        return str(b).strip().lower() in str(a).strip().lower()

    if op == "=":
        return eq(actual, val)
    if op == "≠":
        return not eq(actual, val)
    if op == "contém":
        return contem(actual, val)
    if op == "não contém":
        return not contem(actual, val)
    if op == "está vazio":
        return actual.strip() == ""
    if op == "não está vazio":
        return actual.strip() != ""
    if op == "é um de":
        vals = val if isinstance(val, list) else [val]
        return any(eq(actual, v) for v in vals)
    if op == "não é um de":
        vals = val if isinstance(val, list) else [val]
        return not any(eq(actual, v) for v in vals)
    if op in OPERADORES_NUMERICOS:
        try:
            a = float(re.sub(r"[^\d.,\-]", "", actual).replace(",", "."))
            b = float(str(val).replace(",", "."))
        except (ValueError, TypeError):
            return False
        return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    return False


def task_passes_filters(task: dict, filtros_e: list, filtros_ou: list,
                        fn2id: dict, option_lookup: dict) -> bool:
    cf_by_id = {cf["id"]: cf for cf in task.get("custom_fields", [])}
    if filtros_e and not all(
        _filter_matches(task, f, fn2id, option_lookup, cf_by_id) for f in filtros_e
    ):
        return False
    if filtros_ou and not any(
        _filter_matches(task, f, fn2id, option_lookup, cf_by_id) for f in filtros_ou
    ):
        return False
    return True


def task_passes_filtros_simples(task: dict, filtros: list,
                                fn2id: dict, option_lookup: dict) -> bool:
    if not filtros:
        return True
    filtros_e = [{"campo": f["campo"], "operador": "=", "valor": f["valor"]} for f in filtros]
    return task_passes_filters(task, filtros_e, [], fn2id, option_lookup)
