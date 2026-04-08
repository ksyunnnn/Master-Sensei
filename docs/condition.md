# Condition

Last updated: 2026-04-08 (session 17)

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 22本、GDR 1本（Phase 1実装済み）、596テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム12件、予測5件（解決1/未解決4、Brier 0.2025）、知見27件、イベント162件、トレード4件（#1 +10%利確、#2 スクラッチ、#3 SL決済-4.4%、#4 SOXS long建て中→停戦で含み損-5.2%、SL$33.00危機）
- GitHub Public repo設定: `ksyunnnn/Master-Sensei`（origin）。.gitignore強化 + permissions.deny + noreply email設定済み
- エントリーシグナル研究: @data/research/README.md
- シグナル監視: src/signals/（1シグナル1ファイル、自動レジストリ）。confirmed: H-18-03のみ
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/scan-market-quick`, `/review-events`, `/entry-analysis`, `/sensei-journal`, `/signal-check`
- trades テーブル: ADR-015実装済み（add_trade, close_trade, review_trade）
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **★Trade #4 SOXS決済判断（22:00 JST、最優先）** — 停戦合意でScenario C実現。SOXS引け$33.43、SL$33.00まで$0.43。先物Nasdaq+3%→SOXS gap down -9%($30.4)想定。判断マトリックス:
   - SOXSプレマ≧$33 & Hormuz未開放 → SL取消+ホールド検討
   - SOXSプレマ≧$33 & Hormuz順調 → 開場直後に手動決済
   - SOXSプレマ<$33 → SLに任せる（gap down約定）
   - 即時価格確認: `python /tmp/check_soxs.py`
2. **scan-market** — Hormuz実装状況（船舶通行開始？）、停戦条件の齟齬、先物動向
3. **update-regime** — 4/7引けデータでregime再判定。Brent $95(-14%)でcrisis→high移行か。VIX 25.78、バックワーデーション1.008
4. **停戦の評価** — 2週間限定停戦。4/10イスラマバード和平交渉（Vance副大統領）。K-009完全成就の記録
5. **予測モニタリング** — #2 SOXL $40割れ(55%, 4/11): $56.55で大幅乖離。#3 SOXS +10%超(75%, 4/11): 引け-3.2%で困難化。#4 TQQQ TP$46(35%, 4/11): $44.15。#5 SOXL TP$55.70(25%, 4/11): $56.55で到達済み？要確認

## 未決の検討事項（シグナル研究）

1. **探索をやり直すか**: 1000仮説→実弾1本（H-18-03）。目標10本に対して1/10。再探索するか1本で運用開始するかの判断が必要
2. **シグナル監視アーキテクチャ**: レイヤードアーキテクチャ / Hexagonal / Pipe and Filter の選定。../app/（Next.js）との統合方針。ECA（Event-Condition-Action）ルールの適用
3. **H-18-03のパラメータ展開**: 2日/4日連続は独立仮説か同一仮説のバリエーションか。実弾として追加採用するかの判断

## エントリーシグナル研究: 最終結果

**実弾確定: H-18-03（3日連続下落→ロング）のみ。** 詳細: [data/research/findings/2026Q2-signal-exploration.md](../data/research/findings/2026Q2-signal-exploration.md)
- TQQQ: 勝率64.8%, 摩擦後+1.42%/回, 年+30.6%
- TECL: 勝率64.2%, 摩擦後+1.50%/回, 年+32.7%
- CSCV 70通り: OOS正リターン率100%

## 今セッションの成果（session 17, 4/7 夜 JST）

### scan-market 7回実行: 計11件登録
- **1回目(20:23)**: Trump「taken out」記者会見(neutral/K-009)、Iran 10項目対案(neutral)、S&P先物-0.4%(neutral)
- **2回目(22:44)**: **Kharg Island攻撃**(negative, WTI+3%→$116)、イラン全土インフラ攻撃(neutral/K-024)、IRGC多年油遮断脅迫(neutral/K-009)
- **3回目(00:19)**: Fed Williams「コアインフレほぼ変わらず」(neutral)
- **4回目(01:03)**: **Iran USバックチャネル切断**(negative、市場-0.9%に反応)
- **5回目(11:07)**: **★Trump-Iran 2週間停戦合意**(positive)、Brent-13%→$95(positive)、市場-1.2%→+0.08%全戻し(positive)
- **6回目(11:55)**: 停戦後先物 S&P+2.5%/Nasdaq+3%/WTI-19%(positive)

### update-regime: **neutral→risk_off転換**（12件目）
- VIX **24.17→26.18**(+2.01): 25超えでhigh判定
- VIX/VIX3M **0.976→1.010**: コンタンゴ→バックワーデーション転換
- HYスプレッド 3.13→3.05: 改善（信用市場はまだパニックしていない）
- Brent $110.1→$110.1: 危機水準維持

### entry-analysis: SOXS long 15株 @$35.265（Trade #4）
- **プロセス**: SQQQ/TQQQ/SOXL 3銘柄MAP比較分析→SQQQ longが最もレジーム整合→サクソバンクでSQQQ ETF現物取扱なし判明→CFD口座は証拠金5,167%で不可→SOXS ETF現物(T:外国株式口座)に代替
- **バイアスチェック**: substitution error（SQQQ→SOXSは別の賭け）、アクションバイアス、半導体逆張りリスクを自己指摘→ユーザー判断で探りサイズで実行
- **シナリオ**: 「4/11までに停戦合意なし」(75%)にベット。TP $38.50(+9.2%) / SL $33.00(-6.4%) / R:R 1.4:1
- **約定**: 23:26 JST、成行15株 @$35.265、$529

### sensei-journal: Episode 2「Kharg島の閃光」
- 4 Scene構成: 将軍の首(Khademi殺害)→二つの言語(表の脅迫/裏の外交)→Khargの閃光(期限前攻撃)→信号が変わった(regime転換)

### サクソバンク銘柄調査
- SQQQ: CFDのみ、ETF現物取扱なし（ETFフィルター検索で確認済み）
- SOXS/SOXL: ETF現物+CFD両方取扱あり
- CFD口座(I:株価指数CFD)は既存建玉で証拠金圧迫、現金0円

## 前セッションの成果（session 16, 4/7 朝 JST）

### scan-market: 4件登録
- **South Pars石化施設攻撃**(4/6): イラン石化能力85%オフライン。供給実被害→negative
- **イラン一時停戦拒否**(4/7): 恒久的戦争終結・制裁解除要求。K-009パターン→neutral
- **IRGC海軍「Hormuz不可逆」声明**(4/5): K-024繰り返し声明→neutral
- **Section 232関税改定**(4/2発表4/6発効): 鉄鋼/アルミ/銅50%、医薬品100%→negative（後述：バイアス監査で問題指摘）

### update-regime: neutral(-0.29)記録（11件目）
- VIX 24.17(↓), VIX/VIX3M 0.976(↓改善), HY 3.13(↓), Brent $110.1(↑), USD 120.7(↓)
- 全指標のregime区分は前日と同一。日付が4/7で新規記録

### review-events: 5件検証、2件修正(neg→neu)
- **#150 Section 232関税**: neg→neu。計算基準変更は市場インパクト低、地政学支配環境で埋没
- **#126 F-15E撃墜**: neg→neu。WSO救出成功(KIAゼロ)→Trump political victory転換
- #54 NFP予想: neutral維持。#125 NFP実績+178K: positive維持。#142 WTI>Brent逆転: neutral維持

### バイアス監査（Kahneman 12問）: 自己判断の検証
- scan-marketのimpact判定にKahneman 12問を適用→**⚠️4件**(Q2感情ヒューリスティック/Q3反対意見/Q5代替案/Q10過度慎重)
- **矛盾検出**: review-eventsで#150(Section 232)をneg→neuに修正した直後に、同イベントをnegativeで登録していた
- **K-027記録**: impact判定バイアス固着パターン（lessonが即時適用されない構造的問題）

### プロセス改善: scan-market SKILL.md更新
- 手順3を3a(lesson照合)+3b(登録)に分割
- negativeを付与する前に、同カテゴリの過去lesson(neg→neu修正)との照合を必須化
- 照合結果をimpact_reasoningに明記するルール追加

### 前セッションの成果（session 15, 4/6 午後〜4/7 JST）

### scan-market 3回実行: 計9件登録
- **15:50**: Trump火曜20:00ET Hormuz期限(K-009 3巡目)、WTI-Brent歴史的逆転($111>$107)、月曜先物回復(-0.6%→+0.06%)
- **19:10**: **IRGC情報長官Khademi殺害**(negative, K-024例外の質的変化)、イランHaifa報復ミサイル(2名死亡)、45日停戦枠組み(Pak/Egypt/Turkey提示、イラン未回答)

### entry-analysis: 全銘柄スクリーニング + バイアス監査
- **初回分析**: TQQQ long推奨（R:R 1.1、VIX低下根拠）
- **バイアス監査実施**: Premortem + Kahneman 12質問 → **⚠️7+❌2=9件 → 判断保留**
  - K-009軍事適用を検証: 延長率~80%（関税~95%より低い、60日期限は実行された前例あり）
  - 「エントリーしない」を正式評価 → 水曜エントリーが期待値+リスク両面で優位
  - VIX低下はGood Friday前ヘッジ解消の可能性排除不可
  - 非戦争リスク具体化: AI fatigue(MSFT -20%YTD)、HY complacency(3.17 vs 20yr avg 4.9%)
  - ギャップリスク定量化: SOXLの最大ギャップ-12.18%はSL(-12.7%)にほぼ到達
- **最終判断**: **ノートレード（火曜Hormuz期限後にエントリー判断）**
- シナリオ確率修正: A 55→30%, B 30→40%, C 15→30%

### 予測記録: 2件追加（#4, #5）
- **#4**: TQQQ 4/7-11 TP$46到達 (35%, バイアス監査後に45→35%下方修正)
- **#5**: SOXL 4/7-11 TP$55.70到達 (25%, 35→25%下方修正)

### update-regime: neutral(-0.29)、VIX変化のため記録（10件目）
- VIX **23.87→24.70**(+0.83): VIX低下トレンド否定。GF前ヘッジ解消の疑い強化
- VIX/VIX3M **0.966→0.999**: バックワーデーション境界。月曜に1.0超えるか要注視

### verify-knowledge: K-025 hypothesis→validated
- TP/SL非対称バイアス: 今回のentry-analysisでは60日全体+σベースで設計し、自然に適用されていた

### 前セッション（session 14, 4/6 朝 JST）

### scan-market（月曜開場前、4/6 09:14 JST）: 3件登録
- **Trump 48h ultimatum撤回+5日新停止期限**(4/6): K-009パターン完結（脅迫→IRGC反撃宣言→撤回→交渉延長）→ **positive**
- **IRGC声明: 地域インフラ全体を報復対象に拡大**(4/6): 標的範囲拡大（イスラエル→地域経済全体）→ negative
- **プレマーケット先物-0.6%**(4/6): 穏やかなgap down。ultimatum撤回がギャップダウン回避に寄与

### update-regime: neutral維持(-0.29)、記録スキップ
- Brent $109.05→$110.75（+$1.70）のみ変化、crisis帯内で判定影響なし
- VIX/VIX3M/HY/YC/USD全て前回同一。月曜引け後に再判定

### review-events: 41件検証、**21件修正(51%)**
- **K-024パターン確認**: 10件がnegative→neutral（ミサイル/空爆/IRGC声明）
- **K-017最強事例**: 4/2プレマ-1.84%→引け+0.11%（4.3σ反転）。Trade #3 SLヒットの原因
- **#122データ修正**: 4/2引けを-0.88%と誤記録→実際は+0.11%。中間値の誤認
- **系統的ネガティブバイアス発見**: scan-market登録時にnegative判定が過剰。K-024/K-009対象は初期impactをneutralにすべき

### /sensei-journal 新設 + Episode 1
- `docs/journal/2026-04-06.md`: 創刊号「脅迫と撤回のワルツ」
- 新聞連載風の市場ナラティブスキル。Scene構造・次回予告フォーマット

### 前セッション（session 13, 4/5 JST）

### セキュリティ強化（Public Repo対応）
- **.gitignore強化**: `.env.*`, `*.pem`, `*.key`, `.claude/settings.local.json`, `CLAUDE.local.md`, `.claude/scheduled_tasks.lock` 追加。セクション整理
- **permissions.deny**: `.claude/settings.json` に `Read(.env)` / `Read(.env.*)` 追加（Claude経由の.env読み込みブロック）
- **git email**: `ksyunnnn@users.noreply.github.com` に切替（過去履歴は書き換えず以降のみ）
- **`.env`パーミッション**: `600`に変更
- **残タスク**: GitHub Push Protection をWeb UIで有効化（ユーザー側で対応予定）
- CLAUDE.mdルール追記: 「リモートリポジトリあり。コミット後pushを提案してよい」

### scan-market（4/4 11:25〜4/5 19:57 JST、約32時間）: 4件登録
- **Mahshahr石油化学への空爆**(4/4): 5 KIA/170負傷、272回/日の空爆(day 36)、Bushehr原発補助棟も被弾 → neutral(過去lessonパターン合致、石油化学は原油供給直接影響せず)
- **F-15E WSO救出完了**(4/5): コマンドーレイド成功、米軍KIA回避 → neutral(エスカレーション発火点1つ消失)
- **Trump 48h Hormuz ultimatum**(4/5): 「All Hell」4/6期限と同期 → neutral(K-009パターン、公開脅迫≠市場支配)
- **OPEC+ 206k bpd May hike原則合意**(4/5 事前報道): Hormuz封鎖下でsymbolic → neutral(実供給増なし、Hormuz再開時の下押し材料)

### 重要な二重期限（4/6月曜周辺）
- **Trump 48時間Hormuzウルトゥマタム**: 4/5発→4/6終盤期限
- **エネルギー攻撃停止期限**: 4/7 9:00 JST
- 両者がほぼ同期。週明けにheadline risk・ギャップ警戒

### scan-market 広範2nd pass: 6件追加（計10件）
- **ISM製造業PMI 52.7 / Prices Paid 78.3**(3月): インフレ加速、Fed利下げ遅延圧力
- **TSMC 2026年売上+30%ガイダンス**: HPC 58%、AI capex $600-720B（SOXLポジ材料）
- **Q1決算開幕 4/14**: JPM/Citi 4/14、BAC 4/15 → 市場コンパス
- **30年債入札 4/9**: インフレ警戒下のlong-end需要試金石
- **Defense index -8% March**: Pentagon 4倍増産発注も「conflict priced in」（K-009補強）
- **湾岸諸国UN決議支持**: Hormuz再開に「all necessary measures」

### Obsidian PKM原則からの学び→実装（ADR-020）
- **調査**: docs/references/obsidian-pkm-principles.md（Zettelkasten/Atomic/Linking/Evergreen/CODE）
- **ADR-020**: knowledgeテーブルに`tldr`・`related_knowledge_ids`列追加
- **実装**: schema+migration+add_knowledge拡張+get_backlinks()新設、8テスト追加（計166テスト全パス）
- **残タスク（次回）**: 既存25件のknowledgeへtldrバックフィル

### 前セッション（session 12, 4/3 17:58〜4/4 11:23 JST）

### scan-market 2回実行: 5件登録
- **4/3夕方**: 鉄鋼/アルミ/銅50%関税(Section 232拡大, 4/6発効)、Iran-Omanホルムズ通行許可制プロトコル
- **4/4朝**: NFP +178K(コンセンサス+57Kの3倍超)、F-15E撃墜(初の米固定翼機喪失)、医薬品100%関税(120-180日後発効)

### update-regime: neutral維持(-0.29)、記録スキップ
- 4/2データベースで前回(4/3)と実質同一。Good Friday休場で新データなし
- 次回意味ある更新は4/6(月)

### review-events: 29件検証、8件修正
- 3/30-4/1の「最大エスカレーション→急反転」期間を検証
- 8件全てnegative→neutral修正。共通パターン: 停戦シグナル下では個別エスカレーションが消化される
- **K-024（戦時エスカレーション割引）: hypothesis→tested昇格**（累計13件修正が裏付け）
- **K-020（risk_off下impact逓減）: hypothesis→tested昇格**
- stale知見: 0件（K-024/K-020検証日更新により解消）

### 重要な新材料
- **NFP +178K**: 医療+76Kが牽引だが大幅ビート。失業率4.3%改善、賃金+3.5% YoY(2021年5月以来最低)。Good Fridayで市場反応は月曜持ち越し
- **F-15E撃墜**: パイロット救出、WSO行方不明でイランが懸賞金。A-10も被弾撃墜。過去lessonの「ミサイル交換=neutral」とは質的に異なるエスカレーション
- **関税三重苦**: 鉄鋼50% + 医薬品100% + 原油高 → スタグフレーション懸念鮮明化
- **Iran-Oman Hormuzプロトコル**: 戦時封鎖→恒久的通行許可制への転換。原油構造的高止まりリスク
- **週間パフォーマンス**: S&P +3.4%, Nasdaq +4.4%（戦争開始以来初の週間プラス）

### 前セッション（session 11, 4/2 19:00〜4/3 0:00 JST）

### Trade #3: SOXS long → SL決済(-4.4%)
- **エントリー**: SOXS 28株 × $39.219（成行P2、寄付$40.56の押し目）
- **決済**: SL $37.485ヒット（-$48.55、口座-2.2%）
- **原因**: プレマーケット-1.84%→開場後dip buying反転。Trump演説「nearing completion」を和平と解釈
- **教訓**: K-017再実証（プレマーケット方向≠正規取引方向）。「織り込み済みネガティブ」ではベアエントリーのエッジがない
- **SL機能**: 想定通り損失限定。SL拡大の誘惑を拒否して正解

### レジーム変化
- session開始: risk_off (-1.43) → session中: risk_off (-1.00)に改善
- VIX/VIX3M: 1.109(深いバックワーデーション) → 1.005(ほぼフラット)
- HY_SPREAD: 3.28(widening) → 3.16(normal)
- **セッション中にレジームがポジションと逆方向に動いた**

### scan-market: 7件登録
- Brent $106急騰、イラン軍エスカレ声明、LNGホルムズ通過テスト、IRGC期限空砲、先物悪化+アジア売り、UAE攻撃、開場後dip buying反転

### 半導体感度の分析
- OPEC+/NFP→半導体は間接経路（2-3段階）。マクロベットにはSPXL/TQQQが素直
- 銘柄選定から見直す必要あり

### 前セッション（session 10, 4/2 19:00 JST）

### scan-market速度改善 + quick版新設
- **速度分析**: 6ステップのボトルネック特定。WebSearch並列化(P0)は品質リスク（文脈連鎖断絶・横断分析劣化）があることをバイアスなく評価し、品質劣化ゼロのP1+P2のみ採用
- **P1**: DB前処理3スクリプト→1スクリプト統合（Python起動・DB接続1/3）
- **P2**: SKILL.mdインラインシェルコマンド除去（エラー解消）
- **ADR-008違反修正**: lesson取得の生SQL→`get_impact_lessons()`メソッド新設（TDD、3テスト追加、52テスト全パス）
- **`/scan-market-quick` 新設**: 開場前など時間がないとき用。WebSearch 2回で6カテゴリを広く浅くスキャン、深掘りフラグ付き。lesson参照は意図的にスキップ（impact誤りは`/review-events`で事後補正可能）
- ステップ番号修正（1→4→5→6 の飛びを1→2→3→4に）

### 前セッション（session 9, 4/2 夕方）

### コード改善: `to_save_kwargs()` 実装
- **問題**: `/update-regime` 実行時にRegimeAssessment→save_regime()の属性名マッピングを毎回推測し、4回連続AttributeError
- **原因分析**: `RegimeAssessment.indicators[i].name` / `save_regime()` kwargs / DBカラム名の3者間マッピングが暗黙知だった
- **解決**: `RegimeAssessment.to_save_kwargs(values)` メソッド追加。マッピング定数 `_INDICATOR_TO_DB_REGIME` / `_VALUE_KEY_TO_DB` をregime.py内に1箇所定義
- **テスト**: 3件追加（full data / partial data / シグネチャ照合）。`inspect.signature` でsave_regime()と自動照合
- **SKILL.md更新**: 手順4-5を属性推測不要な形に書き換え
- 全155テストGREEN

### エントリー分析
- SOXL/SOXS MAP独立分解評価実施。結論: **4/5-6バイナリーイベント前でどちらもエッジ薄い**
- レジーム→SOXS有利、K-022→レジーム≠方向、イベント→方向を決定的に支配

### 日次ワークフロー
- scan-market: 3件登録（tariff免除無期限延長、OPEC+ 4/5会合、プレマーケット先物急落）
- update-regime: **risk_off悪化**（score -0.71→-1.43）。VIX 24.5→26.4 high、VIX/VIX3M flat→backwardation、Brent $105.7→$108.2

### 前セッション（session 8, 4/2 昼）の成果
- SOXS/SOXL比較MAP分析、scan-market 3件、update-regime、review-events 7件、K-024/025記録

### 前セッション（session 7, 4/2 朝）

### Trade #2 決済・振り返り
- **Trade #2: SOXL long → スクラッチ決済** — $51.65→$51.631（-$0.49, -0.04%）
  - 日中高値$54.09(+4.7%)到達後、SLをBE($51.65)に引上げ→午後の戻しで約定
  - 引値$52.26。保持していればTP方向に進んでいた
  - **K-023登録**: 3xレバETFでエントリー当日のBE SL引上げは日中ボラ(2-3%)で刈られやすい

### 日次ワークフロー
- scan-market: 7件登録（4/1引け、イラン新攻撃、UK Hormuz会議、Brent<$100、Fed据置確認、ADP +62K、WH演説前ファクトシート）
- update-regime: risk_off維持（score -0.57）。Brent crisis→high改善、VIX/VIX3M contango→flat悪化が相殺
- 予測モニタリング: #2 $40割れ遠い、#3 反証条件ほぼ成立

### 前セッション（session 6, 4/1 夜）の成果
- Trade #2エントリー（$51.65×26株）、scan-market 5件、update_data.py --symbolオプション

### 前セッション（session 5, 4/1 夜）の成果
- `/entry-analysis` スキル実装（ADR-018）、compute_flow_inputs()、scan-market 4件

### 前セッション（session 4, 4/1 午後）の成果
- assess_flow()新設（ADR-017）、scan-market 4件、update-regime risk_off維持、review-events 1件

### 前セッション（session 3, 3/31夜〜4/1未明）の成果
- SOXLロング+10%利確（Trade #1）、ADR-015/016、trades実装、scan-market 19件

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

## マクロ環境メモ（4/7 10:30 JST時点）

- レジーム: **neutral（スコア-0.29）** — 4/7再判定済み。前日と同一regime
  - VIX **24.17** elevated(↓)、VIX/VIX3M **0.976** flat(↓改善)、HY 3.13 normal(↓)、Brent **$110.1** crisis(↑)、USD 120.7 normal(↓)
- **South Pars攻撃**: イラン石化能力85%オフライン。Brent $110超維持の背景
- **イラン停戦拒否**: 一時停戦を拒否、恒久的戦争終結+制裁解除を要求。Trump「significant but not good enough」
- **IRGC海軍声明**: 「Hormuzは二度と以前の状態に戻らない」。包括的作戦計画の最終準備段階
- **Trump火曜Hormuz期限**(5回目): 4/7 20:00 ET（4/8 9:00 JST）。「石器時代に戻す」と脅迫
- **Section 232関税改定**(4/6発効): 鉄鋼/アルミ/銅50%全額課税+医薬品100%。市場は無視
- **WTI>Brent逆転**: 継続中（WTI$112.41 vs Brent$110.11）
- 保有ポジション: **なし**。火曜期限後にエントリー判断（バイアス監査結論）
- **銘柄選定**: TQQQ long候補1位（sigma-0.46, R:R 1.1）。SOXL落選（ギャップリスク+R:R劣後）

## フィードバックループの進捗

GDR-001 Phase 1実装完了。Kolbサイクル（予測→結果→知見→次の予測）の追跡が可能に。
- Phase 1: source_prediction_id + root_cause_category + Brier 3成分分解 → **実装済み**
- Phase 2: EPA + SRS + Error Budget Burn Rate → Lv.2到達時
- Phase 3: Calibration Curve + カテゴリ別分析 → Lv.3到達時

## 健康診断からの処方箋（3/29）

- 毎セッション1件以上の予測記録を厳守（Lv.2到達の最大ボトルネック）
- 確信度の幅を広げる（20%や80%も使う。40-55%に集中するとアンカリング疑い）
- instrument/riskカテゴリの知見を意識的に記録（meta偏重の是正）

## Obstacles

- 予測蓄積が3件のみ（Brier計測開始したが統計的意味はN>=30から）
- レジーム判定がrisk_offとneutralのみ（risk_on未経験。K-002: 判別力未検証）
- イベント#4と#63が重複（CME FedWatch 52%）。重複検出の仕組みが未整備
- Polygon.io Starter契約中（$29/月）。研究完了後に継続/解約を判断

## Completed

- [x] Phase 1-2: データ基盤 + レジーム判定
- [x] ADR-001〜010
- [x] GDR-001: 成長計測体系の設計 + Phase 1実装
- [x] SessionStartフック: SenseiDB化 + [ACTION]フォーマット（ADR-008）
- [x] Stop Hook: command型に簡素化
- [x] Skills導入: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- [x] CLAUDE.md: トリガールール再設計、SQL所有権ルール追加
- [x] 予測#1解決: VIX<25 → False、Brier 0.2025（初計測）
- [x] 予測#1ポストモーテム: root_cause=overconfidence、K-007/K-014連鎖
- [x] ProviderChain統合: update_data.pyでyfinance→FRED自動フォールバック
- [x] ADR-009実装: スナップショット・source列・market_observations廃止・レビュー対応
- [x] ADR-010実装: /scan-market + /review-events + skill_executions
- [x] データ全更新 + レジーム再判定（3/28、risk_off）
- [x] 初回フルスキャン: 15ヶ月×6カテゴリ、32件登録、5知見記録
- [x] 知見全13件検証済み（staleゼロ）
- [x] 予測#2登録: SOXL $40割れ（55%、期限4/11）
- [x] /review-events初回実行: 34件検証、4件impact修正、レビュー率79%
- [x] ADR-011作成: GDR-001 Phase 1スキーマ変更の記録
- [x] ADR-012作成: スキル粒度設計の原則（5原則 + 日次ワークフロー定義）
- [x] MCP DuckDB接続: .mcp.json（相対パス、read-only）、旧設定削除、hookロック競合解消
- [x] scan-market SKILL.md: inline Pythonコメント除去（セキュリティ警告回避）
- [x] 日次ワークフロー初回完走: scan-market→update_data→update-regime→review-events
- [x] Memory運用設計: SoT確立 + キャッシュ層としてのMemory再構成
- [x] CLAUDE.md: Rules 2項目追記 + Memory運用ルールセクション追加
- [x] SKILL.md: scan-market/review-eventsにポジション影響シナリオ指針追加
- [x] SKILL.md: scan-market/review-eventsのheredoc方式移行（obfuscation警告解消）
- [x] SKILL.md: scan-market手順3にlesson照合ステップ追加（K-027対応）
- [x] K-027: impact判定バイアス固着パターン記録+バイアス監査実施
- [x] ADR-013作成: エントリーシグナル研究方法論（3段階ファネル）
- [x] ADR-013追記: バイアス対策（反証テスト4種+カテゴリタイプ4種+プロンプト対策5点+情報アクセス設計）
- [x] アイデア生成: 21手法→67カテゴリ+3メタ+30設計原則（101件カタログ）
- [x] カテゴリタイプ分類: 68件→4タイプ（Parquetにbias_test_type/reason列追加）
- [x] ADR-014作成: Parquet Raw定義+スプリット調整方針
- [x] Polygon.io契約+18銘柄×5年分5分足OHLCV取得（3,456,034バー）
- [x] 予測#3登録: SOXS +10%超再出現（75%、期限4/11）
- [x] K-020/K-021登録: LLM Agentバイアス + Devil's Advocate最適形態
- [x] WIP-progress.md新設: 研究進捗のcondition.mdからの分離
- [x] polygon-data-reference.md新設: API仕様・データ特性記録
- [x] ADR-015: トレード記録のデータ設計 + trades実装（add/close/review_trade）
- [x] ADR-016: 命名規則の明文化
- [x] ADR-017: フロー評価関数 assess_flow()（4指標、方向連動VOLUME_SURGE）
- [x] update_data.py: サマリー表示機能（マクロ/日足/5分足の最新値一覧）
- [x] Trade #1: SOXLロング +10% ($120.15) 利確・記録
- [x] ADR-018: /entry-analysis スキル（最小版）— MAP 3軸+シナリオ別注文設定+trade記録
- [x] compute_flow_inputs(): Parquet→assess_flow入力の自動計算（8テスト追加、150テスト全パス）
- [x] Trade #2: SOXL long $51.65→$51.631 スクラッチ決済（BE SL引上げで刈られ）
- [x] K-023: 3xレバETFのBE SL知見（エントリー当日は日中ボラで刈られやすい）
- [x] ADR-019: 日時供給統一 — now_jst()/today_jst()に16箇所統一、SessionStart時刻注入、152テスト全パス
- [x] verify-knowledge: 8件検証（K-017 validated、K-018修正、6件検証日更新）
- [x] to_save_kwargs(): RegimeAssessment→save_regime()マッピングの冪等化（3テスト追加、155テスト全パス）
- [x] /update-regime SKILL.md: 属性推測不要な手順に書き換え
- [x] scan-market速度改善: P1(DB統合)+P2(シェルコマンド除去)+ADR-008違反修正+ステップ番号修正
- [x] /scan-market-quick新設: 2検索・深掘りフラグ・lesson意図的スキップ
- [x] get_impact_lessons()メソッド新設+テスト3件（52テスト全パス）
- [x] GitHub Public repo設定（ksyunnnn/Master-Sensei、origin、noreply email）
- [x] Publicセキュリティ強化: .gitignore強化 + permissions.deny + .env 600 + push提案ルール
- [x] Obsidian PKM原則調査（docs/references/obsidian-pkm-principles.md）
- [x] ADR-020: knowledgeテーブルにtldr・related_knowledge_ids列追加（8テスト、166テスト全パス）
