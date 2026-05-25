"""Página: Exportar Leads — gera planilha Excel de cards do ClickUp filtrados."""
import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from core.clickup_api import ClickUp
from core.helpers import build_option_lookup, resolve_cf_display
from core.filtros import (
    render_filtros_ui, coletar_filtros, task_passes_filters,
)


def _field_value(task: dict, field_name: str, fn2id: dict, option_lookup: dict) -> str:
    """Extrai um valor exibível de um card para o campo solicitado."""
    if field_name == "Nome":
        return task.get("name", "") or ""
    if field_name == "Status":
        return (task.get("status") or {}).get("status", "") or ""
    if field_name == "Descrição":
        return task.get("description", "") or ""
    if field_name == "Responsável":
        assignees = task.get("assignees", []) or []
        names = [a.get("username") or a.get("email") or "" for a in assignees]
        return ", ".join(n for n in names if n)
    if field_name == "Tags":
        tags = task.get("tags", []) or []
        names = [t.get("name", "") for t in tags if t.get("name")]
        return ", ".join(names)
    if field_name in ("Data criação", "Data início", "Data vencimento"):
        key = {
            "Data criação": "date_created",
            "Data início": "start_date",
            "Data vencimento": "due_date",
        }[field_name]
        ts = task.get(key)
        if ts:
            try:
                return datetime.fromtimestamp(int(ts) / 1000).strftime("%d/%m/%Y")
            except Exception:
                return ""
        return ""
    if field_name == "URL":
        return task.get("url", "") or ""
    if field_name == "ID":
        return task.get("id", "") or ""
    # Custom field por nome
    fid = fn2id.get(field_name)
    if fid:
        for cf in task.get("custom_fields", []):
            if cf["id"] == fid:
                return resolve_cf_display(cf, option_lookup) or ""
    return ""


def render_exportar_leads():
    list_id = os.getenv("CLICKUP_DEFAULT_LIST_ID", "").strip()
    if not list_id:
        st.error("⚠️ Nenhuma lista de origem configurada.")
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

    # Nomes dos membros (para multiselect de Responsável)
    member_names = []
    for m in members:
        u = m.get("user", m)
        username = (u.get("username") or "").strip()
        if username:
            member_names.append(username)
    member_names = sorted(set(member_names))

    # Tags do space (uma chamada à parte; vazio se falhar)
    tag_names = []
    space_id = (list_info.get("space") or {}).get("id")
    if space_id:
        try:
            tags_data = cu._req("GET", f"/space/{space_id}/tag").get("tags", [])
            tag_names = sorted({t.get("name", "") for t in tags_data if t.get("name")})
        except Exception:
            pass

    # Opções de campos pros filtros
    field_names = ["Status", "Responsável", "Tags"] + sorted(fn2id.keys())
    field_options = {
        "Status": status_options,
        "Responsável": member_names,
        "Tags": tag_names,
    }
    for f in fields:
        opts = f.get("type_config", {}).get("options", [])
        if opts:
            field_options[f["name"]] = [o["name"] for o in opts]

    st.markdown(
        f"📋 **Lista de origem:** `{list_name}` &nbsp;&nbsp; "
        f"<span style='color:#6a6a6c'>id: {list_id}</span>",
        unsafe_allow_html=True,
    )

    # ─── 1. Filtros obrigatórios (E) ────────────────────────────────────
    st.subheader("1. Filtros obrigatórios (E)")
    st.caption(
        "Os cards retornados devem satisfazer **todos** estes filtros. "
        "Para `Responsável` e `Tags`, use operadores como `=`, `contém` ou `é um de`."
    )
    render_filtros_ui(st, "el_filtros_e", "el_e", field_names, field_options)

    # ─── 2. Filtros alternativos (OU) ───────────────────────────────────
    st.subheader("2. Filtros alternativos (OU)")
    st.caption(
        "Além dos obrigatórios, o card deve satisfazer **pelo menos um** destes. "
        "Deixe em branco para não usar."
    )
    render_filtros_ui(st, "el_filtros_ou", "el_ou", field_names, field_options)

    filtros_e = coletar_filtros(st, "el_filtros_e", "el_e", field_options)
    filtros_ou = coletar_filtros(st, "el_filtros_ou", "el_ou", field_options)

    # ─── 3. Campos a incluir no Excel ───────────────────────────────────
    st.subheader("3. Campos a incluir no Excel")
    fields_export = [
        "Nome", "Status", "Descrição",
        "Responsável", "Tags",
        "Data criação", "Data início", "Data vencimento",
        "URL", "ID",
    ] + sorted(fn2id.keys())

    selected_fields = st.multiselect(
        "Selecione os campos",
        fields_export,
        default=["Nome", "Status", "Responsável"],
        key="el_fields_export",
    )

    if not selected_fields:
        st.warning("⚠️ Selecione ao menos um campo para incluir no Excel.")
        return

    # ─── 4. Prévia + Exportar ───────────────────────────────────────────
    st.subheader("4. Prévia + Exportar")

    col_v, col_c = st.columns([4, 1])
    with col_v:
        verificar = st.button("🔍 Verificar prévia", use_container_width=True, key="el_verify")
    with col_c:
        if st.button("🗑 Limpar", use_container_width=True, key="el_clear"):
            st.session_state.pop("el_preview", None)
            st.rerun()

    if verificar:
        with st.spinner("Carregando cards do ClickUp..."):
            tasks = cu.get_list_tasks(list_id)

        filtered = [
            t for t in tasks
            if task_passes_filters(t, filtros_e, filtros_ou, fn2id, option_lookup)
        ]

        rows = []
        for task in filtered:
            row = {f: _field_value(task, f, fn2id, option_lookup) for f in selected_fields}
            rows.append(row)
        df_export = pd.DataFrame(rows)

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_export.to_excel(writer, sheet_name="cards", index=False)

        st.session_state.el_preview = {
            "total": len(tasks),
            "filtrados": len(filtered),
            "df_amostra": df_export.head(5),
            "xlsx_bytes": buf.getvalue(),
            "ts": datetime.now().strftime('%Y%m%d_%H%M%S'),
        }

    if "el_preview" in st.session_state:
        p = st.session_state.el_preview
        c1, c2 = st.columns(2)
        c1.metric("Total na lista", p["total"])
        c2.metric("Cards após filtros", p["filtrados"])

        if p["filtrados"] > 0:
            st.markdown("**Amostra dos primeiros 5 cards:**")
            st.dataframe(p["df_amostra"], use_container_width=True, hide_index=True)

            st.download_button(
                label=f"⬇ Baixar planilha completa (XLSX, {p['filtrados']} cards)",
                data=p["xlsx_bytes"],
                file_name=f"exportar_leads_{p['ts']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.info("Nenhum card passa nos filtros configurados.")
