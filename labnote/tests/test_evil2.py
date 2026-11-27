import asyncio, multiprocessing as mp
from labnote.config import Config
from labnote.handlers import Handlers, IncomingFile
from labnote.store import Library

def _today(home, k):
    l = Library(home)
    for i in range(20):
        n = l.today_note(True); l.log(n, f"t{k}-{i}")
    l.close()

def test_today_note_single_across_processes(tmp_path):
    home = tmp_path / "h"; Library(home).close()
    ps = [mp.Process(target=_today, args=(home, k)) for k in range(4)]
    [p.start() for p in ps]; [p.join() for p in ps]
    assert all(p.exitcode == 0 for p in ps)
    l = Library(home); notes = l.list(limit=50); txt = l.read_text(notes[0]); l.close()
    assert len(notes) == 1 and all(f"t{k}-{i}" in txt for k in range(4) for i in range(20))

def test_handlers_concurrent_tasks(tmp_path):
    cfg = Config(token="x", home=tmp_path / "h", guild_ids=frozenset({1}), channel_ids=frozenset({2}),
                 user_ids=frozenset({3}), max_bytes=10**6)
    lib = Library(cfg.home, allowed_ext=cfg.allowed_ext)
    h = Handlers(lib, cfg)
    def inc(i):
        async def r(): return b"a\n%d\n" % i
        return IncomingFile(f"f{i}.csv", 4, r)
    async def main():
        tasks = [h.result_cmd(None, [inc(i)]) for i in range(30)]
        tasks += [h.ingest_webhook(None, 1, 2, "x", [])]
        return await asyncio.wait_for(asyncio.gather(*tasks), 20)
    rs = asyncio.run(main())
    n = lib.today_note(False)
    assert len(lib.attachments(n.id)) == 30 and len(lib.list()) == 1
    lib.close()
