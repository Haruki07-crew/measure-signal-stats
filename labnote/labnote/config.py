"""設定の読み込み（.env と環境変数）。python-dotenv を使わない小さな読み込み器。

環境変数がすでにあれば、そちらを優先する（systemd の EnvironmentFile や Azure の環境変数）。
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOME = "~/home-lab/labnote"
DEFAULT_EXT = (".csv", ".png", ".json", ".jpg", ".jpeg", ".txt")


def load_env_file(path: str | os.PathLike, environ: dict | None = None) -> dict:
    """KEY=VALUE の行を読む。# で始まる行と空行は無視。すでにある環境変数は上書きしない。"""
    env = os.environ if environ is None else environ
    p = Path(path).expanduser()
    loaded = {}
    if not p.is_file():
        return loaded
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        loaded[key] = value
        env.setdefault(key, value)
    return loaded


def _ids(text: str | None) -> frozenset[int]:
    out = set()
    for part in (text or "").replace(" ", "").split(","):
        if part:
            out.add(int(part))
    return frozenset(out)


def get_tz(name: str | None):
    """ZoneInfo が使えない環境（tzdata の無いコンテナ）では、Asia/Tokyo を UTC+9 の固定で代用する。"""
    name = name or "Asia/Tokyo"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        if name == "Asia/Tokyo":
            return _dt.timezone(_dt.timedelta(hours=9), "JST")
        return _dt.UTC


@dataclass(frozen=True)
class Config:
    token: str = ""
    home: Path = field(default_factory=lambda: Path(DEFAULT_HOME).expanduser())
    guild_ids: frozenset[int] = frozenset()
    channel_ids: frozenset[int] = frozenset()
    user_ids: frozenset[int] = frozenset()
    max_bytes: int = 8_000_000
    allowed_ext: tuple[str, ...] = DEFAULT_EXT
    tz_name: str = "Asia/Tokyo"
    webhook_url: str = ""
    ingest_webhook_ids: frozenset[int] = frozenset()

    @property
    def tz(self):
        return get_tz(self.tz_name)

    def is_allowed(self, guild_id: int | None, channel_id: int | None, user_id: int | None) -> bool:
        """サーバー・チャンネル・ユーザーの3つとも許可リストにあるときだけ True。DM（guild なし）は断る。"""
        if guild_id is None or channel_id is None or user_id is None:
            return False
        return (
            guild_id in self.guild_ids
            and channel_id in self.channel_ids
            and user_id in self.user_ids
        )


def load_config(env_file: str | None = None, environ: dict | None = None) -> Config:
    env = os.environ if environ is None else environ
    path = env_file or env.get("LABNOTE_ENV_FILE") or ".env"
    load_env_file(path, env)
    ext = tuple(
        e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
        for e in env.get("LABNOTE_ALLOWED_EXT", ",".join(DEFAULT_EXT)).split(",")
        if e.strip()
    )
    return Config(
        token=env.get("DISCORD_TOKEN", ""),
        home=Path(env.get("LABNOTE_HOME", DEFAULT_HOME)).expanduser(),
        guild_ids=_ids(env.get("LABNOTE_GUILD_IDS")),
        channel_ids=_ids(env.get("LABNOTE_CHANNEL_IDS")),
        user_ids=_ids(env.get("LABNOTE_USER_IDS")),
        max_bytes=int(env.get("LABNOTE_MAX_BYTES", "8000000")),
        allowed_ext=ext,
        tz_name=env.get("LABNOTE_TZ", "Asia/Tokyo"),
        webhook_url=env.get("LABNOTE_WEBHOOK_URL", ""),
        ingest_webhook_ids=_ids(env.get("LABNOTE_INGEST_WEBHOOK_IDS")),
    )
