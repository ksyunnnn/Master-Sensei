# WIP: エントリーシグナル研究 進捗

研究完了後にこのファイルは削除する。成果物は ideation_report.md / ideation_catalog.parquet / ADR-013 に残る。

## ファネル: 1000 → 100 → 10

> 1000のアイデアを検証し、100のアイデアを実験し、10のアイデアを実弾として提示する。

| 段階 | 対応 | 規模 | 状態 |
|------|------|------|------|
| **1000を検証** | Stage 1 スクリーニング（N≧30、方向一致率>50%） | 314事前登録×3339実行 | **完了: 48行通過** |
| **100を実験** | Stage 2 統計検証（BH法p<0.20、Walk-forward、レジーム安定性、複数銘柄） | Stage 1通過分 | **完了: 8行通過（4仮説）+準通過3** |
| **10を実弾** | Stage 3 実用性評価（JST制約・IFD-OCO適合・摩擦後期待値） | Stage 2通過分 | 未着手 |

**現在の候補**: 7仮説（Stage 2通過4 + VIXY準通過3）。目標10に3つ不足 → Round 2で補充必要。

## 残タスク

| # | タスク | 状態 | 依存 |
|---|--------|------|------|
| a | データ品質検証（Tiingo 5分足197日の整合性） | **条件付き合格** | — |
| a2 | Polygon 5分足データ取得（18銘柄×5年、OHLCV+n+vw） | **完了** | — |
| a3 | バイアス対策設計（反証テスト関数・カテゴリタイプ・プロンプト設計） | **完了** | — |
| a4 | カテゴリタイプ分類（68件→4タイプ、ideation_catalog.parquetにbias_test_type列追加） | **完了** | a3 |
| b | utils.py作成（検証テスト+反証テスト・BH法・Walk-forward・スプリット調整） | **完了** | a, a2, a3 |
| c | 検出力分析（Polygon 5年分でのMDE算出） | **完了** | a2 |
| d-pre | ~~Parquetスキーマ拡充~~ → ADR-021でsignal_defs.pyに統合。**不要** | **廃止** | — |
| d1 | signal_defs.py 信号生成関数 + HYPOTHESESリスト（ADR-021 Round 1準備） | **完了** | b, c |
| d1-review | d1 Look-Ahead Bias再チェック（163関数全件） | **完了** | d1 |
| d2 | signal_runner.py（HYPOTHESESを機械実行） | **完了** | d1 |
| d3 | Round 1 実行（全仮説スクリーニング） | **完了** | d2 |
| d4 | random_data_control修正、FRED 5年拡張、マクロ再実行 | **完了** | d3 |
| e1 | Stage 2実装・実行（BH/WF/レジーム/複数銘柄） | **完了** | d4 |
| e2 | Round 2（探索ラウンド、新仮説生成） | 未着手 | e1 |
| e3 | Stage 3（実用性評価、JST/IFD-OCO/摩擦後期待値） | 未着手 | e2 |
| f | 10アイデア選定 | 未着手 | e3 |
| g | Skill/ツール設計・実装 | 未着手 | f |

## 設計メモ

- 口座残高・許容損失は実行時パラメータ（ハードコードしない）
- 出力: シナリオ分析 + 具体注文候補(複数) + 実証ベース推奨
- 手段はSkillに限定しない（Python CLI等も検討）
- feasibility_study/trading-rules.mdの旧ルールは無視。白紙から再設計
- ユーザーの発注パターン: (P1)開場前発注 / (P2)開場1h内 / (P3)開場3h内(避けたい)
- サマータイム中の開場: 22:30 JST（標準時: 23:30 JST）
- 未定義: MAP分析のスコアリング枠組み（3要素の定義、-2〜+2スケール、加重方法）。タスク(f)完了後に正式定義する
- **外部データ依存**: 193サブシグナルの約45%（Cat 3,4,7,8,13,17,18,27,28,32,35,36,37,43,44,47,50,52,53,59等）はVIX/マクロ/イベントデータが必要。signal_defs.pyのヘルパー関数は現時点でOHLCV系のみ。外部データ用ヘルパーはd1実装時に追加する
- **signal_defs.pyヘルパー**: 28関数（既存25 + VIX期間構造, VIXスパイク, ストレス日数）。VIXヘルパーはCat 3,7,8,13,18,27,32,35,37用
- **signal_defs.py信号関数**: 163関数（47カテゴリ）。パラメータ展開含む（Cat 1高安距離×4期間、MA乖離×4期間等）
- **HYPOTHESESリスト**: 314エントリ（long/short展開。direction_fixed=12件は片方向のみ）
- **ROUND2_CANDIDATES**: 21カテゴリ、49サブシグナル（Stage 1結果依存8, 評価指標5, 非エントリー6, DuckDB依存2）
- **Look-Ahead Bias修正**: h_01_09（OR確定前バーをNaN化）、h_03_07（当日→前日の日中Volに変更）
- **signal_runner.py設計仕様（d2実装時の参照）**:
  - 全信号関数は `h_XX_XX(df) -> pd.Series` のインターフェース。dfのみ受け取る
  - HYPOTHESESエントリの `requires_macro` フィールド: runnerがマクロParquetを読み、日付ベースでdfに列マージ（例: `df['vix']`, `df['hy_spread']`）
  - HYPOTHESESエントリの `requires_pair` フィールド: runnerがペアシンボルのデータを読み、`df['pair_Close']`, `df['pair_Volume']`としてマージ
  - `timeframe` フィールド: `daily`（日足のみ）/ `daily_macro`（日足+マクロ）/ `intraday`（5分足）。runnerがデータ読込先を切替
  - マクロデータはN=252-268（~1年）。日足5年と結合時、マクロ範囲外はNaN
  - runnerはAgent裁量なし。HYPOTHESESを順次読み、screen_signal + 反証テストを機械実行
  - 結果はsignal_ideas.csvに記録（ADR-013準拠）
- **574テスト全パス**（signal_defs 290 + research_utils 101 + signal_runner 31 + その他152）
- **d1-review Look-Ahead Bias追加修正**: Critical 3件（h_12_02, h_72_01, h_72_02: transform伝播）、Important 1件（h_14_01: bfill→ffill）
- **float信号の反証テスト設計問題**: random_data_control（FP率≈50%）とreverse_direction_test（diff=0）はfloat信号で不適切。判定対象から除外し、データは記録する設計に修正
- **signal_runner.py**: 314仮説×10-18シンボル=3,468実行。データキャッシュ、エラー耐性、bias_test_type別判定を実装

## タスク(a) 品質検証結果

- 重複: 0件、時系列順序: OK、NaN/ゼロ: なし、OHLC整合性: OK
- バー数: 全営業日78本で一貫（初日のみ部分日あり）
- **要対応**: リバーススプリット3件（TQQQ 2:1、SQQQ 5:1、SOXS 20:1）。5分足は未調整。ADR-014で対処方針を決定済み

## タスク(a2) Polygon品質検証結果

- 基本品質: 全18銘柄で重複0、sorted、NaN 0、OHLC整合性OK、ゼロVolume/NumTrades 0
- リバーススプリット: **6銘柄で計15件**検出（SOXS 3, SQQQ 3, VIXY 4, TECS 2, TQQQ 2, SOXX 1）
- 短縮取引日: 年10日、43バー（ブラックフライデー翌日、7/3、12/24等）。全銘柄一致
- **UUP流動性問題**: 693日（55%）が78バー未満。5分足シグナルに使う場合は欠損バーの扱いに注意
- **TECS**: 141日（11%）が78バー未満。Bull側TECLは33日のみで非対称
- 極端リターン(>10%/5分): スプリット除外後129件。ほぼ全てオープニングバー(09:30)。オーバーナイトギャップが原因 → **オープニングバーを特別扱いする設計が必要**

## セッション中の気づき・学び（作業完了時に削除）

### データソース選定
- Tiingo IEXの`columns`パラメータでVolume取得可能だが、IEX出来高は全体の1-2%で相関0.69。プロキシとしては不十分
- Polygon.io無料プランでは5分足取得不可。Starterが必要（テストで判明）
- Polygon VolumeはSIPだが、adjusted=falseでも小数値。公式ドキュメントと実態が不一致

### 仮説生成プロセス
- **「既存仮説にデータを当てはめる」だけでなく「データから逆引きで新仮説を生む」視点が重要**。ユーザーの「Polygonのデータが網羅する内容を前提に出せるアイデアが他にないか」という問いがCat 68-72を生んだ
- データを見てから仮説を作るp-hackingリスクは、ADR-013 Stage 2の4フィルタ中3つ（BH法、レジーム安定性、銘柄再現）で防御可能。Walk-forwardだけは完全には防げない
- **「うまくいきそう」バイアス**（検証者が無意識に有望シグナルを丁寧に、不毛なシグナルを雑に検証する）→ ADR-013にバイアス対策セクション追記済み。Devil's AdvocateはAgent不要、utils.pyの反証テスト関数群+カテゴリタイプ別適用ルールで対策

### AI Agentバイアス対策（K-020, K-021）
- **「コード実行=バイアスなし」は誤り**。LLM Agentはコードを書き・選び・解釈する各段階でバイアスが入る。自律Agentのsycophancy脆弱性は88%（対話型35%）
- **Devil's Advocateは「Agent」ではなく「反証テスト関数」が最適**。役割としての反論はcognitive bolstering（元の立場強化）を引き起こす（Nemeth 2001）
- **異種モデル混成は「松を目指す」バイアスとサンクコストバイアスの影響下で判断していた**。まずClaude同種で動かし、データに基づき再判断する方針に修正
- **ファネル思想（宝を捨てたくない）が反証テスト設計の指針**。全テスト実行+タイプ別判定適用で、データは取りつつ不適切なテストで宝を捨てない設計

### プロセス改善
- ユーザーの「恣意性なく」「確証バイアスなく」という繰り返しの要求が判断品質を大幅に向上させた。特に「9ヶ月で本当によいか？」「Polygonを十分に活用できているか？」の問いかけがなければ、不十分なデータで研究を開始していた
- **松竹梅で松を目指す**方針が、IEX Volume(竹)→Polygon SIP(松)の判断を導いた
- condition.mdからの研究進捗分離（WIP-progress.md）は、ユーザー発案。セッション間の情報消失リスクを排除する実用的な改善

## ワークログ

### 2026-03-31 session 2: バイアス対策設計

**やったこと:**
1. 検証バイアス対策の3つの案（手順標準化/パラメータ固定/ブラインド評価）を検討
2. AI Agentのバイアスについて網羅的に調査（学術論文+Claude Code公式）
3. Devil's Advocateの最適形態を調査（組織研究/AI多Agent/科学査読/反証フレームワーク）
4. 反証テスト4種の設計とカテゴリタイプ4種の定義
5. 68カテゴリの分類実施（Parquetにbias_test_type/reason列追加）
6. 情報アクセス設計（hypothesis_space.md=SoT, Parquet=構造化インデックス）

**重要な方針転換（3回）:**
1. 「utils.pyだけで十分」→ 調査で誤りと判明。Agentプロンプト対策+反証テスト関数が必要
2. 「5台目のDevil's Advocate Agent追加」→ 調査で逆効果と判明。反証テストを関数化すればAgent不要
3. 「異種モデル（GPT-4o）混成」→ 自己バイアス（松バイアス/サンクコスト）を認識し見送り。データに基づき再判断

**学び（次セッション以降に活かすべき点）:**
- LLM Agentの「コード実行=バイアスなし」仮説は誤り。設計時に常にバイアスリストを参照する（K-020）
- Devil's Advocateは「役割Agent」より「事前定義テスト関数」が研究で支持されている（K-021）
- 判断前に「自分のバイアスは何か」を明示的に列挙すると、歪んだ判断を防げる（Memory: feedback_check_own_bias.md）
- hypothesis_space.mdはRead toolのトークン上限（10,000）を超える。DuckDBクエリなら情報欠落なくアクセスできる
- Parquetスキーマ設計は消費者（utils.py）のコードが先、スキーマが後。先回り最適化を避ける
- 「宝を捨てたくない」ファネル思想が全設計判断の一貫した指針になる

**次にやること:**
- (c) 検出力分析: Polygon 5年分でのMDE算出
- (d-pre) Parquetスキーマ拡充: utils.pyの要件に基づきAgentが必要とする情報を構造化
- (d) 4 Agent並列起動: Stage 1スクリーニング

### 2026-04-03 session 10: d1レビュー + d2実装 + d3実行（タスク d1-review, d2, d3）

**やったこと:**
1. d1 Look-Ahead Bias再チェック（163信号関数全件レビュー）
   - Critical 3件修正: h_12_02（transform('last')同日終値伝播）、h_72_01（アフターマーケット終値+翌朝Open同日伝播）、h_72_02（アフターマーケットVolume合計同日伝播）
   - Important 1件修正: h_14_01（bfill→ffillに変更、OpEx週フラグの逆伝播防止）
   - Important 6件注釈記録: time-of-day全体平均（h_02_04, h_25_01, h_25_02, h_68_02, h_71_01/02/03）は方向性に影響しないため許容
2. signal_runner.py TDD実装（31テスト → 574テスト全パス）
   - データ準備: merge_macro（FREDマクロParquet）、merge_pair（Polygon ETF）
   - ペアマッピング: BEAR_PAIR_MAP（Bull→Bear）、VIXY_PAIR_CATEGORIES（Cat 8）、CROSS_SECTOR_PAIR_MAP（Cat 11）
   - 反証テスト: 全4種実行 + bias_test_type別判定 + float/bool信号型別の判定除外
   - エラー耐性: 信号関数・screen_signal・反証テストのエラーを結果として記録
3. スモークテスト → float信号の反証テスト設計問題を発見・修正
4. Round 1 本実行開始（314仮説×10-18シンボル=3,468実行、推定77分）

**重要な発見（反証テスト設計問題）:**
- random_data_controlはfloat信号でFP率が常に~50%（ランダムリターンとの相関が正になる確率）
- reverse_direction_testはfloat信号でdiff=0（Spearman rは方向ラベルに依存しない）
- 解決: 全テスト実行してデータは記録するが、float信号ではこの2つを判定から除外

**データソース方針:**
- requires_macro → FREDマクロParquet（精度優先、N=252-268）
- requires_pair → Polygon ETFデータ（Bull/Bear対応、クロスセクター、VIXY）

## ワークログ

### 2026-04-02 session 9: 検出力分析 + ADR-021 + ヘルパー関数 (タスク c, d-pre再定義)

**やったこと（検出力分析に加えて）:**

6. ADR-021「シグナル定義と探索の実装方式」を起草・承認
   - 10+ソース調査（AlphaAgent, DFS, PAP, tsfresh, arxiv 2512.12924, Claude Code worktree等）
   - コンセプト: **Dig with intent, verify with discipline.**
   - 2ラウンド制: Round 1（確認: signal_defs.py→signal_runner.py機械実行）→ Round 2（探索）
   - 4 Agent並列→単一スクリプトに縮小（計算3分、Agent裁量不要）
   - タスク d-pre（Parquetスキーマ拡充）→ 不要に（signal_defs.pyが仮説定義のSoT）
7. `src/signal_defs.py` ヘルパー関数25個を TDD で実装
   - 61テスト（自己評価で不備23件追加修正: assert欠落1件、未テスト関数5件、境界7件、反例3件）
   - _bb_positionのstd=0対策修正
8. 自己評価実施 → 総合5.5/10。テスト品質の問題を検出・修正

**自己評価で発見した問題:**
- test_known_at_meanにassert文がなかった（Critical — 空テストで常にパス）
- 5/25関数がテストなし（TDD原則違反）
- 境界テスト・反例テストがほぼなかった
- ADR-021がユーザーに3回修正されてから完成（目的理解不足）

### 2026-04-02 session 9 (続): 検出力分析 (タスク c)

**やったこと:**
1. `compute_mde_binomial()` 実装 — scipy exact binomial + bisect法。正規近似より小サンプルで正確
2. `compute_mde_spearman()` 実装 — Fisher z変換による解析解
3. `power_analysis_report()` 実装 — 全シンボルの5分足読み込み→MDE一覧表
4. 36テスト追加（4層構造: 既知解4、境界4、不変量16(parametrize含む)、反例4、レポート5）
5. 全101テストパス

**MDE結果（α=0.20片側、power=0.80、全18シンボル、5年1254日）:**

| 粒度 | N | MDE二項 | MDE Spearman |
|------|---|---------|-------------|
| 日足 | 1,254 | 52.4% | |r|≥0.048 |
| 5分足バー | ~97,000 | 50.3% | |r|≥0.005 |
| WF2分割(日足) | 627 | 53.4% | |r|≥0.067 |

**解釈:**
- 日足ベースの仮説: 勝率52.4%以上のシグナルのみ検出可能。K-018(60-65%)は十分検出圏内
- 5分足バー単位: 50.3%で検出可能。バーレベルの仮説は高感度だが、ノイズも拾いやすい
- WF2分割: 各セグメント627日で53.4%。安定性要求でMDEが1%上昇
- UUP: バー数93,774（他シンボルは97,462）。流動性問題(55%が78バー未満)の影響

**コードレビュー修正（3件）:**
1. Critical: binom.isf + sf の off-by-one → 棄却域を1つ広く取り検出力過大評価。int化+sf(k_crit)に修正
2. Important: Fisher z近似の前提条件をdocstringに明記（fat-tail下で小サンプル過大評価）
3. Important: n_wf極小時のクランプをNaN返却に変更（実行不可能な状況の誤誘導防止）

### 2026-04-02 session 8: research_utils.py実装 (タスク b)

**やったこと:**
1. `src/research_utils.py` を新規作成（12関数、~700行）
2. `tests/test_research_utils.py` を新規作成（40テスト全パス）
3. `requirements.txt` に scipy, numpy を追加
4. TDDで5フェーズに分けて実装

**実装した関数:**
- データ読み込み: `load_daily`, `load_polygon_5min`（ADR-014スプリット調整含む）
- Stage 1: `screen_signal`（bool/float両対応、二項検定/Spearman相関）
- Stage 2: `bh_correction`, `walk_forward_test`, `regime_stability_test`, `multi_symbol_test`
- 反証テスト: `shuffle_test`, `random_data_control`, `reverse_direction_test`, `period_exclusion_test`
- 記録: `record_result`（fcntl.flock排他ロック、4 Agent並列対応）

**設計判断:**
- データパスは引数化（デフォルト: `../master_sensei/...`）。master_senseiは読み取り専用
- 日足indexがnaive、5分足indexがtz-awareの不一致 → Python dateで統一マッピング
- クロスアセット8銘柄は日足なし → スプリット調整係数=1.0
- numpy boolとPython boolの不一致 → `bool()`でキャスト

**テスト設計で学んだこと:**
- 全バーTrueのシグナルはシャッフルテストで意味をなさない（シャッフルしても同一）
- ランダムリターン×全True信号の偽陽性率は~50%（期待通り）
- 期間除外テストの脆弱シグナルは背景リターンを明確に負にしないと検出できない

**全テスト: 192 passed（既存152 + 新規40）**

### 2026-04-02 session 8 (続): コードレビュー + 修正 + チェックリスト導入

**レビュー方法:**
Web検索で11カテゴリのレビュー観点を収集し、コードレビュ���エージェントで全項目を検査。
自己バイアス（確証バイアス、テスト通過バイアス、スピードバイアス）を事前に列挙。

**発見・修正した問題（5件）:**
1. **Critical**: シャッフルテストp値���反保守的 → Phipson & Smyth (2010) 補正適用
2. **Critical**: record_result TOCTOU��合 → ロック取得後にfile_existsチェック
3. **High**: shuffle_test全True信号でno-op → 定数シグナル検出+早期リターン
4. **High**: float 0.0/1.0がboolと誤��定 → pd.api.types.is_bool_dtype使用
5. **High**: regime_stability_test N整合性 → screen_signal結果のn_samplesで判定

**ドキュメント導入:**
- ADR-020: 統計・金融コードのレビュー基準導入
- docs/code-review-checklist.md: 処方的チェックリスト（3領域: 統計的正確���、金融データ処理、並行処理）
- CLAUDE.md: Rules にチェックリスト参照を追加

**学び:**
- p値計算��+1補正は学術論文レベルの知識が必要。TDDだけでは防げない
- TOCTOU は「テストでは再現しにくいが本番で必ず起きる」並行処理バグの典型
- 自作コードのレビューは「テストが通っている=正しい」バイアスが強い。外部観点（Web調査+レビューエージェント）が必須

**全テスト: 192 passed（修正後も全パス）**

### 2026-04-02 session 8 (続2): テスト恣意性レビュー + テスト指針明文化

**調査した原則（Web調査）:**
- NumPy Testing Guidelines: seed固定は正当。決定論的テスト推奨
- Martin Fowler: 非決定論的テストの排除
- Oracle Problem: 参照実装比較、不変量テスト、変成テスト
- 科学Python: 4層構造（既知解・境界・不変量・反例）

**恣意性評価の再検証:**
- 先の評価で「恣意的」とした10件中、4件は過剰指摘と再判定
  - seed固定+既知解テストは正当（NumPy公式推奨）
  - 問題はテストの欠如と名前/assert不一致
- 本当の問題: テスト名詐欺2件、境界テスト欠如、不変量テスト欠如

**修正内容:**
1. テスト名/assert不一致修正: `test_random_signal_fails` → `test_noise_signal_structure`、`test_selective_signal_low_fp_rate` → `test_random_data_control_structure`
2. 境界テスト8件追加: screen_signal 51%/50%/N=30、BH p==threshold/単一/空入力、walk_forward 奇数分割/セグメント小、regime 全スキップ
3. 不変量テスト16件追加（parametrize×4seed）: p値∈[0,1]、メトリクス∈[0,1]、n_samples>=0、BH出力長一致、alpha単調性、shuffle最小p値

**ドキュメント新設:**
- docs/testing-guidelines.md: 6原則（4層構造、seed正当性、閾値根拠、境界は決定論的、不変量はparametrize、参照実装比較）+ テスト命名規則
- docs/code-review-checklist.md: テスト設計セクション追加

**全テスト: 217 passed（既存152 + research_utils 65）**

## 完了済み

- [x] **e1: Stage 2実装・実行**（src/stage2_filter.py、22テスト、4フィルタ適用、8行通過=4仮説）
- [x] **d4: random_data_control修正+FRED 5年拡張+マクロ再実行**（通過27→39→48）
- [x] **Stage 1-2総括レポート**（data/research/stage1_stage2_report.md、305行）
- [x] d3: Round 1本実行（314仮説×全シンボル=3,339件、14仮説→48行通過）
- [x] d1-review: Look-Ahead Bias再チェック（Critical 3件+Important 1件修正。290テスト全パス）
- [x] d2: signal_runner.py（31テスト、574全パス。3,468実行規模、エラー耐性、float信号判定修正）
- [x] signal_defs.py信号関数+HYPOTHESES（163関数、314エントリ、21 R2候補。290テスト。Look-Ahead修正2+4件、_stress_daysバグ修正1件）
- [x] ADR-021（シグナル定義方式。2ラウンド制、signal_defs.py+signal_runner.py、d-pre不要化）
- [x] signal_defs.pyヘルパー関数（28関数（25+VIX系3）、61+12テスト。自己評価→23件不備修正）
- [x] 検出力分析（MDE算出: 日足52.4%/バー50.3%/WF53.4%。3関数+36テスト、レビュー修正3件、全101テストパス）
- [x] research_utils.py（15関数、101テスト全パス。ADR-013/014準拠）
- [x] カテゴリタイプ分類（68件: unconditional 37, regime_conditional 15, structural 9, direction_fixed 7）
- [x] バイアス対策設計（ADR-013追記: 反証テスト4種、カテゴリタイプ4種、プロンプト対策5点）
- [x] ADR-013設計（3段階ファネル、6領域参照方法論）
- [x] 仮説空間構築（hypothesis_space.md: 67カテゴリ+3メタ、1150-1840仮説）
- [x] 101件カタログ（ideation_catalog.parquet: 68シグナル+3メタ+30設計原則、出典付き）
- [x] 実証分析（プレマーケット→K-017、30/60分→K-018、前日リターン→K-019）
- [x] 5分足データ拡張（130→197日、backtest/から66日結合）

## 参照

- ADR-013: docs/adr/013-entry-signal-research-methodology.md
- ADR-014: docs/adr/014-parquet-raw-and-split-adjustment.md
- ADR-021: docs/adr/021-signal-definition-approach.md
- 仮説空間: data/research/hypothesis_space.md
- 調査レポート: data/research/ideation_report.md
- カタログ: data/research/ideation_catalog.parquet
- Polygonデータ: data/research/polygon_intraday/（取得後）
