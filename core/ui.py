"""Componentes de UI reutilizáveis."""
import streamlit as st
from core.clickup_api import ClickUp
import os


def render_sidebar_header():
    """Logo e título da sidebar."""
    st.sidebar.markdown(
        """
        <div style='text-align: center; padding: 0 0 0.3rem 0;'>
            <h1 style='margin: 0; font-size: 2.5rem;'>🎼</h1>
            <p style='margin: 0.5rem 0 0 0; font-size: 1.2rem; color: #9a9a9c;'><b>Orquestra ClickUp</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_connection_status():
    """Status de conexão — texto pequeno e centralizado, sem background."""
    try:
        cu = ClickUp()
        team_id = os.getenv("CLICKUP_TEAM_ID", "9007176994")
        teams = cu._req("GET", "/team").get("teams", [])
        team = next((t for t in teams if str(t.get("id")) == str(team_id)), None)

        if team:
            st.sidebar.markdown(
                f"""
                <div style='text-align: center; padding: 0 0 1.2rem 0;'>
                    <span style='color: #4ade80; font-size: 0.8rem;'>● Conectado</span>
                    <span style='color: #6a6a6c; font-size: 0.75rem;'> · {team.get('name', team_id)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.sidebar.markdown(
                f"""
                <div style='text-align: center; padding: 0 0 1.2rem 0;'>
                    <span style='color: #fbbf24; font-size: 0.8rem;'>● Workspace não encontrado</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    except Exception:
        st.sidebar.markdown(
            """
            <div style='text-align: center; padding: 0 0 1.2rem 0;'>
                <span style='color: #f87171; font-size: 0.8rem;'>● Sem conexão</span>
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

    # Configurações é o último item — CSS no app.py aplica margin-top: auto
    # no :last-child da sidebar, empurrando este botão para o fundo.
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
