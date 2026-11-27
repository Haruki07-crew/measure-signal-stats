"""CSV・JSON・PNG の簡単な要約（標準ライブラリだけ）。

CSV は教科書の書き方に合わせて、# で始まる行（注釈）を読みとばす（入門1 の led_iv.csv など）。
"""

from __future__ import annotations

import csv
import io
import json
import math
import struct
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
MAX_COLS_SHOWN = 8


def _to_float(text: str):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def summarize_csv_text(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return {"kind": "csv", "rows": 0, "columns": [], "stats": {}}
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader)
    cols = [h.strip() for h in header]
    values: dict[str, list[float]] = {c: [] for c in cols}
    nonnum: dict[str, int] = {c: 0 for c in cols}
    rows = 0
    for row in reader:
        rows += 1
        for c, cell in zip(cols, row, strict=False):
            v = _to_float(cell)
            if v is None:
                if cell.strip():
                    nonnum[c] += 1
            else:
                values[c].append(v)
    stats = {}
    for c in cols:
        xs = values[c]
        if xs and nonnum[c] == 0:
            n = len(xs)
            mean = sum(xs) / n
            sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
            stats[c] = {"n": n, "mean": mean, "sd": sd, "min": min(xs), "max": max(xs)}
    return {"kind": "csv", "rows": rows, "columns": cols, "stats": stats}


def summarize_json_text(text: str) -> dict:
    obj = json.loads(text)
    out: dict = {"kind": "json", "type": type(obj).__name__}
    if isinstance(obj, dict):
        out["keys"] = list(obj.keys())
        out["scalars"] = {
            k: v for k, v in obj.items() if isinstance(v, (str, int, float, bool)) or v is None
        }
    elif isinstance(obj, list):
        out["length"] = len(obj)
    return out


def png_size(data: bytes):
    if data[:8] != PNG_MAGIC or len(data) < 24:
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def summarize_bytes(name: str, data: bytes) -> dict:
    ext = Path(name).suffix.lower()
    if ext == ".csv":
        return summarize_csv_text(data.decode("utf-8-sig"))
    if ext == ".json":
        return summarize_json_text(data.decode("utf-8-sig"))
    if ext == ".png":
        size = png_size(data)
        return {"kind": "png", "width": size[0] if size else None, "height": size[1] if size else None}
    if ext in (".jpg", ".jpeg"):
        return {"kind": "jpeg"}
    if ext == ".txt":
        text = data.decode("utf-8", errors="replace")
        return {"kind": "text", "lines": len(text.splitlines())}
    return {"kind": "other"}


def check_content(name: str, data: bytes) -> str | None:
    """拡張子と中身が合っているかを確かめる。合わなければ理由（文字列）を返す。"""
    ext = Path(name).suffix.lower()
    if ext == ".png" and data[:8] != PNG_MAGIC:
        return "PNG の形式ではありません（拡張子だけ .png）"
    if ext in (".jpg", ".jpeg") and data[:3] != JPEG_MAGIC:
        return "JPEG の形式ではありません"
    if ext in (".csv", ".json", ".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return "UTF-8 の文字として読めません"
        if ext == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                return f"JSON として読めません（{e.msg}、{e.lineno} 行目）"
            except RecursionError:
                return "JSON の入れ子が深すぎます"
    return None


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if 1e-3 <= a < 1e6:
        return f"{v:.4g}"
    return f"{v:.3e}"


def format_summary(name: str, s: dict) -> str:
    kind = s.get("kind")
    if kind == "csv":
        cols = s["columns"]
        head = f"{name}：{s['rows']} 行 × {len(cols)} 列（{', '.join(cols[:MAX_COLS_SHOWN])}"
        head += "…）" if len(cols) > MAX_COLS_SHOWN else "）"
        lines = [head]
        for c, st in list(s["stats"].items())[:MAX_COLS_SHOWN]:
            lines.append(
                f"  {c}: 平均 {_fmt(st['mean'])}、SD {_fmt(st['sd'])}、"
                f"最小 {_fmt(st['min'])}、最大 {_fmt(st['max'])}（n={st['n']}）"
            )
        if len(s["stats"]) > MAX_COLS_SHOWN:
            lines.append(f"  （数値の列はほかに {len(s['stats']) - MAX_COLS_SHOWN} 列）")
        return "\n".join(lines)
    if kind == "json":
        if "keys" in s:
            sc = ", ".join(f"{k}={v}" for k, v in list(s["scalars"].items())[:8])
            return f"{name}：JSON（項目 {len(s['keys'])} 個）{('：' + sc) if sc else ''}"
        return f"{name}：JSON（{s['type']}{'、' + str(s['length']) + ' 個' if 'length' in s else ''}）"
    if kind == "png":
        if s.get("width"):
            return f"{name}：PNG {s['width']}×{s['height']}"
        return f"{name}：PNG"
    if kind == "jpeg":
        return f"{name}：JPEG"
    if kind == "text":
        return f"{name}：テキスト {s['lines']} 行"
    return name
