# Docker で動かす（任意。Raspberry Pi・Azure の VM 共通）

[pi.md](pi.md)（systemd で動かす手順）の代わりに、Docker のコンテナで bot を動かす方法です。どちらか**片方だけ**を使います（同時に動かすと、同じ bot が2つつながります）。

| | systemd（pi.md） | Docker（この手順） |
|---|---|---|
| 入れる物 | uv、専用ユーザー、service のファイル | Docker だけ |
| 起動・更新 | `systemctl`、rsync して `uv sync` | `docker compose up -d --build` の1行 |
| 記録の置き場所 | `/var/lib/labnote` | `labnote/labnote-data/`（手元のフォルダ） |
| 向いている人 | 教科書 II-1 の Linux の運用を練習したい人 | 手順を少なくしたい人、Pi と Azure で同じ形にしたい人 |

Docker の中で動くのは **bot と CLI だけ**です。教科書の本文（Pico への書き込み、シリアル、マイク、Mac の GPU）は Docker では動かないので、これまでどおり Mac で行います。

> ⚠ **秘密情報**：トークンと Webhook の URL は `labnote/.env` だけに書きます（`chmod 600`）。`.env` は `.gitignore` と `.dockerignore` で除外してあるので、Git にもイメージにも入りません。コンテナに渡した値は `docker inspect` で見えるので、**docker グループに入れるのは自分だけ**にします（docker グループに入った人は、その機械の root と同じことができます）。

## 1. Docker を入れる

Raspberry Pi OS（64bit の Lite 版）・Azure の Ubuntu とも、Docker Engine と Compose プラグインを、**Docker の公式ドキュメントの手順**で入れます（入れ方・パッケージの名前は版で変わるので、公式ドキュメントで要確認）。入れたら：

```bash
docker --version
docker compose version          # v2 以上（"docker-compose" ではなく "docker compose"）
sudo usermod -aG docker "$USER" # 自分だけを docker グループに入れる。SSH を入り直すと効く
```

Pi では、systemd 版の bot を動かしていたら先に止めます：`sudo systemctl disable --now labnote-bot.service`（記録を移すときは下の「6. systemd 版から移る」）。

## 2. プログラムを置き、秘密の設定を書く

```bash
# Mac で（.env・.venv・記録は送らない）。git clone で置いてもよい
rsync -av --exclude .env --exclude .venv --exclude labnote-data ./labnote/ labpi:~/labnote/

# Pi（または Azure の VM）で
cd ~/labnote
mkdir -p labnote-data                     # 記録の置き場所。先に自分で作る（Docker に root の持ち物で作らせない）
cp .env.example .env && chmod 600 .env
nano .env                                  # DISCORD_TOKEN と3つの許可リストを書く（docs/discord_setup.md）
```

`.env` の `LABNOTE_HOME` は、Docker 版では使われません（コンテナの中は `/data` に固定。`labnote-data/` が `/data` につながる）。

## 3. 確かめてから起動する

```bash
cd ~/labnote
export LABNOTE_UID=$(id -u) LABNOTE_GID=$(id -g)     # コンテナを自分の UID で動かす（既定は 1000:1000）
docker compose -f deploy/docker/compose.yaml build
docker compose -f deploy/docker/compose.yaml run --rm bot --check    # 設定だけ確かめる。終了コード 0 なら OK
docker compose -f deploy/docker/compose.yaml up -d
docker compose -f deploy/docker/compose.yaml logs -f                 # Ctrl+C でログの表示だけ止まる
```

`--check` が「DISCORD_TOKEN が見本の値のままか、空です」と言ったら `.env` を直します。`LoginFailure: Improper token` はトークンの写し間違いです（開発者ポータルで作り直して `.env` に書き、`up -d` をやり直す）。

毎回 `export` するのを省くなら、`~/.bashrc` に `export LABNOTE_UID=$(id -u) LABNOTE_GID=$(id -g)` を足します。

**決めてあること**（`deploy/docker/compose.yaml`）：
- **受け口を開けない**：`ports:` を書いていません。bot は Discord へ外向きにつなぐだけなので、ufw も Azure の NSG も、受け口を足す必要はありません。
- **root で動かさない**：自分の UID で動きます（`user:`）。コンテナの中のファイルは書き換えられず（`read_only`）、特権はすべて外してあります（`cap_drop: ALL`、`no-new-privileges`）。
- **落ちたら起動し直す**：`restart: unless-stopped` なので、落ちたときと、Pi・VM を再起動したときに自動で上がります（自分で `down`・`stop` したときは上がりません）。トークンの誤りなどでは起動し直しを繰り返すだけなので（間隔はだんだん長くなる）、起動の前に必ず `--check` で確かめ、`logs` に同じエラーが並んでいたら `down` して `.env` を直します。
- **ログが増え続けない**：5MB×3個まで（`logging`）。

## 4. CLI をコンテナで使う

```bash
cd ~/labnote
dc() { docker compose -f deploy/docker/compose.yaml "$@"; }    # 長いので関数にする
dc run --rm --entrypoint labnote bot list
dc run --rm --entrypoint labnote bot show 1
dc run --rm --entrypoint labnote bot log today "Pi から追記"
```

bot と同時に使っても、SQLite の書き込みはロックで1つずつになるので壊れません。

## 5. 更新・バックアップ・止める

```bash
cd ~/labnote
# 更新：Mac で直したら手順2の rsync をもう一度（clone したなら git pull）して
dc up -d --build

# バックアップ（SQLite の写し＋notes/＋data/）。labnote-data/backup/latest にできる
dc run --rm --entrypoint labnote bot backup /data/backup/latest
# Mac で受け取る（labnote-data は自分の持ち物なので、そのまま rsync できる）
rsync -av labpi:~/labnote/labnote-data/backup/latest/ ~/labnote_backup/

# 止める（記録は labnote-data/ に残る）
dc down
# イメージも消す
dc down --rmi local
```

毎日自動でバックアップしたいときは、`crontab -e` に次の1行を足します（時刻は例）：

```cron
30 3 * * * cd ~/labnote && LABNOTE_UID=1000 LABNOTE_GID=1000 docker compose -f deploy/docker/compose.yaml run --rm --entrypoint labnote bot backup /data/backup/latest >/dev/null 2>&1
```

（`1000` は `id -u`・`id -g` の値に合わせる）

## 6. systemd 版から移る

```bash
sudo systemctl disable --now labnote-bot.service labnote-backup.timer
cd ~/labnote && mkdir -p labnote-data
sudo rsync -a /var/lib/labnote/ ./labnote-data/
sudo chown -R "$(id -u):$(id -g)" labnote-data
dc run --rm --entrypoint labnote bot reindex     # 索引を作り直す（念のため）
dc up -d
```

`/etc/labnote/labnote.env` の中身は、`~/labnote/.env` に写します（`chmod 600`）。移り終わって動きを確かめたら、`/etc/labnote/labnote.env` は消します（秘密を2か所に残さない）。

## うまくいかないとき

| 症状 | 原因と対処 |
|---|---|
| `bind source path does not exist` | `labnote-data/` を作っていない。`mkdir -p labnote-data` |
| `Permission denied: '/data/notes'` | `labnote-data/` の持ち主と `LABNOTE_UID` が合っていない。`ls -ln` で持ち主を見て、`export LABNOTE_UID=$(id -u) LABNOTE_GID=$(id -g)` をしてから実行する |
| 上のどちらでもないのに `Permission denied` | rootless モードの Docker では、コンテナの中の UID の対応が変わる。rootless のときは `LABNOTE_UID=0 LABNOTE_GID=0`（コンテナの中の root が、外では自分のユーザーになる）を試す（Docker の公式ドキュメントで要確認） |
| `Read-only file system: '/data/...'` | Mac の Docker（Docker Desktop・lima など）で、ホームのフォルダが読み取り専用でつながれている。この手順は Pi・Azure の VM 向け。Mac では Docker を使わず `uv run --extra bot labnote-bot`（README）で動かす |
| `env file ... not found` | `labnote/.env` が無い。手順2の `cp .env.example .env` |
| ずっと再起動している | `dc logs --tail 50` で理由を見る。`dc down` して、トークン・許可リストを直し、`--check` のあと `dc up -d` |
| `/結果` で送ったファイルが無い | `labnote-data/data/<番号>/` を見る。Pi の空きは `df -h` |

Azure の VM で使うときは、[azure.md](azure.md) の「1. VM を作る」まで進めてから、この手順の1から行います。止め忘れの費用の注意は azure.md のとおりです（Docker にしても VM の料金は同じ）。
