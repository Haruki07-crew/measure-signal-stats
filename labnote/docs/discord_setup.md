# Discord の bot を作って、Mac で試す

Discord の開発者ポータルで bot（アプリケーション）を作り、自分だけのサーバーに招待して、Mac で `labnote-bot` を動かします。
**画面の項目名・場所は変わることがあります。ここに書いた名前は執筆時（2026年11月）の目安なので、開発者ポータルの画面と公式ドキュメントで要確認です。**

## 0. はじめに決めておくこと

- bot を入れるのは、**自分だけ（または信頼できる少人数だけ）のサーバー**にします。実験ノートは自分の記録なので、人の多いサーバーには入れません。
- bot 用のチャンネル（例：`#labnote`）を1つ作り、bot はそのチャンネルでだけ答えるようにします（`.env` の許可リスト）。

## 1. アプリケーションと bot を作る

1. ブラウザで Discord の開発者ポータル（Developer Portal）を開き、自分のアカウントでログインします。
2. 「Applications」→「New Application」で名前（例：`labnote`）を付けて作ります。
3. 「General Information」の「Application ID」を控えます（招待の URL に使う。秘密ではありません）。
4. 左の「Bot」を開きます。
   - 「Reset Token」でトークンを作り、表示された文字列を **その場で** Mac の `labnote/.env` の `DISCORD_TOKEN=` に貼ります。トークンはパスワードと同じです。チャット・スクリーンショット・Git に出さないでください（漏れたときは [security.md](security.md)）。
   - 「Public Bot」はオフにします（自分以外がこの bot を招待できないようにする）。
   - 「Privileged Gateway Intents」の3つ（Presence Intent・Server Members Intent・Message Content Intent）は、**すべてオフのまま**にします。スラッシュコマンドだけなら要りません。例外は下の「Webhook の取り込み」を使うときの Message Content Intent だけです。

### 必要な Intent（最小限）

labnote-bot がコードで頼む Intent は `guilds` だけです（`labnote/bot.py` の `build_bot`）。
スラッシュコマンドは「interaction」として届くので、メッセージを読む Intent（Message Content）は要りません。
`.env` に `LABNOTE_INGEST_WEBHOOK_IDS` を書いたときだけ、`guild_messages` と `message_content`（特権）を頼みます。
そのときは開発者ポータルで Message Content Intent をオンにしないと、bot の起動時にエラーになります。

## 2. 招待の URL を作って、サーバーに入れる

開発者ポータルの「OAuth2」（または「Installation」）の URL Generator で、次を選びます（項目名は要確認）。

- スコープ（scopes）：`bot` と `applications.commands`
- Bot の権限（Bot Permissions）：`View Channels`・`Send Messages`・`Attach Files`・`Read Message History`

`Administrator` は付けません。できた URL をブラウザで開き、自分のサーバーを選んで認証します。

URL Generator を使わずに作るなら、次の形です（`YOUR_APPLICATION_ID` を手順1-3 の値に）。
`permissions` の数は、上の4つの権限のビット（View Channels＝1024、Send Messages＝2048、Attach Files＝32768、Read Message History＝65536）の合計 101376 です（ビットの値は公式ドキュメントの Permissions の表で要確認）。

```text
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot+applications.commands&permissions=101376
```

`Read Message History` は、Webhook の取り込みで bot が元のメッセージに返信するときに使います。取り込みを使わないなら外してもかまいません（35840）。

チャンネルの権限で bot を `#labnote` だけに入れたいときは、サーバーの設定でほかのチャンネルの「チャンネルを見る」を bot のロールから外します（`.env` の許可リストとの二重の守り）。

## 3. 許可リストの ID を調べる

Discord のアプリの「設定」→「詳細設定」（Advanced）で「開発者モード」（Developer Mode）をオンにすると、右クリック（スマートフォンは長押し）に「ID をコピー」が出ます（項目名は要確認）。

| .env の名前 | 何の ID | どこで右クリック |
|---|---|---|
| `LABNOTE_GUILD_IDS` | サーバー | 左のサーバーのアイコン |
| `LABNOTE_CHANNEL_IDS` | チャンネル | `#labnote` |
| `LABNOTE_USER_IDS` | 自分 | 自分の名前 |

カンマで区切れば複数書けます。**3つとも合うときだけ** bot は答えます。1つでも空なら、bot は起動を止めます（`labnote-bot --check` で確かめられる）。
ID は秘密ではありませんが、公開のリポジトリには書かないでください（`.env` は `.gitignore` 済み）。

## 4. Mac で動かす

```bash
cd labnote                                  # このリポジトリの labnote/
cp .env.example .env && chmod 600 .env      # トークン・ID を書く
uv sync --locked --extra bot                # discord.py（版は pyproject.toml で固定）を入れる
uv run labnote init                         # LABNOTE_HOME（既定 ~/home-lab/labnote）を作る
uv run --extra bot labnote-bot --check      # 設定だけ確かめる（つながない）。エラーが出なければ OK
uv run --extra bot labnote-bot              # 動かす（Ctrl-C で止める）
```

`ログインしました：labnote#1234` と `サーバー … にコマンド 6 個を登録` が出たら、Discord の `#labnote` で `/` を打ちます。
コマンドは許可リストのサーバーにだけ登録するので、すぐに出ます（出ないときは Discord のアプリを再読み込みする）。

| コマンド | 何をするか | 例 |
|---|---|---|
| `/記録 メモ:` | 今日のノートの「メモ（時刻つき）」に1行足す。今日のノートが無ければ「今日のメモ」を作る | `/記録 メモ:電池 5.42V、室温 21℃` |
| `/結果 ファイル: [ファイル2:] [ノート番号:] [説明:]` | 添付を `data/<番号>/` に保存し、ノートの「結果」と「データのファイル」に追記。CSV なら行数・列・平均・SD・最小・最大を返す | motor_run.py の `run_d500.csv` と `run_d500.json` を2つ添付 |
| `/一覧 [件数:] [章:]` | 最近のノート | `/一覧 章:ch4` |
| `/見る 番号:` | ノートの中身（長いと切る）と、.md・添付のファイル | `/見る 番号:12` |
| `/探す 言葉:` | 題名・本文から探す（空白で区切ると、すべてを含むもの） | `/探す 言葉:stall 電池` |
| `/今日` | 今日のノートのまとめ（メモの数、ファイルの数、最後のファイルの要約） | |

コマンド名と引数名は日本語です。Discord の名前の決まり（1〜32文字、小文字のある文字は小文字だけ。漢字・ひらがな・カタカナは大文字・小文字がないので使える）は、公式ドキュメントの「Application Command Naming」で確かめました。
Discord の表示言語を英語にしている人には、公式のローカライズ（`name_localizations`）で `/log` `/result` `/list` `/show` `/search` `/today` と英語の名前が出ます（中身は同じコマンド）。

bot が書いたノートは、CLI からも同じように見えます（同じ `LABNOTE_HOME` を開くため）。

```bash
uv run labnote list
uv run labnote show 12
```

## 5. Webhook で送る（labnote-send）

Pico・Pi の記録を、bot を通さずにチャンネルへ送る方法です。送るだけなので、bot が止まっていても届きます。

1. `#labnote` の「チャンネルの編集」→「連携サービス」（Integrations）→「ウェブフック」（Webhooks）→「新しいウェブフック」で作り、「ウェブフック URL をコピー」します（項目名は要確認）。
2. URL を `.env` の `LABNOTE_WEBHOOK_URL=` に貼ります。**Webhook の URL を知っている人は誰でもそのチャンネルに書き込めます。トークンと同じ秘密情報です。**
3. 送ります。

```bash
# 第4章：motor_run.py が書いた CSV と、同じ名前の JSON を一緒に、要約つきで
uv run labnote-send file ~/home-lab/ch4/data/run_d500.csv --pair -m "第4章 d=500"
# 第0章：Pi の pi_mqtt_logger.py の lab.db から、直近60分の要約と CSV（Pi で実行。docs/pi.md）
labnote-send mqtt --db ~/lab/lab.db --minutes 60 --dev pico1-leak
```

`--to local` にすると Webhook を使わず、その機械の labnote に直接足します（Pi の上で bot と同じ置き場所に書くときは、[pi.md](pi.md) の 4 のとおり `sudo -u labnote` で動かす）。

### Webhook の取り込み（任意）

Webhook で送ったファイルを、bot が自動でノートに取り込むこともできます。

1. Webhook の URL の `https://discord.com/api/webhooks/<数字>/<文字列>` の **数字の部分**（Webhook の ID）を `.env` の `LABNOTE_INGEST_WEBHOOK_IDS=` に書きます。後ろの文字列は書きません。
2. 開発者ポータルの Bot の画面で Message Content Intent をオンにします（特権 Intent。添付と本文を読むのに必要）。
3. bot を起動し直します。

本文に `note:12` と書いて送ると #12 に、書かなければ今日のノートに入ります（`labnote-send … --note 12` で付く）。
取り込むのは、許可リストのサーバー・チャンネルに届いた、ID が一致する Webhook のメッセージだけです。人が書いたメッセージは読みません。
