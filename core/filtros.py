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
    if campo == "Responsável":
        assignees = task.get("assignees", []) or []
        names = [a.get("username") or a.get("email") or "" for a in assignees]
        return ", ".join(n for n in names if n)
    if campo == "Tags":
        tags = task.get("tags", []) or []
        names = [t.get("name", "") for t in tags if t.get("name")]
        return ", ".join(names)
    fid = fn2id.get(campo)
    if not fid:
        return ""
    cf = cf_by_id.get(fid)
    if not cf:
        return ""
    return resolve_cf_display(cf, option_lookup) or ""


# Campos que armazenam múltiplos valores num único card (set semantics)
CAMPOS_MULTI = {"Responsável", "Tags"}


def _filter_matches(task: dict, f: dict, fn2id: dict,
                    option_lookup: dict, cf_by_id: dict) -> bool:
    actual = _get_actual_value(task, f["campo"], fn2id, option_lookup, cf_by_id)
    op = f.get("operador", "=")
    val = f.get("valor")
    campo = f.get("campo", "")

    def eq(a, b):
        return str(a).strip().lower() == str(b).strip().lower()

    def contem(a, b):
        return str(b).strip().lower() in str(a).strip().lower()

    # Campos multi-valor (Responsável, Tags) usam semântica de conjunto
    if campo in CAMPOS_MULTI:
        items = {x.strip().lower() for x in actual.split(",") if x.strip()}
        if op == "=":
            return bool(val) and str(val).strip().lower() in items
        if op == "≠":
            return not (bool(val) and str(val).strip().lower() in items)
        if op == "contém":
            return contem(actual, val)
        if op == "não contém":
            return not contem(actual, val)
        if op == "está vazio":
            return not items
        if op == "não está vazio":
            return bool(items)
        if op == "é um de":
            vals = val if isinstance(val, list) else [val]
            return any(str(v).strip().lower() in items for v in vals)
        if op == "não é um de":
            vals = val if isinstance(val, list) else [val]
            return not any(str(v).strip().lower() in items for v in vals)
        return False

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


def render_filtros_ui(st, state_key: str, prefix: str,
                      field_names: list, field_options: dict):
    """Renderiza uma seção de filtros (lista de dicts) no Streamlit.

    Mantém estado em st.session_state[state_key]. Use em conjunto com
    coletar_filtros() para extrair os valores configurados.
    """
    if state_key not in st.session_state:
        st.session_state[state_key] = [{"id": 0}]
    if "_next_fid" not in st.session_state:
        st.session_state._next_fid = 1000

    to_remove = None
    lista = st.session_state[state_key]

    for filtro in lista:
        fid = filtro["id"]
        c1, c2, c3, c4 = st.columns([2, 1.5, 2.3, 0.4])
        with c1:
            st.selectbox(
                "Campo", [""] + field_names,
                key=f"{prefix}_campo_{fid}", label_visibility="collapsed",
            )
        with c2:
            st.selectbox(
                "Operador", OPERADORES,
                key=f"{prefix}_op_{fid}", label_visibility="collapsed",
            )
        with c3:
            campo_sel = st.session_state.get(f"{prefix}_campo_{fid}", "")
            op_sel = st.session_state.get(f"{prefix}_op_{fid}", "=")
            opts = field_options.get(campo_sel, [])

            if op_sel in OPERADORES_SEM_VALOR:
                st.markdown(
                    "<div style='color:#888;padding:0.4rem 0;text-align:center'>— sem valor —</div>",
                    unsafe_allow_html=True,
                )
            elif op_sel in OPERADORES_MULTI and opts:
                st.multiselect(
                    "Valor", opts,
                    key=f"{prefix}_valor_multi_{fid}",
                    label_visibility="collapsed",
                    placeholder="Selecione um ou mais",
                )
            elif opts and op_sel in ("=", "≠"):
                st.selectbox(
                    "Valor", [""] + opts,
                    key=f"{prefix}_valor_select_{fid}",
                    label_visibility="collapsed",
                )
            else:
                placeholder = (
                    "valor1, valor2, ..." if op_sel in OPERADORES_MULTI
                    else "Digite um número" if op_sel in OPERADORES_NUMERICOS
                    else "Digite o valor"
                )
                st.text_input(
                    "Valor", key=f"{prefix}_valor_text_{fid}",
                    label_visibility="collapsed",
                    placeholder=placeholder,
                )
        with c4:
            if len(lista) > 1:
                if st.button("✕", key=f"{prefix}_rem_{fid}", use_container_width=True):
                    to_remove = fid

    if to_remove is not None:
        st.session_state[state_key] = [f for f in lista if f["id"] != to_remove]
        st.rerun()

    if st.button("＋ Adicionar filtro", key=f"{prefix}_add"):
        st.session_state[state_key].append({"id": st.session_state._next_fid})
        st.session_state._next_fid += 1
        st.rerun()


def coletar_filtros(st, state_key: str, prefix: str, field_options: dict) -> list:
    """Lê os widgets criados por render_filtros_ui e devolve a lista de filtros
    no formato {campo, operador, valor} (pronto para task_passes_filters)."""
    out = []
    for f in st.session_state.get(state_key, []):
        fid = f["id"]
        campo = st.session_state.get(f"{prefix}_campo_{fid}", "")
        operador = st.session_state.get(f"{prefix}_op_{fid}", "=")
        if not campo:
            continue
        if operador in OPERADORES_SEM_VALOR:
            out.append({"campo": campo, "operador": operador, "valor": None})
            continue
        opts = field_options.get(campo, [])
        if operador in OPERADORES_MULTI and opts:
            valor = st.session_state.get(f"{prefix}_valor_multi_{fid}", [])
            if not valor:
                continue
        elif opts and operador in ("=", "≠"):
            valor = st.session_state.get(f"{prefix}_valor_select_{fid}", "")
            if not valor:
                continue
        else:
            valor_raw = st.session_state.get(f"{prefix}_valor_text_{fid}", "")
            if not valor_raw or not str(valor_raw).strip():
                continue
            if operador in OPERADORES_MULTI:
                valor = [v.strip() for v in str(valor_raw).split(",") if v.strip()]
                if not valor:
                    continue
            else:
                valor = valor_raw
        out.append({"campo": campo, "operador": operador, "valor": valor})
    return out
