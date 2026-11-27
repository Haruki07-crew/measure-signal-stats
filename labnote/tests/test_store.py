import sqlite3

import pytest

from conftest import SAMPLE_CSV
from labnote.store import LabnoteError, Library, append_to_section, parse_front_matter, safe_filename
from labnote.summary import PNG_MAGIC, summarize_csv_text


def tiny_png():
    return PNG_MAGIC + b"\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\0" * 9


def test_new_note_uses_template_and_front_matter(lib):
    n = lib.new_note("ch4", "スイープ 1回目", date="2026-11-27", purpose="デューティと回転数")
    assert n.id == 1 and n.path == "notes/2026/2026-11-27_ch4_0001.md"
    text = lib.read_text(n)
    meta, _ = parse_front_matter(text)
    assert meta["id"] == "1" and meta["chapter"] == "ch4" and meta["title"] == "スイープ 1回目"
    for sec in ("目的", "条件", "配線", "結果", "気づき", "次にやること", "データのファイル"):
        assert f"## {sec}" in text
    assert "デューティと回転数" in text.split("## 目的")[1].split("## ")[0]
    assert lib.new_note("ch4", "2つ目").id == 2


def test_bad_chapter_and_title(lib):
    with pytest.raises(LabnoteError):
        lib.new_note("../etc", "x")
    with pytest.raises(LabnoteError):
        lib.new_note("ch4", "   ")


def test_append_to_section_keeps_order():
    text = "# t\n\n## A\nx\n\n## B\ny\n"
    out = append_to_section(text, "A", "- new")
    assert out == "# t\n\n## A\nx\n- new\n\n## B\ny\n"
    out2 = append_to_section(out, "C", "- c")
    assert out2.endswith("## C\n- c\n")


def test_add_result_csv_png_json(lib):
    n = lib.new_note("ch4", "RUN")
    a = lib.add_result(n, "run_d500.csv", SAMPLE_CSV)
    assert a.path == "data/0001/run_d500.csv" and "3 行 × 3 列" in a.summary and "平均 143.3" in a.summary
    lib.add_result(n, "run_d500.json", b'{"d1": 500, "freq": 1000, "port": "/dev/cu.usbmodem1"}')
    p = lib.add_result(n, "plot.png", tiny_png())
    assert "640×480" in p.summary
    again = lib.add_result(n, "run_d500.csv", SAMPLE_CSV)       # 上書きしない
    assert again.path == "data/0001/run_d500_2.csv"
    text = lib.read_text(n)
    assert "[run_d500.csv](../../data/0001/run_d500.csv)" in text
    assert "![plot.png](../../data/0001/plot.png)" in text
    assert len(lib.attachments(n.id)) == 4


def test_add_result_rejects_bad_content(lib):
    n = lib.new_note("ch4", "RUN")
    with pytest.raises(LabnoteError, match="PNG"):
        lib.add_result(n, "fake.png", b"not a png")
    with pytest.raises(LabnoteError, match="JSON"):
        lib.add_result(n, "x.json", b"{broken")
    with pytest.raises(LabnoteError, match="大きすぎ"):
        lib.add_result(n, "x.csv", b"a\n" * 100, max_bytes=10)
    strict = Library(lib.home, allowed_ext=(".csv",))
    with pytest.raises(LabnoteError, match="受け付けません"):
        strict.add_result(n, "x.exe", b"MZ")
    strict.close()


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\x\\run 1.CSV") == "run_1.csv"
    assert safe_filename("電池.csv") == "file.csv"


def test_today_note_and_log(lib):
    n = lib.today_note()
    assert n.chapter == "misc"
    assert lib.today_note().id == n.id                         # 2回目は同じノート
    entry = lib.log(n, "電池 5.42V\n室温 21℃", author="me")
    assert entry.endswith("\n  室温 21℃") and "（me）" in entry
    assert "電池 5.42V" in lib.read_text(n).split("## メモ（時刻つき）")[1]
    assert "メモ 1 件" in lib.day_summary()


def test_search_list(lib):
    a = lib.new_note("ch4", "失速の確認")
    lib.log(a, "I,stall で止まった。糸が軸に巻き付いていた")
    lib.new_note("intro1", "Lチカ")
    assert [n.id for n, _ in lib.search("stall 糸")] == [a.id]
    assert lib.search("100%_") == []                            # % と _ は文字として探す
    assert [n.chapter for n in lib.list(chapter="intro1")] == ["intro1"]
    assert len(lib.list()) == 2


def test_reindex_rebuilds_from_markdown(lib, home):
    n = lib.new_note("ch4", "RUN")
    lib.add_result(n, "run.csv", SAMPLE_CSV)
    lib.close()
    for p in home.glob("labnote.db*"):
        p.unlink()
    lb = Library(home)
    assert lb.list() == []
    assert lb.reindex() == (1, 1)
    assert lb.get(1).title == "RUN" and lb.attachments(1)[0].name == "run.csv"
    assert lb.new_note("ch5", "次").id == 2
    lb.close()


def test_backup_is_consistent(lib, tmp_path):
    n = lib.new_note("ch4", "RUN")
    lib.add_result(n, "run.csv", SAMPLE_CSV)
    dest = lib.backup(tmp_path / "bk")
    con = sqlite3.connect(dest / "labnote.db")
    assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
    con.close()
    assert (dest / "data/0001/run.csv").read_bytes() == SAMPLE_CSV
    with pytest.raises(LabnoteError):
        lib.backup(lib.home / "notes" / "bk")


def test_csv_summary_skips_comments_and_text_columns():
    s = summarize_csv_text("# c\ncolor,R\nred,100\nblue,220\n")
    assert s["rows"] == 2 and list(s["stats"]) == ["R"]


def test_bundled_template_matches_notes_template():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert (root / "notes/template.md").read_text() == (root / "labnote/template.md").read_text()


def _today_worker(home, q):
    lb = Library(home)
    q.put(lb.today_note().id)
    lb.close()


def test_today_note_created_once_across_processes(tmp_path):
    import multiprocessing as mp

    home = tmp_path / "h"
    Library(home).close()
    q = mp.Queue()
    ps = [mp.Process(target=_today_worker, args=(home, q)) for _ in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    ids = {q.get() for _ in ps}
    lb = Library(home)
    assert ids == {1} and len(lb.list(limit=10)) == 1          # 同時に呼んでも今日のノートは1つ
    lb.close()
