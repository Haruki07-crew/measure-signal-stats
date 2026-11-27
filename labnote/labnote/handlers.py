"""bot のコマンドの処理（discord を import しない部分）。

bot.py は Discord の interaction から Request と IncomingFile を作って、ここを呼ぶだけにしている。
そのため、Discord につながなくても、偽の interaction で試せる（tests/test_handlers.py）。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .store import LabnoteError, Library

log = logging.getLogger("labnote.bot")

DISCORD_LIMIT = 2000            # 1通の文字数の上限（公式ドキュメントで要確認）
MAX_FILES_SHOWN = 4             # /show で一緒に返す添付の数
NOTE_REF_RE = re.compile(r"\bnote[:=]\s*(\d+)\b", re.IGNORECASE)


@dataclass
class Request:
    guild_id: int | None
    channel_id: int | None
    user_id: int | None
    user_name: str = ""


@dataclass
class IncomingFile:
    filename: str
    size: int
    read: Callable[[], Awaitable[bytes]]
    content_type: str | None = None


@dataclass
class Reply:
    text: str
    files: list[Path] = field(default_factory=list)
    ephemeral: bool = False


def clip(text: str, limit: int = DISCORD_LIMIT - 50) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（長いので切りました。全文は添付の .md か labnote show で）"


def code_block(text: str) -> str:
    return "```\n" + text.replace("```", "'''") + "\n```"


class Handlers:
    def __init__(self, lib: Library, cfg: Config):
        self.lib = lib
        self.cfg = cfg
        # SQLite とファイルの読み書きは同期の処理なので、event loop を止めないようにスレッドで動かす。
        # 接続は1つなので、このロックで1本ずつ順に通す（ほかのプロセスとの取り合いは store の書き込みロック）
        self._lock = threading.RLock()

    def run_locked(self, fn: Callable, *args, **kwargs):
        with self._lock:
            return fn(*args, **kwargs)

    async def _call(self, fn: Callable, *args, **kwargs):
        return await asyncio.to_thread(self.run_locked, fn, *args, **kwargs)

    # ---- 権限 ----
    def authorize(self, req: Request) -> Reply | None:
        if self.cfg.is_allowed(req.guild_id, req.channel_id, req.user_id):
            return None
        log.warning("断った: guild=%s channel=%s user=%s", req.guild_id, req.channel_id, req.user_id)
        return Reply("このサーバー・チャンネル・ユーザーでは使えません（.env の許可リスト）", ephemeral=True)

    # ---- コマンド ----
    def log_cmd(self, req: Request, text: str) -> Reply:
        note = self.lib.today_note(create=True)
        entry = self.lib.log(note, text, author=req.user_name or None)
        return Reply(f"#{note.id}「{note.title}」に追記しました\n{entry}")

    async def result_cmd(self, req: Request, files: list[IncomingFile], note_ref: int | None = None,
                         caption: str | None = None) -> Reply:
        files = [f for f in files if f is not None]
        if not files:
            raise LabnoteError("ファイルを添付してください")
        note = await self._call(self.lib.get, note_ref) if note_ref else await self._call(self.lib.today_note, True)
        lines = [f"#{note.id}「{note.title}」に保存しました"]
        for f in files:
            # 読み込む前に、大きさと拡張子で断る（大きなファイルをメモリに読まない）
            ext = Path(f.filename).suffix.lower()
            if ext not in self.cfg.allowed_ext:
                lines.append(f"✗ {f.filename}：{ext or '拡張子なし'} は受け付けません")
                continue
            if f.size > self.cfg.max_bytes:
                lines.append(f"✗ {f.filename}：大きすぎます（上限 {self.cfg.max_bytes} バイト）")
                continue
            data = await f.read()
            try:
                att = await self._call(self.lib.add_result, note, f.filename, data, source="discord",
                                       caption=caption, max_bytes=self.cfg.max_bytes)
            except LabnoteError as e:
                lines.append(f"✗ {e}")
                continue
            lines.append(code_block(att.summary))
        return Reply("\n".join(lines))

    def list_cmd(self, req: Request, n: int = 10, chapter: str | None = None) -> Reply:
        notes = self.lib.list(limit=max(1, min(n, 25)), chapter=chapter or None)
        if not notes:
            return Reply("ノートはまだありません")
        rows = [f"#{x.id:<4} {x.date} {x.chapter:<8} {x.title}" for x in notes]
        return Reply(code_block("\n".join(rows)))

    def show_cmd(self, req: Request, note_id: int) -> Reply:
        note = self.lib.get(note_id)
        text = self.lib.read_text(note)
        files = [self.lib.home / note.path]
        total = files[0].stat().st_size
        for a in reversed(self.lib.attachments(note.id)):
            p = self.lib.home / a.path
            if len(files) > MAX_FILES_SHOWN or not p.exists():
                break
            if total + a.size > self.cfg.max_bytes:
                continue
            files.append(p)
            total += a.size
        return Reply(clip(f"#{note.id} {note.date} [{note.chapter}] {note.title}\n" + code_block(text)),
                     files=files)

    def search_cmd(self, req: Request, words: str) -> Reply:
        hits = self.lib.search(words, limit=10)
        if not hits:
            return Reply(f"「{words}」は見つかりませんでした")
        rows = [f"#{n.id:<4} {n.date} {n.chapter:<8} {n.title}\n      …{s}…" for n, s in hits]
        return Reply(code_block("\n".join(rows)))

    def today_cmd(self, req: Request) -> Reply:
        return Reply(code_block(self.lib.day_summary()))

    # ---- Webhook で届いたメッセージの取り込み（任意） ----
    async def ingest_webhook(self, webhook_id: int | None, guild_id: int | None, channel_id: int | None,
                             content: str, files: list[IncomingFile]) -> Reply | None:
        if webhook_id is None or webhook_id not in self.cfg.ingest_webhook_ids:
            return None
        if guild_id not in self.cfg.guild_ids or channel_id not in self.cfg.channel_ids:
            return None
        m = NOTE_REF_RE.search(content or "")
        note_ref = int(m.group(1)) if m else None
        req = Request(guild_id, channel_id, None, "webhook")
        if files:
            caption = (content or "").splitlines()[0][:100] if content else None
            r = await self.result_cmd(req, files, note_ref=note_ref, caption=caption)
            return r
        if content and content.strip():
            note = await self._call(self.lib.get, note_ref) if note_ref else await self._call(self.lib.today_note, True)
            await self._call(self.lib.log, note, content.strip()[:1500], author="webhook")
            return Reply(f"#{note.id} に追記しました")
        return None


def request_from_interaction(interaction) -> Request:
    user = getattr(interaction, "user", None)
    return Request(
        guild_id=getattr(interaction, "guild_id", None),
        channel_id=getattr(interaction, "channel_id", None),
        user_id=getattr(user, "id", None),
        user_name=getattr(user, "display_name", "") or getattr(user, "name", "") or "",
    )


def incoming_from_attachment(att) -> IncomingFile:
    return IncomingFile(filename=att.filename, size=att.size, read=att.read,
                        content_type=getattr(att, "content_type", None))


async def dispatch(interaction, handlers: Handlers, action: Callable, *args,
                   make_file: Callable[[Path], object] | None = None, **kwargs) -> Reply:
    """interaction を受けて、権限を確かめ、処理を呼び、返事を送る（bot.py の各コマンドの共通部分）。"""
    req = request_from_interaction(interaction)
    denied = handlers.authorize(req)
    if denied is not None:
        await interaction.response.send_message(denied.text, ephemeral=True)
        return denied
    await interaction.response.defer(thinking=True)     # 3秒以内に返事をしないと失敗になるため先に「考え中」
    try:
        if inspect.iscoroutinefunction(action):
            reply = await action(req, *args, **kwargs)      # 中で lib を呼ぶところは _call でスレッドに逃がす
        else:
            reply = await asyncio.to_thread(handlers.run_locked, action, req, *args, **kwargs)
    except LabnoteError as e:
        reply = Reply(f"エラー：{e}")
    except Exception:
        log.exception("コマンドの処理で失敗")
        reply = Reply("内部のエラーです（Pi なら journalctl -u labnote-bot で確かめる）")
    send_kwargs = {"content": clip(reply.text)}
    if reply.files and make_file is not None:
        send_kwargs["files"] = [make_file(p) for p in reply.files]
    await interaction.followup.send(**send_kwargs)
    return reply
