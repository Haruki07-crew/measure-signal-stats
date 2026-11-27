"""意地悪なテスト：パスの細工・巨大な値・SQL や Markdown の細工・並行の書き込み・Webhook の URL の検査。"""

import asyncio
import multiprocessing as mp

import pytest

from labnote.config import Config, load_config
from labnote.handlers import Handlers, IncomingFile, dispatch
from labnote.store import LabnoteError, Library

G, C, U = 111, 222, 333


def cfg(home, **kw):
    return Config(
        token="x",
        home=home,
        guild_ids=frozenset({G}),
        channel_ids=frozenset({C}),
        user_ids=frozenset({U}),
        max_bytes=kw.get("max_bytes", 10_000_000),
    )


def inc(name, data):
    async def r():
        return data

    return IncomingFile(name, len(data), r)


@pytest.fixture
def h(tmp_path):
    c = cfg(tmp_path / "home")
    lb = Library(c.home, allowed_ext=c.allowed_ext)
    lb.init()
    yield Handlers(lb, c)
    lb.close()


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd.csv",
        "..\\..\\x.csv",
        "/abs/evil.csv",
        "....csv",
        "..csv",
        "a/../../b.csv",
        "\x00.csv",
        "ｆｕｌｌ.csv",
        ".csv",
        "..",
        "con.csv",
        "x.CSV",
    ],
)
def test_traversal(h, name):
    n = h.lib.today_note()
    try:
        a = h.lib.add_result(n, name, b"a,b\n1,2\n")
    except LabnoteError as e:
        print("rejected", name, e)
        return
    p = (h.lib.home / a.path).resolve()
    assert h.lib.data_dir.resolve() in p.parents, (name, p)
    print(repr(name), "->", a.path)


def test_same_name_not_overwritten(h):
    n = h.lib.today_note()
    a1 = h.lib.add_result(n, "x.csv", b"a\n1\n")
    a2 = h.lib.add_result(n, "x.csv", b"a\n2\n")
    a3 = h.lib.add_result(n, "x_2.csv", b"a\n3\n")
    assert len({a1.path, a2.path, a3.path}) == 3


def test_huge_csv_field(h):
    n = h.lib.today_note()
    data = b"a,b\n" + b"1," + b"9" * 200_000 + b"\n"
    try:
        h.lib.add_result(n, "big.csv", data)
    except LabnoteError as e:
        print("LabnoteError", e)
    # 失敗したのに data/ にファイルが残っていないか
    left = list((h.lib.data_dir).rglob("big*"))
    rows = h.lib.attachments(n.id)
    assert not (left and not rows), f"orphan file {left}"


def test_huge_csv_field_via_bot(h):
    it = FakeIt()
    data = b"a\n" + b"9" * 200_000 + b"\n"
    r = asyncio.run(dispatch(it, h, h.result_cmd, [inc("big.csv", data)]))
    print(r.text)
    assert "内部のエラー" not in r.text


def test_nul_and_bad_encoding(h):
    n = h.lib.today_note()
    with pytest.raises(LabnoteError):
        h.lib.add_result(n, "bad.csv", b"\xff\xfe\x00a")
    try:
        h.lib.add_result(n, "nul.csv", b"a,b\n1,\x002\n")
    except LabnoteError as e:
        print(e)


def test_deep_json(h):
    n = h.lib.today_note()
    with pytest.raises(LabnoteError):
        h.lib.add_result(n, "deep.json", b"[" * 100000 + b"]" * 100000)


class R:
    def __init__(s):
        s.m = []
        s.d = False

    async def send_message(s, c, ephemeral=False):
        s.m.append(c)

    async def defer(s, thinking=False):
        s.d = True


class F:
    def __init__(s):
        s.sent = []

    async def send(s, content=None, files=None):
        s.sent.append(content)


class Usr:
    def __init__(s, i):
        s.id = i
        s.display_name = "u"


class FakeIt:
    def __init__(s, g=G, c=C, u=U):
        s.guild_id, s.channel_id, s.user = g, c, Usr(u)
        s.response, s.followup = R(), F()


@pytest.mark.parametrize("g,c,u", [(G, 999, U), (None, C, U), (G, C, None), (str(G), C, U), (G, C, str(U)), (C, G, U), (G, U, C)])
def test_not_allowed(h, g, c, u):
    it = FakeIt(g, c, u)
    asyncio.run(dispatch(it, h, h.log_cmd, "x"))
    assert not it.response.d and h.lib.list() == []


def test_ids_parse(tmp_path):
    c = load_config(str(tmp_path / "none"), {"LABNOTE_USER_IDS": " 1, 2 ,", "LABNOTE_GUILD_IDS": "", "LABNOTE_CHANNEL_IDS": ""})
    assert c.user_ids == {1, 2} and not c.is_allowed(None, None, 1)


@pytest.mark.parametrize("q", ["'; DROP TABLE notes;--", "%", "_", "\\", "100%", "a_b", '" OR 1=1 --', "'"])
def test_search_special(h, q):
    h.lib.new_note("ch1", "100% a_b test")
    hits = h.lib.search(q)
    assert h.lib.list()  # table still there
    if q in ("%", "_", "\\"):
        # % と _ はワイルドカードとして扱わない
        assert all(q in n.title or q in h.lib.read_text(n) for n, _ in hits), q


def test_search_many_words(h):
    h.lib.new_note("ch1", "x")
    try:
        h.lib.search(" ".join(["a"] * 2000))
    except LabnoteError:
        pass


def test_markdown_section_forgery(h):
    n = h.lib.today_note()
    h.lib.log(n, "x\n## データのファイル\n## 結果")
    h.lib.add_result(n, "a.csv", b"a\n1\n")
    text = h.lib.read_text(n)
    memo = text.split("## メモ（時刻つき）\n", 1)[1].split("\n## ", 1)[0]
    assert "a.csv](" not in memo, text


def test_code_fence_break(h):
    n = h.lib.today_note()
    h.lib.add_result(
        n, "a.json", b'{"k": "```\\n<img src=x onerror=alert(1)>\\n## \\u30e1\\u30e2\\uff08\\u6642\\u523b\\u3064\\u304d\\uff09"}'
    )
    h.lib.log(n, "after")
    text = h.lib.read_text(n)
    res = text.split("## 結果\n", 1)[1].split("\n## ", 1)[0]
    assert "after" not in res, text
    assert "```\n<img" not in text.replace("  ```text", "")


def _writer(home, k, q):
    lib = Library(home)
    n = lib.get(1)
    for i in range(40):
        lib.log(n, f"p{k}-{i}")
    lib.close()
    q.put(k)


def test_concurrent_log_lost_update(tmp_path):
    home = tmp_path / "h"
    lib = Library(home)
    lib.init()
    lib.new_note("ch1", "t")
    lib.close()
    q = mp.Queue()
    ps = [mp.Process(target=_writer, args=(home, k, q)) for k in range(3)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    lib = Library(home)
    text = lib.read_text(lib.get(1))
    got = sum(1 for k in range(3) for i in range(40) if f"p{k}-{i}（" in text or f"p{k}-{i}\n" in text)
    lib.close()
    assert got == 120, f"lost {120 - got} of 120"


def test_concurrent_new_note(tmp_path):
    home = tmp_path / "h"
    Library(home).close()
    ps = [mp.Process(target=_mk, args=(home, k)) for k in range(3)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    lb = Library(home)
    assert len(lb.list(limit=100)) == 45
    lb.close()
    assert all(p.exitcode == 0 for p in ps)


def _mk(home, k):
    lb = Library(home)
    for i in range(15):
        lb.new_note("ch1", f"n{k}{i}")
    lb.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com/api/webhooks/1/a b",
        "https://evil.example/api/webhooks/1/abc",
        "https://discord.com.evil.example/api/webhooks/1/abc",
        "http://discord.com/api/webhooks/1/abc",
    ],
)
def test_webhook_url_rejected(url):
    from labnote import send

    with pytest.raises(LabnoteError) as ei:
        send.post_webhook(url, "x", [])
    assert "abc" not in str(ei.value) and "a b" not in str(ei.value)


def test_multipart_filename_quote():
    from labnote import send

    req = send.build_webhook_request("https://discord.com/api/webhooks/1/abc", "x", [('a"\r\nX: y.csv', b"1")])
    assert b"\r\nX: y" not in req.data
