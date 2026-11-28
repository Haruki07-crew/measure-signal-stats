"""同時に書き込んでも記録が失われないこと（別のプロセス・同時の bot のコマンド）。"""

import asyncio
import multiprocessing as mp

from labnote.config import Config
from labnote.handlers import Handlers, IncomingFile
from labnote.store import Library


def _today(home, k):
    lib = Library(home)
    for i in range(20):
        note = lib.today_note(True)
        lib.log(note, f"t{k}-{i}")
    lib.close()


def test_today_note_single_across_processes(tmp_path):
    home = tmp_path / "h"
    Library(home).close()
    ps = [mp.Process(target=_today, args=(home, k)) for k in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    assert all(p.exitcode == 0 for p in ps)
    lib = Library(home)
    notes = lib.list(limit=50)
    txt = lib.read_text(notes[0])
    lib.close()
    assert len(notes) == 1
    assert all(f"t{k}-{i}" in txt for k in range(4) for i in range(20))


def test_handlers_concurrent_tasks(tmp_path):
    cfg = Config(token="x", home=tmp_path / "h", guild_ids=frozenset({1}), channel_ids=frozenset({2}),
                 user_ids=frozenset({3}), max_bytes=10**6)
    lib = Library(cfg.home, allowed_ext=cfg.allowed_ext)
    h = Handlers(lib, cfg)

    def inc(i):
        async def read():
            return b"a\n%d\n" % i
        return IncomingFile(f"f{i}.csv", 4, read)

    async def main():
        tasks = [h.result_cmd(None, [inc(i)]) for i in range(30)]
        tasks += [h.ingest_webhook(None, 1, 2, "x", [])]
        return await asyncio.wait_for(asyncio.gather(*tasks), 20)

    asyncio.run(main())
    note = lib.today_note(False)
    assert len(lib.attachments(note.id)) == 30
    assert len(lib.list()) == 1
    lib.close()
