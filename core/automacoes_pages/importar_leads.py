"""Página: Importar Leads — cria cards em massa a partir de uma planilha."""
import os
import pandas as pd
import streamlit as st

from core.clickup_api import ClickUp

NAO_MAPEAR = "— não mapear —"
VALOR_FIXO = "Valores no Clickup (escolher abaixo)"
STATUS_PADRAO = "(padrão da lista)"


def _carregar_planilha(uploaded) -> pd.DataFrame | None:
    """Lê .xlsx ou .csv para DataFrame."""
    try:
        if uploaded.name.lower().endswith(".csv"):
            return pd.read_csv(uploaded)
        return pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        return None


def _resolver_valor_custom_field(cf: dict, valor_bruto) -> str | int | None:
    """Converte o valor da planilha para o formato esperado pelo custom field.

    Para dropdown/labels, busca o option_id pelo nome. Para outros tipos, retorna string.
    Retorna None se o valor for vazio ou não puder ser resolvido.
    """
    if pd.isna(valor_bruto):
        return None
    val_str = str(valor_bruto).strip()
    if not val_str or val_str.lower() in ("nan", "none"):
        return None

    cf_type = cf.get("type", "")

    # Dropdown / labels → precisa do option_id
    if cf_type in ("drop_down", "labels"):
        options = cf.get("type_config", {}).get("options", [])
        opt = next((o for o in options if o["name"].strip().lower() == val_str.lower()), None)
        return opt["id"] if opt else None

    # Number → int/float
    if cf_type == "number":
        try:
            return float(val_str.replace(",", "."))
        except ValueError:
            return None

    # Demais tipos: text, email, phone, url, etc.
    return val_str


def render_importar_leads():
    """Renderiza a página de importação de leads."""
    list_id = os.getenv("CLICKUP_DEFAULT_LIST_ID", "").strip()

    if not list_id:
        st.error("⚠️ Nenhuma lista de destino configurada.")
        st.info("Abra **⚙️ Configurações** na sidebar e preencha `CLICKUP_DEFAULT_LIST_ID`.")
        return

    cu = ClickUp()

    # ── Carregar info da lista ─────────────────────────────────────────────
    try:
        list_info = cu.get_list(list_id)
        custom_fields = cu.get_list_custom_fields(list_id)
    except Exception as e:
        st.error(f"Erro ao carregar dados da lista do ClickUp: {e}")
        return

    list_name = list_info.get("name", list_id)
    status_options = [s["status"] for s in list_info.get("statuses", [])]

    st.markdown(f"📋 **Lista de destino:** `{list_name}` &nbsp;&nbsp; <span style='color:#6a6a6c'>id: {list_id}</span>", unsafe_allow_html=True)

    # ── 1. Upload ──────────────────────────────────────────────────────────
    st.subheader("1. Selecione a planilha")
    uploaded = st.file_uploader(
        "Planilha de leads (.xlsx ou .csv)", type=["xlsx", "csv"], key="il_upload"
    )

    if not uploaded:
        st.caption("Aguardando upload da planilha...")
        return

    df = _carregar_planilha(uploaded)
    if df is None or df.empty:
        st.warning("Planilha vazia ou inválida.")
        return

    # ── 2. Pré-visualização ────────────────────────────────────────────────
    st.subheader("2. Pré-visualização")
    st.caption(f"**{len(df)}** linhas · **{len(df.columns)}** colunas")
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)

    # ── 3. Mapeamento ──────────────────────────────────────────────────────
    st.subheader("3. Mapeamento de colunas")

    colunas = [NAO_MAPEAR] + [str(c) for c in df.columns]

    st.markdown("**Campos do card**")
    col_n1, col_n2, col_n3 = st.columns(3)
    with col_n1:
        col_nome = st.selectbox("Nome do card *", colunas, key="il_map_name")
    with col_n2:
        col_desc = st.selectbox("Descrição", colunas, key="il_map_desc")
    with col_n3:
        status_fix = st.selectbox(
            "Status inicial",
            [STATUS_PADRAO] + status_options,
            key="il_map_status",
        )

    st.markdown("**Custom fields da lista**")
    st.caption("Cada campo pode ser mapeado a uma coluna OU ter um valor fixo aplicado a todos os cards.")
    if not custom_fields:
        st.caption("_Esta lista não tem custom fields configurados no ClickUp._")
        custom_field_mapping = {}
    else:
        custom_field_mapping = {}
        # Cada custom field tem: selectbox (origem) + input (se valor fixo)
        col_a, col_b = st.columns(2)
        for i, cf in enumerate(custom_fields):
            target_col = col_a if i % 2 == 0 else col_b
            with target_col:
                opcoes = [NAO_MAPEAR, VALOR_FIXO] + [str(c) for c in df.columns]
                escolhida = st.selectbox(
                    f"{cf['name']}",
                    opcoes,
                    key=f"il_map_cf_{cf['id']}",
                    help=f"Tipo: `{cf.get('type', '?')}`",
                )

                if escolhida == NAO_MAPEAR:
                    continue

                if escolhida == VALOR_FIXO:
                    cf_type = cf.get("type", "")

                    # Dropdown / labels: oferecer as opções existentes no ClickUp
                    if cf_type in ("drop_down", "labels"):
                        options = cf.get("type_config", {}).get("options", [])
                        option_names = [o["name"] for o in options]
                        valor = st.selectbox(
                            f"↳ Valor para todos os cards",
                            ["(selecione)"] + option_names,
                            key=f"il_map_cf_fixo_{cf['id']}",
                            label_visibility="collapsed",
                        )
                        if valor != "(selecione)":
                            custom_field_mapping[cf["id"]] = {
                                "cf": cf, "modo": "fixo", "valor": valor,
                            }

                    # Number: input numérico
                    elif cf_type == "number":
                        valor = st.number_input(
                            f"↳ Valor para todos os cards",
                            key=f"il_map_cf_fixo_{cf['id']}",
                            label_visibility="collapsed",
                            value=None,
                            placeholder="Digite o número",
                        )
                        if valor is not None:
                            custom_field_mapping[cf["id"]] = {
                                "cf": cf, "modo": "fixo", "valor": valor,
                            }

                    # Demais tipos: texto livre
                    else:
                        valor = st.text_input(
                            f"↳ Valor para todos os cards",
                            key=f"il_map_cf_fixo_{cf['id']}",
                            label_visibility="collapsed",
                            placeholder="Digite o valor fixo",
                        )
                        if valor.strip():
                            custom_field_mapping[cf["id"]] = {
                                "cf": cf, "modo": "fixo", "valor": valor.strip(),
                            }
                else:
                    # É uma coluna da planilha
                    custom_field_mapping[cf["id"]] = {
                        "cf": cf, "modo": "coluna", "coluna": escolhida,
                    }

    # Validação
    if col_nome == NAO_MAPEAR:
        st.warning("⚠️ Selecione uma coluna para **Nome do card** para continuar.")
        return

    # ── 4. Prévia da importação ────────────────────────────────────────────
    st.subheader("4. Prévia (primeiros 3 cards)")
    for i in range(min(3, len(df))):
        row = df.iloc[i]
        nome_card = str(row[col_nome]) if pd.notna(row[col_nome]) else "(vazio)"
        with st.expander(f"Card {i+1}: {nome_card}", expanded=(i == 0)):
            preview_data = {"Nome": nome_card}
            if col_desc != NAO_MAPEAR:
                desc = row[col_desc]
                preview_data["Descrição"] = str(desc) if pd.notna(desc) else "(vazio)"
            if status_fix != STATUS_PADRAO:
                preview_data["Status"] = status_fix
            for cf_id, info in custom_field_mapping.items():
                if info["modo"] == "fixo":
                    preview_data[info["cf"]["name"]] = f"📌 {info['valor']} (fixo)"
                else:
                    val = row[info["coluna"]]
                    preview_data[info["cf"]["name"]] = str(val) if pd.notna(val) else "(vazio)"
            st.json(preview_data, expanded=True)

    # ── 5. Executar ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("5. Executar")

    # Inicializa flag de cancelamento
    if "il_cancel" not in st.session_state:
        st.session_state.il_cancel = False
    if "il_running" not in st.session_state:
        st.session_state.il_running = False

    col_run, col_cancel = st.columns([3, 1])
    with col_run:
        start_clicked = st.button(
            f"▶ Importar {len(df)} leads",
            type="primary",
            use_container_width=True,
            key="il_run",
            disabled=st.session_state.il_running,
        )
    with col_cancel:
        if st.button("⏹ Cancelar", use_container_width=True, key="il_cancel_btn"):
            st.session_state.il_cancel = True

    if start_clicked:
        st.session_state.il_cancel = False
        st.session_state.il_running = True

        report = []
        bar = st.progress(0.0, text="Iniciando...")
        status_text = st.empty()

        for i, (_, row) in enumerate(df.iterrows()):
            # Checa cancelamento
            if st.session_state.il_cancel:
                status_text.warning(f"⏹ Importação cancelada após {i} linhas.")
                break

            nome = str(row[col_nome]).strip() if pd.notna(row[col_nome]) else ""
            if not nome:
                report.append({"linha": i + 1, "nome": "", "card_id": "", "status": "pulado (nome vazio)"})
                bar.progress((i + 1) / len(df), text=f"Linha {i+1}/{len(df)}")
                continue

            payload = {}
            if col_desc != NAO_MAPEAR and pd.notna(row[col_desc]):
                payload["description"] = str(row[col_desc])
            if status_fix != STATUS_PADRAO:
                payload["status"] = status_fix

            bar.progress((i + 1) / len(df), text=f"Criando {i+1}/{len(df)} — {nome[:50]}")

            try:
                task = cu.create_task(list_id, name=nome, **payload)
                task_id = task["id"]

                for cf_id, info in custom_field_mapping.items():
                    valor_bruto = info["valor"] if info["modo"] == "fixo" else row[info["coluna"]]
                    valor = _resolver_valor_custom_field(info["cf"], valor_bruto)
                    if valor is not None:
                        try:
                            cu.set_custom_field(task_id, cf_id, valor)
                        except Exception:
                            pass  # falha silenciosa em campo isolado não invalida o card

                report.append({"linha": i + 1, "nome": nome, "card_id": task_id, "status": "criado"})
            except Exception as e:
                report.append({"linha": i + 1, "nome": nome, "card_id": "", "status": f"erro: {e}"})

        bar.empty()
        status_text.empty()
        st.session_state.il_running = False

        df_rep = pd.DataFrame(report)
        criados = (df_rep["status"] == "criado").sum()
        erros = df_rep["status"].str.startswith("erro").sum()
        pulados = df_rep["status"].str.startswith("pulado").sum()

        st.success(f"✅ {criados} criados · {erros} com erro · {pulados} pulados")
        st.dataframe(df_rep, use_container_width=True, hide_index=True)

        from datetime import datetime
        csv_bytes = df_rep.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇ Baixar relatório CSV",
            data=csv_bytes,
            file_name=f"relatorio_importar_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
