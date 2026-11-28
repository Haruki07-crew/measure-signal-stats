# measure-signal-stats

自宅でひとりで進める **電子計測 × 信号処理 × 統計** の実験教科書と、実験ノートを管理する道具です。

- **教科書**：[`textbook.html`](textbook.html)（1ファイル。ブラウザで開くだけで読めます）。GitHub Pages で公開している場合は https://haruki07-crew.github.io/measure-signal-stats/ からも読めます。
- **ノートブック**：[`notebooks/`](notebooks/)（34冊。Google Colab か Jupyter で、Pico やセンサがなくても動く部分を上から順に試せます）。
- **実験ノートと Discord bot**：[`labnote/`](labnote/)（実験のメモと結果を Markdown＋SQLite で残す CLI と、Discord から記録を送る・見る bot。Raspberry Pi・Azure で動かす手順つき）。

## 想定している読者と内容
- 高専・大学の学生（Python が書ける、統計の基礎を学んだ）が、Raspberry Pi Pico 2 W・Raspberry Pi 5・Mac など手持ちの機材で、計測と解析を一通り体験する。
- 入門（Lチカ・はんだ付け・I2C センサ・サーボ）→ 電子計測（I-V 特性、MOSFET、コンデンサ、モータ、ダイオード）→ データ収集（Pi、通信、データベース）→ GPU の使い方 → 音響信号処理（離散時間信号から音源分離まで）→ 最終演習。
- 読む道筋と所要時間は、教科書の表紙の「読む道筋と所要時間」にあります（配属前の必修の道は約40〜60時間）。

## 始める前に
- **買う物を決める**：教科書の付録B-2「購入リスト」で、すでに持っている物にチェックを入れます。チェックした物は「持っている物」に移り、残った物が買う物になります（チェックはブラウザの中だけに保存されます）。本文の「手持ち」「買い足す」は著者の環境を基準にした言い方です。
- **よくある質問**：[`FAQ.md`](FAQ.md)（Mac でないといけないか、部品の代用、Raspberry Pi 5 なしで進められるか、費用、どの章から始めるか など）。
- **Claude Code に質問する**：このリポジトリをクローンし、そのフォルダで Claude Code を起動すると、[`CLAUDE.md`](CLAUDE.md) の案内に沿って教科書の該当する章を探して答えます。

  ```bash
  git clone https://github.com/Haruki07-crew/measure-signal-stats.git
  cd measure-signal-stats
  claude
  # 例：「Windows でも進められますか？」「サーボを SG90 に代えてもいいですか？」
  ```

## 安全について
電池・モータ・はんだごて・大きな音を扱います。教科書の「全章共通の約束」と、各章の冒頭の「安全の最小カード」を必ず読んでから進めてください。部品の定格・極性・接点の種類は、赤い「必ず確認」の印の所でデータシートを確かめてください。この教科書のとおりに作業して生じた損害について、著作者は責任を負いません。

## ライセンス
- 教科書の文章と図：CC BY 4.0（[`LICENSE-CONTENT.md`](LICENSE-CONTENT.md)）
- コード（本文中のコード、`notebooks/`、`labnote/`）：MIT（[`LICENSE`](LICENSE)）
- 引用と著作権の確かめ方：[`COPYRIGHT_CHECK.md`](COPYRIGHT_CHECK.md)

著作者：Haruki07-crew
