"""Páginas das automações — uma função render_* por automação."""
from .importar_leads import render_importar_leads
from .atualizar_em_massa import render_atualizar_em_massa

__all__ = ["render_importar_leads", "render_atualizar_em_massa"]
