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
]


def get_automacao(auto_id: str) -> dict | None:
    """Retorna uma automação pelo ID."""
    return next((a for a in AUTOMACOES if a["id"] == auto_id), None)


def listar_automacoes(apenas_disponiveis=False) -> list:
    """Retorna lista de automações."""
    if apenas_disponiveis:
        return [a for a in AUTOMACOES if a.get("disponivel", True)]
    return AUTOMACOES
