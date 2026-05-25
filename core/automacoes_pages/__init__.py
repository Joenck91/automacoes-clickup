"""Páginas das automações — uma função render_* por automação."""
from .importar_leads import render_importar_leads
from .atualizar_em_massa import render_atualizar_em_massa
from .exportar_leads import render_exportar_leads
from .atualizar_por_filtros import render_atualizar_por_filtros

__all__ = [
    "render_importar_leads",
    "render_atualizar_em_massa",
    "render_exportar_leads",
    "render_atualizar_por_filtros",
]
