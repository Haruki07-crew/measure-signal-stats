"""bot のコマンドを、Discord につながずに偽の interaction で試す。"""

import pytest

from conftest import CHANNEL, GUILD, SAMPLE_CSV, USER, run
from labnote.handlers import Handlers, IncomingFile, dispatch
from labnote.store import Library


class FakeResponse:
    def __init__(self):
        self.messages, self.deferred = [], False

    async def send_message(self, content, ephemeral=False):
        self.messages.append((content, ephemeral))

    async def defer(self, thinking=False):
        self.deferred = True


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, files=None):
        self.sent.append((content, files))


class FakeUser:
    def __init__(self, uid, name="tester"):
        self.id, self.display_name = uid, name


class FakeInteraction:
    def __init__(self, guild=GUILD, channel=CHANNEL, user=USER):
        self.guild_id, self.channel_id, self.user = guild, channel, FakeUser(user)
        self.response, self.followup = FakeResponse(), FakeFollowup()


class FakeAttachment:
    def __init__(self, filename, data, size=None):
        self.filename, self._data = filename, data
        self.size = len(data) if size is None else size
        self.content_type = None
        self.reads = 0

    async def read(self):
        self.reads += 1
        return self._data


def att(name, data, size=None):
    a = FakeAttachment(name, data, size)
    return a, IncomingFile(a.filename, a.size, a.read)


@pytest.fixture
def h(cfg):
    lb = Library(cfg.home, allowed_ext=cfg.allowed_ext)
    yield Handlers(lb, cfg)
    lb.close()


def test_denied_outside_allowlist(h):
    for kw in ({"guild": 999}, {"channel": 999}, {"user": 999}, {"guild": None}):
        it = FakeInteraction(**kw)
        r = run(dispatch(it, h, h.log_cmd, "x"))
        assert r.ephemeral and it.response.messages[0][1] is True
        assert not it.response.deferred and it.followup.sent == []
    assert h.lib.list() == []                                   # 何も書いていない


def test_log_goes_to_today_note(h):
    it = FakeInteraction()
    run(dispatch(it, h, h.log_cmd, "電池 5.42V"))
    assert it.response.deferred
    content, files = it.followup.sent[0]
    assert "追記しました" in content and files is None
    note = h.lib.today_note(create=False)
    assert "電池 5.42V（tester）" in h.lib.read_text(note)


def test_result_csv_summary_and_limits(h):
    a1, f1 = att("run_d500.csv", SAMPLE_CSV)
    a2, f2 = att("big.csv", b"x", size=10_000)                  # 上限 1000 バイトを超える
    a3, f3 = att("evil.exe", b"MZ")
    it = FakeInteraction()
    run(dispatch(it, h, h.result_cmd, [f1, f2, f3], None, "1回目"))
    content = it.followup.sent[0][0]
    assert "3 行 × 3 列" in content and "rpm: 平均 143.3" in content
    assert "big.csv：大きすぎます" in content and "受け付けません" in content
    assert a2.reads == 0 and a3.reads == 0                      # 断ったものは読み込まない
    note = h.lib.today_note(create=False)
    assert [x.name for x in h.lib.attachments(note.id)] == ["run_d500.csv"]


def test_result_into_given_note_and_bad_png(h):
    n = h.lib.new_note("ch4", "スイープ")
    _, f = att("fig.png", b"not png")
    it = FakeInteraction()
    run(dispatch(it, h, h.result_cmd, [f], n.id, None))
    assert "PNG の形式ではありません" in it.followup.sent[0][0]
    it2 = FakeInteraction()
    run(dispatch(it2, h, h.result_cmd, [f], 99, None))
    assert it2.followup.sent[0][0].startswith("エラー：ノート 99")


def test_list_show_search_today(h, cfg):
    import dataclasses
    h.cfg = dataclasses.replace(cfg, max_bytes=100_000)
    n = h.lib.new_note("ch4", "失速の確認", date="2026-11-27")
    h.lib.log(n, "I,stall で止まった")
    h.lib.add_result(n, "run.csv", SAMPLE_CSV)
    it = FakeInteraction()
    run(dispatch(it, h, h.list_cmd, 5, None))
    assert "失速の確認" in it.followup.sent[0][0]

    it = FakeInteraction()
    run(dispatch(it, h, h.show_cmd, n.id, make_file=lambda p: p.name))
    content, files = it.followup.sent[0]
    assert "I,stall" in content and len(content) < 2000
    assert files == ["2026-11-27_ch4_0001.md", "run.csv"]

    it = FakeInteraction()
    run(dispatch(it, h, h.search_cmd, "stall"))
    assert "#1" in it.followup.sent[0][0]
    it = FakeInteraction()
    run(dispatch(it, h, h.search_cmd, "見つからない言葉"))
    assert "見つかりませんでした" in it.followup.sent[0][0]

    it = FakeInteraction()
    run(dispatch(it, h, h.today_cmd))
    assert "のノート" in it.followup.sent[0][0]


def test_long_note_is_clipped(h):
    n = h.lib.new_note("ch4", "長い")
    for i in range(40):
        h.lib.log(n, "とても長いメモ" * 10 + str(i))
    it = FakeInteraction()
    run(dispatch(it, h, h.show_cmd, n.id))
    assert len(it.followup.sent[0][0]) <= 2000 and "切りました" in it.followup.sent[0][0]


def test_internal_error_is_hidden(h):
    def boom(req):
        raise RuntimeError("secret path /etc/labnote")
    it = FakeInteraction()
    run(dispatch(it, h, boom))
    assert "内部のエラー" in it.followup.sent[0][0] and "secret" not in it.followup.sent[0][0]


def test_ingest_webhook(h, cfg):
    import dataclasses
    h.cfg = dataclasses.replace(cfg, ingest_webhook_ids=frozenset({555}))
    n = h.lib.new_note("ch4", "RUN")
    _, f = att("run.csv", SAMPLE_CSV)
    assert run(h.ingest_webhook(None, GUILD, CHANNEL, "x", [f])) is None           # 人のメッセージ
    assert run(h.ingest_webhook(777, GUILD, CHANNEL, "x", [f])) is None            # 知らない Webhook
    assert run(h.ingest_webhook(555, 999, CHANNEL, "x", [f])) is None              # 別のサーバー
    r = run(h.ingest_webhook(555, GUILD, CHANNEL, f"note:{n.id} motor_run", [f]))
    assert "保存しました" in r.text and h.lib.attachments(n.id)[0].source == "discord"
    r = run(h.ingest_webhook(555, GUILD, CHANNEL, "MQTT の要約だけ", []))
    assert "追記しました" in r.text


def test_build_bot_registers_commands(cfg, home):
    pytest.importorskip("discord")
    from labnote.bot import build_bot, check_config

    lb = Library(home)
    client = build_bot(cfg, lb)
    cmds = {c.name: c for c in client.labnote_tree.get_commands()}
    assert set(cmds) == {"記録", "結果", "一覧", "見る", "探す", "今日"}
    assert [p.display_name for p in cmds["結果"].parameters] == ["ファイル", "ファイル2", "ノート番号", "説明"]
    assert client.intents.message_content is False                # 既定では特権 Intent を使わない
    assert check_config(cfg) == []
    lb.close()


def test_english_names_translator(cfg, home):
    discord = pytest.importorskip("discord")
    from discord import app_commands

    from labnote.bot import build_bot, english_names_class

    lb = Library(home)
    client = build_bot(cfg, lb)
    tree = client.labnote_tree

    async def payload():
        await tree.set_translator(english_names_class()())
        return [await c.get_translated_payload(tree, tree.translator) for c in tree.get_commands()]
    got = {p["name"]: p for p in run(payload())}
    assert got["記録"]["name_localizations"]["en-US"] == "log"
    assert got["結果"]["options"][0]["name"] == "ファイル"
    assert got["結果"]["options"][0]["name_localizations"]["en-US"] == "file"
    assert "ja" not in got["記録"]["name_localizations"]
    for name in got:
        app_commands.commands.validate_name(name)            # discord.py の名前の検査を通る
    lb.close()
    assert discord.Locale.japanese.value == "ja"


def test_sync_work_runs_off_the_event_loop_thread(h):
    import threading

    seen = {}

    def probe(req):
        seen["thread"] = threading.get_ident()
        return h.list_cmd(req)

    async def go():
        seen["loop"] = threading.get_ident()
        await dispatch(FakeInteraction(), h, probe)
    run(go())
    assert seen["thread"] != seen["loop"]                     # SQLite の処理は別のスレッドで動く
