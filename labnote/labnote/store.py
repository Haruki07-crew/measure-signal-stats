"""実験ノートの本体：Markdown のノート（正本）と、SQLite の索引（labnote.db）。

置き場所（LABNOTE_HOME）の中身:
  notes/template.md                 ひな形（無ければ labnote に同梱のものを使う）
  notes/<年>/<日付>_<章>_<番号>.md   ノート（Git で管理できるテキスト）
  data/<番号>/<ファイル>             ノートに足したデータ（CSV・PNG・JSON など）
  labnote.db                        索引（notes/ と data/ から `labnote reindex` で作り直せる）

CLI と bot は同じ置き場所を開く。SQLite は WAL にして、同時に開いても待つようにしている。
"""

from __future__ import annotations

import contextlib
import csv
import datetime as _dt
import hashlib
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import get_tz
from .summary import check_content, format_summary, summarize_bytes

CHAPTER_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9._-]+")
SEC_RESULT = "結果"
SEC_LOG = "メモ（時刻つき）"
SEC_FILES = "データのファイル"
DEFAULT_CHAPTER = "misc"
MAX_TITLE = 120
MAX_LOG = 1500
MAX_CAPTION = 200
MAX_SEARCH_WORDS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,          -- LABNOTE_HOME から見た相対パス
    date TEXT NOT NULL,                 -- YYYY-MM-DD
    chapter TEXT NOT NULL,
    title TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    body TEXT NOT NULL                  -- 検索用の写し（正本は Markdown）
);
CREATE INDEX IF NOT EXISTS idx_notes_date ON notes(date);
CREATE TABLE IF NOT EXISTS attachments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL REFERENCES notes(id),
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    added TEXT NOT NULL,
    source TEXT NOT NULL,               -- cli / discord / webhook / send
    summary TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_att_note ON attachments(note_id);
"""


class LabnoteError(Exception):
    """利用者に見せてよい失敗（ファイルの種類が違う、ノートが無い など）。"""


@dataclass
class Note:
    id: int
    path: str
    date: str
    chapter: str
    title: str
    created: str
    updated: str


@dataclass
class Attachment:
    id: int
    note_id: int
    path: str
    name: str
    kind: str
    size: int
    added: str
    source: str
    summary: str


def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[end + 5:]


def append_to_section(text: str, section: str, addition: str) -> str:
    """`## section` の節の終わり（次の `## ` の前）に addition を足す。節が無ければ末尾に作る。"""
    lines = text.split("\n")
    head = f"## {section}"
    try:
        # 字下げした行（メモの2行目以降・要約の中）は節の見出しとみなさない（ノートの改ざんを防ぐ）
        start = next(i for i, ln in enumerate(lines) if ln.rstrip() == head)
    except StopIteration:
        body = text.rstrip("\n")
        return f"{body}\n\n{head}\n{addition.rstrip()}\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") or lines[i].startswith("# "):
            end = i
            break
    block = lines[start + 1:end]
    while block and not block[-1].strip():
        block.pop()
    new = block + addition.rstrip("\n").split("\n")
    tail = lines[end:]
    if tail:
        new.append("")
    return "\n".join(lines[: start + 1] + new + tail).rstrip("\n") + "\n"


def human_size(n: int) -> str:
    if n < 1000:
        return f"{n} B"
    if n < 1_000_000:
        return f"{n / 1000:.1f} kB"
    return f"{n / 1_000_000:.1f} MB"


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    stem, suffix = Path(base).stem, Path(base).suffix.lower()
    stem = SAFE_CHAR_RE.sub("_", stem).strip("._") or "file"
    suffix = SAFE_CHAR_RE.sub("", suffix)
    return (stem[:80] + suffix)[:96]


class Library:
    def __init__(self, home: str | Path, tz_name: str = "Asia/Tokyo",
                 allowed_ext: tuple[str, ...] | None = None):
        self.home = Path(home).expanduser().resolve()
        self.notes_dir = self.home / "notes"
        self.data_dir = self.home / "data"
        self.db_path = self.home / "labnote.db"
        self.tz = get_tz(tz_name)
        self.allowed_ext = allowed_ext
        self.home.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)
        # check_same_thread=False：bot は処理をスレッドに逃がす（handlers.py が1本ずつ順に呼ぶ）
        self.con = sqlite3.connect(self.db_path, timeout=10, isolation_level=None, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=10000")
        self.con.executescript(SCHEMA)

    def close(self):
        self.con.close()

    # ---- 時刻 ----
    def now(self) -> _dt.datetime:
        return _dt.datetime.now(self.tz).replace(microsecond=0)

    def today(self) -> str:
        return self.now().date().isoformat()

    # ---- ひな形 ----
    def template_text(self) -> str:
        local = self.notes_dir / "template.md"
        if local.is_file():
            return local.read_text(encoding="utf-8")
        return (Path(__file__).parent / "template.md").read_text(encoding="utf-8")

    def init(self) -> Path:
        """置き場所を作り、ひな形を notes/template.md に写す（あれば何もしない）。"""
        local = self.notes_dir / "template.md"
        if not local.exists():
            shutil.copyfile(Path(__file__).parent / "template.md", local)
        return local

    # ---- 読み出し ----
    def _row_to_note(self, r) -> Note:
        return Note(r["id"], r["path"], r["date"], r["chapter"], r["title"], r["created"], r["updated"])

    def get(self, note_id: int) -> Note:
        r = self.con.execute("SELECT * FROM notes WHERE id=?", (int(note_id),)).fetchone()
        if r is None:
            raise LabnoteError(f"ノート {note_id} はありません（labnote list で番号を確かめる）")
        return self._row_to_note(r)

    def resolve(self, ref: str | int) -> Note:
        """番号（12）、ファイルのパス、または today を受け付ける。"""
        s = str(ref).strip()
        if s == "today":
            return self.today_note(create=True)
        if s.isdigit():
            return self.get(int(s))
        p = Path(s).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p) if (Path.cwd() / p).exists() else (self.home / p)
        try:
            rel = p.resolve().relative_to(self.home).as_posix()
        except ValueError as e:
            raise LabnoteError(f"{s} は LABNOTE_HOME（{self.home}）の中のノートではありません") from e
        r = self.con.execute("SELECT * FROM notes WHERE path=?", (rel,)).fetchone()
        if r is None:
            raise LabnoteError(f"{s} は索引にありません（labnote reindex を試す）")
        return self._row_to_note(r)

    def read_text(self, note: Note) -> str:
        return (self.home / note.path).read_text(encoding="utf-8")

    def list(self, limit: int = 10, chapter: str | None = None) -> list[Note]:
        if chapter:
            rows = self.con.execute(
                "SELECT * FROM notes WHERE chapter=? ORDER BY date DESC, id DESC LIMIT ?", (chapter, limit))
        else:
            rows = self.con.execute("SELECT * FROM notes ORDER BY date DESC, id DESC LIMIT ?", (limit,))
        return [self._row_to_note(r) for r in rows]

    def attachments(self, note_id: int) -> list[Attachment]:
        rows = self.con.execute("SELECT * FROM attachments WHERE note_id=? ORDER BY id", (note_id,))
        return [Attachment(r["id"], r["note_id"], r["path"], r["name"], r["kind"], r["size"],
                           r["added"], r["source"], r["summary"]) for r in rows]

    def search(self, query: str, limit: int = 10) -> list[tuple[Note, str]]:
        words = [w for w in query.split() if w]
        if not words:
            raise LabnoteError("探す言葉を入れてください")
        if len(words) > MAX_SEARCH_WORDS:            # 言葉が多すぎると SQLite の式の深さの上限を超える
            raise LabnoteError(f"探す言葉は {MAX_SEARCH_WORDS} 個までにしてください")
        cond, args = [], []
        for w in words:
            esc = w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            cond.append("(title || ' ' || chapter || ' ' || body) LIKE ? ESCAPE '\\'")
            args.append(f"%{esc}%")
        sql = f"SELECT * FROM notes WHERE {' AND '.join(cond)} ORDER BY date DESC, id DESC LIMIT ?"
        out = []
        for r in self.con.execute(sql, (*args, limit)):
            body = r["body"]
            i = body.lower().find(words[0].lower())
            if i < 0:
                snippet = r["title"]
            else:
                snippet = body[max(0, i - 30): i + 50].replace("\n", " ")
            out.append((self._row_to_note(r), snippet.strip()))
        return out

    # ---- 書き込み ----
    def _sync_row(self, note: Note, text: str):
        meta, _ = parse_front_matter(text)
        title = meta.get("title", note.title)
        updated = self.now().isoformat()
        self.con.execute(
            "UPDATE notes SET body=?, title=?, updated=? WHERE id=?", (text, title, updated, note.id))
        note.updated, note.title = updated, title

    @contextlib.contextmanager
    def _locked(self):
        """Markdown の読み→書きを、ほかのプロセス（bot と CLI）と取り合わないように SQLite の書き込みロックで囲む。"""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        self.con.execute("COMMIT")

    def _write(self, note: Note, text: str):
        path = self.home / note.path
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)                       # 書きかけのファイルが残らないように置き換える
        self._sync_row(note, text)

    def new_note(self, chapter: str, title: str, date: str | None = None, purpose: str | None = None) -> Note:
        chapter = (chapter or DEFAULT_CHAPTER).strip()
        if not CHAPTER_RE.match(chapter):
            raise LabnoteError("章は英数字・-・_ の32文字以内で書く（例：ch4、intro1、ii4）")
        title = " ".join((title or "").split())[:MAX_TITLE]
        if not title:
            raise LabnoteError("題名を入れてください")
        date = date or self.today()
        _dt.date.fromisoformat(date)            # 形式の確認（YYYY-MM-DD）
        with self._locked():                    # 番号の取り合いを防ぐ（CLI と bot が同時に作っても重ならない）
            nid = self._insert_note_locked(chapter, title, date, purpose)
        return self.get(nid)

    def _insert_note_locked(self, chapter: str, title: str, date: str, purpose: str | None) -> int:
        """書き込みロック（_locked）の中で呼ぶ。番号を決め、Markdown を書き、索引に入れる。"""
        created = self.now().isoformat()
        nid = (self.con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM notes").fetchone()[0])
        rel = f"notes/{date[:4]}/{date}_{chapter}_{nid:04d}.md"
        text = (self.template_text()
                .replace("{{id}}", str(nid)).replace("{{date}}", date)
                .replace("{{chapter}}", chapter).replace("{{title}}", title)
                .replace("{{created}}", created))
        if purpose:
            text = append_to_section(text, "目的", purpose.strip())
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise LabnoteError(f"{rel} がすでにあります（labnote reindex で索引を直す）")
        path.write_text(text, encoding="utf-8")
        try:
            self.con.execute(
                "INSERT INTO notes(id, path, date, chapter, title, created, updated, body) "
                "VALUES (?,?,?,?,?,?,?,?)", (nid, rel, date, chapter, title, created, created, text))
        except BaseException:
            path.unlink(missing_ok=True)        # 索引に入らなかったファイルを残さない
            raise
        return nid

    def today_note(self, create: bool = True) -> Note | None:
        """今日の日付のノートのうち、いちばん新しく更新したもの。無ければ『今日のメモ』を作る。

        探すのと作るのを同じ書き込みロックの中で行うので、bot と CLI が同時に呼んでも2つできない。
        """
        sql = "SELECT * FROM notes WHERE date=? ORDER BY updated DESC, id DESC LIMIT 1"
        r = self.con.execute(sql, (self.today(),)).fetchone()
        if r is not None or not create:
            return self._row_to_note(r) if r is not None else None
        today = self.today()
        with self._locked():
            r = self.con.execute(sql, (today,)).fetchone()     # ロックを取ったあとにもう一度見る
            nid = r["id"] if r is not None else self._insert_note_locked(
                DEFAULT_CHAPTER, f"{today} のメモ", today, None)
        return self.get(nid)

    def log(self, note: Note, text: str, author: str | None = None) -> str:
        text = text.strip()
        if not text:
            raise LabnoteError("メモが空です")
        if len(text) > MAX_LOG:
            raise LabnoteError(f"メモは {MAX_LOG} 文字までにしてください")
        stamp = self.now().strftime("%H:%M")
        who = f"（{author}）" if author else ""
        first, *rest = text.splitlines()
        entry = f"- {stamp} {first}{who}" + "".join(f"\n  {ln}" for ln in rest)
        with self._locked():                    # 読んでから書くまでの間に、ほかのプロセスの追記を消さない
            self._write(note, append_to_section(self.read_text(note), SEC_LOG, entry))
        return entry

    def check_file(self, name: str, data: bytes, max_bytes: int | None = None) -> str | None:
        ext = Path(name).suffix.lower()
        if self.allowed_ext is not None and ext not in self.allowed_ext:
            return f"{ext or '拡張子なし'} は受け付けません（{' '.join(self.allowed_ext)}）"
        if max_bytes is not None and len(data) > max_bytes:
            return f"大きすぎます（{human_size(len(data))}、上限 {human_size(max_bytes)}）"
        if not data:
            return "中身が空です"
        return check_content(name, data)

    def add_result(self, note: Note, name: str, data: bytes, source: str = "cli",
                   caption: str | None = None, max_bytes: int | None = None) -> Attachment:
        problem = self.check_file(name, data, max_bytes)
        if problem:
            raise LabnoteError(f"{Path(name).name}：{problem}")
        fname = safe_filename(name)
        try:                                    # ファイルを置く前に要約する（失敗したらファイルを残さない）
            summ = format_summary(fname, summarize_bytes(fname, data))
        except (csv.Error, ValueError, RecursionError) as e:
            raise LabnoteError(f"{fname}：中身を読めません（{type(e).__name__}）") from None
        summ = summ.replace("```", "'''")       # 値や列名の ``` でノートのコードブロックを閉じさせない
        if caption:
            caption = " ".join(caption.split())[:MAX_CAPTION].replace("```", "'''")
        with self._locked():
            return self._add_result_locked(note, fname, data, source, caption, summ)

    def _add_result_locked(self, note: Note, fname: str, data: bytes, source: str,
                           caption: str | None, summ: str) -> Attachment:
        folder = self.data_dir / f"{note.id:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / fname
        k = 2
        while target.exists():                  # 同じ名前は上書きせずに _2, _3 を付ける
            target = folder / f"{Path(fname).stem}_{k}{Path(fname).suffix}"
            k += 1
        target.write_bytes(data)
        if target.name != fname:
            summ = summ.replace(fname, target.name, 1)
        kind = Path(target.name).suffix.lower().lstrip(".")
        added = self.now().isoformat()
        rel = target.relative_to(self.home).as_posix()
        note_dir = (self.home / note.path).parent
        link = Path("../" * len(note_dir.relative_to(self.home).parts) + rel).as_posix()
        stamp = self.now().strftime("%H:%M")
        text = self.read_text(note)
        line = f"- [{target.name}]({link})（{stamp}、{source}、{human_size(len(data))}）"
        if caption:
            line += f" {caption}"
        text = append_to_section(text, SEC_FILES, line)
        res = f"- {stamp} `{target.name}`（{source} で追加。自動の要約）\n\n  ```text\n"
        res += "".join(f"  {ln}\n" for ln in summ.splitlines()) + "  ```"
        if kind == "png" or kind in ("jpg", "jpeg"):
            res += f"\n\n  ![{target.name}]({link})"
        text = append_to_section(text, SEC_RESULT, res)
        cur = self.con.execute(
            "INSERT INTO attachments(note_id, path, name, kind, size, sha256, added, source, summary) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (note.id, rel, target.name, kind, len(data), hashlib.sha256(data).hexdigest(), added, source, summ))
        self._write(note, text)
        return Attachment(cur.lastrowid, note.id, rel, target.name, kind, len(data), added, source, summ)

    # ---- まとめ・保守 ----
    def day_summary(self, date: str | None = None) -> str:
        date = date or self.today()
        rows = self.con.execute("SELECT * FROM notes WHERE date=? ORDER BY id", (date,)).fetchall()
        if not rows:
            return f"{date} のノートはまだありません"
        lines = [f"{date} のノート {len(rows)} 件"]
        for r in rows:
            atts = self.attachments(r["id"])
            sec = r["body"].split(f"## {SEC_LOG}", 1)
            nlog = sum(1 for ln in sec[1].split("\n## ", 1)[0].splitlines() if ln.startswith("- ")) \
                if len(sec) == 2 else 0
            lines.append(f"#{r['id']} [{r['chapter']}] {r['title']}：メモ {nlog} 件、ファイル {len(atts)} 個")
            for a in atts[-3:]:
                lines.append(f"    {a.summary.splitlines()[0]}")
        return "\n".join(lines)

    def reindex(self) -> tuple[int, int]:
        """notes/ と data/ から索引を作り直す（labnote.db を消してしまったとき、Git から戻したとき）。"""
        seen = set()
        n_notes = n_att = 0
        self.con.execute("BEGIN IMMEDIATE")
        try:
            for p in sorted(self.notes_dir.rglob("*.md")):
                rel_parts = p.relative_to(self.notes_dir).parts
                if p.name == "template.md" or rel_parts[0] == "examples":
                    continue
                text = p.read_text(encoding="utf-8")
                meta, _ = parse_front_matter(text)
                if not meta.get("id", "").isdigit():
                    continue
                nid = int(meta["id"])
                rel = p.relative_to(self.home).as_posix()
                created = meta.get("created", "")
                self.con.execute(
                    "INSERT INTO notes(id, path, date, chapter, title, created, updated, body) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path, "
                    "date=excluded.date, chapter=excluded.chapter, title=excluded.title, body=excluded.body",
                    (nid, rel, meta.get("date", ""), meta.get("chapter", DEFAULT_CHAPTER),
                     meta.get("title", p.stem), created, created, text))
                seen.add(nid)
                n_notes += 1
                folder = self.data_dir / f"{nid:04d}"
                if folder.is_dir():
                    for f in sorted(folder.iterdir()):
                        if not f.is_file():
                            continue
                        frel = f.relative_to(self.home).as_posix()
                        if self.con.execute("SELECT 1 FROM attachments WHERE path=?", (frel,)).fetchone():
                            n_att += 1
                            continue
                        data = f.read_bytes()
                        try:
                            summ = format_summary(f.name, summarize_bytes(f.name, data))
                        except Exception:
                            summ = f.name
                        self.con.execute(
                            "INSERT INTO attachments(note_id, path, name, kind, size, sha256, added, source, "
                            "summary) VALUES (?,?,?,?,?,?,?,?,?)",
                            (nid, frel, f.name, f.suffix.lower().lstrip("."), len(data),
                             hashlib.sha256(data).hexdigest(), self.now().isoformat(), "reindex", summ))
                        n_att += 1
            ids = [r[0] for r in self.con.execute("SELECT id FROM notes")]
            for nid in ids:
                if nid not in seen:
                    self.con.execute("DELETE FROM attachments WHERE note_id=?", (nid,))
                    self.con.execute("DELETE FROM notes WHERE id=?", (nid,))
            for r in self.con.execute("SELECT id, path FROM attachments").fetchall():
                if not (self.home / r["path"]).exists():
                    self.con.execute("DELETE FROM attachments WHERE id=?", (r["id"],))
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        return n_notes, n_att

    def backup(self, dest: str | Path) -> Path:
        """書き込み中でも一貫した SQLite の写しと、notes/・data/ の写しを dest に作る。"""
        dest = Path(dest).expanduser().resolve()
        if dest == self.home or self.home in dest.parents and dest.parts[len(self.home.parts)] in (
                "notes", "data"):
            raise LabnoteError("バックアップ先を notes/ や data/ の中にしないでください")
        dest.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(dest / "labnote.db")
        with out:
            self.con.backup(out)
        out.close()
        shutil.copytree(self.notes_dir, dest / "notes", dirs_exist_ok=True)
        shutil.copytree(self.data_dir, dest / "data", dirs_exist_ok=True)
        return dest
