"""Componentes de UI reutilizáveis."""
import streamlit as st
from core.clickup_api import ClickUp
import os


def render_sidebar_header():
    """Logo e título da sidebar."""
    st.sidebar.markdown(
        """
        <div style='text-align: center; padding: 2rem 0; border-bottom: 1px solid #2c2c2e;'>
            <h1 style='margin: 0; font-size: 2.5rem;'>🎼</h1>
            <p style='margin: 0.5rem 0 0 0; font-size: 1.2rem; color: #9a9a9c;'><b>Orquestra ClickUp</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_connection_status():
    """Status de conexão na sidebar."""
    try:
        cu = ClickUp()
        team_id = os.getenv("CLICKUP_TEAM_ID", "9007176994")
        teams = cu._req("GET", "/team").get("teams", [])
        team = next((t for t in teams if str(t.get("id")) == str(team_id)), None)

        if team:
            st.sidebar.markdown(
                f"""
                <div style='padding: 0.8rem; margin: 0.5rem 0; background: #1e3a2f; border-radius: 8px;'>
                    <span style='color: #4ade80; font-size: 0.85rem;'>● Conectado</span>
                    <p style='margin: 0.3rem 0 0 0; font-size: 0.75rem; color: #9a9a9c;'>{team.get('name', team_id)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.sidebar.warning(f"Token válido, mas workspace `{team_id}` não encontrado.")
    except Exception as e:
        st.sidebar.markdown(
            f"""
            <div style='padding: 0.8rem; margin: 0.5rem 0; background: #3a1e1e; border-radius: 8px;'>
                <span style='color: #f87171; font-size: 0.85rem;'>● Erro</span>
                <p style='margin: 0.3rem 0 0 0; font-size: 0.7rem; color: #9a9a9c;'>Verifique as configurações</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_nav_menu(automacoes: list, page_ativa: str) -> str:
    """Menu de navegação na sidebar. Retorna a página selecionada."""
    st.sidebar.markdown("<p style='margin-top: 1rem; margin-bottom: 0.5rem; font-size: 0.75rem; color: #6a6a6c; text-transform: uppercase; font-weight: 600;'>AUTOMAÇÕES</p>", unsafe_allow_html=True)

    pagina_selecionada = page_ativa

    for auto in automacoes:
        key = auto["id"]
        label = f"{auto['icon']} {auto['titulo']}"
        is_active = page_ativa == key

        col_icon, col_label = st.sidebar.columns([0.15, 0.85])
        with col_icon:
            pass  # spacing
        with col_label:
            if st.button(
                label,
                key=f"nav_{key}",
                use_container_width=True,
                disabled=not auto.get("disponivel", True),
            ):
                pagina_selecionada = key

    st.sidebar.markdown("<hr style='margin: 1rem 0; border: none; border-top: 1px solid #2c2c2e;'>", unsafe_allow_html=True)
    st.sidebar.markdown("<p style='margin: 0.5rem 0; font-size: 0.75rem; color: #6a6a6c; text-transform: uppercase; font-weight: 600;'>SISTEMA</p>", unsafe_allow_html=True)

    if st.sidebar.button("⚙️ Configurações", key="nav_config", use_container_width=True):
        pagina_selecionada = "__config__"

    return pagina_selecionada


def render_main_welcome():
    """Tela de boas-vindas quando nenhuma automação está selecionada."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            """
            <div style='text-align: center; padding: 3rem 0;'>
                <p style='font-size: 3rem; margin: 0;'>🎼</p>
                <h2 style='color: #9a9a9c; margin: 1rem 0 0.5rem 0;'>Bem-vindo à Orquestra ClickUp</h2>
                <p style='color: #6a6a6c; margin: 0;'>Selecione uma automação na barra lateral para começar.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
