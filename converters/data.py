"""Data conversions between CSV, TSV, XLSX, JSON, YAML, XML and TOML.

Spreadsheet-style files are read as tables (pandas), JSON/YAML/TOML/XML as
nested data. Going from nested data to a table flattens it; going the other
way turns each row into a record.
"""
from __future__ import annotations

import json
import re
import tomllib
from io import StringIO
from pathlib import Path

from formats import ext_of, stem_of, unique_path

pd = tomli_w = xmltodict = yaml = None   # loaded by _imports()


def _imports():
    """Load pandas and friends on first use, so the tray app stays small."""
    global pd, tomli_w, xmltodict, yaml
    if pd is None:
        import pandas as pd
        import tomli_w
        import xmltodict
        import yaml

CATEGORY = "Data"
TABULAR = {"csv", "tsv", "xlsx"}
TREE = {"json", "yaml", "toml", "xml"}
SOURCES = TARGETS = TABULAR | TREE

_NUMBER = re.compile(r"-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?$")
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


# ---- reading ---------------------------------------------------------------

def _infer_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Columns that are clearly numeric become numbers. Codes with leading
    zeros (007, 01234) stay as text so they survive the round trip."""
    for col in df.columns:
        values = df[col][df[col] != ""]
        if len(values) and values.map(lambda v: bool(_NUMBER.match(v.strip()))).all():
            numbers = pd.to_numeric(df[col].where(df[col] != "", None))
            if (numbers.dropna() % 1 == 0).all():
                numbers = numbers.astype("Int64")   # whole numbers stay whole even with blanks
            df[col] = numbers
    return df


def _read(src: Path):
    """Return ("tables", {name: DataFrame}) or ("tree", nested data)."""
    ext = ext_of(src)
    if ext == "xlsx":
        return "tables", pd.read_excel(src, sheet_name=None)
    if ext in ("csv", "tsv"):
        df = pd.read_csv(StringIO(_read_text(src)), sep="," if ext == "csv" else "\t",
                         dtype=str, keep_default_na=False)
        return "tables", {stem_of(src): _infer_numbers(df)}
    text = _read_text(src)
    if ext == "json":
        return "tree", json.loads(text)
    if ext == "yaml":
        docs = list(yaml.safe_load_all(text))
        return "tree", docs[0] if len(docs) == 1 else docs
    if ext == "toml":
        return "tree", tomllib.loads(text)
    return "tree", xmltodict.parse(text)


# ---- shape changes -----------------------------------------------------------

def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))


def _frame(items: list) -> pd.DataFrame:
    if items and all(isinstance(i, dict) for i in items):
        df = pd.json_normalize(items)
    else:
        df = pd.DataFrame({"value": items})
    # Lists that json_normalize couldn't flatten become JSON text in the cell.
    return df.map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)


def _tree_to_tables(obj) -> dict[str, pd.DataFrame]:
    # Skip wrapper levels such as {"rows": {"row": [...]}} from XML.
    while isinstance(obj, dict) and len(obj) == 1 and isinstance(next(iter(obj.values())), (dict, list)):
        key, inner = next(iter(obj.items()))
        if isinstance(inner, list):
            return {key: _frame(inner)}
        obj = inner
    if isinstance(obj, list):
        return {"data": _frame(obj)}
    if isinstance(obj, dict):
        if obj and all(isinstance(v, list) for v in obj.values()):
            return {k: _frame(v) for k, v in obj.items()}   # e.g. one list per sheet
        return {"data": _frame([obj])}
    return {"data": pd.DataFrame({"value": [obj]})}


def _tables_to_tree(tables: dict[str, pd.DataFrame], target: str):
    if target == "xml":
        if len(tables) == 1:
            return {"rows": {"row": _records(next(iter(tables.values())))}}
        return {"workbook": {_xml_name(n): {"row": _records(df)} for n, df in tables.items()}}
    if len(tables) == 1:
        return _records(next(iter(tables.values())))
    return {name: _records(df) for name, df in tables.items()}


# ---- writing ---------------------------------------------------------------

def _xml_name(key) -> str:
    key = str(key)
    if key.startswith(("@", "#")):
        return key   # xmltodict attribute / text markers
    key = re.sub(r"[^\w.-]", "_", key)
    return key if re.match(r"[A-Za-z_]", key) else f"_{key}"


def _xml_safe(obj):
    if isinstance(obj, dict):
        return {_xml_name(k): _xml_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_xml_safe(v) for v in obj]
    return obj


def _toml_safe(obj):
    """TOML has no null, so drop None values."""
    if isinstance(obj, dict):
        return {str(k): _toml_safe(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_toml_safe(v) for v in obj if v is not None]
    return obj


def _write_tree(obj, dst: Path, target: str) -> None:
    if target == "json":
        text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    elif target == "yaml":
        text = yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
    elif target == "toml":
        obj = _toml_safe(obj)
        text = tomli_w.dumps(obj if isinstance(obj, dict) else {"items": obj})
    else:
        obj = _xml_safe(obj)
        if not (isinstance(obj, dict) and len(obj) == 1
                and isinstance(next(iter(obj.values())), dict)):
            obj = {"root": obj if isinstance(obj, dict) else {"item": obj}}
        text = xmltodict.unparse(obj, pretty=True)
    dst.write_text(text, encoding="utf-8")


def _sheet_names(names) -> list[str]:
    out = []
    for name in names:
        base = _BAD_SHEET_CHARS.sub("_", str(name))[:31] or "Sheet"
        candidate, n = base, 2
        while candidate in out:
            candidate = f"{base[:28]} {n}"
            n += 1
        out.append(candidate)
    return out


def _write_tables(tables: dict[str, pd.DataFrame], dst: Path, target: str,
                  stem: str) -> list[Path] | None:
    if target == "xlsx":
        with pd.ExcelWriter(dst, engine="openpyxl") as xw:
            for sheet, df in zip(_sheet_names(tables), tables.values()):
                df.to_excel(xw, sheet_name=sheet, index=False)
        return None
    sep = "," if target == "csv" else "\t"
    if len(tables) == 1:
        next(iter(tables.values())).to_csv(dst, sep=sep, index=False, encoding="utf-8-sig")
        return None
    # CSV/TSV hold one table, so a multi-sheet workbook becomes one file per sheet.
    outputs = []
    for name, df in tables.items():
        path = unique_path(dst.parent, f"{stem} - {name}", target)
        df.to_csv(path, sep=sep, index=False, encoding="utf-8-sig")
        outputs.append(path)
    return outputs


def convert(src: Path, dst: Path) -> list[Path] | None:
    _imports()
    target = ext_of(dst)
    kind, content = _read(src)
    if target in TABULAR:
        tables = content if kind == "tables" else _tree_to_tables(content)
        return _write_tables(tables, dst, target, stem_of(src))
    obj = _tables_to_tree(content, target) if kind == "tables" else content
    _write_tree(obj, dst, target)
    return None
