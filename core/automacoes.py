"""Catálogo de automações."""

AUTOMACOES = [
    {
        "id": "importar_leads",
        "icon": "📥",
        "titulo": "Importar Leads",
        "descricao": "Cria cards em massa a partir de uma planilha de leads",
        "disponivel": True,
        "render_fn": "render_importar_leads",
    },
    {
        "id": "atualizar_em_massa",
        "icon": "🔄",
        "titulo": "Atualização em Massa",
        "descricao": "Atualiza cards existentes a partir de uma planilha com regras configuráveis",
        "disponivel": True,
        "render_fn": "render_atualizar_em_massa",
    },
    {
        "id": "exportar_leads",
        "icon": "📤",
        "titulo": "Exportar Leads",
        "descricao": "Gera planilha Excel de cards do ClickUp aplicando filtros (E e OU)",
        "disponivel": True,
        "render_fn": "render_exportar_leads",
    },
    {
        "id": "atualizar_por_filtros",
        "icon": "🎯",
        "titulo": "Atualizar por Filtros",
        "descricao": "Atualiza cards selecionados via filtros do ClickUp, sem planilha",
        "disponivel": True,
        "render_fn": "render_atualizar_por_filtros",
    },
]


def get_automacao(auto_id: str) -> dict | None:
    """Retorna uma automação pelo ID."""
    return next((a for a in AUTOMACOES if a["id"] == auto_id), None)


def listar_automacoes(apenas_disponiveis=False) -> list:
    """Retorna lista de automações."""
    if apenas_disponiveis:
        return [a for a in AUTOMACOES if a.get("disponivel", True)]
    return AUTOMACOES
