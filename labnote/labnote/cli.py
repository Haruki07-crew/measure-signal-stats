"""labnote：実験ノートの CLI。

使い方（labnote のフォルダで。置き場所は --home か .env の LABNOTE_HOME。既定は ~/home-lab/labnote）:
  uv run labnote init
  uv run labnote new --chapter ch4 --title "スイープ 1回目" [--purpose "..."] [--date 2026-11-27]
  uv run labnote log today "電池 5.42V。室温 21℃"
  uv run labnote add-result 3 ~/home-lab/ch4/data/sweep_1.csv [--caption "..."]
  uv run labnote list [--chapter ch4] [-n 20]
  uv run labnote show 3
  uv run labnote search 失速 電池
  uv run labnote today
  uv run labnote reindex
  uv run labnote backup ~/labnote_backup
ノートの指定は、番号（3）・ファイルのパス・today（今日のノート。無ければ作る）のどれか。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .store import LabnoteError, Library


def open_library(args) -> Library:
    cfg = load_config(args.env)
    home = Path(args.home).expanduser() if args.home else cfg.home
    return Library(home, tz_name=cfg.tz_name)


def cmd_init(lib: Library, args) -> int:
    t = lib.init()
    print(f"置き場所：{lib.home}\nひな形：{t}\n索引：{lib.db_path}")
    return 0


def cmd_new(lib: Library, args) -> int:
    note = lib.new_note(args.chapter, args.title, date=args.date, purpose=args.purpose)
    print(f"#{note.id} を作りました：{lib.home / note.path}")
    return 0


def cmd_log(lib: Library, args) -> int:
    note = lib.resolve(args.note)
    entry = lib.log(note, " ".join(args.text), author=args.author)
    print(f"#{note.id} に追記：{entry}")
    return 0


def cmd_add_result(lib: Library, args) -> int:
    note = lib.resolve(args.note)
    for f in args.files:
        p = Path(f).expanduser()
        if not p.is_file():
            raise LabnoteError(f"{p} がありません")
        att = lib.add_result(note, p.name, p.read_bytes(), source="cli", caption=args.caption)
        print(f"#{note.id} に {att.path} を足しました\n{att.summary}")
    return 0


def cmd_list(lib: Library, args) -> int:
    notes = lib.list(limit=args.n, chapter=args.chapter)
    if not notes:
        print("ノートはまだありません（labnote new で作る）")
    for n in notes:
        print(f"#{n.id:<4} {n.date}  {n.chapter:<8} {n.title}")
    return 0


def cmd_show(lib: Library, args) -> int:
    note = lib.resolve(args.note)
    print(lib.read_text(note))
    atts = lib.attachments(note.id)
    if atts:
        print("---- 添付（LABNOTE_HOME から見たパス）----")
        for a in atts:
            print(f"{a.path}（{a.source}）")
    return 0


def cmd_search(lib: Library, args) -> int:
    hits = lib.search(" ".join(args.words), limit=args.n)
    if not hits:
        print("見つかりませんでした")
    for n, snip in hits:
        print(f"#{n.id:<4} {n.date}  {n.chapter:<8} {n.title}\n      …{snip}…")
    return 0


def cmd_today(lib: Library, args) -> int:
    print(lib.day_summary(args.date))
    return 0


def cmd_reindex(lib: Library, args) -> int:
    n, a = lib.reindex()
    print(f"索引を作り直しました：ノート {n} 件、ファイル {a} 個")
    return 0


def cmd_backup(lib: Library, args) -> int:
    dest = lib.backup(args.dest)
    print(f"バックアップ：{dest}（labnote.db・notes/・data/）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="labnote", description="実験ノート（Markdown＋SQLite の索引）")
    p.add_argument("--home", help="置き場所（既定は .env の LABNOTE_HOME、無ければ ~/home-lab/labnote）")
    p.add_argument("--env", help=".env のパス（既定は今のフォルダの .env）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="置き場所とひな形を作る").set_defaults(func=cmd_init)

    s = sub.add_parser("new", help="ひな形から新しいノートを作る")
    s.add_argument("--chapter", required=True, help="章（ch4、intro1、ii4 など）")
    s.add_argument("--title", required=True)
    s.add_argument("--purpose", help="目的（あとで Markdown を直接書いてもよい）")
    s.add_argument("--date", help="YYYY-MM-DD（既定は今日）")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("log", help="時刻つきの短いメモを足す")
    s.add_argument("note", help="番号・パス・today")
    s.add_argument("text", nargs="+")
    s.add_argument("--author", help="書いた人の表示（任意）")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("add-result", help="CSV・PNG・JSON を data/ に置き、ノートに追記する")
    s.add_argument("note", help="番号・パス・today")
    s.add_argument("files", nargs="+")
    s.add_argument("--caption", help="ファイルの説明（任意）")
    s.set_defaults(func=cmd_add_result)

    s = sub.add_parser("list", help="最近のノート")
    s.add_argument("--chapter")
    s.add_argument("-n", type=int, default=10)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="ノートの中身")
    s.add_argument("note")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("search", help="題名・本文から探す（言葉をすべて含むもの）")
    s.add_argument("words", nargs="+")
    s.add_argument("-n", type=int, default=10)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("today", help="今日のまとめ")
    s.add_argument("--date", help="YYYY-MM-DD（既定は今日）")
    s.set_defaults(func=cmd_today)

    sub.add_parser("reindex", help="notes/ と data/ から索引を作り直す").set_defaults(func=cmd_reindex)

    s = sub.add_parser("backup", help="labnote.db・notes/・data/ の写しを作る")
    s.add_argument("dest")
    s.set_defaults(func=cmd_backup)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lib = open_library(args)
        try:
            return args.func(lib, args)
        finally:
            lib.close()
    except LabnoteError as e:
        print(f"エラー：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
