import json
import sqlite3
import time

import pytest

from conftest import SAMPLE_CSV
from labnote import send
from labnote.store import LabnoteError, Library

URL = "https://discord.com/api/webhooks/1/abc"


def make_lab_db(path, now):
    """第0章の pi_mqtt_logger.py と同じ形の messages。"""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, recv_unix REAL NOT NULL, "
                "topic TEXT NOT NULL, payload TEXT NOT NULL, dev TEXT, seq INTEGER)")
    for seq in (1, 2, 4, 5):                                       # seq 3 が欠けている
        d = {"dev": "pico1-leak", "seq": seq, "ticks_ms": seq * 10000, "v_l": 0.5 + seq / 100, "temp_c": 21.0}
        con.execute("INSERT INTO messages(recv_unix, topic, payload, dev, seq) VALUES (?,?,?,?,?)",
                    (now - 600 + seq * 10, "lab/pico1-leak/telemetry", json.dumps(d), d["dev"], seq))
    con.execute("INSERT INTO messages(recv_unix, topic, payload, dev, seq) VALUES (?,?,?,?,?)",
                (now - 7200, "lab/old/telemetry", "{}", "old", 1))      # 区間の外
    con.execute("INSERT INTO messages(recv_unix, topic, payload, dev, seq) VALUES (?,?,?,?,?)",
                (now - 60, "lab/bench", "not json", None, None))
    con.commit()
    con.close()


def test_mqtt_window(tmp_path):
    now = time.time()
    db = tmp_path / "lab.db"
    make_lab_db(db, now)
    text, csv_bytes = send.mqtt_window(db, 60, None, now=now)
    assert "6 件" not in text and "：5 件" in text
    assert "pico1-leak：4 件、seq の欠け 1（1〜5）" in text
    assert "v_l: 平均" in text and "ticks_ms" not in text
    assert csv_bytes.decode().splitlines()[0] == "recv_unix,topic,dev,seq,payload"
    only, _ = send.mqtt_window(db, 60, "pico1-leak", now=now)
    assert "：4 件" in only
    with pytest.raises(LabnoteError):
        send.mqtt_window(tmp_path / "none.db", 60, None)


def test_collect_pair(tmp_path):
    (tmp_path / "run_d500.csv").write_bytes(SAMPLE_CSV)
    (tmp_path / "run_d500.json").write_text('{"d1": 500}')
    got = send.collect_files([str(tmp_path / "run_d500.csv")], pair=True)
    assert [p.name for p in got] == ["run_d500.csv", "run_d500.json"]


def test_webhook_request_body():
    req = send.build_webhook_request(URL, "要約 @everyone", [("run.csv", SAMPLE_CSV)])
    body = req.data
    assert b'name="payload_json"' in body and b'filename="run.csv"' in body
    assert b'"parse": []' in body                                   # メンションを飛ばさない
    with pytest.raises(LabnoteError):
        send.build_webhook_request("https://discord.com/api/webhooks/your-webhook-id/your-webhook-token", "x", [])


def test_post_webhook_hides_url(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(send.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LabnoteError) as e:
        send.post_webhook(URL, "x", [])
    assert "abc" not in str(e.value) and "401" in str(e.value)


def test_post_webhook_ok(monkeypatch):
    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    seen = {}

    def fake_urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return R()
    monkeypatch.setattr(send.urllib.request, "urlopen", fake_urlopen)
    assert send.post_webhook(URL, "x", [("a.csv", b"a\n1\n")]) == 200
    assert seen["ua"].startswith("labnote-send")


def test_main_local_file_and_mqtt(tmp_path, capsys):
    home = tmp_path / "home"
    env = tmp_path / "t.env"
    env.write_text(f"LABNOTE_HOME={home}\n")
    (tmp_path / "run_d500.csv").write_bytes(SAMPLE_CSV)
    (tmp_path / "run_d500.json").write_text('{"d1": 500}')
    rc = send.main(["--env", str(env), "file", str(tmp_path / "run_d500.csv"), "--pair", "--to", "local",
                    "--chapter", "ch4", "--title", "RUN d500"])
    assert rc == 0
    now = time.time()
    make_lab_db(tmp_path / "lab.db", now)
    assert send.main(["--env", str(env), "mqtt", "--db", str(tmp_path / "lab.db"), "--to", "local",
                      "--note", "1"]) == 0
    lib = Library(home)
    names = [a.name for a in lib.attachments(1)]
    assert names[:2] == ["run_d500.csv", "run_d500.json"] and names[2].startswith("mqtt_")
    lib.close()
    assert send.main(["--env", str(env), "text", "--to", "webhook", "-m", "x"]) == 1   # URL 未設定
