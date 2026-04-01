# ADR-018: /entry-analysis スキル（最小版）

Status: accepted
Date: 2026-04-01

## Context

Session 3でTrade #1（SOXL +10%）を実行した際、以下の問題が発生した:

1. **後知恵バイアス**: entry_reasoningが利確後に事後記録された（created_at: 4/1 15:23、entry_date: 3/31）
2. **記録者の問題**: ユーザーの意思決定をMaster Senseiが要約。ユーザー自身の言葉ではない
3. **再現性の欠如**: 即興の分析フロー（マクロ6/10等）が標準化されていない

ADR-012の見直しトリガーに「予測が5-10件に到達してからスキル化を検討」とあるが、
現在3件（解決1）。後知恵バイアスの排除は予測件数に依存しない緊急性があるため早期着手する。

### 自己評価で検出したバイアス

- **Session 3アンカリング**: 地政学シナリオに固定されたテンプレートを回避する必要がある
- **複雑性バイアス**: 初版では銘柄比較・期待値計算・予測自動起草を含めない

## Decision

### スコープ（最小版）

| 含む | 含まない（将来拡張） |
|------|-------------------|
| 3軸MAP分析（Regime + Flow + Event Risk） | 銘柄比較（4軸目） |
| シナリオ別の注文設定（エントリー価格・TP・SL） | 期待値の定量計算 |
| Confidence選択肢→ユーザー確認→add_trade()記録 | 予測の自動起草 |
| 関連知見・既存予測の参照 | 結果分布の確率計算 |

### ユーザーが最も知りたいこと

「いくらで入る？」— 抽象的なスコアではなく、シナリオに基づく具体的な注文設定が核心。

### 3軸MAP分析

Charter 3.3の独立分解評価を適用。各軸を独立に評価してから統合する。

| 軸 | 実装 | 出力 |
|----|------|------|
| Regime | assess_regime() | risk_on / neutral / risk_off + スコア |
| Flow | assess_flow() + compute_flow_inputs() | bullish / neutral / bearish + スコア |
| Event Risk | get_active_events()で今後7日分 | イベント件数・カテゴリ・密度 |

### シナリオ構築

- テンプレート固定しない。イベント・レジームから動的に2-3シナリオを構築
- 各シナリオに確率を付与（Tetlock方式）
- 対象銘柄の想定値動きをシナリオごとに推定

### 注文設定の根拠

- **TP/SL**: 日足の20日σ・SMAから統計的根拠を計算。「なんとなく+10%/-5%」は禁止
- **エントリー価格**: 前日終値・直近サポレジから
- **数量**: ユーザーのポートフォリオルールに基づく

### Confidence

Master Senseiが3段階の選択肢を根拠付きで提示。ユーザーが選択。

### trade記録

ユーザー確認後、add_trade()を自動実行:
- entry_reasoning: MAP分析結果+シナリオの構造化テキスト（エントリー時点で記録=後知恵バイアス排除）
- regime_at_entry, vix_at_entry, brent_at_entry: Parquetから自動取得
- confidence_at_entry: ユーザー選択値
- setup_type: シナリオから導出

## Implementation

### 新規ファイル
- `.claude/skills/entry-analysis/SKILL.md` — スキル本体
- `docs/adr/018-entry-analysis-skill.md` — 本ADR

### 変更ファイル
- `src/flow.py` — compute_flow_inputs()追加（Parquet→assess_flow入力の自動計算）
- `tests/test_flow.py` — compute_flow_inputs()テスト追加
- `CLAUDE.md` — Skills一覧更新

### ADR-012 P1-P5適合確認

| 原則 | 適合 | 理由 |
|------|------|------|
| P1: 単一責務 | OK | 「この銘柄にいくらで入るか」という1つの判断サイクル |
| P2: 単独実行可能 | OK | データが古い場合はスキル内で警告+update_data.py提案 |
| P3: インフラと判断の分離 | OK | データ取得はupdate_data.py。スキルはassess_regime/assess_flowを呼ぶだけ |
| P4: オーケストレーションは外 | OK | scan-market→update-regime→entry-analysisの順序はCLAUDE.mdの行動ルール |
| P5: 状態検出と行動指示の分離 | OK | Hookが状態検出、CLAUDE.mdが指示、スキルが実行 |

## Consequences

- エントリー時点でentry_reasoningが自動記録される（後知恵バイアス排除）
- 分析フォーマットが標準化される（assess_regime + assess_flow + events）
- スナップショットが自動取得される
- 見直しトリガー:
  - 10トレード蓄積後、entry_reasoningのフォーマットを振り返り改善
  - ADR-013研究のutils.py完成時、銘柄比較（4軸目）を追加検討
  - confidence選択肢の較正（calibration curveで検証）
