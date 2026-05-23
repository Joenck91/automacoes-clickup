"""Orquestra ClickUp — app principal com roteamento via sidebar."""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv, set_key, dotenv_values

from core.clickup_api import ClickUp
from core.ui import render_sidebar_header, render_connection_status, render_nav_menu, render_main_welcome
from core.automacoes import listar_automacoes

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

# ── Config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Orquestra ClickUp",
    page_icon="🎼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilo global ──────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Remover sidebar padrão do Streamlit */
    [data-testid="stSidebarNav"] { display: none; }

    /* Botões da navbar */
    .stButton > button {
        width: 100%;
        text-align: left;
        padding: 0.6rem 1rem;
        border-radius: 6px;
        border: none;
        background: transparent;
        color: #9a9a9c;
        transition: all 0.2s ease;
        font-size: 0.95rem;
    }
    .stButton > button:hover {
        background: #2c2c2e;
        color: #e8e8ea;
    }
    .stButton > button:focus {
        background: #3a3a3e;
        color: #4a90e2;
    }

    /* Main area */
    .main { padding: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state ──────────────────────────────────────────────────────────
if "pagina_ativa" not in st.session_state:
    st.session_state.pagina_ativa = None  # Nenhuma página selecionada = welcome

# ── SIDEBAR ────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_header()
    render_connection_status()

    automacoes = listar_automacoes()
    pagina_nova = render_nav_menu(automacoes, st.session_state.pagina_ativa)

    if pagina_nova != st.session_state.pagina_ativa:
        st.session_state.pagina_ativa = pagina_nova
        st.rerun()

# ── MAIN AREA (roteamento) ─────────────────────────────────────────────────

pagina = st.session_state.pagina_ativa

# ── Página: Configurações ──────────────────────────────────────────────────
if pagina == "__config__":
    st.title("⚙️ Configurações")
    st.caption("Credenciais e configurações do workspace ClickUp.")

    st.divider()

    env_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    def mask(val: str) -> str:
        if not val or len(val) < 8:
            return val or ""
        return val[:4] + "••••••••" + val[-4:]

    col_a, col_b, col_c = st.columns([2, 1.5, 1.5])

    with col_a:
        token_atual = env_vals.get("CLICKUP_TOKEN", "")
        novo_token = st.text_input(
            "CLICKUP_TOKEN",
            value=token_atual,
            type="password",
            placeholder="pk_xxxxxxxxxxxxxxxx",
            help="Settings → Apps → API Token no ClickUp",
        )

    with col_b:
        team_atual = env_vals.get("CLICKUP_TEAM_ID", "9007176994")
        novo_team = st.text_input(
            "CLICKUP_TEAM_ID",
            value=team_atual,
            placeholder="9007176994",
            help="ID numérico do workspace (aparece na URL)",
        )

    with col_c:
        list_atual = env_vals.get("CLICKUP_DEFAULT_LIST_ID", "")
        novo_list = st.text_input(
            "CLICKUP_DEFAULT_LIST_ID",
            value=list_atual,
            placeholder="901303636701",
            help="ID da lista padrão (opcional)",
        )

    if st.button("💾 Salvar e testar conexão", type="primary", use_container_width=True):
        if not novo_token.strip():
            st.error("CLICKUP_TOKEN é obrigatório.")
        else:
            if not ENV_PATH.exists():
                ENV_PATH.touch()
            set_key(str(ENV_PATH), "CLICKUP_TOKEN", novo_token.strip())
            set_key(str(ENV_PATH), "CLICKUP_TEAM_ID", novo_team.strip())
            set_key(str(ENV_PATH), "CLICKUP_DEFAULT_LIST_ID", novo_list.strip())

            try:
                cu_test = ClickUp(token=novo_token.strip())
                teams = cu_test._req("GET", "/team").get("teams", [])
                team = next(
                    (t for t in teams if str(t.get("id")) == novo_team.strip()), None
                )
                if team:
                    st.success(f"✅ Salvo! Conectado ao workspace **{team.get('name')}**.")
                else:
                    st.warning("✅ Salvo! Token válido, mas workspace não encontrado com esse ID.")
                st.rerun()
            except Exception as e:
                st.error(f"Configurações salvas, mas erro na conexão: {e}")

    st.divider()

    if token_atual:
        st.caption(f"**Token atual:** `{mask(token_atual)}`")
        st.caption(f"**Team ID:** `{team_atual}`")
        if list_atual:
            st.caption(f"**List padrão:** `{list_atual}`")

# ── Página: Automação específica ───────────────────────────────────────────
elif pagina and pagina != "__config__":
    auto = next((a for a in automacoes if a["id"] == pagina), None)
    if auto:
        st.title(f"{auto['icon']} {auto['titulo']}")
        st.caption(auto.get("descricao", ""))
        st.divider()
        st.info("Automação em desenvolvimento. Volte em breve!")
    else:
        st.error(f"Automação '{pagina}' não encontrada.")

# ── Página: Boas-vindas (padrão) ───────────────────────────────────────────
else:
    render_main_welcome()
