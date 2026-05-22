"""Hub de automações ClickUp — página inicial."""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.clickup_api import ClickUp

load_dotenv()

st.set_page_config(
    page_title="Hub ClickUp — Booz",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .auto-card {
        border: 1px solid #2c2c2e;
        border-radius: 12px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 0.8rem;
        background: #1a1a1c;
        transition: border-color 0.15s ease;
    }
    .auto-card:hover { border-color: #4a90e2; }
    .auto-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 0.3rem; }
    .auto-desc { color: #9a9a9c; font-size: 0.92rem; margin-bottom: 0.6rem; }
    .auto-meta { color: #6a6a6c; font-size: 0.78rem; }
    .badge {
        display: inline-block; padding: 2px 8px; border-radius: 6px;
        font-size: 0.72rem; font-weight: 500; margin-right: 0.4rem;
    }
    .badge-disponivel { background: #1e3a2f; color: #4ade80; }
    .badge-em-breve { background: #3a2f1e; color: #fbbf24; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🤖 Hub de Automações ClickUp")
st.caption("Centro de comando para automações repetitivas no workspace do Grupo Booz.")

col_status, col_env = st.columns([2, 1])

with col_status:
    try:
        cu = ClickUp()
        teams = cu._req("GET", "/team").get("teams", [])
        team_id = os.getenv("CLICKUP_TEAM_ID", "9007176994")
        team = next((t for t in teams if str(t.get("id")) == str(team_id)), None)
        if team:
            st.success(f"✅ Conectado ao workspace **{team.get('name', team_id)}** ({team_id})")
        else:
            st.warning(f"⚠️ Token válido, mas workspace {team_id} não encontrado.")
    except Exception as e:
        st.error(f"❌ Erro de conexão: {e}")
        st.info("Verifique o `CLICKUP_TOKEN` no arquivo `.env`.")

with col_env:
    list_id = os.getenv("CLICKUP_DEFAULT_LIST_ID", "")
    if list_id:
        st.info(f"📋 Lista padrão: `{list_id}`")

st.divider()

AUTOMACOES = []


def render_card(auto: dict):
    status = auto.get("status", "disponivel")
    badge_class = "badge-disponivel" if status == "disponivel" else "badge-em-breve"
    badge_text = "Disponível" if status == "disponivel" else "Em breve"
    tags_html = " ".join(f"<span class='badge'>{t}</span>" for t in auto.get("tags", []))

    st.markdown(
        f"""
        <div class='auto-card'>
            <div class='auto-title'>{auto['titulo']}</div>
            <div class='auto-desc'>{auto['descricao']}</div>
            <div class='auto-meta'>
                <span class='badge {badge_class}'>{badge_text}</span>
                {tags_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.subheader("Automações disponíveis")

if not AUTOMACOES:
    st.info(
        "ℹ️ Nenhuma automação cadastrada ainda.\n\n"
        "Quando você descrever a primeira automação, ela aparecerá aqui."
    )
else:
    cols = st.columns(2)
    for i, auto in enumerate(AUTOMACOES):
        with cols[i % 2]:
            render_card(auto)

st.divider()
with st.expander("ℹ️ Sobre este hub"):
    st.markdown(
        """
        **Estrutura:**
        - `app.py` — esta página
        - `pages/` — automações (um arquivo por automação)
        - `core/` — biblioteca compartilhada
        - `.env` — credenciais (NUNCA commitar)
        """
    )
