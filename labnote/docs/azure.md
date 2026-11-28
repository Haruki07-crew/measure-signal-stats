# Azure で動かす

Pi を使わない（または Pi が止まっている間も bot を動かしたい）ときの方法です。
**いちばん簡単で安い方法として、小さな Linux の VM（仮想マシン）1台に、Pi と同じ手順で入れる方法**を選びます。
Pi の [pi.md](pi.md) の手順がほぼそのまま使え、SQLite と `notes/` は VM のディスクに残ります。

もう1つの方法（Azure Container Instances）は、最後に要点だけ書きます。

> **料金について**：VM のサイズの料金、学生向けの特典（Azure for Students のクレジットなど）、無料アカウントの12か月の無料枠（B1s などの時間数）は、**公式サイトで要確認（執筆時点の目安）**です。
> 特典の条件・残りのクレジットは、Azure ポータルの「コスト管理」で確かめてください。
> bot は1日中動かすものなので、無料枠の時間を超えないか、サイズとディスクの種類の料金を先に確かめます。

## ⚠ 止め忘れ・消し忘れの費用

- VM は **「停止（割り当て解除）」** にしないと、OS の中でシャットダウンしただけでは料金がかかり続けることがあります（`az vm deallocate`）。
- 割り当て解除しても、**ディスクと公開 IP アドレス**には料金がかかることがあります。使い終わったら **リソースグループごと消す**のが確実です（下の「消す」）。
- 「予算」（Budgets）で、月の上限を決めてメールで知らせる設定を先に作っておきます（ポータルの「コスト管理」→「予算」。項目名は要確認）。

## 1. VM を作る（Azure CLI）

Mac に Azure CLI を入れ（`brew install azure-cli`。入れ方は公式ドキュメントで要確認）、ログインします。

```bash
az login
az account show --output table                  # 使うサブスクリプション（学生向けなど）を確かめる

RG=rg-labnote
LOC=japaneast                                   # 近いリージョン。無料枠の対象のサイズがあるかは要確認
az group create --name $RG --location $LOC

# Ubuntu の小さな VM。SSH の鍵は Pi とは別に作る（~/.ssh/id_ed25519_azure）
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_azure -C labnote-azure
az vm create --resource-group $RG --name labnote-vm \
  --image Ubuntu2404 --size Standard_B1s \
  --admin-username azureuser --ssh-key-values ~/.ssh/id_ed25519_azure.pub \
  --public-ip-sku Standard --nsg-rule SSH
```

イメージの別名（`Ubuntu2404`）とサイズ（`Standard_B1s`）が使えるかは、`az vm image list --output table`・`az vm list-sizes --location $LOC --output table` で要確認です。
B1s はメモリが 1GiB 程度で、labnote-bot には十分です（Python の bot は数十MB）。

### SSH の受け口を自分の IP だけにする

`--nsg-rule SSH` は、22番をインターネット全体に開けます。自分の今の IP アドレスだけに絞ります。

```bash
MYIP=$(curl -s https://api.ipify.org)           # 自分のグローバル IP（変わることがある）
az network nsg rule update --resource-group $RG --nsg-name labnote-vmNSG \
  --name default-allow-ssh --source-address-prefixes "$MYIP/32"
az network nsg rule list --resource-group $RG --nsg-name labnote-vmNSG --output table
```

NSG と規則の名前（`labnote-vmNSG`・`default-allow-ssh`）は、`az vm create` が付けた名前を `az network nsg list --resource-group $RG --output table` で確かめてから使います。
もっと固くするなら、VM にも Tailscale を入れて tailnet から SSH し、NSG の 22番の規則を消します（Pi の II-1 と同じ考え方。Tailscale の ACL で VM にもタグを付ける）。

**bot のために開けるポートはありません。** bot は Discord へ外向きにつなぐだけです（Pi の ufw と同じ）。

## 2. Pi と同じ手順で入れる

```bash
ssh -i ~/.ssh/id_ed25519_azure azureuser@<VM の公開 IP>      # az vm show -d -g $RG -n labnote-vm --query publicIps -o tsv
sudo apt update && sudo apt -y upgrade
sudo apt -y install rsync sqlite3
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH (NSG で自分の IP だけ)'
sudo ufw enable
timedatectl                                     # System clock synchronized: yes
```

Docker で動かすなら、ここから [docker.md](docker.md) の 1 に進みます（下の pi.md の手順は要りません）。

あとは [pi.md](pi.md) の **1〜4・6** を、`labpi` を VM（`azureuser@<IP>`）に読み替えてそのまま行います。
Ubuntu 24.04 の `/usr/bin/python3` は 3.12 系で、labnote（3.11 以上）が動きます（`python3 --version` で確かめる）。
**同じトークンで Pi と Azure の両方の bot を同時に動かさないでください。** どちらか一方を止めます（`sudo systemctl disable --now labnote-bot`）。

### データの永続化

- `notes/`・`data/`・`labnote.db` は VM の OS ディスクの `/var/lib/labnote` にあります。VM を再起動しても、割り当て解除しても残ります。**VM（とディスク）を削除すると消えます。**
- 消す前と、定期的に、Mac へバックアップを取ります（pi.md の 6 と同じ。`rsync -av -e "ssh -i ~/.ssh/id_ed25519_azure" azureuser@<IP>:/var/lib/labnote/backup/latest/ ~/home-lab/backup_labnote_azure/`）。

### 秘密情報

- いちばん簡単なのは Pi と同じ `/etc/labnote/labnote.env`（root:labnote、640）です。VM のディスクは Azure の側で暗号化されます（既定の設定は公式ドキュメントで要確認）。
- もう一段固くするなら、トークンを **Azure Key Vault** のシークレットに入れ、VM に **マネージド ID** を付けて、起動の前に読む形にします（要点だけ）：
  `az keyvault create` → `az keyvault secret set --name discord-token --value …`（コマンドの履歴に残らないように `--file` を使う）→ `az vm identity assign` → Key Vault のアクセスの設定（RBAC の「Key Vault Secrets User」など。要確認）→ VM の中で `az keyvault secret show --query value -o tsv` を `ExecStartPre` から呼んで `/run/labnote/labnote.env` に書く。
  1人で使う bot なら env ファイルで十分なことが多いです。

## 3. 止める・消す

```bash
az vm deallocate --resource-group $RG --name labnote-vm    # 止める（割り当て解除。ディスクの料金は残ることがある）
az vm start --resource-group $RG --name labnote-vm         # また動かす

# 全部消す（先に Mac へバックアップ）。リソースグループの中の VM・ディスク・IP・NSG がすべて消える
az group delete --name $RG --yes --no-wait
az group list --output table                               # 数分たってから、rg-labnote が無くなったことを確かめる
```

- `--public-ip-sku Standard` の公開 IP は静的で、割り当て解除して `az vm start` し直しても変わりません（公式ドキュメントで要確認）。SSH できなくなったときに変わっているのは、たいてい **自分の側のグローバル IP（MYIP）** です。上の「SSH の受け口を自分の IP だけにする」の2行で、NSG の規則を今の MYIP に直します。
- `az group delete --no-wait` はすぐに戻りますが、削除は裏で数分かかります。直後の `az group list` には `rg-labnote` が（状態 Deleting で）残っているので、数分待ってから確かめます。

## もう1つの方法：Azure Container Instances（要点だけ）

- labnote をコンテナのイメージにして（`python:3.12-slim` に labnote を入れ、`CMD ["labnote-bot"]`）、Azure Container Registry などに置き、`az container create` で1つだけ動かします。VM の OS の更新が要らないのが利点です。
- トークンは `--secure-environment-variables DISCORD_TOKEN=…`（ポータルに値が表示されない環境変数）で渡すか、Key Vault から読みます。
- 記録は、コンテナを作り直すと消えるので、**Azure Files** の共有をボリュームとしてマウントして `LABNOTE_HOME` にします（`--azure-file-volume-share-name` など。要確認）。
  ⚠ Azure Files は SMB のネットワークのファイルシステムで、**SQLite の WAL（labnote が使う書き方）はネットワークのファイルシステムでは正しく動かない**ことが SQLite の公式ドキュメントに書かれています。使うなら labnote.db はコンテナの中の一時的な場所に置き、起動するたびに `labnote reindex` で Azure Files の `notes/`・`data/` から作り直す、のような工夫が要ります。
- 常に動かすと、VM より高くなることがあります（料金は公式サイトで要確認）。止めるのは `az container stop`、消すのは `az group delete`。

この手間があるので、この本では **VM の方法を勧めます。**
