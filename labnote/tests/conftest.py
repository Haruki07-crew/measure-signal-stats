import asyncio
import os

import pytest

from labnote.config import Config
from labnote.store import Library

GUILD, CHANNEL, USER = 111, 222, 333


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """手元の .env や LABNOTE_HOME を読まないように、環境変数を消して今のフォルダを tmp にする。"""
    for k in list(os.environ):
        if k.startswith("LABNOTE_") or k == "DISCORD_TOKEN":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def lib(home):
    lb = Library(home)
    lb.init()
    yield lb
    lb.close()


@pytest.fixture
def cfg(home):
    return Config(token="x", home=home, guild_ids=frozenset({GUILD}), channel_ids=frozenset({CHANNEL}),
                  user_ids=frozenset({USER}), max_bytes=1000)


def run(coro):
    return asyncio.run(coro)


SAMPLE_CSV = b"# motor_run.py \xe3\x81\xae\xe4\xbe\x8b\nduty,rpm,i_mA\n0,0,60\n500,180,62\n1000,250,65\n"
