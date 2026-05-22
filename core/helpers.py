"""Helpers compartilhados entre automações."""
import re
import unicodedata
from datetime import datetime
import pandas as pd


def normalize(s: str) -> str:
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()


def normalize_cnpj(raw) -> str:
    return re.sub(r"\D", "", str(raw or ""))


def normalize_phone(raw) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits


def format_phone(raw) -> str:
    digits = normalize_phone(raw)
    if len(digits) < 10:
        return str(raw or "").strip()
    ddd, number = digits[:2], digits[2:]
    sep = 5 if len(number) >= 9 else 4
    return f"({ddd}) {number[:sep]}-{number[sep:]}"


def to_ms(dt) -> int:
    if not isinstance(dt, datetime):
        dt = pd.to_datetime(dt).to_pydatetime()
    return int(dt.timestamp() * 1000)


def build_option_lookup(fields: list) -> dict:
    lookup = {}
    for f in fields:
        opts = f.get("type_config", {}).get("options", [])
        if opts:
            lookup[f["id"]] = {opt.get("orderindex"): opt["name"] for opt in opts}
    return lookup


def resolve_cf_display(cf: dict, option_lookup: dict) -> str:
    val = cf.get("value")
    if val is None:
        return ""
    fid = cf.get("id", "")
    if fid in option_lookup:
        try:
            resolved = option_lookup[fid].get(int(val))
            if resolved:
                return resolved
        except (TypeError, ValueError):
            pass
    if isinstance(val, dict):
        return val.get("name") or str(val)
    if isinstance(val, list):
        return ", ".join(v.get("name") if isinstance(v, dict) else str(v) for v in val)
    return str(val)


def field_id(fields: list, name: str) -> str | None:
    return next((f["id"] for f in fields if f["name"] == name), None)


def option_id(fields: list, field_name: str, option_name: str) -> str | None:
    for f in fields:
        if f["name"] == field_name:
            for opt in f.get("type_config", {}).get("options", []):
                if opt["name"] == option_name:
                    return opt["id"]
    return None
