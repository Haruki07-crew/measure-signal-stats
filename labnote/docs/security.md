# 安全に使うために

## 秘密情報の置き場所

| もの | 置き場所 | Git |
|---|---|---|
| bot のトークン（`DISCORD_TOKEN`） | Mac：`labnote/.env`（600）／Pi・VM：`/etc/labnote/labnote.env`（root:labnote、640） | 入れない（`.gitignore` 済み） |
| Webhook の URL（`LABNOTE_WEBHOOK_URL`） | 同じ `.env`、Pi の自分用は `~/.config/labnote/send.env`（600） | 入れない |
| サーバー・チャンネル・ユーザーの ID | 同じ `.env` | 入れない（秘密ではないが、公開しない） |

- `.env.example` には見本の値（`your-discord-bot-token` など）だけを書きます。
- トークンや URL をコマンドの引数に書かないでください（シェルの履歴と `ps` に残ります）。labnote-send は `.env` からだけ読みます。
- コミットの前に `git status` と `git diff --cached` で、`.env` が入っていないことを確かめます。`git check-ignore -v .env` で除外されているかも確かめられます。

## トークン・Webhook の URL が漏れたとき

漏れた（Git に入れた、画面を共有した、チャットに貼った）と思ったら、**すぐに作り直します**。消してコミットし直しても、履歴やほかの人の手元に残っているので、それだけでは足りません。

1. **bot のトークン**：開発者ポータルの Bot の画面で「Reset Token」。古いトークンはその場で使えなくなります。新しいトークンを Pi の `/etc/labnote/labnote.env`（と Mac の `.env`）に書いて、`sudo systemctl restart labnote-bot`。
   公開のリポジトリにトークンを push すると、Discord がそれを見つけて自動で無効にし、知らせてくることがあります（公式ドキュメントで要確認）。そのときも同じように作り直します。
2. **Webhook の URL**：チャンネルの設定の「ウェブフック」から、その Webhook を **削除** して新しく作り、`LABNOTE_WEBHOOK_URL`（と `LABNOTE_INGEST_WEBHOOK_IDS` の ID）を書き換えます。
3. 漏れていた間に、知らないメッセージやファイルがチャンネルに来ていないか、`labnote list` で知らないノートができていないかを見ます。
4. Git の履歴から消すのは、そのあとです（ほかの秘密と同じ。教科書の II-1・II-4 の秘密の扱いを参照）。

## bot が受け取るもの

- 答えるのは、`.env` の許可リストの **サーバー・チャンネル・ユーザーの3つがすべて合うとき**だけです。DM には答えません。断ったときは本人にだけ見える返事（ephemeral）を返し、ログに ID を残します。
- 受け取るファイルは、**拡張子**（既定 `.csv .png .json .jpg .jpeg .txt`。`LABNOTE_ALLOWED_EXT`）と **大きさ**（既定 8MB。`LABNOTE_MAX_BYTES`）で、**読み込む前に**断ります。そのあと中身も確かめます（PNG・JPEG の先頭のバイト、CSV・JSON が UTF-8 で読めるか、JSON として正しいか）。
- ファイル名は英数字と `._-` だけにして `data/<番号>/` に保存します（`../` などで別の場所に書けない）。同じ名前は上書きせず `_2` を付けます。
- 受け取ったファイルを **実行したり、開いて解釈したりはしません**（CSV の数値の要約を除く）。
- bot の返事はメンションを飛ばさない設定（`AllowedMentions.none()`）にしています。メモに `@everyone` と書いても通知は飛びません。
- 内部のエラーの中身（パスなど）は Discord には返さず、journald のログにだけ書きます。

## 送らないもの

- **個人情報**（氏名・住所・電話番号・学校名・顔の写る写真・人の声の録音）は、ノートにも Discord にも書かない・送らないでください。Discord のサーバーに置いたものは、自分の手元から消しても Discord の側に残ることがあります。
- Wi-Fi の SSID・パスワード、MQTT のパスワード、`labconfig.py` の中身を、ノートやメモに写さないでください。
- 実験の写真に、家の中・郵便物・画面の通知などが写っていないか、送る前に確かめます。
- 研究室のデータを扱うときは、外部のサービス（Discord・Azure）に置いてよいか、先に研究室の決まりを確かめます。

## 権限を小さくする

- 招待のときの Bot の権限は、[discord_setup.md](discord_setup.md) の4つだけにします（`Administrator` を付けない）。「Public Bot」はオフ。
- 特権 Intent（Message Content など）は、Webhook の取り込みを使うときだけオンにします。
- Pi・VM では、専用のユーザー `labnote`、root 所有の `/opt/labnote`、`ProtectSystem=strict` などのサービス（[pi.md](pi.md)）で動かします。受け口のポートは開けません。
