"""labnote-send：教科書の実験の記録を、Discord（Webhook）か、手元の labnote に送る小さな道具。

例（Mac の ~/home-lab/ch4 で第4章の RUN のあと。labnote のフォルダは --project で指す）:
  uv run --project ~/path/to/labnote labnote-send file data/run_d500.csv --pair --to webhook
      → run_d500.csv と、motor_run.py が同じ名前で書く run_d500.json の2つを、要約つきで Webhook に送る
  uv run --project ~/path/to/labnote labnote-send file data/run_d500.csv --pair --to local --note 3
      → Webhook を使わず、この機械の labnote（LABNOTE_HOME）のノート #3 に直接足す
例（Pi で。第0章の pi_mqtt_logger.py が書く ~/lab/lab.db の messages を、直近60分だけ要約して送る）:
  labnote-send mqtt --db ~/lab/lab.db --minutes 60 [--dev pico1-leak] --to webhook

Webhook の URL は秘密情報なので、.env の LABNOTE_WEBHOOK_URL に書く（コマンドの引数に書かない。
シェルの履歴に残るため）。Webhook で送ったものを bot に取り込ませるには docs/discord_setup.md の「Webhook の取り込み」。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .store import LabnoteError, Library, safe_filename
from .summary import format_summary, summarize_bytes

USER_AGENT = "labnote-send/0.1"
# Discord の Webhook の URL の形。打ち間違いで別のホストにデータを送らない・URL の中の空白などで
# urllib が URL（秘密）を含む例外を出さないように、送る前にこの形だけを通す
WEBHOOK_URL_RE = re.compile(r"^https://(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]+$")
WEBHOOK_MAX_BYTES = 8_000_000           # Webhook の添付の上限の目安（公式ドキュメントで要確認）


def multipart(fields: dict[str, str], files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    boundary = "labnote" + uuid.uuid4().hex
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
                  f"Content-Type: application/json\r\n\r\n".encode())
        buf.write(value.encode("utf-8") + b"\r\n")
    for i, (field, filename, data) in enumerate(files):
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field or f'files[{i}]'}\"; "
                  f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode())
        buf.write(data + b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def build_webhook_request(url: str, content: str, files: list[tuple[str, bytes]]) -> urllib.request.Request:
    if "your-webhook" in url or not WEBHOOK_URL_RE.match(url):
        raise LabnoteError("LABNOTE_WEBHOOK_URL が未設定か、見本の値か、"
                           "Discord の Webhook の URL の形ではありません（.env に書く）")
    payload = {"content": content[:1900], "allowed_mentions": {"parse": []}}
    body, ctype = multipart({"payload_json": json.dumps(payload, ensure_ascii=False)},
                            [(f"files[{i}]", safe_filename(name), data) for i, (name, data) in enumerate(files)])
    return urllib.request.Request(url, data=body, method="POST",
                                  headers={"Content-Type": ctype, "User-Agent": USER_AGENT})


def post_webhook(url: str, content: str, files: list[tuple[str, bytes]], timeout: float = 20) -> int:
    req = build_webhook_request(url, content, files)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:      # 送りすぎ：言われた秒数だけ待ってやり直す
                wait = float(e.headers.get("Retry-After", "2"))
                time.sleep(min(wait, 30))
                continue
            # URL（秘密）をエラーに出さない
            raise LabnoteError(f"Webhook への送信に失敗しました（HTTP {e.code}）") from None
        except urllib.error.URLError as e:
            raise LabnoteError(f"Webhook につながりません（{e.reason}）") from None
        except (OSError, ValueError) as e:              # 例外のメッセージに URL が入ることがあるので種類だけ出す
            raise LabnoteError(f"Webhook への送信に失敗しました（{type(e).__name__}）") from None
    raise LabnoteError("Webhook への送信をあきらめました（429 が続いた）")


def collect_files(paths: list[str], pair: bool) -> list[Path]:
    out: list[Path] = []
    for s in paths:
        p = Path(s).expanduser()
        if not p.is_file():
            raise LabnoteError(f"{p} がありません")
        out.append(p)
        if pair and p.suffix.lower() == ".csv":      # motor_run.py・rc_capture.py などは同じ名前の .json を書く
            j = p.with_suffix(".json")
            if j.is_file() and j not in out:
                out.append(j)
    return out


def mqtt_window(db: Path, minutes: float, dev: str | None, now: float | None = None) -> tuple[str, bytes]:
    """第0章の messages（recv_unix, topic, payload, dev, seq）の直近の区間を、要約と CSV にする。"""
    if not db.is_file():
        raise LabnoteError(f"{db} がありません")
    now = time.time() if now is None else now
    t0 = now - minutes * 60
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)    # 読むだけ（ロガーの書き込みを邪魔しない）
    try:
        sql = "SELECT recv_unix, topic, dev, seq, payload FROM messages WHERE recv_unix >= ?"
        args: list = [t0]
        if dev:
            sql += " AND dev = ?"
            args.append(dev)
        rows = con.execute(sql + " ORDER BY recv_unix", args).fetchall()
    finally:
        con.close()
    per: dict[str, dict] = defaultdict(lambda: {"n": 0, "seqs": [], "last": 0.0, "num": defaultdict(list)})
    keys: list[str] = []
    for recv, _topic, d, seq, payload in rows:
        k = d or "(dev なし)"
        s = per[k]
        s["n"] += 1
        s["last"] = recv
        if seq is not None:
            s["seqs"].append(int(seq))
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            obj = None
        if isinstance(obj, dict):
            for key, v in obj.items():
                if key in ("seq", "ticks_ms") or isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue
                s["num"][key].append(float(v))
                if key not in keys:
                    keys.append(key)
    lines = [f"MQTT の記録（{db.name}、直近 {minutes:g} 分{('、dev=' + dev) if dev else ''}）：{len(rows)} 件"]
    for k, s in per.items():
        seqs = s["seqs"]
        lost = ""
        if len(seqs) >= 2:
            span = max(seqs) - min(seqs) + 1
            lost = f"、seq の欠け {span - len(set(seqs))}（{min(seqs)}〜{max(seqs)}）"
        age = now - s["last"]
        lines.append(f"{k}：{s['n']} 件{lost}、最後の受信は {age:.0f} 秒前")
        for key, xs in list(s["num"].items())[:6]:
            lines.append(f"    {key}: 平均 {sum(xs) / len(xs):.4g}（最小 {min(xs):.4g}、最大 {max(xs):.4g}）")
    if not rows:
        lines.append("この区間には記録がありません（Pico の電源・Wi-Fi・lab-logger を確かめる）")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["recv_unix", "topic", "dev", "seq", "payload"])
    w.writerows(rows)
    return "\n".join(lines), out.getvalue().encode("utf-8")


def deliver(to: str, cfg, text: str, files: list[tuple[str, bytes]], note: str | None,
            chapter: str | None, title: str | None, caption: str | None = None) -> str:
    if to == "webhook":
        total = sum(len(d) for _, d in files)
        if total > WEBHOOK_MAX_BYTES:
            raise LabnoteError(f"ファイルが大きすぎます（合計 {total} バイト）。--to local を使う")
        prefix = f"note:{note} " if note and note != "today" else ""
        status = post_webhook(cfg.webhook_url, prefix + text, files)
        return f"Webhook に送りました（HTTP {status}）"
    lib = Library(cfg.home, tz_name=cfg.tz_name)
    try:
        if note:
            n = lib.resolve(note)
        elif title:
            n = lib.new_note(chapter or "misc", title)
        else:
            n = lib.today_note(create=True)
        for name, data in files:
            lib.add_result(n, name, data, source="send", caption=caption)
        if not files:
            lib.log(n, text, author="labnote-send")
        return f"#{n.id}（{lib.home / n.path}）に足しました"
    finally:
        lib.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="labnote-send", description="実験の記録を Discord か labnote に送る")
    ap.add_argument("--env", help=".env のパス（既定は今のフォルダの .env、無ければ環境変数）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("file", "mqtt", "text"):
        s = sub.add_parser(name)
        s.add_argument("--to", choices=("webhook", "local"), default="webhook")
        s.add_argument("--note", help="ノートの番号か today（local の既定は今日のノート）")
        s.add_argument("--chapter", help="--title と一緒に使うと新しいノートを作る（local）")
        s.add_argument("--title")
        s.add_argument("-m", "--message", default="", help="一緒に送る短い文")
        if name == "file":
            s.add_argument("files", nargs="+")
            s.add_argument("--pair", action="store_true", help="CSV と同じ名前の .json も送る")
        elif name == "mqtt":
            s.add_argument("--db", default="~/lab/lab.db")
            s.add_argument("--minutes", type=float, default=60)
            s.add_argument("--dev")
            s.add_argument("--no-csv", action="store_true", help="要約だけ送る（CSV を付けない）")
    args = ap.parse_args(argv)
    cfg = load_config(args.env)
    try:
        if args.cmd == "file":
            paths = collect_files(args.files, args.pair)
            files = [(p.name, p.read_bytes()) for p in paths]
            summ = [format_summary(n, summarize_bytes(n, d)) for n, d in files]
            text = "\n".join(x for x in [args.message, "```", *summ, "```"] if x)
        elif args.cmd == "mqtt":
            summ, data = mqtt_window(Path(args.db).expanduser(), args.minutes, args.dev)
            stamp = time.strftime("%Y%m%d_%H%M")
            files = [] if args.no_csv else [(f"mqtt_{stamp}.csv", data)]
            text = "\n".join(x for x in [args.message, "```", summ, "```"] if x)
        else:
            files, text = [], args.message
            if not text:
                raise LabnoteError("-m で文を入れてください")
        print(deliver(args.to, cfg, text, files, args.note, args.chapter, args.title, args.message or None))
        if args.cmd != "text":
            print(text)
        return 0
    except LabnoteError as e:
        print(f"エラー：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
