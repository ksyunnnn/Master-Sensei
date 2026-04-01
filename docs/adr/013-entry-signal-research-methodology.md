# ADR-013: エントリーシグナル研究の方法論

Status: accepted
Date: 2026-03-30

## Context

毎晩エントリー判断を提案するSkill（またはツール）の設計にあたり、
シグナルのアイデアを大量に検証し、実証的に有効なものだけを採用する必要がある。

課題:
- 多数のアイデアを同時検証すると偽発見（多重検定問題）が発生する
- 小サンプル（日足1256日、5分足197日）で効果量の検出力に限界がある
- バックテスト過適合のリスク（Bailey & López de Prado 2014）

6領域の方法論を調査し、統合的なフレームワークを設計した。
さらに5つのアイデア生成手法（SCAMPER、逆ブレインストーミング、前提反転、ビソシエーション、de Bono Po）を
適用し、30カテゴリ・約900-1100仮説の空間を構築した。

仮説空間の詳細: `data/research/hypothesis_space.md`

## 参照した方法論

| 領域 | 核心 | 適用箇所 |
|------|------|---------|
| 統計学: BH法（FDR制御） | 多重検定でBonferroniは厳しすぎ、FDR制御が実用的 | Stage 2フィルタ |
| クオンツ: Deflated Sharpe Ratio | 試行回数を記録しないバックテストは無意味 | 全試行記録の義務化 |
| A/Bテスト: 検出力分析 | 事前にMDE（最小検出可能効果）を定義 | Stage 1前の事前分析 |
| 創薬: スクリーニングファネル | 早期は偽陰性回避、後段で厳格化 | Stage 1/2の閾値設計 |
| ML: 特徴量選択 | Filter→Wrapperの二段。安定性も評価 | Stage 1=filter, Stage 2=wrapper |
| VC: ディールフロー | Fast screen→Due diligence。thesis fitが重要 | Stage 3のthesis適合評価 |

## Decision

> 3段階スクリーニングファネルで検証する。全試行を記録し、フィルタ基準は事前定義。

### データソース

| データ | 期間 | 用途 |
|--------|------|------|
| 日足 10銘柄 | 2021-03〜2026-03（1256日） | 長期パターン、曜日効果 |
| 5分足 4銘柄（SOXL/TQQQ/TECL/SPXL） | 2025-06〜2026-03（197日） | 日中パターン。backtestリポジトリから66日分を結合 |
| マクロ 9指標 | 2025-03〜2026-03 | レジーム条件付き分析 |
| DuckDB（イベント・知見） | 全期間 | イベント密度分析 |

5分足はmaster_senseiの130日にbacktest/data/cache/intraday/の66日（2025-06-26〜2025-09-25）を結合。
重複期間はmaster_sensei側を優先。カラム構造は同一（OHLC）。

### 結果の保存

全検証結果を `data/research/signal_ideas.csv` に記録する。

カラム: id, agent, category, hypothesis, direction, symbols_tested, n_samples,
metric_name, metric_value, pvalue, regime_condition, holding_period, source, raw_detail

### Stage 1: スクリーニング（偽陰性回避）

| 条件 | 閾値 |
|------|------|
| サンプル数 | N >= 30 |
| 方向性 | ランダムより良い傾向がある（一致率>50% or 正の相関） |

脱落したものも全件記録（試行回数の追跡。DSRの前提）。

### Stage 2: 検証（統計的厳密性）

| 条件 | 閾値 | 根拠 |
|------|------|------|
| BH法補正後 p値 | < 0.20 | FDR 20%制御。小サンプルで5%は厳しすぎ |
| Walk-forward検証 | 2分割以上のOOS期間で符号一致 | バックテスト過適合防止 |
| レジーム安定性 | 2レジーム以上で同方向 | レジーム依存の偽シグナル排除 |
| 複数銘柄再現 | 2銘柄以上 | 銘柄固有ノイズ排除 |

### Stage 3: 実用性評価

| 観点 | 評価内容 |
|------|---------|
| Thesis fit | JST制約・IFD-OCO・レバETF・デイトレ/スイングとの適合性 |
| 独立性 | 他の通過シグナルと相関が低いか |
| 実装シンプルさ | 毎晩の運用で計算可能か |
| 効果量 | DSR補正後のSharpe or 実用的なリターン改善幅 |

### 仮説空間

30カテゴリ、約900-1100仮説。詳細は `data/research/hypothesis_space.md` を参照。

生成に使用した手法:
- ドメイン知識 + Web調査12件 → Cat 1-10
- Zwicky Box（形態学的分析） → 次元Bの欠落発見、Cat 14-17
- SCAMPER → Cat 11-13
- 逆ブレインストーミング → Cat 18
- 前提の反転 → Cat 19-22, 26-28
- ビソシエーション（異分野衝突） → Cat 21, 22, 25, 29, 30
- ランダム刺激 → Cat 23, 24
- de Bono Po（挑発） → Cat 18, 25

### 研究の実行体制

4並列のAgentで分担:

| Agent | 担当カテゴリ | 推定仮説数 |
|-------|------------|----------|
| A: シグナル定量アナリスト | Cat 1, 2, 5, 9, 11, 16, 23, 25, 26 | ~250 |
| B: レジーム条件付きアナリスト | Cat 3, 7, 8, 13, 17, 18, 27, 28 | ~250 |
| C: 出口戦略・構造アナリスト | Cat 6, 14, 19, 20, 21, 22, 24, 29, 30 | ~250 |
| D: 外部知見リサーチャー | Cat 4, 10, 12, 15 + 全カテゴリの文献裏付け | ~150 + 文献 |

## バイアス対策（2026-03-31追記）

### 背景

LLM Agentは「コードを実行するだけ」ではなく、コードを書き・選び・解釈する各段階でバイアスが入る。
自律Agentはsycophancy脆弱性が対話型より高く（88% vs 35%, arXiv 2411.15287）、
RLHFにより29-41%のポジティビティバイアスを持つ（Sweetser 2025）。

役割としてのDevil's Advocate Agentは逆効果（cognitive bolstering, Nemeth 2001）。
DAの権限は事前定義基準から来るべき（POPPER 2025）。

### 対策1: utils.pyの反証テスト関数群

Devil's Advocateを「Agent」ではなく「反証テスト関数」として実装する。

| テスト | 内容 | 全仮説で判定に使用 |
|--------|------|------------------|
| シャッフルテスト | 日付ランダム並替で同結果が出ないか | **必須** |
| ランダムデータ対照 | 既知ランダム系列での偽陽性率 | **必須** |
| 逆方向テスト | 反対方向でも同等に機能するか | **条件付き** |
| 期間除外テスト | 特定期間を除くと消失するか | **条件付き** |

設計原則:
- 全テストを全仮説に対して**実行**する（データは常に取る）
- **判定に使う**のはカテゴリタイプに応じたテストのみ
- 判定に使わなかった結果もCSVに記録（後から見直し可能）

### 対策2: カテゴリタイプ別の反証テスト適用ルール

| タイプ | 判定に使うテスト | 例 |
|--------|----------------|-----|
| 無条件シグナル | 4つ全て | 曜日効果、開場後パターン |
| レジーム条件付きシグナル | シャッフル + ランダム対照 + 逆方向 | 高VIX→平均回帰 |
| 方向固定シグナル | シャッフル + ランダム対照 + 期間除外 | VIXスパイク→下落 |
| 構造的シグナル | 4つ全て | レバETFリバランスフロー |

- 複数タイプに該当するカテゴリは、判定テストが少ないほう（緩いほう）を採用する
- 分類に迷うカテゴリも同様に最も緩いタイプに入れる（Stage 1の偽陰性回避思想と整合）
- 67カテゴリ×タイプの対応表はAgent起動前に確定させる → **確定済み（2026-03-31）**
- 各反証テストの具体的な手順・閾値・判定基準はutils.pyのdocstringに定義する（本ADRは方針決定のみ）

#### 分類結果サマリー（2026-03-31確定）

| タイプ | 件数 | 判定に使うテスト |
|--------|------|----------------|
| unconditional | 37 | 4つ全て |
| regime_conditional | 15 | シャッフル + ランダム対照 + 逆方向 |
| structural | 9 | 4つ全て |
| direction_fixed | 7 | シャッフル + ランダム対照 + 期間除外 |

全件の分類と判断根拠: `data/research/ideation_catalog.parquet` の `bias_test_type` / `bias_test_type_reason` 列。

判断原則:
- 複数タイプに該当する場合、判定テストが少ないほう（緩いほう）を採用
- 元シグナルのタイプが事前不明なメタカテゴリ（Cat-16逆シグナル、Cat-45遅延エントリー）はunconditionalにデフォルト
- VIX「水準」を観測する（Cat-03）とVIX「レジーム条件」で戦略を切り替える（Cat-07）は区別。前者はunconditional、後者はregime_conditional

情報アクセスの設計:
- hypothesis_space.md = Source of Truth（全情報: サブシグナル詳細、パラメータ、相互参照、注意書き）
- ideation_catalog.parquet = 構造化インデックス（クエリ用: id, name, description, bias_test_type, bias_test_type_reason）
- Agentはまず Parquet をクエリし、詳細が必要な場合は hypothesis_space.md の該当セクションを参照する
- Parquet スキーマの拡充（Agentが必要とする情報の構造化）はutils.py実装後、Agent起動前に実施する（タスクd-pre）

### 対策3: Agentプロンプト設計

| 対策 | 防ぐバイアス | 根拠 |
|------|------------|------|
| 生成と検証の分離 — Agentは検証のみ | 自己確認バイアス | ACM ICAIF 2025 |
| 反証の義務化 — 「無効である証拠」報告必須 | 確認バイアス | POPPER 2025 |
| 第三者フレーミング — 「仮説ID: H-042」で渡す | sycophancy | arXiv 2411.15287 |
| null結果の明示的要求 — 「シグナルなし」の例を含める | ポジティビティバイアス | Sweetser 2025 |
| 全件強制記録 — 通過・脱落問わずCSVに書く | 選択的報告 | Bailey & López de Prado 2014 |

### 対策4: 異種モデル混成

現時点では見送り。Claude同種4台で開始し、Stage 1結果を見てから再判断する。
見送り理由: 追加効果が事前に見積もれない。データに基づく判断を優先。

### 参照文献（バイアス対策）

- Nemeth, C.J. et al. (2001). Devil's advocate versus authentic dissent. European J. of Social Psychology, 31, 707-720.
- Schweiger, D.M. et al. (1986). Group Approaches for Improving Strategic Decision Making. Academy of Management J., 29(1), 51-71.
- Sharma et al. (2025). Sycophancy in LLMs: Causes and Mitigations. arXiv 2411.15287.
- Sweetser (2025). LLM Positivity Bias in Strategic Analysis.
- POPPER (2025). Automated Hypothesis Validation with Agentic Sequential Falsifications. arXiv 2502.09858.
- ACM ICAIF (2025). Your AI, Not Your View: Bias of LLMs in Investment Analysis.
- arXiv 2509.08713. Hidden Pitfalls of AI Scientist Systems.
- Murrell, A.J. et al. (1993). Consensus vs devil's advocacy: Task structure influence. J. of Business Communication, 30, 399-414.

## 既知の実証結果（本ADR作成時点）

| 仮説 | 結果 | 知見ID |
|------|------|--------|
| プレマーケットの方向が正規取引を予測する | 否定（一致率50.77%） | K-017 |
| 開場後30分が残り時間を予測する | 否定（一致率50.8-56.9%, 相関~0） | K-018 |
| 開場後60分が残り時間を予測する | 微弱な肯定（一致率60.8-64.6%）ただしレジーム不安定 | K-018 |
| 前日リターンが翌日を予測する | 否定（一致率47-50%, わずかに平均回帰） | K-019 |

## Consequences

- `data/research/` ディレクトリを作業場として使用
- 全Agentの出力を `signal_ideas.csv` に統合
- Stage 1/2のフィルタは機械的に適用（恣意性排除）
- Stage 3のみMaster Senseiが判断し、根拠を付記
- 検出力分析をAgent起動前に実施し、検出不可能な効果量を明示する
- 見直しトリガー: 5分足データが500日を超えた時点でStage 2閾値を再評価
