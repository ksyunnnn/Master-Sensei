# ADR-034: events 登録基準 ── チャネル分類法と2層プロトコル

Status: accepted
Date: 2026-07-06
Supersedes: ADR-003 の events Write基準（inclusion 判定部分）

## Context

ADR-003 の events Write基準は「対象シンボルの価格に**影響しうる**イベント → 登録」だった。運用の結果、この基準には構造的欠陥があることが判明した。

素朴な登録基準は2案あり、**欠陥が逆向き**で、片方の修正では解けない:

- **案A「実際に価格が動いたイベントを登録する」**: 登録判断は scan の時点で行うが、「動いたか」が判明するのは事後。未来を知らないと適用できない（**look-ahead バイアス**）。さらに「その時は無風で、後から効いてくる」slow-burn なイベントを構造的に取りこぼす。
- **案B「価格に影響しうるイベントを登録する」（ADR-003 現行）**: 「影響しうる」は明確な境界を持たない**曖昧述語**。判断者・その日の状況でブレ、時間とともに解釈がドリフトする（**陳腐化**）。

実害の実例（2026-07-01）: 「Meta が余剰 AI compute を cloud 再販」との報道は、半導体を直接動かした discrete 触媒（当日 SOXX −6.41%）だったが、"positioning の一部" と解釈され events に登録されないまま失われた。後日この下落の因果を再調査する必要が生じた ── これは「入力データから再導出できない外部事実を記録し損ね、過去の因果が失われる」という Decision Tracking Principle（ADR-003 冒頭, Verraes 2019）の失敗そのものである。

案A の欠陥は「時間の向き」（事後情報を事前判断に使う）、案B の欠陥は「境界の曖昧さ」。この2つを**別々の居場所に配置し直す**設計が必要になった。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: realized impact（動いたか）で登録 | 客観的・事後検証可 | scan 時点に適用不能（look-ahead）、slow-burn 取りこぼし | 不採用 |
| B: 「影響しうるか」で登録（ADR-003 現行） | ex-ante に適用可 | 曖昧述語でブレ・陳腐化。個別判断を毎回要求 | 不採用（本ADRで supersede） |
| C: チャネル分類法＋2層プロトコル＋採点ループ | 中核は decidable な lookup、周縁は構造化判断＋可逆捕捉、realized impact は出口の採点のみで使用 | チャネル台帳の事前整備・保守コスト | **採用** |

## Decision

> events の登録は、以下の**2層**で判定する。inclusion 判定に realized price impact（実際に動いたか）を**用いない**（look-ahead 禁止）。
>
> **Rule層（中核・decidable）**: 事前登録された「チャネル台帳」（`docs/event-channels.md`, git 版管理）への**照合**。イベントが台帳のいずれかのチャネルへのショックなら登録する。どのチャネルにも当たらず、新規経路の兆候もなければ登録しない。判定は個別のフワフワ判断でなく、台帳との lookup に落ちる。
>
> **Standard層（周縁・曖昧ケース）**: 台帳に綺麗に当たらないイベントは、下記の固定サブ質問で**構造化判断**し、**迷う場合は `impact=neutral`・低 relevance で捕捉する**（登録は安価で可逆、非捕捉は恒久的サイレント損失＝非対称）。新規経路の疑いは台帳の「候補チャネル」節に記録する。
>
> **出口（採点）**: realized impact は事後採点（`review-events`）でのみ用い、チャネル台帳の**昇格/降格**に反映する。台帳の変更は明示的な版管理された編集として行い、ドリフトを監査可能にする。
>
> **verification は inclusion と独立のゲート**: ソースの信頼性（Tier1-2 × 2ソース等, ADR-010）は「載せると決めた事実を信じてよいか」の検証であり、「載せるべきか」の inclusion 条件ではない。

**Standard層の固定サブ質問（Mediating Assessments Protocol, 各々独立に答えてから総合）:**
1. 伝播チャネルが想定できるか（できれば *どれ* か／新規なら候補として台帳にメモ）
2. どの銘柄へ波及するか。direct / indirect / background のどれか
3. 価格系列から再導出できる事実に過ぎないか（Yes なら除外 ── 値動きそのものは Parquet の領域）
4. 既存 events と重複しないか（dedup 基準は timestamp + category + summary, ADR-003 を継承）

**impact 既定は neutral**（ADR-010 のバイアス補正を継承）。realized impact が確認されるまで方向を主張しない。

## Rationale

決定 C は複数の確立した理論が同一の結論に収束する:

- **Value of Information（Howard 1966）**: 記録に値する情報＝「どの決定が最適かを変えうるもの」。チャネルは我々の決定曲面（regime 入力・entry/sizing・predictions）への入力として定義され、「世界について影響しうるか（不可知）」を「我々の決定規則の入力か（可知）」に置換する。
- **Markov blanket / boundary（Pearl）**: ターゲットの Markov boundary は、予測に必要十分な最小変数集合であり、boundary の外の変数は boundary を知れば余剰。世界の網羅ではなく boundary（＝少数チャネル）だけを記録すれば、過剰登録と過少登録を同時に回避できる。チャネル台帳を意図的に小さく保つ理由。
- **事前登録された materiality（SASB Materiality Map の方法論）**: 「何がその業種の財務業績を歴史的・実証的に動かすか」を事前に確定し版管理する。個別イベントごとの陳腐化する判断を、明示的・版管理されたチャネル台帳の編集に置き換える。
- **Rules vs Standards（Kaplow 1992）**: 頻度が高く均質な中核は rule（ex ante に確定＝lookup）、稀で異質な周縁は standard（ex post に判断）で扱うのが最小コスト。2層構造はこの使い分けの実装。
- **Clinical vs Actuarial Judgment（Dawes, Faust & Meehl 1989）**: formula 化不能な領域では、判断を「頭の中の case-by-case」でなくモデル（台帳）構築へ向ける。周縁の構造化判断の出力が採点され、台帳を育てる。
- **Noise / Mediating Assessments Protocol（Kahneman, Sibony & Sunstein 2021）**: 総合直感でなく固定サブ質問を独立に答える decision hygiene が、判断者・セッション間のノイズを低減する。
- **非対称エラー設計**: 非捕捉＝恒久的サイレント損失、過剰捕捉＝可逆（`events.status` の dismiss）。期待コストが非対称なので、曖昧時は捕捉側に倒す。これが案A/B が取りこぼす slow-burn への設計的回答。
- **event study 法（MacKinlay 1997 / Kothari 2008）**: realized abnormal return による materiality 測定は、inclusion（入口）でなく事後採点（出口）に位置づける。「動いたか」の情報を、決定の入口に混ぜず出口の台帳保守にのみ使うことで look-ahead を排除する。

## Consequences

- **新規 `docs/event-channels.md`（チャネル台帳）を SoT として作成**。git 版管理。本 ADR は台帳の実体（チャネルの具体リスト）を持たない ── ADR は immutable、台帳は育つ living データなので分離する（台帳を ADR 本文に書くと、更新のたびに ADR 不変ルールを破る）。
- **自己修正ループの接続**: `review-events` を「事後採点 → チャネル昇格/降格」に接続する。昇格/降格は台帳ドキュメントの明示編集として行い、git diff がドリフトの監査証跡になる。
- **スキル手順の更新**: `scan-market` / `scan-market-quick` / `entry-analysis` の events 登録手順を2層プロトコルに合わせて改訂する（各 SKILL.md, 別作業）。
- **ADR-003 の扱い**: events の inclusion 基準は本 ADR により supersede。本 ADR が accepted になった時点で、ADR-003 の Status/該当節に「events の inclusion 基準は ADR-034 により一部 supersede」と注記する（Nygard 慣行: 旧 ADR の substance は書き換えず、supersede ポインタのみ付す）。dedup 基準・impact neutral 既定（ADR-010）は継承。
- **将来の見直しトリガー**:
  - lookup をコードで自動化する／events 行にチャネルを DB 側の整合制約付きで持たせたくなった場合 → 台帳の構造化フォーマット化（YAML/JSON）または DB テーブルへの昇格を再検討（可逆な移行）。
  - チャネル台帳が肥大化（目安 >12）した場合 → Markov boundary の最小性が崩れていないか再評価。
  - 採点データが特定チャネルの無効を示した場合 → 降格。
