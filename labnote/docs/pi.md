# Raspberry Pi で動かす（教科書の II-1 の Pi）

教科書の II-1 で用意した Pi（ホスト名 `labpi`、Raspberry Pi OS **Lite**、SSH は鍵だけ、ufw で受け口を閉じ、Tailscale で外から SSH）で、`labnote-bot` を systemd のサービスとして常に動かします。
II-1 の `labstatus.service` と同じ考え方で、**専用のユーザー・root 所有のプログラム・最小権限**にします。

| 置き場所 | 中身 | 持ち主 |
|---|---|---|
| `/opt/labnote/` | このフォルダ（labnote）の写しと `.venv` | root（サービスから書き換えられない） |
| `/etc/labnote/labnote.env` | トークン・許可リスト・Webhook の URL | root:labnote、640 |
| `/var/lib/labnote/` | 記録（`notes/`・`data/`・`labnote.db`・`backup/`） | labnote（systemd の `StateDirectory`） |
| `/etc/systemd/system/labnote-bot.service` | サービスの設定（`deploy/` にある） | root |

## ufw・Tailscale との関係

- bot は **Discord のサーバーへ外向きに（HTTPS と WebSocket で）つなぐだけ**です。Discord から Pi へ入ってくる通信はありません。そのため **ufw に規則を足しません**（II-1 の `default deny incoming` のまま。外向きは `allow outgoing`）。ルーターのポート開放もしません。
- Tailscale は、Mac から Pi に SSH する道（`labpi-ts`）として、これまでどおり使います。bot の通信は Tailscale を通らず、ふつうのインターネットに出ます（Pi で exit node を使っているときはそこを通ります）。tailnet の ACL（SSH だけ）も変えません。
- Pi の時計がずれていると TLS の接続に失敗することがあります。`timedatectl` で `System clock synchronized: yes` を確かめます。

## 1. uv とプログラムを置く

Mac から（このリポジトリの `labnote/` で）Pi の自分のホームに送ります。Git で clone してもかまいません（更新が楽になる。下の「更新のしかた」）。

```bash
# Mac で。.env・.venv・記録は送らない
rsync -av --delete --exclude .venv --exclude .env --exclude labnote.db --exclude data/ \
      --exclude __pycache__ ./ labpi:~/labnote-src/
```

Pi で（`ssh labpi`）：

```bash
# uv（第0章と同じ公式のインストーラ。自分のユーザーの ~/.local/bin に入る）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.profile            # または SSH を入り直す
uv --version

# サービス専用のユーザー（ログイン不可・ホームなし）
sudo useradd --system --no-create-home --shell /usr/sbin/nologin labnote
# 自分を labnote グループに入れる（記録を読んでバックアップするため。入り直すと効く）
sudo usermod -aG labnote "$USER"

# プログラムを root 所有で /opt/labnote に置き、Pi の /usr/bin/python3 で環境を作る
sudo mkdir -p /opt/labnote
sudo rsync -a --delete --exclude .venv ~/labnote-src/ /opt/labnote/
cd /opt/labnote
sudo env UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/var/cache/labnote-uv \
     "$HOME/.local/bin/uv" sync --locked --no-dev --extra bot --python /usr/bin/python3
/opt/labnote/.venv/bin/python -c "import discord, labnote; print(discord.__version__)"
```

`--locked` は、`uv.lock` と `pyproject.toml` が食い違っていたら解き直さずに止まる指定です（第0章と同じ）。
Python は uv に配らせず（`UV_PYTHON_DOWNLOADS=never`）、Pi の `/usr/bin/python3` を使います。uv が配る Python は root のホームに入り、`labnote` ユーザーから読めないためです。labnote は Python 3.11 以上で動きます（Pi の Python の版は `python3 --version` で確かめる）。

## 2. 秘密の設定を置く

```bash
sudo install -d -m 750 -o root -g labnote /etc/labnote
sudo install -m 640 -o root -g labnote /opt/labnote/.env.example /etc/labnote/labnote.env
sudo nano /etc/labnote/labnote.env
```

`DISCORD_TOKEN`・`LABNOTE_GUILD_IDS`・`LABNOTE_CHANNEL_IDS`・`LABNOTE_USER_IDS` を書きます（[discord_setup.md](discord_setup.md)）。
`LABNOTE_HOME` の行は残っていてもかまいません（サービスは `/var/lib/labnote` に固定している）。
**Mac で試していた bot は止めてから** Pi で動かします（同じトークンで2つ動かすと、両方が返事をしようとして混乱します）。

## 3. サービスを登録する

```bash
sudo install -o root -g root -m 644 /opt/labnote/deploy/labnote-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now labnote-bot
systemctl status labnote-bot --no-pager
journalctl -u labnote-bot -n 30 --no-pager       # 「ログインしました」「コマンド 6 個を登録」
journalctl -u labnote-bot -f                     # 動いている間のログ（Ctrl-C で抜ける）
```

`labnote-bot.service` の要点：

- `User=labnote`・`NoNewPrivileges`・`ProtectSystem=strict`・`ProtectHome=yes` など（II-1 の labstatus と同じ最小権限）。書けるのは `StateDirectory` の `/var/lib/labnote` だけです。
- `Restart=on-failure`・`RestartSec=10`。ネットワークが切れたときの再接続は discord.py が自分で行い、プログラムが落ちたときだけ systemd が起動し直します。5分に5回落ちたらあきらめます（`StartLimitBurst`）。
- 終了コード 2（トークンが見本のまま、許可リストが空）は、起動し直しても直らないので `RestartPreventExitStatus=2` で止めます。`journalctl` でエラーを読んで直し、`sudo systemctl restart labnote-bot`。
- ログは journald に入ります（`print` ではなく logging。トークンは出しません）。

自動で起動し直すことを確かめます（II-1 の手順F と同じ）。

```bash
sudo systemctl kill -s KILL labnote-bot
sleep 12
systemctl status labnote-bot --no-pager          # active (running) に戻っている
systemd-analyze security labnote-bot | tail -n 1 # 保護の点数（小さいほど固い）
```

## 4. Pi の上で CLI を使う

記録は `labnote` ユーザーの持ち物なので、CLI も同じユーザーで動かします。`~/.bashrc` に別名を置くと楽です。

```bash
alias labnote='sudo -u labnote env LABNOTE_HOME=/var/lib/labnote LABNOTE_ENV_FILE=/nonexistent /opt/labnote/.venv/bin/labnote'
labnote list
labnote show 12
```

### 第0章の MQTT の記録を送る

第0章の `pi_mqtt_logger.py` は、あなたのユーザーの `~/lab/lab.db` に書いています（`messages` の表）。
labnote-send は lab.db を **読むだけ**（`mode=ro`）で開くので、ロガーの書き込みを邪魔しません。
Webhook の URL だけを書いた設定を、自分のホームに別に作ります。

```bash
install -d -m 700 ~/.config/labnote
printf 'LABNOTE_WEBHOOK_URL=%s\n' 'https://discord.com/api/webhooks/your-webhook-id/your-webhook-token' > ~/.config/labnote/send.env
chmod 600 ~/.config/labnote/send.env
nano ~/.config/labnote/send.env                  # 見本の URL を本物に書き換える
/opt/labnote/.venv/bin/labnote-send --env ~/.config/labnote/send.env mqtt --db ~/lab/lab.db --minutes 60
```

Webhook を通さずに bot と同じ置き場所（`/var/lib/labnote`）へ直接足す `--to local` は、記録の持ち主の `labnote` ユーザーで動かします（自分のユーザーのままだと `/var/lib/labnote` に書けません）。
`labnote` ユーザーは自分のホームの `~/lab/lab.db` を読めないことがあるので、要約したい CSV はいったん `/tmp` に書き出すか、ファイルを `/tmp` に写してから送ります。

```bash
cp ~/data/run_d500.csv ~/data/run_d500.json /tmp/        # Pi に置いた CSV と JSON（例）
sudo -u labnote env LABNOTE_HOME=/var/lib/labnote LABNOTE_ENV_FILE=/nonexistent \
     /opt/labnote/.venv/bin/labnote-send file /tmp/run_d500.csv --pair --to local --note 12
rm /tmp/run_d500.csv /tmp/run_d500.json
```

1時間ごとに送るなら、`crontab -e` に次の1行を足します（送りすぎないように。Webhook には回数の制限があります。公式ドキュメントで要確認）。

```text
5 * * * * /opt/labnote/.venv/bin/labnote-send --env ~/.config/labnote/send.env mqtt --db ~/lab/lab.db --minutes 60 --no-csv
```

II-3 で PostgreSQL に移したあとは lab.db が増えなくなります。そのときは II-4 の `ii4_export.py --out` で書き出した CSV を `labnote-send file ii4_msgs.csv` で送ります。

## 5. 更新のしかた

```bash
# Mac で直したら、手順1の rsync をもう一度（clone したなら Pi で cd ~/labnote-src && git pull）
# Pi で：
sudo rsync -a --delete --exclude .venv ~/labnote-src/ /opt/labnote/
cd /opt/labnote
sudo env UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/var/cache/labnote-uv \
     "$HOME/.local/bin/uv" sync --locked --no-dev --extra bot --python /usr/bin/python3
sudo install -o root -g root -m 644 /opt/labnote/deploy/labnote-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart labnote-bot
journalctl -u labnote-bot -n 20 --no-pager
```

discord.py の版を上げるときは、Mac で `pyproject.toml` の `discord.py==…` を直して `uv lock`、`uv run --extra bot pytest` を通してから送ります（公式の変更履歴で、使っている機能が変わっていないか要確認）。
Discord の側の仕様が変わって古い版がつながらなくなることがあります。`journalctl` に接続のエラーが続くときは、まず版を確かめます。

## 6. バックアップ（SQLite と notes/ を Mac に）

SQLite は書き込み中にファイルを写すと壊れたコピーになることがあるので、`labnote backup` で一貫した写し（SQLite の backup の仕組み）を作ってから、Mac に rsync します。毎日自動で作るには、タイマーを登録します。

```bash
# Pi で（一度だけ）
sudo install -o root -g root -m 644 /opt/labnote/deploy/labnote-backup.service /opt/labnote/deploy/labnote-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now labnote-backup.timer
sudo systemctl start labnote-backup.service       # 今すぐ1回
systemctl list-timers labnote-backup.timer --no-pager
ls -l /var/lib/labnote/backup/latest/
```

```bash
# Mac で（labnote グループに入ったあと、SSH を入り直してから）
mkdir -p ~/home-lab/backup_labnote
rsync -av labpi:/var/lib/labnote/backup/latest/ ~/home-lab/backup_labnote/   # 外からなら labpi-ts
sqlite3 ~/home-lab/backup_labnote/labnote.db "SELECT COUNT(*) FROM notes;"
```

`labnote.db` は索引なので、無くしても `notes/` と `data/` があれば `labnote reindex` で作り直せます。大事なのは `notes/` と `data/` です。
Pi の microSD は壊れることがあるので、Mac への写しを定期的に取ってください。

## 7. 止める・消す

```bash
sudo systemctl disable --now labnote-bot labnote-backup.timer
sudo rm /etc/systemd/system/labnote-bot.service /etc/systemd/system/labnote-backup.*
sudo systemctl daemon-reload
# 記録まで消すときだけ（先にバックアップ）：sudo rm -rf /var/lib/labnote /opt/labnote /etc/labnote
```
