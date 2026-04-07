# エントリーシグナル・アイデア生成レポート

Date: 2026-03-30
Author: Master Sensei (Lv.1 見習い)
Session: scan-market → update-regime → エントリー分析 → Skill設計検討 → アイデア生成

---

## 1. 背景と目的

日本時間（JST）で米国市場に参加するユーザーのために、毎晩エントリー判断を提案するツールを設計する。その前段として、検証すべきシグナルのアイデアを**網羅的・非恣意的**に列挙する必要があった。

目標: 「1000個のアイデアを検証し、100を実験し、10を実弾として提示する」ファネルの入口を作ること。

## 2. 実証分析の結果（アイデア生成の前提）

アイデア生成に先立ち、「いつ分析すべきか」の実証分析を行った。

### 2.1 プレマーケット（4:00-9:30 ET）の予測力

| 指標 | 結果 | ソース |
|------|------|--------|
| 方向一致率 | **50.77%**（コイン投げ同等） | [Morpher集計](https://www.morpher.com/blog/pre-market-momentum-trading-strategy) |
| $10-25株ロング勝率 | 22.2%（平均リターン-2.74%） | 学術研究(2006) |
| $25-50株ロング勝率 | 0%（平均リターン-4.65%） | 同上 |

**結論: プレマーケットの方向に予測力はない。** → DuckDB knowledge K-017に記録済み

### 2.2 開場後30分/60分の予測力（手元5分足データ, N=197日）

| 時間帯 | SOXL | TQQQ | TECL | SPXL | 評価 |
|--------|------|------|------|------|------|
| 最初30分→残り | 一致率50.8%, r=0.005 | 56.9%, r=0.011 | 51.5%, r=0.012 | 55.4%, r=-0.133 | **予測力なし** |
| 最初60分→残り | 61.5%, r=0.193 | 60.8%, r=0.202 | 63.8%, r=0.171 | 64.6%, r=0.086 | **微弱なシグナル** |

VIXレジーム別ではVIX>=25（現在の環境）のサンプルがN=13で信頼不足。

**結論: 「いつ分析するか」は判断の質にほぼ影響しない。** → K-018, K-019に記録済み

### 2.3 データの拡張

backtest/data/cache/intraday/から5分足66日分（2025-06-26〜2025-09-25）を結合し、SOXL/TQQQ/TECL/SPXLの5分足を**130日→197日**に拡張した。

## 3. 検証方法論の設計（ADR-013）

6領域の方法論を調査し、3段階スクリーニングファネルを設計した。

| 領域 | 核心 | 我々への適用 | ソース |
|------|------|------------|--------|
| 統計学: BH法 | 多重検定でFDR制御 | Stage 2でFDR≤20%制御 | [Columbia FDR解説](https://www.publichealth.columbia.edu/research/population-health-methods/false-discovery-rate) |
| クオンツ: Deflated Sharpe Ratio | 試行回数を記録しないバックテストは無意味 | 全試行をCSVに記録 | [Bailey & López de Prado 2014](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) |
| A/Bテスト: 検出力分析 | 事前にMDEを定義 | Agent起動前に検出力計算 | Evan Miller Calculator |
| 創薬: スクリーニングファネル | 早期は偽陰性回避、後段で厳格化 | Stage 1は緩く、Stage 2で厳格 | [PMC Hit Identification](https://pmc.ncbi.nlm.nih.gov/articles/PMC3772997/) |
| ML: 特徴量選択 | Filter→Wrapperの二段 | Stage 1=filter, Stage 2=wrapper | [ScienceDirect Benchmark](https://www.sciencedirect.com/science/article/pii/S016794731930194X) |
| VC: ディールフロー | Fast screen→Due diligence | Stage 3でthesis fit評価 | [GoingVC Due Diligence](https://www.goingvc.com/post/venture-capital-due-diligence-the-screening-process) |

**フィルタ基準:**
- Stage 1（スクリーニング）: N≧30、方向一致率>50%
- Stage 2（検証）: BH補正p<0.20、Walk-forward符号一致、2レジーム安定、2銘柄再現
- Stage 3（実用性）: JST適合、独立性、シンプルさ、摩擦後期待値

## 4. アイデア生成: 20の手法と62のシグナルカテゴリ

（Cat 1-67の67番号のうち、旧Cat 10/15/21/22はメタ次元に移動、Cat 30は統合カテゴリのため、実質62シグナルカテゴリ + 3メタ次元）

### 4.1 適用した手法の全一覧

| # | 手法 | 説明 | 新規Cat | 累計 |
|---|------|------|--------|------|
| 1 | **ドメイン知識 + Web調査** | トレーディング・学術文献12件の直接調査 | 9 | 9 |
| 2 | **Zwicky Box** | 問題を独立次元に分解し全組合せを列挙（Fritz Zwicky, 1940s） | 3 | 12 |
| 3 | **SCAMPER** | Substitute/Combine/Adapt/Modify/Put to other use/Eliminate/Reverse（Osborn 1953/Eberle 1971） | 3 | 15 |
| 4 | **逆ブレインストーミング** | 「確実に負ける方法」を列挙し反転（[HBR 2017](https://hbr.org/2017/08/to-come-up-with-a-good-idea-start-by-imagining-the-worst-idea-possible)） | 1 | 16 |
| 5 | **前提の反転** | 隠れた前提6つを洗い出し反転 | 5 | 21 |
| 6 | **ビソシエーション（第1回）** | 天気予報 × ポーカー × 免疫系 × 音楽 × 潮汐（[Koestler 1964](https://www.themarginalian.org/2013/05/20/arthur-koestler-creativity-bisociation/)） | 2+M2 | 23 |
| 7 | **ランダム刺激（第1回）** | 「鏡」からの強制連想（[de Bono Lateral Thinking](https://www.debonogroup.com/services/core-programs/lateral-thinking/)） | 2 | 25 |
| 8 | **de Bono Po** | 「市場は毎日同じ」「最良のトレード=しない」という挑発的仮定 | 1 | 26 |
| 9 | **TRIZ** | 矛盾（高リターン vs 低リスク）に40の発明原則を適用（[Altshuller](https://www.triz40.com/aff_Principles_TRIZ.php)） | 2 | 28 |
| 10 | **シネクティクス** | 4種のアナロジー: 個人的/直接/象徴的/ファンタジー（[Gordon 1960](https://geniusrevive.com/en/synectics/)） | 1 | 29 |
| 11 | **コンセプトファン** | 「エントリーシグナル」→「レバETFで稼ぐ方法」→「JST下で米市場リターン」と段階的に抽象化（[de Bono](https://www.mycoted.com/Concept_Fan)） | 1 | 30 |
| 12 | **スターバースティング** | Who/What/When/Where/Why/Howの6問で探索 | 4 | 34 |
| 13 | **アトリビュート・リスティング** | 「トレード」の属性を分解し各属性を変形（[Crawford 1931](https://www.mycoted.com/Attribute_Listing)） | 1 | 35 |
| 14 | **Lotus Blossom** | 中心テーマから8方向（価格/時間/参加者/情報/構造/心理/コスト/制約）に展開（[松村安雄](https://thoughtegg.com/lotus-blossom-creative-technique/)） | 2 | 37 |
| 15 | **ランダム刺激（第2回）** | 「渋滞」「体温計」「種まき」からの強制連想 | 4 | 41 |
| 16 | **異分野ビソシエーション** | ゲーム理論 × [Lotka-Volterra生態学](https://arxiv.org/abs/0810.4844) × 孫子 × [Moneyball](https://medium.com/@adhvikvak/moneyball-the-economics-of-outsmarting-the-system-f54ffc6c8ada) | 2 | 43 |
| 17 | **世界文学** | [ドストエフスキー](https://www.cambridge.org/core/journals/advances-in-psychiatric-treatment/article/from-the-gambler-within-dostoyevskys-the-gambler/D7ACB14B9EAD00EB8EF65512C28EADAA)『賭博者』、[アシモフ](https://bigthink.com/high-culture/asimov-foundation-mathematical-sociology/)『ファウンデーション』、メルヴィル『白鯨』、キャロル『鏡の国のアリス』、ガルシア=マルケス『百年の孤独』、[ボルヘス](https://hypercritic.org/collection/jorge-luis-borges-fictions-1944-review)『伝奇集』、[川端](https://en.wikipedia.org/wiki/The_Master_of_Go)『碁の名人』、タレブ『アンチフラジャイル』、宮本武蔵『五輪書』 | 6 | 49 |
| 18 | **古典文学・漫画・アニメ・映画・哲学・音楽** | ギリシャ悲劇、[カイジ](https://www.rostercon.com/en/magazine/tv-show/gambling-tropes-in-anime-exploring-the-high-stakes-world-of-kaiji-and-kakegurui-391345)、HUNTER×HUNTER、PSYCHO-PASS、[銀河英雄伝説](https://www.cbr.com/code-geass-similar-anime/)、[ビッグ・ショート](https://www.quantvps.com/blog/11-best-trading-finance-movies)、マトリックス、インセプション、テネット、STEINS;GATE、エヴァンゲリオン、ストア哲学、禅、老子、侘び寂び、バッハ、ジャズ | 6+原則 | 55 |
| 19 | **歴史（第1波）** | [堂島米会所](https://en.wikipedia.org/wiki/Honma_Munehisa)(1697)、[バブル3事例](https://en.wikipedia.org/wiki/Extraordinary_Popular_Delusions_and_the_Madness_of_Crowds)(マッケイ1841)、[クラウゼヴィッツ](https://en.wikipedia.org/wiki/On_War)『戦争論』、[シルクロード商人](https://vocal.media/01/the-merchant-s-legacy-how-ancient-trade-routes-shaped-modern-financial-wisdom)、[暴落前兆研究](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-024-00457-2)(EPJ Data Science)、[確率論の起源](https://en.wikipedia.org/wiki/History_of_probability)(パスカル/フェルマ 1654) | 3+原則 | 58 |
| 20 | **歴史（第2波）+ 追加深化** | [ロスチャイルド/ワーテルロー](https://www.sandhillglobaladvisors.com/blog/high-frequency-trading-the-evolution-of-the-carrier-pigeon/)(1815)、[VOC/デ・ラ・ベガ](https://www.worldsfirststockexchange.com/2021/01/22/confusion-de-confusiones-1688-a-historical-stock-exchange-drama/)(1602-1688)、[クラッスス](https://imperiumromanum.pl/en/curiosities/crassus-fire-brigade/)(古代ローマ)、[ソロス再帰性](https://gavinlucas22.medium.com/what-is-george-soros-theory-of-reflexivity-5e9c88091a59)(1987/1992)、[リバモア](https://quantstrategy.io/blog/jesse-livermore-trading-methods-and-rules/)(1923)、[LTCM](https://en.wikipedia.org/wiki/Long-Term_Capital_Management)(1998)、[タレス](https://itrevolution.com/articles/the-worlds-first-options-trader-hit-it-big-in-the-year-600-bc/)(紀元前600年)、[鉄道マニア](https://en.wikipedia.org/wiki/Railway_Mania)(1840s)、[メディチ](https://www.edology.com/blog/accounting-finance/3-medici-banking-innovations)(ルネサンス)、[冷戦/シェリング](https://science.howstuffworks.com/game-theory5.htm) | 5+原則 | 63 |

**合計: 20手法 → 62シグナルカテゴリ + 3メタ次元 + 25設計原則**

### 4.2 着想源の全体像

```
トレーディング理論 ─── 学術文献12件
統計学/ML ────────── 方法論6領域
創造性手法 ────────── SCAMPER, Zwicky, TRIZ, シネクティクス, Po, Lotus等13手法
自然科学 ──────────── 物理(減衰振動), 生態学(Lotka-Volterra), 免疫系, 疫学
人文学 ────────────── 小説9作品, 哲学4流派, 音楽2ジャンル
視覚芸術 ──────────── 漫画4作品, アニメ5作品, 映画5作品
歴史 ──────────────── 古代ローマ〜冷戦まで14のエピソード
実務 ──────────────── 料理, 建築, 格闘技, スポーツ(Moneyball)
```

### 4.3 特に注目すべき着想

以下は全62カテゴリから、選定基準を明示した上で抽出したものである。

#### 学術的裏付けが強い発見（選定基準: 査読付き学術誌に複数の実証研究がある）
- **高VIX→平均回帰、低VIX→モメンタム** (Cat 7): Economic Modelling誌、J. of Asset Management誌で複数の実証研究あり。現在VIX 30.8（高VIX）のため即座に検証可能
- **レバETFリバランスフローが引け前モメンタムと翌日平均回帰を誘発** (Cat 6/14): Swiss Finance Institute研究
- **原油ボラティリティは株式リターンの強い予測因子** (Cat 4): Journal of Banking & Finance

#### 既存文献にない独自の着想（選定基準: Web調査で類似アプローチが見つからなかったもの）
- **「免罪体質」検出** (Cat 55, PSYCHO-PASSから): シグナルが効かない市場状態を積極的に特定する。通常のバックテストでは「平均」を見るが、「失敗条件」を見る視点
- **再帰的フィードバック加速度** (Cat 65, ソロスから): フィードバックループの「存在」ではなく「速度変化」を見る。加速→減速の転換点が反転シグナル
- **制約と誓約** (Cat 54, HUNTER×HUNTERから): 厳しい制約をかけた戦略のほうが万能戦略より精度が高いという仮説
- **結果→シグナル逆引き** (Cat 49, 鏡の国のアリスから): 通常の「シグナル→結果」ではなく「大きな結果の前日→何が起きていたか」の逆方向分析

#### 設計原則として重要な着想
- **侘び寂び**: 60%の精度で十分。完璧を求めると過適合する
- **リバモア**: 「座っていることで金を稼いだ」。エントリーよりエグジット（保有継続）が重要
- **デ・ラ・ベガ（1688）**: 市場参加者は「理由を発明する」。後付け合理化に注意
- **LTCM**: ノーベル賞級のモデルも極端な市場で破綻する。テールリスクの明示的考慮が必須

### 4.4 サイズ見積もり

| 段階 | 推定数 |
|------|--------|
| シグナル源（62カテゴリ × 平均3.3サブシグナル） | ~205 |
| × 読み方（水準/変化/モメンタム/極値/ブレイクアウト/パターン） | ~500-700 |
| × 方向（順張り/逆張り） | ~830-1220 |
| + メタ次元（アンサンブル/期待値/サイジング） | +100-200 |
| + Stage展開（逆シグナル/組合せ/動的閾値/遅延版） | +150-350 |
| **合計** | **推定1080-1770** |

## 5. 恣意性の評価

### 5.1 プロセスの透明性

- 全検索クエリ（38件+追加12件）を記録
- 適用した手法20種を全て列挙
- 各カテゴリに着想源を明記
- 試したが新カテゴリに至らなかったもの（Six Thinking Hats、マンダラート等）も記載

### 5.2 残存する恣意性

| 観点 | 評価 | 対策 |
|------|------|------|
| 検索クエリの選択 | 私の知識に依存 | 20手法の適用で構造的にカバー |
| ランダム刺激の単語選択 | 「鏡」「渋滞」「体温計」「種まき」は私が選択 | 4語に拡大。完全ランダム生成は未実施 |
| 着想源の文化的偏り | 西洋+日本中心。中東・アフリカ・南米の文学/歴史は限定的 | Agentに追加ビソシエーションを指示可能 |
| サイズ見積もりの仮定 | 「平均3.3サブシグナル」「有意味な読み方の数」は仮定 | Agent実行後に実数で置換 |

## 6. 追補: Polygon.ioデータ拡張（2026-03-31）

### 6.1 経緯

タスク(a)データ品質検証で、Tiingo IEX 5分足に**Volumeが含まれない**ことが判明。研究の1000仮説検証に出来高データが必要なカテゴリ（Cat 2, 9, 25, 42, 46, 64等）があるため、代替データソースを調査した。

Tiingo IEXの`columns`パラメータでVolumeは取得可能になったが、IEX取引所のみ（全体の1-2%）で品質が不十分（日次変化率の相関0.69）。全取引所合算（SIP）のVolume付き5分足データが必要と判断。

### 6.2 Polygon.io Starter ($29/月) の選定理由

10サービスを比較調査した結果:

| 観点 | Polygon.io Starter |
|------|-------------------|
| Volume種別 | SIP全取引所合算 |
| 5分足過去データ | 5年以上（2021-04〜） |
| コスト | $29/月（最安クラス） |
| 即日利用 | サインアップ即APIキー発行 |
| レート制限 | 無制限API calls |
| 価格精度 | Tiingoとの平均差$0.005（実質同一） |

比較対象: Alpaca ($99/月でSIP), Alpha Vantage ($50/月, 30req/分), EODHD ($30/月), Twelve Data ($29/月, 過去範囲不確実), Databento ($199/月, 高品質だが高コスト), FirstRate Data ($99/年一括)

### 6.3 Polygon固有のデータフィールド

Polygon 5分足バーはTiingoにない3つのフィールドを含む:

| フィールド | 内容 | Tiingo | 研究での用途 |
|-----------|------|--------|------------|
| `v` | 出来高（SIP全取引所合算） | IEXのみ(1-2%) | Cat 2, 9, 25, 42, 46, 64 |
| `n` | **取引回数** | なし | **Cat 68, 69（新規）** |
| `vw` | **バー内VWAP** | なし | **Cat 70（新規）** |

さらに拡張時間帯（プレマーケット4:00-9:30, アフター16:00-20:00 ET）のデータも含まれ、Cat 71, 72（新規）が可能に。

### 6.4 新カテゴリ（Cat 68-72）

| Cat | 名称 | シグナル源 | サブシグナル数 |
|-----|------|----------|-------------|
| 68 | 平均取引サイズ(v/n)パターン | Polygon `n` | 3 |
| 69 | 取引回数スパイクと出来高スパイクの乖離 | Polygon `n`+`v` | 3 |
| 70 | バー内VWAP乖離（微細な方向圧力） | Polygon `vw` | 3 |
| 71 | プレマーケット出来高水準（方向ではなく量） | Polygon拡張時間帯 | 3 |
| 72 | アフターマーケット→翌朝乖離 | Polygon拡張時間帯 | 2 |

### 6.5 追加シンボル

Polygonで取得可能になったクロスアセットETF:

| シンボル | 用途 | 関連カテゴリ |
|---------|------|------------|
| SOXX | SOX指数代替。トラッキングエラー分析が検証可能に | Cat 6 |
| SPY, QQQ | S&P/Nasdaq 5分足。リード/ラグ分析 | Cat 4, 11, 12 |
| HYG | HYスプレッドの日中変動（FRED 1-2日遅延の解消） | Cat 4, 7 |
| TLT | 金利の日中変動プロキシ | Cat 4 |
| USO, UUP, IWM | 原油・ドル・小型株の日中プロキシ | Cat 4 |

計18銘柄（既存8 + VIXY, TECS + 上記8）× 5年分を取得予定。

### 6.6 影響まとめ

| 指標 | 変更前 | 変更後 |
|------|--------|--------|
| シグナルカテゴリ | 62 | **67** |
| カタログ総件数 | 96 | **101** |
| 推定仮説数 | 1,080-1,770 | **1,150-1,840** |
| 5分足銘柄数 | 8 | **18** |
| 5分足期間 | 9ヶ月 | **5年** |
| 5分足Volume | なし | **SIP全取引所合算** |
| Parquet推定サイズ | 2.1 MB | **62-83 MB** |

### 6.7 データ品質の検証結果

| 検証項目 | 結果 |
|---------|------|
| 全8銘柄で5分足Volume取得 | OK（バー数145-192/日、銘柄による） |
| レギュラーセッション78本 | Tiingoと一致 |
| 価格精度（Tiingoとの比較） | 平均差$0.005、最大$0.045 |
| Volume小数問題 | adjusted=falseでも小数あり。公式説明と不一致。整数丸めで実害なし |
| 5分足Volume合計 vs 日足Volume | 89-97%（オークション等の差） |
| 過去データ範囲 | 2021-04-01〜（5年分確認） |
| タイムゾーン | ミリ秒Unixエポック(UTC)。ET変換確認済み |

## 7. 次のステップ（更新版）

1. **Polygon 5分足データ取得**: 18銘柄×5年分 → data/research/polygon_intraday/
2. **utils.py作成**: 一致率計算・BH法・Walk-forward・スプリット調整・Polygon読み込み
3. **検出力分析**: Polygon 5年分でのMDE算出
4. **4 Agent並列起動**: hypothesis_space.mdを入力として実行
5. **結果統合**: signal_ideas.csv → Stage 1 → Stage 2 → Stage 3
6. **Skill/ツール設計**: 10のアイデアをもとに実装

## 7. 参考文献（主要なもの）

### 方法論
- Bailey, D.H. & López de Prado, M. (2014). The Deflated Sharpe Ratio. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- Bailey, D.H. et al. (2015). The Probability of Backtest Overfitting. [PDF](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
- Harvey, C.R. Backtesting. [CME](https://www.cmegroup.com/education/files/backtesting.pdf)

### レバETF研究
- Swiss Finance Institute. Liquidity Provision to Leveraged ETFs. [RePEc](https://ideas.repec.org/p/chf/rpseri/rp2240.html)
- ArXiv. Compounding Effects in Leveraged ETFs. [ArXiv](https://arxiv.org/html/2504.20116v1)

### レジーム切替
- Economic Modelling. A regime-switching model of stock returns with momentum and mean reversion. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0264999323000494)
- J. of Asset Management. Market volatility, momentum, and reversal: a switching strategy. [Springer](https://link.springer.com/article/10.1057/s41260-024-00372-1)

### クロスアセット
- Journal of Banking & Finance. Cross-asset time-series momentum: Crude oil volatility. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378426622002849)

### 暴落前兆
- EPJ Data Science. Early warning signals for stock market crashes. [SpringerOpen](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-024-00457-2)

### 歴史
- de la Vega, J. (1688). Confusion de Confusiones. [World's First Stock Exchange](https://www.worldsfirststockexchange.com/2021/01/22/confusion-de-confusiones-1688-a-historical-stock-exchange-drama/)
- Mackay, C. (1841). Extraordinary Popular Delusions. [Wikipedia](https://en.wikipedia.org/wiki/Extraordinary_Popular_Delusions_and_the_Madness_of_Crowds)
- 本間宗久 (1755). 三猿金泉秘録. [Wikipedia](https://en.wikipedia.org/wiki/Honma_Munehisa)
- Lefèvre, E. (1923). Reminiscences of a Stock Operator.

### 創造性手法
- Koestler, A. (1964). The Act of Creation. [The Marginalian](https://www.themarginalian.org/2013/05/20/arthur-koestler-creativity-bisociation/)
- Altshuller, G. (1946-85). TRIZ 40 Inventive Principles. [TRIZ40](https://www.triz40.com/aff_Principles_TRIZ.php)
- Zwicky, F. (1940s). Morphological Analysis. [Swemorph](https://www.swemorph.com/pdf/gma.pdf)
