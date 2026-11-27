"""labnote-bot：実験ノートの Discord bot（discord.py 2.7 系。版は pyproject.toml で固定）。

実行（labnote のフォルダで。.env にトークンと許可リスト）:
  uv run --extra bot labnote-bot
  uv run --extra bot labnote-bot --check     # 設定だけ確かめて終わる（Discord につながない）

スラッシュコマンド：/記録 /結果 /一覧 /見る /探す /今日（英語の表示の Discord では /log /result /list /show /search /today）
コマンドは許可リストのサーバー（LABNOTE_GUILD_IDS）にだけ登録する（すぐ反映され、ほかのサーバーには出ない）。
bot は Discord へ外向きにつなぐだけなので、受け口のポートは開けない（ufw・Azure の NSG に規則を足さない）。
"""

import argparse
import logging
import sys

from .config import Config, load_config
from .handlers import Handlers, dispatch, incoming_from_attachment
from .store import Library

log = logging.getLogger("labnote.bot")


def check_config(cfg: Config) -> list[str]:
    problems = []
    if not cfg.token or cfg.token.startswith("your-"):
        problems.append("DISCORD_TOKEN が見本の値のままか、空です")
    for name, ids in (("LABNOTE_GUILD_IDS", cfg.guild_ids), ("LABNOTE_CHANNEL_IDS", cfg.channel_ids),
                      ("LABNOTE_USER_IDS", cfg.user_ids)):
        if not ids:
            problems.append(f"{name} が空です（空だと誰にも答えません）")
    return problems


def english_names_class():
    """name_localizations（Discord の公式のローカライズ）に英語の名前を入れる discord.py の Translator。"""
    from discord import Locale, app_commands

    class EnglishNames(app_commands.Translator):
        async def translate(self, string, locale, context):
            if locale in (Locale.american_english, Locale.british_english):
                return string.extras.get("en")
            return None                              # ほかの言語の Discord には日本語の名前のまま出る

    return EnglishNames


def build_bot(cfg: Config, lib: Library):
    import discord
    from discord import app_commands

    EnglishNames = english_names_class()

    handlers = Handlers(lib, cfg)
    intents = discord.Intents.none()
    intents.guilds = True                       # スラッシュコマンドだけなら、これで足りる
    if cfg.ingest_webhook_ids:
        intents.guild_messages = True           # Webhook の取り込みを使うときだけ
        intents.message_content = True          # 特権 Intent（開発者ポータルでオンにする）

    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)
    loc = app_commands.locale_str

    def make_file(path):
        return discord.File(path, filename=path.name)

    # コマンド名・引数名は日本語（Discord の名前の決まり：1〜32文字、小文字のある文字は小文字。
    # 漢字・かなは大文字小文字がないので使える）。英語の表示の Discord には、下の EnglishNames で英語の名前を出す。
    @tree.command(name=loc("記録", en="log"), description=loc("短いメモを今日のノートに足す",
                                                             en="Add a short memo to today's note"))
    @app_commands.rename(text=loc("メモ", en="text"))
    @app_commands.describe(text="メモ（例：電池 5.42V、室温 21℃）")
    async def log_cmd(interaction: discord.Interaction, text: str):
        await dispatch(interaction, handlers, handlers.log_cmd, text)

    @tree.command(name=loc("結果", en="result"),
                  description=loc("CSV・PNG・JSON を保存してノートに追記（CSV は要約を返す）",
                                  en="Save CSV/PNG/JSON to a note (CSV is summarized)"))
    @app_commands.rename(file=loc("ファイル", en="file"), file2=loc("ファイル2", en="file2"),
                         note=loc("ノート番号", en="note"), caption=loc("説明", en="caption"))
    @app_commands.describe(file="添付するファイル", file2="2つ目（任意。motor_run.py の .csv と .json など）",
                           note="ノートの番号（省くと今日のノート）", caption="説明（任意）")
    async def result_cmd(interaction: discord.Interaction, file: discord.Attachment,
                         file2: discord.Attachment | None = None, note: int | None = None,
                         caption: str | None = None):
        files = [incoming_from_attachment(a) for a in (file, file2) if a is not None]
        await dispatch(interaction, handlers, handlers.result_cmd, files, note, caption)

    @tree.command(name=loc("一覧", en="list"), description=loc("最近のノート", en="Recent notes"))
    @app_commands.rename(n=loc("件数", en="count"), chapter=loc("章", en="chapter"))
    @app_commands.describe(n="件数（25まで）", chapter="章で絞る（例：ch4）")
    async def list_cmd(interaction: discord.Interaction, n: int = 10, chapter: str | None = None):
        await dispatch(interaction, handlers, handlers.list_cmd, n, chapter)

    @tree.command(name=loc("見る", en="show"), description=loc("ノートの中身と添付", en="Show a note"))
    @app_commands.rename(note_id=loc("番号", en="id"))
    @app_commands.describe(note_id="ノートの番号")
    async def show_cmd(interaction: discord.Interaction, note_id: int):
        await dispatch(interaction, handlers, handlers.show_cmd, note_id, make_file=make_file)

    @tree.command(name=loc("探す", en="search"),
                  description=loc("ノートを言葉で探す（空白で区切るとすべてを含むもの）", en="Search notes"))
    @app_commands.rename(words=loc("言葉", en="words"))
    @app_commands.describe(words="探す言葉")
    async def search_cmd(interaction: discord.Interaction, words: str):
        await dispatch(interaction, handlers, handlers.search_cmd, words)

    @tree.command(name=loc("今日", en="today"), description=loc("今日のまとめ", en="Today's summary"))
    async def today_cmd(interaction: discord.Interaction):
        await dispatch(interaction, handlers, handlers.today_cmd)

    @client.event
    async def setup_hook():
        await tree.set_translator(EnglishNames())
        for gid in cfg.guild_ids:
            guild = discord.Object(id=gid)
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            log.info("サーバー %s にコマンド %d 個を登録", gid, len(synced))

    @client.event
    async def on_ready():
        log.info("ログインしました：%s（サーバー %d 個に参加）", client.user, len(client.guilds))

    if cfg.ingest_webhook_ids:
        @client.event
        async def on_message(message: discord.Message):
            if message.webhook_id is None:
                return
            reply = await handlers.ingest_webhook(
                message.webhook_id, message.guild.id if message.guild else None, message.channel.id,
                message.content, [incoming_from_attachment(a) for a in message.attachments])
            if reply is not None:
                await message.reply(reply.text[:1900], mention_author=False)

    client.labnote_tree = tree                  # テストで登録したコマンドを確かめるため
    return client


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="labnote-bot")
    ap.add_argument("--env", help=".env のパス（既定は今のフォルダの .env）")
    ap.add_argument("--check", action="store_true", help="設定を確かめるだけ（つながない）")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.env)
    problems = check_config(cfg)
    for p in problems:
        log.error(p)
    log.info("置き場所：%s（許可：サーバー %d、チャンネル %d、ユーザー %d）", cfg.home,
             len(cfg.guild_ids), len(cfg.channel_ids), len(cfg.user_ids))
    if args.check:                              # 何も作らずに終わる
        return 1 if problems else 0
    if problems:
        return 2                                # 設定の誤りは再起動しても直らない（service の RestartPreventExitStatus=2）
    lib = Library(cfg.home, tz_name=cfg.tz_name, allowed_ext=cfg.allowed_ext)
    lib.init()
    client = build_bot(cfg, lib)
    try:
        client.run(cfg.token, log_handler=None)  # ログは上の basicConfig（journald に出る）
    finally:
        lib.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
