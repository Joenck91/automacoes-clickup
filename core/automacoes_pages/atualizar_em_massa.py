"""Página: Atualização em Massa — atualiza cards existentes a partir de uma planilha.

Fluxo:
1. Upload + preview da planilha
2. Configurar chaves de busca (CNPJ, telefone, email) — cascata
3. (Opcional) Filtros para limitar a busca a um subconjunto de cards no ClickUp
4. Regras de atualização (uma ou mais). Cada regra:
   - Campo a atualizar (Status, Descrição, ou qualquer custom field)
   - Valor (fixo ou coluna da planilha)
   - (Opcional) Filtro da planilha — só aplica se a linha satisfaz
   - (Opcional) Filtro do ClickUp — só aplica se o card atual satisfaz
5. Prévia (3 cards) + execução
"""
import io
import os
import re
from datetime import datetime, date
import pandas as pd
import streamlit as st

from core.clickup_api import ClickUp
from core.helpers import build_option_lookup, resolve_cf_display
from core.filtros import (
    OPERADORES, OPERADORES_SEM_VALOR, OPERADORES_MULTI, OPERADORES_NUMERICOS,
    task_passes_filters,
)


# ── Constantes ────────────────────────────────────────────────────────────
VALOR_FIXO = "Valor fixo"
COLUNA = "Coluna da planilha"
TARGET_STATUS = "🎯 Status"
TARGET_DESC = "📝 Descrição"
TARGET_DATA_INICIO = "📅 Data de início"
TARGET_DATA_VENCIMENTO = "📅 Data de vencimento"
TARGET_RESPONSAVEL = "👤 Responsável"

# Marcadores especiais para o campo do ClickUp ao definir chaves de busca
CAMPO_QUALQUER = "🔍 Qualquer campo (lupa)"
CAMPO_NOME_CARD = "Nome do card"
CAMPO_DESCRICAO = "Descrição"


# ══════════════════════════════════════════════════════════════════════════
#                              HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _get_task_field_value(task: dict, campo: str):
    """Lê o valor de um campo do card.

    Aceita 'Nome do card', 'Descrição' ou o nome de qualquer custom field.
    """
    if campo == CAMPO_NOME_CARD:
        return task.get("name")
    if campo == CAMPO_DESCRICAO:
        return task.get("description")
    for cf in task.get("custom_fields", []):
        if cf.get("name") == campo:
            return cf.get("value")
    return None


def _build_task_haystack(task: dict) -> str:
    """Concatena TODO o texto do card (nome + descrição + todos os custom fields).

    Usado pelo modo lupa: busca o valor da planilha em qualquer lugar do card.
    """
    parts = [task.get("name") or "", task.get("description") or ""]
    for cf in task.get("custom_fields", []):
        val = cf.get("value")
        if val is not None:
            parts.append(str(val))
    return " ║ ".join(parts)


def _build_search_indexes(tasks: list, search_keys: list) -> list:
    """Constrói um índice por chave de busca, mesma ordem da lista.

    Cada índice é uma tupla (mode, data):
    - mode='exact' → data é {valor_exato: [tasks]} (campo específico)
    - mode='lupa'  → data é [(task, haystack_lower), ...] (busca em todo o texto)
    """
    indexes = []
    for key in search_keys:
        campo = key.get("campo")
        if not campo:
            indexes.append(("exact", {}))
            continue

        if campo == CAMPO_QUALQUER:
            haystacks = [(t, _build_task_haystack(t).lower()) for t in tasks]
            indexes.append(("lupa", haystacks))
            continue

        idx: dict = {}
        for task in tasks:
            val = _get_task_field_value(task, campo)
            if val is None:
                continue
            s = str(val).strip()
            if not s or s.lower() == "none":
                continue
            idx.setdefault(s, []).append(task)
        # Deduplica
        for k in idx:
            seen, unique = set(), []
            for t in idx[k]:
                if t["id"] not in seen:
                    seen.add(t["id"])
                    unique.append(t)
            idx[k] = unique
        indexes.append(("exact", idx))
    return indexes


def _find_cards(row, search_keys: list, indexes: list) -> tuple[list, str, str]:
    """Tenta cada chave em cascata.

    Retorna (cards, descrição_método, valor_pesquisado).
    - Se encontrou: valor_pesquisado é o valor que casou.
    - Se não encontrou: valor_pesquisado lista todos os valores que foram tentados
      (útil pra debug).

    'exact' → comparação exata (após trim) com o valor do campo configurado.
    'lupa'  → substring case-insensitive em todo o texto do card.
    """
    valores_tentados = []
    for key, (mode, data) in zip(search_keys, indexes):
        coluna = key.get("coluna")
        campo = key.get("campo")
        if not coluna or not campo or coluna not in row.index:
            continue
        raw = row[coluna]
        if pd.isna(raw):
            continue
        val = str(raw).strip()
        if not val or val.lower() == "nan":
            continue

        valores_tentados.append(f'{coluna}="{val}"')

        if mode == "lupa":
            val_lower = val.lower()
            results = [t for t, hay in data if val_lower in hay]
            if results:
                return results, f"{coluna} → {campo}", val
        else:  # exact
            if val in data:
                return data[val], f"{coluna} → {campo}", val
    return [], "não encontrado", " | ".join(valores_tentados)


def _row_passes_filter(row, filter_spec: dict) -> bool:
    """Avalia se uma linha da planilha satisfaz um filtro."""
    if not filter_spec or not filter_spec.get("coluna"):
        return True

    col = filter_spec["coluna"]
    op = filter_spec.get("operador", "=")
    val = filter_spec.get("valor")

    if col not in row.index:
        return False

    actual_raw = row[col]
    actual = "" if pd.isna(actual_raw) else str(actual_raw)
    val_str = "" if val is None else str(val)

    a_norm = actual.strip().lower()
    v_norm = val_str.strip().lower()

    if op == "=":          return a_norm == v_norm
    if op == "≠":          return a_norm != v_norm
    if op == "contém":     return v_norm in a_norm
    if op == "não contém": return v_norm not in a_norm
    if op == "está vazio":      return actual.strip() == ""
    if op == "não está vazio":  return actual.strip() != ""
    if op in OPERADORES_NUMERICOS:
        try:
            a = float(re.sub(r"[^\d.,\-]", "", actual).replace(",", "."))
            b = float(str(val).replace(",", "."))
        except (ValueError, TypeError):
            return False
        return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    return False


def _card_passes_filter(task, filter_spec: dict, fn2id, option_lookup) -> bool:
    """Avalia se um card do ClickUp satisfaz um filtro (delega ao filtros.py)."""
    if not filter_spec or not filter_spec.get("campo"):
        return True
    return task_passes_filters(task, [filter_spec], [], fn2id, option_lookup)


def _row_passes_filters(row, filters_list: list) -> bool:
    """TODAS as condições da lista devem passar (AND). Lista vazia → True."""
    if not filters_list:
        return True
    return all(_row_passes_filter(row, f) for f in filters_list)


def _card_passes_filters(task, filters_list: list, fn2id, option_lookup) -> bool:
    """TODAS as condições da lista devem passar (AND). Lista vazia → True."""
    if not filters_list:
        return True
    return all(_card_passes_filter(task, f, fn2id, option_lookup) for f in filters_list)


def _resolver_data(valor_bruto) -> int | None:
    """Converte um valor (date/datetime/Timestamp/string) em milissegundos epoch.

    Aceita formato brasileiro (dd/mm/yyyy) por padrão.
    Retorna None se o valor for vazio ou inválido.
    """
    if valor_bruto is None:
        return None
    if isinstance(valor_bruto, float) and pd.isna(valor_bruto):
        return None
    if isinstance(valor_bruto, datetime):
        return int(valor_bruto.timestamp() * 1000)
    if isinstance(valor_bruto, date):
        dt = datetime.combine(valor_bruto, datetime.min.time())
        return int(dt.timestamp() * 1000)
    try:
        dt = pd.to_datetime(valor_bruto, dayfirst=True).to_pydatetime()
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _formatar_data(valor_bruto) -> str:
    """Formata um valor de data para exibição (dd/mm/yyyy). Vazio se inválido."""
    if valor_bruto is None or (isinstance(valor_bruto, float) and pd.isna(valor_bruto)):
        return "(vazio)"
    if isinstance(valor_bruto, (datetime, date)):
        return valor_bruto.strftime("%d/%m/%Y")
    try:
        return pd.to_datetime(valor_bruto, dayfirst=True).strftime("%d/%m/%Y")
    except Exception:
        return str(valor_bruto)


def _resolver_assignees(valor_bruto, members_map: dict) -> list:
    """Resolve nome(s)/email(s) para uma lista de user IDs do ClickUp.

    Aceita:
    - String única: 'Luis' ou 'luis@booz.com.br'
    - Lista do multiselect: ['Luis', 'Maria']
    - String com separadores: 'Luis, Maria; Pedro'
    """
    if valor_bruto is None:
        return []
    if isinstance(valor_bruto, float) and pd.isna(valor_bruto):
        return []

    if isinstance(valor_bruto, list):
        nomes = valor_bruto
    else:
        s = str(valor_bruto).strip()
        if not s or s.lower() in ("none", "nan"):
            return []
        nomes = re.split(r'[,;|/]', s)

    ids = []
    for nome in nomes:
        chave = str(nome).strip().lower()
        if not chave:
            continue
        uid = members_map.get(chave)
        if uid and uid not in ids:
            ids.append(uid)
    return ids


def _resolver_valor_para_campo(target: str, cf: dict | None, valor_bruto, option_lookup: dict):
    """Resolve o valor bruto (string ou outro) para o formato esperado pelo ClickUp.

    target: "🎯 Status", "📝 Descrição", ou nome do custom field
    cf: dict do custom field (ou None para Status/Descrição)
    """
    # Checkbox: tratamos antes da normalização (False é valor válido)
    if cf is not None and cf.get("type") == "checkbox":
        if isinstance(valor_bruto, bool):
            return valor_bruto
        if valor_bruto is None or (isinstance(valor_bruto, float) and pd.isna(valor_bruto)):
            return None
        val_lower = str(valor_bruto).strip().lower()
        if val_lower in ("true", "sim", "s", "1", "yes", "y", "marcado", "x", "✓"):
            return True
        if val_lower in ("false", "não", "nao", "n", "0", "no", "desmarcado", "-", ""):
            return False
        return None

    if valor_bruto is None or (isinstance(valor_bruto, float) and pd.isna(valor_bruto)):
        return None
    val_str = str(valor_bruto).strip()
    if not val_str or val_str.lower() == "none":
        return None

    # Status e Descrição: passam direto como string
    if target in (TARGET_STATUS, TARGET_DESC):
        return val_str

    # Custom field: depende do tipo
    if cf is None:
        return val_str
    cf_type = cf.get("type", "")

    if cf_type in ("drop_down", "labels"):
        options = cf.get("type_config", {}).get("options", [])
        opt = next((o for o in options if o["name"].strip().lower() == val_str.lower()), None)
        return opt["id"] if opt else None

    if cf_type == "number":
        try:
            return float(val_str.replace(",", "."))
        except ValueError:
            return None

    return val_str


# ══════════════════════════════════════════════════════════════════════════
#                          UI: SUB-RENDERS
# ══════════════════════════════════════════════════════════════════════════

def _render_filtro(prefix: str, filter_id, field_options_planilha: list,
                   field_names_clickup: list, field_options_clickup: dict,
                   tipo: str) -> dict:
    """Renderiza um único filtro (linha com campo + operador + valor).

    tipo: "planilha" (campo = coluna da planilha) ou "clickup" (campo = campo do card)
    Retorna o filter_spec {campo/coluna, operador, valor}.
    """
    campos = field_options_planilha if tipo == "planilha" else field_names_clickup
    key_root = f"{prefix}_{filter_id}_{tipo}"

    c1, c2, c3 = st.columns([2, 1.4, 2.4])
    with c1:
        campo = st.selectbox(
            "Campo", [""] + campos,
            key=f"{key_root}_campo", label_visibility="collapsed",
        )
    with c2:
        op = st.selectbox(
            "Op", OPERADORES,
            key=f"{key_root}_op", label_visibility="collapsed",
        )
    with c3:
        opts = field_options_clickup.get(campo, []) if tipo == "clickup" else []
        if op in OPERADORES_SEM_VALOR:
            st.caption("— sem valor —")
            valor = None
        elif opts and op in ("=", "≠"):
            valor = st.selectbox(
                "Valor", [""] + opts,
                key=f"{key_root}_valor", label_visibility="collapsed",
            )
            if not valor:
                valor = None
        else:
            valor = st.text_input(
                "Valor", key=f"{key_root}_valor", label_visibility="collapsed",
                placeholder="Digite o valor",
            )
            if not valor.strip():
                valor = None

    if not campo:
        return {}

    spec = {"operador": op, "valor": valor}
    if tipo == "planilha":
        spec["coluna"] = campo
    else:
        spec["campo"] = campo
    return spec


def _render_atualizacao(rule_id, upd_id, df, fields, fn2id, status_options,
                         member_names: list, allow_remove: bool) -> dict:
    """Renderiza UM bloco (campo + origem + valor) dentro de uma regra."""
    cols_planilha = [str(c) for c in df.columns]
    prefix = f"am_rule_{rule_id}_upd_{upd_id}"

    # Botão de remover esta atualização (só quando há mais de uma)
    if allow_remove:
        col_l, col_r = st.columns([10, 1])
        with col_r:
            if st.button("✕", key=f"{prefix}_rem", help="Remover este campo desta regra"):
                for r in st.session_state.am_rules:
                    if r["id"] == rule_id:
                        r["updates"] = [u for u in r.get("updates", []) if u["id"] != upd_id]
                        break
                st.rerun()

    target_opts = [""] + [
        TARGET_STATUS, TARGET_DESC,
        TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO,
        TARGET_RESPONSAVEL,
    ] + sorted(fn2id.keys())
    target = st.selectbox(
        "Campo a atualizar", target_opts, key=f"{prefix}_target",
    )

    if not target:
        st.caption("_Selecione o campo a atualizar para continuar._")
        return {}

    source = st.radio(
        "Origem do valor", [VALOR_FIXO, COLUNA],
        key=f"{prefix}_source", horizontal=True,
    )

    valor_fixo = None
    valor_coluna = None

    if source == VALOR_FIXO:
        if target == TARGET_STATUS:
            valor_fixo = st.selectbox(
                "Novo status", [""] + status_options, key=f"{prefix}_val_status",
            )
        elif target == TARGET_DESC:
            valor_fixo = st.text_area(
                "Nova descrição", key=f"{prefix}_val_desc",
                placeholder="Texto que será gravado na descrição do card",
            )
        elif target in (TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO):
            valor_fixo = st.date_input(
                "Nova data", value=None, key=f"{prefix}_val_date",
                format="DD/MM/YYYY",
            )
        elif target == TARGET_RESPONSAVEL:
            valor_fixo = st.multiselect(
                "Responsáveis (serão adicionados aos atuais)",
                member_names, key=f"{prefix}_val_assignees",
                help="Selecione um ou mais membros do workspace.",
            )
        else:
            cf = next((f for f in fields if f["id"] == fn2id.get(target)), None)
            cf_type = cf.get("type", "") if cf else ""
            if cf_type in ("drop_down", "labels"):
                opts = [o["name"] for o in cf.get("type_config", {}).get("options", [])]
                valor_fixo = st.selectbox(
                    "Novo valor", [""] + opts, key=f"{prefix}_val_dd",
                )
            elif cf_type == "checkbox":
                valor_fixo = st.checkbox(
                    "Marcar a caixa", key=f"{prefix}_val_chk",
                    help="Marque para deixar a caixa preenchida; desmarque para deixar vazia.",
                )
            elif cf_type == "number":
                valor_fixo = st.number_input(
                    "Novo valor", value=None, key=f"{prefix}_val_num",
                    placeholder="Digite o número",
                )
            else:
                valor_fixo = st.text_input(
                    "Novo valor", key=f"{prefix}_val_txt",
                    placeholder="Digite o valor",
                )
    else:
        valor_coluna = st.selectbox(
            "Coluna da planilha", [""] + cols_planilha, key=f"{prefix}_val_col",
        )

    return {
        "target": target,
        "source": source,
        "valor_fixo": valor_fixo,
        "valor_coluna": valor_coluna,
    }


def _render_regra(rule: dict, df, fields, fn2id, field_names_clickup,
                  field_options_clickup, status_options, member_names: list) -> dict:
    """Renderiza uma regra (cabeçalho + lista de atualizações + filtros).

    Cada regra tem 1+ atualizações (campo + valor) e UM conjunto de filtros
    que vale para todas as atualizações da regra.
    """
    rule_id = rule["id"]
    cols_planilha = [str(c) for c in df.columns]

    # Garante estrutura de updates
    if "updates" not in rule or not rule["updates"]:
        rule["updates"] = [{"id": 0}]

    # Header com botão de remover a regra inteira
    col_titulo, col_rem = st.columns([10, 1])
    with col_titulo:
        st.markdown(f"**Regra #{rule_id + 1}**")
    with col_rem:
        if len(st.session_state.am_rules) > 1:
            if st.button("✕", key=f"am_rule_rem_{rule_id}",
                         help="Remover esta regra inteira"):
                st.session_state.am_rules = [
                    r for r in st.session_state.am_rules if r["id"] != rule_id
                ]
                st.rerun()

    # ── Atualizações (lista) ────────────────────────────────────────
    st.markdown("**Atualizar:**")

    atualizacoes_specs = []
    n_updates = len(rule["updates"])

    for i, upd in enumerate(rule["updates"]):
        if i > 0:
            st.markdown("<hr style='margin:0.5rem 0; border:none; border-top:1px solid #2c2c2e'>", unsafe_allow_html=True)
        upd_spec = _render_atualizacao(
            rule_id, upd["id"], df, fields, fn2id, status_options,
            member_names, allow_remove=(n_updates > 1),
        )
        if upd_spec.get("target"):
            atualizacoes_specs.append(upd_spec)

    if st.button("＋ Adicionar outro campo a esta regra",
                 key=f"am_rule_add_upd_{rule_id}"):
        next_upd_id = max([u["id"] for u in rule["updates"]], default=-1) + 1
        rule["updates"].append({"id": next_upd_id})
        st.rerun()

    # ── Filtros opt-in (múltiplas condições com AND) ───────────────
    with st.expander("Aplicar em apenas alguns cards"):
        st.caption(
            "Por padrão, a regra vale para **todos os cards encontrados**. "
            "Ligue as opções abaixo para limitar. Várias condições são combinadas com **AND** (todas precisam passar)."
        )

        # --- Filtros da planilha (lista de condições) ---
        usar_filtro_row = st.checkbox(
            "Filtrar pela linha da planilha",
            key=f"am_rule_uf_planilha_{rule_id}",
            help="Aplica só nas linhas que satisfazem todas as condições (ex.: coluna 'Respondeu' preenchida).",
        )
        row_filters = []
        if usar_filtro_row:
            if "row_conds" not in rule or not rule["row_conds"]:
                rule["row_conds"] = [{"id": 0}]
            n_row = len(rule["row_conds"])
            for cond in rule["row_conds"]:
                cid = cond["id"]
                if n_row > 1:
                    col_f, col_x = st.columns([20, 1])
                    with col_f:
                        fs = _render_filtro(
                            f"am_rule_{rule_id}_rowf", cid, cols_planilha,
                            field_names_clickup, field_options_clickup, "planilha",
                        )
                    with col_x:
                        st.markdown("<div style='padding-top:0.35rem'></div>", unsafe_allow_html=True)
                        if st.button("✕", key=f"am_rule_{rule_id}_row_rem_{cid}", help="Remover condição"):
                            rule["row_conds"] = [c for c in rule["row_conds"] if c["id"] != cid]
                            st.rerun()
                else:
                    fs = _render_filtro(
                        f"am_rule_{rule_id}_rowf", cid, cols_planilha,
                        field_names_clickup, field_options_clickup, "planilha",
                    )
                if fs:
                    row_filters.append(fs)
            if st.button("＋ Outra condição (planilha)", key=f"am_rule_{rule_id}_row_add"):
                next_id = max([c["id"] for c in rule["row_conds"]], default=-1) + 1
                rule["row_conds"].append({"id": next_id})
                st.rerun()

        # --- Filtros do ClickUp (lista de condições) ---
        usar_filtro_card = st.checkbox(
            "Filtrar pelo estado atual do card no ClickUp",
            key=f"am_rule_uf_clickup_{rule_id}",
            help="Aplica só em cards que satisfazem todas as condições (ex.: Status = Novo E Telefone Adicional vazio).",
        )
        card_filters = []
        if usar_filtro_card:
            if "card_conds" not in rule or not rule["card_conds"]:
                rule["card_conds"] = [{"id": 0}]
            n_card = len(rule["card_conds"])
            for cond in rule["card_conds"]:
                cid = cond["id"]
                if n_card > 1:
                    col_f, col_x = st.columns([20, 1])
                    with col_f:
                        fs = _render_filtro(
                            f"am_rule_{rule_id}_cardf", cid, cols_planilha,
                            field_names_clickup, field_options_clickup, "clickup",
                        )
                    with col_x:
                        st.markdown("<div style='padding-top:0.35rem'></div>", unsafe_allow_html=True)
                        if st.button("✕", key=f"am_rule_{rule_id}_card_rem_{cid}", help="Remover condição"):
                            rule["card_conds"] = [c for c in rule["card_conds"] if c["id"] != cid]
                            st.rerun()
                else:
                    fs = _render_filtro(
                        f"am_rule_{rule_id}_cardf", cid, cols_planilha,
                        field_names_clickup, field_options_clickup, "clickup",
                    )
                if fs:
                    card_filters.append(fs)
            if st.button("＋ Outra condição (ClickUp)", key=f"am_rule_{rule_id}_card_add"):
                next_id = max([c["id"] for c in rule["card_conds"]], default=-1) + 1
                rule["card_conds"].append({"id": next_id})
                st.rerun()

    return {
        "id": rule_id,
        "atualizacoes": atualizacoes_specs,
        "row_filters": row_filters,
        "card_filters": card_filters,
    }


# ══════════════════════════════════════════════════════════════════════════
#                            RENDER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════

def render_atualizar_em_massa():
    list_id = os.getenv("CLICKUP_DEFAULT_LIST_ID", "").strip()
    if not list_id:
        st.error("⚠️ Nenhuma lista de destino configurada.")
        st.info("Abra **⚙️ Configurações** na sidebar e preencha `CLICKUP_DEFAULT_LIST_ID`.")
        return

    cu = ClickUp()

    # Carrega lista, fields, status e membros
    try:
        list_info = cu.get_list(list_id)
        fields = cu.get_list_custom_fields(list_id)
        team_id = os.getenv("CLICKUP_TEAM_ID", "9007176994")
        members = cu.get_members(team_id)
    except Exception as e:
        st.error(f"Erro ao carregar dados da lista: {e}")
        return

    list_name = list_info.get("name", list_id)
    status_options = [s["status"] for s in list_info.get("statuses", [])]
    fn2id = {f["name"]: f["id"] for f in fields}
    option_lookup = build_option_lookup(fields)
    field_names_clickup = ["Status"] + sorted(fn2id.keys())
    field_options_clickup = {"Status": status_options}
    field_options_clickup.update({
        f["name"]: [o["name"] for o in f.get("type_config", {}).get("options", [])]
        for f in fields if f.get("type_config", {}).get("options")
    })

    # Mapa de membros para resolver nome/email/primeiro-nome → user_id
    members_map: dict = {}
    member_names: list = []
    for m in members:
        u = m.get("user", m)
        uid = u.get("id")
        username = (u.get("username") or "").strip()
        email = (u.get("email") or "").strip()
        if not uid:
            continue
        if username:
            member_names.append(username)
            members_map[username.lower()] = uid
            first = username.split()[0].split("@")[0].split(".")[0]
            if first:
                members_map.setdefault(first.lower(), uid)
        if email:
            members_map[email.lower()] = uid
            local = email.split("@")[0]
            if local:
                members_map.setdefault(local.lower(), uid)
    member_names = sorted(set(member_names))

    st.markdown(
        f"📋 **Lista de destino:** `{list_name}` &nbsp;&nbsp; "
        f"<span style='color:#6a6a6c'>id: {list_id}</span>",
        unsafe_allow_html=True,
    )

    # ─── 1. Upload ─────────────────────────────────────────────────────
    st.subheader("1. Planilha")
    uploaded = st.file_uploader(
        "Planilha de leads (.xlsx ou .csv)", type=["xlsx", "csv"], key="am_upload",
    )
    if not uploaded:
        st.caption("Aguardando upload da planilha...")
        return

    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        return

    if df.empty:
        st.warning("Planilha vazia.")
        return

    st.caption(f"**{len(df)}** linhas · **{len(df.columns)}** colunas")
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)

    cols_planilha = [str(c) for c in df.columns]

    # ─── 2. Chaves de busca configuráveis ──────────────────────────────
    st.subheader("2. Como encontrar os cards no ClickUp")
    st.caption(
        "Configure as chaves de busca em ordem de prioridade. A primeira chave "
        "que encontrar um card vence.\n\n"
        "**Comparação:** exata (caractere por caractere, com trim) para campos específicos; "
        "para `🔍 Qualquer campo (lupa)`, busca por substring em todo o texto do card "
        "— igual à lupa do ClickUp."
    )

    if "am_search_keys" not in st.session_state:
        st.session_state.am_search_keys = [{"id": 0}]
    if "am_next_skey_id" not in st.session_state:
        st.session_state.am_next_skey_id = 1

    campo_opcoes = [""] + [CAMPO_QUALQUER, CAMPO_NOME_CARD, CAMPO_DESCRICAO] + sorted(fn2id.keys())

    search_keys = []
    for skey in st.session_state.am_search_keys:
        skid = skey["id"]
        with st.container(border=True):
            c_titulo, c_rem = st.columns([10, 1])
            with c_titulo:
                st.markdown(f"**Chave #{skid + 1}**")
            with c_rem:
                if len(st.session_state.am_search_keys) > 1:
                    if st.button("✕", key=f"am_skey_rem_{skid}", help="Remover esta chave"):
                        st.session_state.am_search_keys = [
                            s for s in st.session_state.am_search_keys if s["id"] != skid
                        ]
                        st.rerun()

            c1, c2 = st.columns(2)
            with c1:
                coluna = st.selectbox(
                    "Coluna da planilha", [""] + cols_planilha,
                    key=f"am_skey_col_{skid}",
                )
            with c2:
                campo = st.selectbox(
                    "Campo no ClickUp", campo_opcoes,
                    key=f"am_skey_field_{skid}",
                )

            if coluna and campo:
                search_keys.append({
                    "id": skid, "coluna": coluna, "campo": campo,
                })

    if st.button("＋ Adicionar chave de busca", key="am_skey_add"):
        st.session_state.am_search_keys.append({"id": st.session_state.am_next_skey_id})
        st.session_state.am_next_skey_id += 1
        st.rerun()

    if not search_keys:
        st.warning("⚠️ Configure ao menos uma chave de busca completa (coluna + campo) para continuar.")
        return

    # ─── 3. Regras de atualização ──────────────────────────────────────
    st.subheader("3. Regras de atualização")

    if "am_rules" not in st.session_state:
        st.session_state.am_rules = [{"id": 0, "updates": [{"id": 0}]}]
    if "am_next_rule_id" not in st.session_state:
        st.session_state.am_next_rule_id = 1

    regras_specs = []
    for rule in st.session_state.am_rules:
        with st.container(border=True):
            spec = _render_regra(
                rule, df, fields, fn2id,
                field_names_clickup, field_options_clickup, status_options,
                member_names,
            )
            if spec.get("atualizacoes"):
                regras_specs.append(spec)

    if st.button("＋ Adicionar regra", key="am_rule_add"):
        st.session_state.am_rules.append({
            "id": st.session_state.am_next_rule_id,
            "updates": [{"id": 0}],
        })
        st.session_state.am_next_rule_id += 1
        st.rerun()

    if not regras_specs:
        st.warning("⚠️ Adicione ao menos uma regra de atualização para continuar.")
        return

    # ─── 4. Prévia ─────────────────────────────────────────────────────
    st.subheader("4. Prévia")

    col_prev1, col_prev2 = st.columns([4, 1])
    with col_prev1:
        verificar_clicked = st.button("🔍 Verificar prévia", use_container_width=True)
    with col_prev2:
        if st.button("🗑 Limpar", use_container_width=True, key="am_previa_clear"):
            st.session_state.pop("am_previa", None)
            st.rerun()

    if verificar_clicked:
        with st.spinner("Carregando cards do ClickUp..."):
            tasks = cu.get_list_tasks(list_id)

        indexes = _build_search_indexes(tasks, search_keys)

        # Contagem global + relatório detalhado em uma única passada
        linhas_com_match = 0
        cards_afetados = set()
        cards_com_mudanca = set()
        preview_rows = []
        sample_data = []  # primeiras 3 linhas, com cards e mudanças prontas pra exibir
        for i, (_, row_all) in enumerate(df.iterrows()):
            matched_all, metodo, valor_pesquisado = _find_cards(row_all, search_keys, indexes)
            is_sample = i < 3

            if not matched_all:
                preview_rows.append({
                    "linha": i + 1,
                    "valor_pesquisado": valor_pesquisado,
                    "card_id": "",
                    "card_nome": "",
                    "status_atual": "",
                    "metodo": "—",
                    "mudancas": "",
                    "vai_alterar": "Não (não encontrado)",
                })
                if is_sample:
                    sample_data.append({"i": i + 1, "matched": False})
                continue

            linhas_com_match += 1
            sample_cards = []
            for task_all in matched_all:
                cards_afetados.add(task_all["id"])
                mudancas_lista = []
                mudancas_detalhe = []
                for regra in regras_specs:
                    if not _row_passes_filters(row_all, regra["row_filters"]):
                        continue
                    if not _card_passes_filters(task_all, regra["card_filters"], fn2id, option_lookup):
                        continue
                    for at in regra["atualizacoes"]:
                        valor_bruto = at["valor_fixo"] if at["source"] == VALOR_FIXO else row_all.get(at["valor_coluna"])
                        if at["target"] in (TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO):
                            display_val = _formatar_data(valor_bruto)
                        elif at["target"] == TARGET_RESPONSAVEL:
                            if isinstance(valor_bruto, list):
                                display_val = ", ".join(valor_bruto) if valor_bruto else "(vazio)"
                            else:
                                display_val = str(valor_bruto) if valor_bruto is not None else "(vazio)"
                        else:
                            display_val = str(valor_bruto) if valor_bruto is not None else "(vazio)"
                        mudancas_lista.append(f"{at['target']}: {display_val}")
                        mudancas_detalhe.append({"campo": at["target"], "novo_valor": display_val})
                if mudancas_lista:
                    cards_com_mudanca.add(task_all["id"])
                preview_rows.append({
                    "linha": i + 1,
                    "valor_pesquisado": valor_pesquisado,
                    "card_id": task_all["id"],
                    "card_nome": task_all.get("name", ""),
                    "status_atual": (task_all.get("status") or {}).get("status", ""),
                    "metodo": metodo,
                    "mudancas": " | ".join(mudancas_lista) if mudancas_lista else "",
                    "vai_alterar": "Sim" if mudancas_lista else "Não (filtros excluíram)",
                })
                if is_sample and len(sample_cards) < 3:
                    sample_cards.append({
                        "card_id": task_all["id"],
                        "nome": task_all.get("name", ""),
                        "status_atual": (task_all.get("status") or {}).get("status", ""),
                        "mudancas": mudancas_detalhe or "(nenhuma — filtros excluíram este card)",
                    })

            if is_sample:
                sample_data.append({
                    "i": i + 1,
                    "matched": True,
                    "metodo": metodo,
                    "n_total": len(matched_all),
                    "primeiro_nome": (matched_all[0].get("name") or "")[:60],
                    "cards": sample_cards,
                })

        # Gera o XLSX da prévia já em memória
        df_previa = pd.DataFrame(preview_rows)
        buf_previa = io.BytesIO()
        with pd.ExcelWriter(buf_previa, engine="openpyxl") as writer:
            df_previa.to_excel(writer, sheet_name="previa", index=False)

        from datetime import datetime as _dt
        st.session_state.am_previa = {
            "total_tasks": len(tasks),
            "linhas_com_match": linhas_com_match,
            "n_cards_afetados": len(cards_afetados),
            "n_cards_com_mudanca": len(cards_com_mudanca),
            "linhas_sem_match": len(df) - linhas_com_match,
            "n_preview_rows": len(df_previa),
            "xlsx_bytes": buf_previa.getvalue(),
            "ts": _dt.now().strftime('%Y%m%d_%H%M%S'),
            "sample": sample_data,
        }

    # ── Render persistente da prévia (sobrevive a reruns) ──────────────
    if "am_previa" in st.session_state:
        p = st.session_state.am_previa
        st.caption(f"{p['total_tasks']} cards na lista.")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Linhas com match", p["linhas_com_match"])
        m2.metric("Cards encontrados (únicos)", p["n_cards_afetados"])
        m3.metric("Cards que serão alterados", p["n_cards_com_mudanca"])
        m4.metric("Linhas sem match", p["linhas_sem_match"])

        st.download_button(
            label=f"⬇ Baixar prévia detalhada (XLSX, {p['n_preview_rows']} linhas)",
            data=p["xlsx_bytes"],
            file_name=f"previa_atualizar_em_massa_{p['ts']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.markdown("**Amostra das 3 primeiras linhas:**")
        for s in p["sample"]:
            if not s["matched"]:
                st.info(f"Linha {s['i']}: nenhum card encontrado.")
                continue
            with st.expander(
                f"Linha {s['i']} → {s['n_total']} card(s) (via {s['metodo']}): {s['primeiro_nome']}",
                expanded=(s["i"] == 1),
            ):
                for card in s["cards"]:
                    st.json(card)

    # ─── 5. Executar ───────────────────────────────────────────────────
    st.subheader("5. Executar")

    if "am_cancel" not in st.session_state:
        st.session_state.am_cancel = False
    if "am_running" not in st.session_state:
        st.session_state.am_running = False

    col_run, col_cancel = st.columns([3, 1])
    with col_run:
        start_clicked = st.button(
            f"▶ Atualizar a partir de {len(df)} linhas",
            type="primary", use_container_width=True, key="am_run",
        )
    with col_cancel:
        if st.button("⏹ Cancelar", use_container_width=True, key="am_cancel_btn"):
            st.session_state.am_cancel = True

    if start_clicked:
        st.session_state.am_cancel = False
        st.session_state.am_running = True

        with st.spinner("Carregando cards do ClickUp..."):
            tasks = cu.get_list_tasks(list_id)

        indexes = _build_search_indexes(tasks, search_keys)

        report = []
        bar = st.progress(0.0, text="Iniciando...")

        for i, (_, row) in enumerate(df.iterrows()):
            if st.session_state.am_cancel:
                st.warning(f"⏹ Interrompido após {i} linhas.")
                break

            bar.progress((i + 1) / len(df), text=f"Linha {i+1}/{len(df)}")

            matched, metodo, _ = _find_cards(row, search_keys, indexes)

            if not matched:
                report.append({
                    "linha": i + 1, "card_id": "", "metodo": "—",
                    "status": "não encontrado",
                })
                continue

            for task in matched:
                aplicou = []
                for regra in regras_specs:
                    if not _row_passes_filters(row, regra["row_filters"]):
                        continue
                    if not _card_passes_filters(task, regra["card_filters"], fn2id, option_lookup):
                        continue

                    for at in regra["atualizacoes"]:
                        valor_bruto = (
                            at["valor_fixo"] if at["source"] == VALOR_FIXO
                            else row.get(at["valor_coluna"])
                        )

                        try:
                            if at["target"] == TARGET_STATUS:
                                if valor_bruto:
                                    cu.update_task(task["id"], {"status": str(valor_bruto)})
                                    aplicou.append("status")
                            elif at["target"] == TARGET_DESC:
                                if valor_bruto:
                                    cu.update_task(task["id"], {"description": str(valor_bruto)})
                                    aplicou.append("descricao")
                            elif at["target"] == TARGET_DATA_INICIO:
                                ms = _resolver_data(valor_bruto)
                                if ms is not None:
                                    cu.update_task(task["id"], {"start_date": ms})
                                    aplicou.append("data início")
                            elif at["target"] == TARGET_DATA_VENCIMENTO:
                                ms = _resolver_data(valor_bruto)
                                if ms is not None:
                                    cu.update_task(task["id"], {"due_date": ms})
                                    aplicou.append("data vencimento")
                            elif at["target"] == TARGET_RESPONSAVEL:
                                user_ids = _resolver_assignees(valor_bruto, members_map)
                                if user_ids:
                                    cu.update_task(task["id"], {"assignees": {"add": user_ids, "rem": []}})
                                    aplicou.append(f"responsáveis (+{len(user_ids)})")
                            else:
                                cf = next((f for f in fields if f["id"] == fn2id.get(at["target"])), None)
                                valor_resolvido = _resolver_valor_para_campo(
                                    at["target"], cf, valor_bruto, option_lookup,
                                )
                                if valor_resolvido is not None and cf:
                                    cu.set_custom_field(task["id"], cf["id"], valor_resolvido)
                                    aplicou.append(at["target"])
                        except Exception as e:
                            report.append({
                                "linha": i + 1, "card_id": task["id"], "metodo": metodo,
                                "status": f"erro em '{at['target']}': {e}",
                            })

                report.append({
                    "linha": i + 1, "card_id": task["id"], "metodo": metodo,
                    "status": f"atualizado ({', '.join(aplicou)})" if aplicou else "nenhuma regra aplicou (filtros excluíram)",
                })

        bar.empty()
        st.session_state.am_running = False

        df_rep = pd.DataFrame(report)
        atualizados = df_rep["status"].str.startswith("atualizado").sum() if not df_rep.empty else 0
        nao_encontrados = (df_rep["status"] == "não encontrado").sum() if not df_rep.empty else 0
        erros = df_rep["status"].str.startswith("erro").sum() if not df_rep.empty else 0

        st.success(
            f"✅ {atualizados} cards atualizados · "
            f"{nao_encontrados} não encontrados · "
            f"{erros} erros"
        )
        st.dataframe(df_rep, use_container_width=True, hide_index=True)

        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_bytes = df_rep.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇ Baixar relatório (CSV)",
                data=csv_bytes,
                file_name=f"relatorio_atualizar_em_massa_{ts}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        # Excel só com as linhas da planilha que não acharam card
        nao_enc_idx = [r["linha"] - 1 for r in report if r["status"] == "não encontrado"]
        if nao_enc_idx:
            df_nao_enc = df.iloc[nao_enc_idx].copy()
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_nao_enc.to_excel(writer, sheet_name="nao_encontradas", index=False)
            with col_dl2:
                st.download_button(
                    label=f"⬇ Baixar {len(nao_enc_idx)} linhas não encontradas (XLSX)",
                    data=buf.getvalue(),
                    file_name=f"nao_encontradas_{ts}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
