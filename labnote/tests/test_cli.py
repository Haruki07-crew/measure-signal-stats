from conftest import SAMPLE_CSV
from labnote.cli import main


def cli(home, *args):
    return main(["--home", str(home), "--env", str(home.parent / "no.env"), *args])


def test_cli_flow(home, tmp_path, capsys):
    assert cli(home, "init") == 0
    assert (home / "notes/template.md").is_file()
    assert cli(home, "new", "--chapter", "ch4", "--title", "スイープ", "--purpose", "傾きを見る") == 0
    f = tmp_path / "sweep_1.csv"
    f.write_bytes(SAMPLE_CSV)
    assert cli(home, "add-result", "1", str(f)) == 0
    assert cli(home, "log", "today", "電池", "5.42V") == 0
    capsys.readouterr()
    assert cli(home, "list") == 0
    assert "スイープ" in capsys.readouterr().out
    assert cli(home, "show", "1") == 0
    out = capsys.readouterr().out
    assert "sweep_1.csv" in out and "電池 5.42V" in out
    assert cli(home, "search", "5.42V") == 0
    assert "#1" in capsys.readouterr().out
    assert cli(home, "today") == 0
    assert "ファイル 1 個" in capsys.readouterr().out
    assert cli(home, "reindex") == 0
    assert cli(home, "backup", str(tmp_path / "bk")) == 0
    assert (tmp_path / "bk/labnote.db").is_file()


def test_cli_errors(home, capsys):
    assert cli(home, "show", "99") == 1
    assert "ノート 99 はありません" in capsys.readouterr().err
    assert cli(home, "add-result", "today", str(home / "nothing.csv")) == 1


def test_cli_show_by_path(home, capsys):
    cli(home, "new", "--chapter", "intro1", "--title", "Lチカ", "--date", "2026-11-01")
    capsys.readouterr()
    assert cli(home, "show", "notes/2026/2026-11-01_intro1_0001.md") == 0
    assert "Lチカ" in capsys.readouterr().out


def test_home_from_env_file(tmp_path, capsys):
    env = tmp_path / "x.env"
    env.write_text(f"LABNOTE_HOME={tmp_path / 'h2'}\n# comment\n")
    assert main(["--env", str(env), "init"]) == 0
    assert (tmp_path / "h2/notes/template.md").is_file()
