# GDR-001: 成長計測体系の設計

Status: proposed
Date: 2026-03-27

## Context

Master Sensei Lv.1（見習い）の現段階で、成長を計測する仕組みが不足している。

- **市場判断の成長**: Brier Score, Calibration Curveが設計済み（Charter §4）だが、予測1件のため未稼働
- **システム設計の成長**: ADR + CLAUDE.md Rulesで記録しているが、計測する仕組みがない
- **学習サイクルの完遂**: 予測→結果→知見→次の予測、という連鎖が追跡されていない

Charterの習熟度Lv.1-5は件数・スコアベースだが、Lv.2到達前（N<30）の成長を可視化する手段がない。

## Research

4領域から12の手法を調査した。

### 領域1: 予測・意思決定の成長計測

| 手法 | 出典 | 計測対象 |
|------|------|---------|
| Brier Score 3成分分解 | Murphy (1973), Tetlock | Reliability（較正）, Resolution（情報弁別力）, Uncertainty（基準分散） |
| Baseline Score | Metaculus | 無情報ベースライン（50%）との比較。知識が付加価値を生んでいるか |
| Log Score | Metaculus, Good Judgment | 極端な外しへの厳格なペナルティ |
| Decision Journal | Annie Duke, Shane Parrish | 判断時点の思考の永続化。結果主義（Resulting）の排除 |
| Spaced Repetition (SM-2/FSRS) | Wozniak, Anki | 知識定着率。復習間隔の最適化 |

**重要な発見**: Brier Scoreの3成分分解により「何が良くて何が足りないか」を特定できる。Resolutionの推移で「情報弁別力の成長」、Reliabilityの推移で「較正の改善」を分離追跡可能。N≧30で統計的に有効。

### 領域2: SRE・システム成熟度

| 手法 | 出典 | 計測対象 |
|------|------|---------|
| Error Budget / Burn Rate | Google SRE | 許容失敗率の消費速度。行動モード自動切替 |
| CMMI成熟度モデル | Carnegie Mellon SEI | プロセス成熟度5段階。定量的管理への移行条件 |
| OKR/KPI | Google, Intel | 四半期目標と継続的ヘルスチェック |
| Post-mortem metrics | SRE | 「同じ失敗を繰り返しているか」の定量化 |

**重要な発見**: Error Budget Burn Rateにより「いつ改善に集中すべきか」を定量判断できる。Charter §6のError Budget概念に「消費速度」の軸を追加可能。N≧10で実用的。

### 領域3: AI自己評価・メタ認知

| 手法 | 出典 | 計測対象 |
|------|------|---------|
| Reflexion | Shinn et al. (NeurIPS 2023) | 言語的反省をエピソード記憶に蓄積。重み更新不要で+20%改善 |
| CoALA | Princeton (2023) | 4メモリ分類（Working/Procedural/Semantic/Episodic） |
| MemGPT/Letta | Packer et al. (2023) | 3層メモリ管理（Core/Conversational/Archival） |

**重要な発見**: Master SenseiはCoALAの4メモリ分類にほぼ完全に対応。設計の妥当性が外部理論で裏付けられた。

| CoALA | Master Sensei |
|-------|--------------|
| Working Memory | SessionStart Hook注入状態 |
| Procedural Memory | CLAUDE.md + Charter |
| Semantic Memory | knowledge DB + Parquet |
| Episodic Memory | predictions + regime_assessments |

Reflexionの「言語的反省→エピソード記憶」は、予測ポストモーテム→knowledge DBへの連鎖として形式化可能。

### 領域4: 人間の成長メカニズム・学習科学

| 手法 | 出典 | 計測対象 |
|------|------|---------|
| Deliberate Practice | Ericsson (1993) | 意図的練習の4条件（目標/フィードバック/挑戦/反復） |
| Dreyfus Model | Dreyfus & Dreyfus (1980) | 5段階の技能習得（Novice→Expert）。ルール依存→直感的判断への移行 |
| Growth Mindset / Metacognition | Dweck (2006), Schraw & Dennison (1994) | メタ認知的知識と制御 |
| Kolb's Experiential Learning | Kolb (1984) | 経験→省察→概念化→実験のサイクル |
| EPA (Entrustable Professional Activities) | ten Cate (2005) | 活動単位ごとの信頼度追跡（医学教育） |
| Bloom's Taxonomy | Bloom (1956) | 認知プロセス6段階（記憶→創造） |

**重要な発見**:
- Dreyfusモデルの5段階はCharter Lv.1-5と構造が一致。「ルール依存→パターン認識→直感的判断」の移行を`reasoning_type`で追跡可能
- EPAの「活動単位ごとの信頼度」は、予測件数が少なくてもプロセス面の成長を可視化できる
- Kolbサイクルの「完遂率」が最も重要な指標。予測→結果→知見→次の予測の連鎖がMaster Senseiで最も欠けている部分

### 領域横断の共通原則

4領域から6つの共通パターンを抽出した。

1. **サイクルを閉じる** — Kolb, SRE Post-mortem, Reflexion, Deliberate Practice全てが「経験→振り返り→概念化→次の行動」の完遂を成長の最低条件としている
2. **結果ではなくプロセスを評価する** — Annie Dukeの結果主義排除、SREのBlameless Post-mortem、Growth Mindsetの「失敗=学習機会」
3. **段階的に信頼を拡大する** — EPA, Dreyfus, CMMI, Charter Lv.1-5が同一構造
4. **分解してから統合する** — Brier 3成分分解, Bloom, Charter §3.3 MAP方式
5. **判断時点のスナップショットを永続化する** — ADR-003 Decision Tracking Principle, Decision Journal, Reflexion
6. **統計的最小Nを意識する** — Brier≧30, Calibration≧50, Error Budget≧10, EPA≧連続N回

## Options

### Phase 1（最小実装）

| 施策 | コスト | 得られるもの | 採否 |
|------|--------|------------|------|
| `knowledge.source_prediction_id` カラム追加 | 1カラム | Kolbサイクル完遂率の追跡 | **採用** |
| 予測解決時に `root_cause_category` 記録 | 1カラム | 失敗パターンの分類と再発率 | **採用** |
| Brier Score 3成分分解の算出関数 | コードのみ | Reliability/Resolutionの分離追跡 | **採用** |
| Baseline Score算出関数 | コードのみ | 無情報ベースラインとの比較 | **採用** |

### Phase 2（中規模）

| 施策 | コスト | 得られるもの | 採否 |
|------|--------|------------|------|
| `epa_assessments` テーブル | 新テーブル（5カラム） | 活動単位ごとの信頼度追跡 | **採用** |
| knowledge SRSフィールド | 2-3カラム | 知見の動的再検証スケジュール | **採用** |
| Error Budget Burn Rate | コードのみ | 行動モード自動切替 | **採用** |

### Phase 3（発展）

| 施策 | コスト | 得られるもの | 採否 |
|------|--------|------------|------|
| Calibration Curve定期生成 | コードのみ | 過信/過小評価の検出（N≧50） | **採用** |
| カテゴリ別Brier Score | コードのみ | 得意/不得意領域の特定 | **採用** |
| `predictions.reasoning_type` | 1カラム | Dreyfus段階移行の追跡 | **採用** |

### 不採用

| 手法 | 理由 |
|------|------|
| Elo Rating | 比較対象（複数エージェント）が前提。単独システムに不向き |
| 知識グラフ (Zep Graphiti) | 知見6件のスケールでは不要。Lv.5（100件超）で再評価 |
| FSRS機械学習最適化 | レビュー回数不足で学習データが足りない。SM-2簡略版で十分 |
| DSPy プロンプト自動最適化 | プロンプト自動書換えはADR-003のガバナンス（明示的変更記録）と矛盾 |
| MemGPT自律メモリ管理 | 既にCoALA対応の3層構造あり。ADR-003のルールベース管理の方が金融ドメインで適切 |
| CMMI全面適用 | 個人+AIシステムには過剰。エッセンスのみ借用 |
| Peer Score | 比較対象が存在しない。Baseline Scoreで代替 |

## Decision

> Phase 1-3の段階的導入を採用する。
> Phase 1はLv.1段階（現在）で即時実装可能。予測件数に依存しないプロセス指標でLv.2到達前の成長を可視化する。
> Phase 2はLv.2到達時（予測≧30件）に実装。EPAとSRSで成長追跡を多面化する。
> Phase 3はLv.3到達時（Brier<0.25）に実装。統計的に有意な分析が可能になる段階。

## Charter Impact

- **§1 Identity**: Lv.2-5の昇格基準にEPA信頼度、サイクル完遂率を追加候補
- **§4 Self-Evaluation**: Brier 3成分分解、Baseline Score、Error Budget Burn Rateを追加
- **§4.4 事後検証サイクル**: root_cause_categoryによる失敗パターン分類を追加
- **§5 Knowledge Management**: source_prediction_idによるKolbサイクル連鎖、SRSによる動的再検証スケジュール

Charter改訂はPhase 1実装後、十分なデータ（N≧10）が蓄積されてから実施する。

## Consequences

- Phase 1実装のADRを作成（ADR-009）
- `knowledge`テーブルに`source_prediction_id`カラム追加
- `predictions`テーブルに`root_cause_category`カラム追加
- db.pyにBrier 3成分分解・Baseline Score算出関数を追加
- CLAUDE.mdの文書構造セクションにGDRを追加
- 見直しトリガー: Lv.2昇格時、またはPhase 1実装後3ヶ月
