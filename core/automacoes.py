"""Catálogo de automações."""

AUTOMACOES = [
    # Exemplo (descomente quando tiver a primeira automação):
    # {
    #     "id": "disparos",
    #     "icon": "📨",
    #     "titulo": "Disparos",
    #     "descricao": "Atualiza cards via planilha de campanha",
    #     "disponivel": True,
    #     "render_fn": "render_disparos",  # função em core/automacoes/ ou importada dinâmicamente
    # },
]


def get_automacao(auto_id: str) -> dict | None:
    """Retorna uma automação pelo ID."""
    return next((a for a in AUTOMACOES if a["id"] == auto_id), None)


def listar_automacoes(apenas_disponiveis=False) -> list:
    """Retorna lista de automações."""
    if apenas_disponiveis:
        return [a for a in AUTOMACOES if a.get("disponivel", True)]
    return AUTOMACOES
