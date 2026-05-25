"""Página: Atualizar por Filtros — atualiza cards selecionados via filtros do ClickUp.

Diferente da Atualização em Massa, não usa planilha. Os cards são selecionados
diretamente pelos filtros configurados, e as regras de atualização aplicam
valores fixos (não há coluna de planilha de onde tirar valores).
"""
import os
from datetime import datetime, date

import pandas as pd
import streamlit as st

from core.clickup_api import ClickUp
from core.helpers import build_option_lookup
from core.filtros import (
    render_filtros_ui, coletar_filtros, task_passes_filters,
)
from core.automacoes_pages.atualizar_em_massa import (
    TARGET_STATUS, TARGET_DESC,
    TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO, TARGET_RESPONSAVEL,
    _resolver_data, _resolver_assignees, _resolver_valor_para_campo, _formatar_data,
    _card_passes_filters, _render_filtro,
)


# ══════════════════════════════════════════════════════════════════════════
#                          UI: SUB-RENDERS
# ══════════════════════════════════════════════════════════════════════════

def _render_atualizacao_filtro(rule_id, upd_id, fields, fn2id, status_options,
                                member_names, allow_remove: bool) -> dict:
    """Renderiza UM bloco de atualização (campo + valor fixo) dentro de uma regra."""
    prefix = f"apf_rule_{rule_id}_upd_{upd_id}"

    if allow_remove:
        col_l, col_r = st.columns([10, 1])
        with col_r:
            if st.button("✕", key=f"{prefix}_rem", help="Remover este campo desta regra"):
                for r in st.session_state.apf_rules:
                    if r["id"] == rule_id:
                        r["updates"] = [u for u in r.get("updates", []) if u["id"] != upd_id]
                        break
                st.rerun()

    target_opts = [""] + [
        TARGET_STATUS, TARGET_DESC,
        TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO,
        TARGET_RESPONSAVEL,
    ] + sorted(fn2id.keys())
    target = st.selectbox("Campo a atualizar", target_opts, key=f"{prefix}_target")

    if not target:
        st.caption("_Selecione o campo a atualizar para continuar._")
        return {}

    valor_fixo = None

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
                help="Marque para preencher; desmarque para deixar vazia.",
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

    return {"target": target, "valor_fixo": valor_fixo}


def _render_regra_filtro(rule: dict, fields, fn2id,
                          field_names_clickup, field_options_clickup,
                          status_options, member_names) -> dict:
    """Renderiza uma regra com 1+ atualizações e filtros opcionais por regra."""
    rule_id = rule["id"]

    if "updates" not in rule or not rule["updates"]:
        rule["updates"] = [{"id": 0}]

    col_titulo, col_rem = st.columns([10, 1])
    with col_titulo:
        st.markdown(f"**Regra #{rule_id + 1}**")
    with col_rem:
        if len(st.session_state.apf_rules) > 1:
            if st.button("✕", key=f"apf_rule_rem_{rule_id}",
                         help="Remover esta regra inteira"):
                st.session_state.apf_rules = [
                    r for r in st.session_state.apf_rules if r["id"] != rule_id
                ]
                st.rerun()

    st.markdown("**Atualizar:**")
    atualizacoes_specs = []
    n_updates = len(rule["updates"])
    for i, upd in enumerate(rule["updates"]):
        if i > 0:
            st.markdown(
                "<hr style='margin:0.5rem 0; border:none; border-top:1px solid #2c2c2e'>",
                unsafe_allow_html=True,
            )
        upd_spec = _render_atualizacao_filtro(
            rule_id, upd["id"], fields, fn2id, status_options,
            member_names, allow_remove=(n_updates > 1),
        )
        if upd_spec.get("target"):
            atualizacoes_specs.append(upd_spec)

    if st.button("＋ Adicionar outro campo a esta regra",
                 key=f"apf_rule_add_upd_{rule_id}"):
        next_upd_id = max([u["id"] for u in rule["updates"]], default=-1) + 1
        rule["updates"].append({"id": next_upd_id})
        st.rerun()

    # Filtros adicionais por regra (só ClickUp — não há planilha aqui)
    with st.expander("Aplicar em apenas alguns dos cards filtrados"):
        st.caption(
            "Por padrão, a regra vale para **todos os cards selecionados** pelos filtros do passo 1. "
            "Liga abaixo para refinar ainda mais."
        )

        usar_filtro = st.checkbox(
            "Filtrar pelo estado atual do card",
            key=f"apf_rule_uf_{rule_id}",
            help="Aplica só nos cards que satisfazem todas as condições (AND).",
        )
        card_filters = []
        if usar_filtro:
            if "card_conds" not in rule or not rule["card_conds"]:
                rule["card_conds"] = [{"id": 0}]
            n_card = len(rule["card_conds"])
            for cond in rule["card_conds"]:
                cid = cond["id"]
                if n_card > 1:
                    col_f, col_x = st.columns([20, 1])
                    with col_f:
                        fs = _render_filtro(
                            f"apf_rule_{rule_id}_cardf", cid, [],
                            field_names_clickup, field_options_clickup, "clickup",
                        )
                    with col_x:
                        st.markdown(
                            "<div style='padding-top:0.35rem'></div>",
                            unsafe_allow_html=True,
                        )
                        if st.button("✕", key=f"apf_rule_{rule_id}_card_rem_{cid}",
                                     help="Remover condição"):
                            rule["card_conds"] = [
                                c for c in rule["card_conds"] if c["id"] != cid
                            ]
                            st.rerun()
                else:
                    fs = _render_filtro(
                        f"apf_rule_{rule_id}_cardf", cid, [],
                        field_names_clickup, field_options_clickup, "clickup",
                    )
                if fs:
                    card_filters.append(fs)
            if st.button("＋ Outra condição", key=f"apf_rule_{rule_id}_card_add"):
                next_id = max([c["id"] for c in rule["card_conds"]], default=-1) + 1
                rule["card_conds"].append({"id": next_id})
                st.rerun()

    return {
        "id": rule_id,
        "atualizacoes": atualizacoes_specs,
        "card_filters": card_filters,
    }


# ══════════════════════════════════════════════════════════════════════════
#                            RENDER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════

def render_atualizar_por_filtros():
    list_id = os.getenv("CLICKUP_DEFAULT_LIST_ID", "").strip()
    if not list_id:
        st.error("⚠️ Nenhuma lista de destino configurada.")
        st.info("Abra **⚙️ Configurações** na sidebar e preencha `CLICKUP_DEFAULT_LIST_ID`.")
        return

    cu = ClickUp()

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

    # Membros do workspace
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

    # Tags do space (mesma estratégia do Exportar Leads)
    tag_names: list = []
    space_id = (list_info.get("space") or {}).get("id")
    if space_id:
        try:
            tags_data = cu._req("GET", f"/space/{space_id}/tag").get("tags", [])
            tag_names = sorted({t.get("name", "") for t in tags_data if t.get("name")})
        except Exception:
            pass

    # Opções para filtros
    field_names_clickup = ["Status", "Responsável", "Tags"] + sorted(fn2id.keys())
    field_options_clickup = {
        "Status": status_options,
        "Responsável": member_names,
        "Tags": tag_names,
    }
    for f in fields:
        opts = f.get("type_config", {}).get("options", [])
        if opts:
            field_options_clickup[f["name"]] = [o["name"] for o in opts]

    st.markdown(
        f"📋 **Lista:** `{list_name}` &nbsp;&nbsp; "
        f"<span style='color:#6a6a6c'>id: {list_id}</span>",
        unsafe_allow_html=True,
    )

    # ─── 1. Filtros pra selecionar cards ───────────────────────────────
    st.subheader("1. Filtros pra selecionar cards")
    st.caption(
        "Configure os filtros que definem **quais cards** serão considerados. "
        "Para `Responsável` e `Tags`, use operadores como `=`, `contém` ou `é um de`."
    )

    st.markdown("**Filtros obrigatórios (E)**")
    render_filtros_ui(st, "apf_filtros_e", "apf_e", field_names_clickup, field_options_clickup)

    st.markdown("**Filtros alternativos (OU)** — opcional")
    render_filtros_ui(st, "apf_filtros_ou", "apf_ou", field_names_clickup, field_options_clickup)

    filtros_e = coletar_filtros(st, "apf_filtros_e", "apf_e", field_options_clickup)
    filtros_ou = coletar_filtros(st, "apf_filtros_ou", "apf_ou", field_options_clickup)

    if not filtros_e and not filtros_ou:
        st.warning("⚠️ Configure ao menos um filtro para selecionar os cards.")
        return

    # ─── 2. Regras de atualização ──────────────────────────────────────
    st.subheader("2. Regras de atualização")
    st.caption(
        "Defina o que será alterado nos cards selecionados. "
        "Cada regra pode ter um ou mais campos a atualizar, e filtros opcionais para refinar ainda mais."
    )

    if "apf_rules" not in st.session_state:
        st.session_state.apf_rules = [{"id": 0, "updates": [{"id": 0}]}]
    if "apf_next_rule_id" not in st.session_state:
        st.session_state.apf_next_rule_id = 1

    regras_specs = []
    for rule in st.session_state.apf_rules:
        with st.container(border=True):
            spec = _render_regra_filtro(
                rule, fields, fn2id,
                field_names_clickup, field_options_clickup,
                status_options, member_names,
            )
            if spec.get("atualizacoes"):
                regras_specs.append(spec)

    if st.button("＋ Adicionar regra", key="apf_rule_add"):
        st.session_state.apf_rules.append({
            "id": st.session_state.apf_next_rule_id,
            "updates": [{"id": 0}],
        })
        st.session_state.apf_next_rule_id += 1
        st.rerun()

    if not regras_specs:
        st.warning("⚠️ Adicione ao menos uma regra de atualização para continuar.")
        return

    # ─── 3. Prévia ─────────────────────────────────────────────────────
    st.subheader("3. Prévia")

    col_v, col_c = st.columns([4, 1])
    with col_v:
        verificar = st.button("🔍 Verificar prévia", use_container_width=True, key="apf_verify")
    with col_c:
        if st.button("🗑 Limpar", use_container_width=True, key="apf_clear"):
            st.session_state.pop("apf_preview", None)
            st.rerun()

    if verificar:
        with st.spinner("Carregando cards do ClickUp..."):
            tasks = cu.get_list_tasks(list_id)

        filtered = [
            t for t in tasks
            if task_passes_filters(t, filtros_e, filtros_ou, fn2id, option_lookup)
        ]

        cards_com_mudanca = 0
        sample = []
        for task in filtered:
            mudancas = []
            for regra in regras_specs:
                if regra["card_filters"] and not _card_passes_filters(
                    task, regra["card_filters"], fn2id, option_lookup
                ):
                    continue
                for at in regra["atualizacoes"]:
                    valor = at["valor_fixo"]
                    if at["target"] in (TARGET_DATA_INICIO, TARGET_DATA_VENCIMENTO):
                        display = _formatar_data(valor)
                    elif at["target"] == TARGET_RESPONSAVEL:
                        if isinstance(valor, list):
                            display = ", ".join(valor) if valor else "(vazio)"
                        else:
                            display = str(valor) if valor is not None else "(vazio)"
                    else:
                        display = str(valor) if valor is not None else "(vazio)"
                    mudancas.append({"campo": at["target"], "novo_valor": display})
            if mudancas:
                cards_com_mudanca += 1
                if len(sample) < 5:
                    sample.append({
                        "card_id": task["id"],
                        "nome": task.get("name", ""),
                        "status_atual": (task.get("status") or {}).get("status", ""),
                        "mudancas": mudancas,
                    })

        st.session_state.apf_preview = {
            "total": len(tasks),
            "filtrados": len(filtered),
            "com_mudanca": cards_com_mudanca,
        }

    if "apf_preview" in st.session_state:
        p = st.session_state.apf_preview
        c1, c2, c3 = st.columns(3)
        c1.metric("Total na lista", p["total"])
        c2.metric("Cards filtrados", p["filtrados"])
        c3.metric("Cards que serão alterados", p["com_mudanca"])

    # ─── 4. Executar ───────────────────────────────────────────────────
    st.subheader("4. Executar")

    if "apf_cancel" not in st.session_state:
        st.session_state.apf_cancel = False

    col_run, col_cancel = st.columns([3, 1])
    with col_run:
        executar = st.button(
            "▶ Executar atualização",
            type="primary", use_container_width=True, key="apf_run",
        )
    with col_cancel:
        if st.button("⏹ Cancelar", use_container_width=True, key="apf_cancel_btn"):
            st.session_state.apf_cancel = True

    if executar:
        st.session_state.apf_cancel = False

        with st.spinner("Carregando cards do ClickUp..."):
            tasks = cu.get_list_tasks(list_id)

        filtered = [
            t for t in tasks
            if task_passes_filters(t, filtros_e, filtros_ou, fn2id, option_lookup)
        ]

        if not filtered:
            st.warning("Nenhum card passa nos filtros configurados — nada a fazer.")
            return

        report = []
        bar = st.progress(0.0, text="Iniciando...")

        for i, task in enumerate(filtered):
            if st.session_state.apf_cancel:
                st.warning(f"⏹ Interrompido após {i} cards.")
                break

            bar.progress((i + 1) / len(filtered),
                         text=f"Card {i+1}/{len(filtered)} — {task.get('name', '?')[:50]}")

            aplicou = []
            for regra in regras_specs:
                if regra["card_filters"] and not _card_passes_filters(
                    task, regra["card_filters"], fn2id, option_lookup
                ):
                    continue
                for at in regra["atualizacoes"]:
                    valor = at["valor_fixo"]
                    try:
                        if at["target"] == TARGET_STATUS:
                            if valor:
                                cu.update_task(task["id"], {"status": str(valor)})
                                aplicou.append("status")
                        elif at["target"] == TARGET_DESC:
                            if valor:
                                cu.update_task(task["id"], {"description": str(valor)})
                                aplicou.append("descricao")
                        elif at["target"] == TARGET_DATA_INICIO:
                            ms = _resolver_data(valor)
                            if ms is not None:
                                cu.update_task(task["id"], {"start_date": ms})
                                aplicou.append("data início")
                        elif at["target"] == TARGET_DATA_VENCIMENTO:
                            ms = _resolver_data(valor)
                            if ms is not None:
                                cu.update_task(task["id"], {"due_date": ms})
                                aplicou.append("data vencimento")
                        elif at["target"] == TARGET_RESPONSAVEL:
                            user_ids = _resolver_assignees(valor, members_map)
                            if user_ids:
                                cu.update_task(task["id"], {"assignees": {"add": user_ids, "rem": []}})
                                aplicou.append(f"responsáveis (+{len(user_ids)})")
                        else:
                            cf = next((f for f in fields if f["id"] == fn2id.get(at["target"])), None)
                            valor_resolvido = _resolver_valor_para_campo(
                                at["target"], cf, valor, option_lookup,
                            )
                            if valor_resolvido is not None and cf:
                                cu.set_custom_field(task["id"], cf["id"], valor_resolvido)
                                aplicou.append(at["target"])
                    except Exception as e:
                        report.append({
                            "card_id": task["id"], "nome": task.get("name", ""),
                            "status": f"erro em '{at['target']}': {e}",
                        })

            report.append({
                "card_id": task["id"],
                "nome": task.get("name", ""),
                "status_anterior": (task.get("status") or {}).get("status", ""),
                "status": f"atualizado ({', '.join(aplicou)})" if aplicou else "nenhuma regra aplicou (filtros das regras excluíram)",
            })

        bar.empty()

        df_rep = pd.DataFrame(report)
        atualizados = df_rep["status"].str.startswith("atualizado").sum() if not df_rep.empty else 0
        erros = df_rep["status"].str.startswith("erro").sum() if not df_rep.empty else 0

        st.success(f"✅ {atualizados} cards atualizados · {erros} erros")
        st.dataframe(df_rep, use_container_width=True, hide_index=True)

        csv_bytes = df_rep.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇ Baixar relatório CSV",
            data=csv_bytes,
            file_name=f"relatorio_atualizar_por_filtros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
