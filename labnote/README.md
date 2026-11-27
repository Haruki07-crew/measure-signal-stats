# labnote：実験ノートと Discord bot

教科書（電子計測 × 信号処理 × 統計の実験）を進めながら、**毎回の実験のメモと記録を残す**ための小さな道具です。

- **ノートは Markdown のファイル**（`notes/<年>/<日付>_<章>_<番号>.md`）。テキストなので Git で管理でき、どのエディタでも読めます。
- **データは `data/<番号>/`** に置き、ノートに自動で追記します（CSV は行数・列・平均・SD・最小・最大の要約つき）。
- **索引は SQLite**（`labnote.db`）。一覧・検索に使います。ノートとデータから `labnote reindex` で作り直せます。
- **CLI**（`labnote`）と **Discord bot**（`labnote-bot`）が、同じ置き場所を読み書きします。Mac で書いたノートを Discord から見る、Discord から送った図を Mac で見る、ができます。
- **labnote-send**：第4章の `motor_run.py` の CSV・JSON や、第0章の MQTT の記録（Pi の `lab.db`）を、Discord の Webhook か手元の labnote に送ります。

CLI は Python の標準ライブラリだけで動きます。bot を使うときだけ discord.py（版は `pyproject.toml` で `==` に固定、`uv.lock` に記録）を入れます。
コードは MIT License です（[LICENSE](LICENSE)）。

## すぐ試す

### 1. Mac で CLI だけ（5分）

教科書の第0章で入れた uv を使います。このフォルダ（`labnote/`）で：

```bash
uv sync --locked                    # 標準ライブラリだけなので、すぐ終わる
uv run labnote init                 # 置き場所 ~/home-lab/labnote を作る（--home で変えられる）
uv run labnote new --chapter ch4 --title "スイープ 1回目" --purpose "デューティと回転数の関係を見る"
uv run labnote log today "電池 5.42V、室温 21℃"
uv run labnote add-result today ~/home-lab/ch4/data/sweep_1.csv ~/home-lab/ch4/data/sweep_1.json
uv run labnote list
uv run labnote show 1
uv run labnote search 電池
uv run labnote today
```

ノートの指定は、番号（`1`）・ファイルのパス・`today`（今日のいちばん新しいノート。無ければ「今日のメモ」を作る）のどれでもかまいません。
置き場所は `--home`、または `.env` の `LABNOTE_HOME` で変えられます（`cp .env.example .env`）。
ノートは、できたファイルをエディタで開いて直接書き足してかまいません（そのあと `labnote reindex` で検索に反映）。

ひな形は [notes/template.md](notes/template.md)（日付・章・目的・条件・配線・結果・気づき・次にやること・メモ・データのファイル）です。
置き場所の `notes/template.md` を書き換えると、次から作るノートに効きます。
書き方の例は [notes/examples/](notes/examples/)（教科書の「期待される結果の例と、うまくいかないとき」の表と見比べる書き方）にあります。

### 2. Discord の bot

[docs/discord_setup.md](docs/discord_setup.md) の手順で bot を作り、`.env` にトークンと許可リスト（サーバー・チャンネル・ユーザーの ID）を書いて：

```bash
uv sync --locked --extra bot
uv run --extra bot labnote-bot --check        # 設定だけ確かめる
uv run --extra bot labnote-bot
```

スラッシュコマンドは `/記録`（今日のノートにメモ）・`/結果`（CSV・PNG・JSON を保存して追記。CSV は要約を返す）・`/一覧`・`/見る`・`/探す`・`/今日` です。
Discord を英語の表示にしている人には `/log` `/result` `/list` `/show` `/search` `/today` と出ます。

### 3. Raspberry Pi で常に動かす

教科書 II-1 の Pi（`labpi`、Lite 版）に、専用ユーザー・systemd のサービス（`labnote-bot.service`、`Restart=on-failure`）で入れます。
bot は外向きにつなぐだけなので、ufw の受け口は開けません。→ [docs/pi.md](docs/pi.md)

### 4. Azure で動かす

小さな Linux の VM に、Pi と同じ手順で入れます。止め忘れの費用と、消し方も書いてあります。→ [docs/azure.md](docs/azure.md)

安全のこと（トークンが漏れたとき、受け取るファイルの制限、送らないもの）は [docs/security.md](docs/security.md) にまとめました。

## 教科書の章とのつながり

| 教科書 | labnote でできること |
|---|---|
| 第0章（uv と版の固定、MQTT → SQLite のロガー） | uv で動かす（`uv sync --locked`）。`labnote-send mqtt --db ~/lab/lab.db` で、`pi_mqtt_logger.py` の `messages` の直近の件数・seq の欠け・平均を送る |
| 入門1〜3・第3章などの CSV | `labnote add-result` で保存。`#` で始まる注釈の行は要約で読みとばす（入門1 の `led_iv.csv` など） |
| 第4章（`motor_run.py` の `.csv` と `.json`） | `labnote-send file data/run_d500.csv --pair`、または bot の `/結果` に2つ添付 |
| II-1（Pi・SSH・systemd・ufw・Tailscale） | `labnote-bot.service` を labstatus と同じ考え方（専用ユーザー・最小権限）で動かす。ufw・ACL は変えない |
| II-3・II-4（PostgreSQL・受信 API） | `ii4_export.py --out` の CSV を `labnote-send file` で送る |
| 各章の「期待される結果の例と、うまくいかないとき」 | ノートの「結果」「気づき」に、期待・実際・表のどの行に当たったか・対処を分けて書く（`notes/examples/`） |

## Git で管理する

- 置き場所（既定 `~/home-lab/labnote`）は、このリポジトリとは別の場所です。**自分の実験ノートを公開のリポジトリに入れないでください。** 教科書の II-1 で作った `~/home-lab` の（非公開の）Git に入れるのがおすすめです。
- 入れるもの：`notes/`（テキスト）。入れないもの：`labnote.db`（作り直せる）、`.env`（秘密）、大きなデータ。
- `data/` は大きくなりやすいので、既定では外します。小さな PNG だけ入れたいなら、置き場所の `.gitignore` を次のようにします（大きな CSV・WAV は Mac・Pi の間で rsync するか、バックアップで残す）。

```gitignore
labnote.db
labnote.db-*
.env
data/**
!data/*/
!data/**/*.png
```

## フォルダの構成

```text
labnote/
├── README.md               この説明
├── LICENSE                 MIT
├── pyproject.toml          依存（bot だけ discord.py==2.7.1）、ruff・pytest の設定
├── uv.lock                 実際に入る版（uv sync --locked で同じ版がそろう）
├── .env.example            設定の見本（.env にコピーして使う。.env は Git に入れない）
├── .gitignore
├── labnote/
│   ├── store.py            ノート（Markdown）と索引（SQLite）。作る・追記・添付・検索・reindex・backup
│   ├── summary.py          CSV・JSON・PNG の要約と中身の確認（標準ライブラリだけ）
│   ├── cli.py              labnote コマンド
│   ├── handlers.py         bot のコマンドの処理（discord を import しない。テストしやすい）
│   ├── bot.py              labnote-bot（discord.py。スラッシュコマンドの登録だけ）
│   ├── send.py             labnote-send（Webhook・手元への送信、MQTT の lab.db の要約）
│   ├── config.py           .env と環境変数、許可リスト
│   └── template.md         同梱のひな形（notes/template.md と同じ）
├── notes/
│   ├── template.md         ノートのひな形
│   └── examples/           書き方の例（第4章・入門1）
├── deploy/
│   ├── labnote-bot.service     systemd のサービス（Pi・Azure の VM）
│   ├── labnote-backup.service  毎日のバックアップ（任意）
│   └── labnote-backup.timer
├── docs/
│   ├── discord_setup.md    bot の作り方・Intent・招待の URL・Mac で試す・Webhook
│   ├── pi.md               Raspberry Pi（uv・systemd・更新・バックアップ・Tailscale）
│   ├── azure.md            Azure（小さな VM。Container Instances は要点）
│   └── security.md         秘密情報・漏れたとき・受け取るファイルの制限・送らないもの
└── tests/                  pytest（Discord につながずに、偽の interaction で試す）
```

## テスト

```bash
uv sync --locked --extra bot
uv run --extra bot pytest -q          # Discord・ネットワークにはつながない
uv run ruff check .
```

テストは、一時フォルダの置き場所で、ノートの作成・追記・添付（CSV・PNG・JSON、大きすぎる・種類の違うファイルを断る）・検索・reindex・backup、CLI、bot のコマンド（偽の interaction で、許可リストの外を断る・長い返事を切る・内部のエラーを隠す）、日本語のコマンド名と英語の名前（`name_localizations`）、Webhook の送信（偽の通信）、第0章の `messages` の表の要約を確かめます。

## 確かめていないこと

実際の Discord への接続、Raspberry Pi と Azure の上での動作（systemd のサービス、バックアップのタイマー）は、この README を書いた時点では確かめていません。
Discord・Azure の画面の項目名、料金、上限の値は変わることがあるので、公式のドキュメント・サイトで確かめてください。
