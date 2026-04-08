# Obsidian PKM 原則 — ナレッジ構築の参考情報

Status: reference
Date: 2026-04-05
Purpose: Master Senseiのknowledge/events/condition.md設計に対する外部視点の参照資料

---

## 1. 核原則: ノートは思考の媒体、保管庫ではない

Andy Matuschak: "Knowledge work needs a durable, iterative medium."
価値は**集めること**ではなく**再処理**から生まれる。

**Master Senseiへの示唆**: 「書き込み量」ではなく「再読・再執筆の頻度」で品質を測る。

---

## 2. Zettelkasten 3層構造（Sönke Ahrens）

| 層 | 役割 | Master Sensei対応 |
|---|------|-----------------|
| Fleeting notes | 数日で捨てる生の観察 | scan-marketの会話出力 |
| Literature notes | 他者の情報+ソース、1アイデア1ノート | events テーブル |
| Permanent notes | 自分の主張、単独完結、原子的 | knowledge テーブル |

**規律**: fleeting観察を即座にpermanentへ昇格させない。書き直して独立した主張にするまで待つ。
→ ADR-003「過去の自分が判断を誤る」テストと整合。

---

## 3. Atomicity ルール

Matuschak: "Evergreen notes should be atomic."

テスト:
- タイトルを断定形の主張にできるか？
  - Good: "VIX term structure inversion precedes regime shifts"
  - Bad: "VIX notes"
- 複数の文脈から参照されても読者が迷わないか？

**Master Sensei**: `knowledge.content` は単一主張であるべき。「and also...」が出たらK-YYYに分割。

---

## 4. Linking Philosophy（graphなしで80%の価値）

Obsidianの双方向リンクが価値を生む理由: **予期せぬ隣接ノート**を発見できるから。

Graph view なしでも achievable:
- **明示的参照**: `knowledge.source_prediction_id` の拡張として `related_knowledge_ids` を追加
- **Backlink queries**: SQL で「K-015を参照する全predictions/events」を取得
- **Link density > Taxonomy**: Nick Milo "Linking Your Thinking" — リンク数がノートの価値に比例

**アクション**: knowledge書き込み時、最も関連する既存knowledge 3件をsurfaceして明示的リンク判断を強制する。

---

## 5. MOC (Maps of Content) — 編集された索引

MOCは**手書きの入口**、自動生成リストではない。Nick Milo: "a MOC is an opinionated tour through a topic"。

**Master Sensei**: condition.md は既にMOCとして機能。ただし session summaries が無限蓄積する設計は MOC として不健全（argumentative structure ではなく log になる）。

---

## 6. Evergreen 進化

Matuschak: ノートは**密にリンクされ、概念志向で、毎回遭遇時に書き直される**べき。

Bryan Jenks: 6ヶ月revisionされないノートは居場所を問われるべき。

**Master Sensei**: `last_verified_date` + stale機構は正しい。不足は: **再検証時にcontentもrewrite**すること。日付だけ更新は死んだノート。

---

## 7. Tags vs Folders vs Links（community consensus）

| 用途 | 向き |
|------|-----|
| Folders | ライフサイクル・状態（inbox, archive）、トピックではない |
| Tags | 横断属性（status, confidence, domain）、ノートでない属性 |
| Links | 概念（再度考えるかもしれないものはノート化してリンク） |

**Master Sensei照合**:
- `knowledge.category` → tag的（正しい）
- `verification_status` → folder的（正しい）
- トピックタグは追加しない。トピックはknowledgeエントリにしてリンクする。

---

## 8. Daily Notes → Permanent Notes パイプライン

Daily note = **capture buffer and dispatcher**（日記ではない）。
毎朝の儀式: 昨日のdaily noteをレビュー → 永続的なものをpermanent notesに昇格 → クリア。

**Master Sensei**: scan-market や session log が daily note 相当。
欠けている儀式: **セッション終了時の明示的昇格ステップ** — "今日のevents/観察からknowledgeに昇格すべきは?"

Stop Hookに部分的に含まれるが、明示的なプロンプトとしては弱い。

---

## 9. Progressive Summarization（Tiago Forte CODE）

Capture → Organize → Distill → Express

Distill = 層化ハイライト: 重要部分を太字、核心を強調、要約を記述。

**Master Senseiへの示唆**: 全ノートに**数秒で取り出せる圧縮形式**。
→ `knowledge.tldr` 列（1文）を `content` と別に持つ。100件スキャン時にtldrを読み、行動時にcontentを読む。

---

## 10. 警戒すべきアンチパターン

| アンチパターン | 症状 | 指標 |
|------------|-----|------|
| Collector's fallacy | 処理なき収集 | write-to-revisit比 >10:1 |
| Premature categorization | ノート前の分類体系構築 | 30件未満で分類固定 |
| Tag sprawl | 1ノートに>2タグ、単発使用タグ | 要剪定 |
| Fake atomicity | 機械的分割で各ノート単独で無意味 | — |
| Link theater | リンクのためのリンク | "読者が飛んで得するか？" |
| Tool tinkering over writing | ツールが主、執筆が従 | Jenksの警告 |

---

## Master Sensei 現状との整合性サマリ

既に整合している:
- ADR-003のガバナンス = Permanent notes 昇格基準
- knowledge lifecycle（hypothesis→tested→validated/invalidated）= Evergreen 進化
- condition.md = MOC 的機能
- `last_verified_date` + stale機構 = 再検証サイクル
- K-XXX / ADR-XXX 番号体系 = Zettelkasten IDs

追加余地（高レバレッジ）:
- **A**: knowledge-to-knowledge リンク（`related_knowledge_ids`）
- **B**: `tldr` 列（Progressive Summarization）
- **C**: 再検証時のcontent rewrite義務化
- **D**: condition.md のsession log 分離
- **E**: セッション終了時のknowledge昇格プロンプト明示化

## 参照元

- Andy Matuschak — Evergreen notes: https://notes.andymatuschak.org/Evergreen_notes
- Sönke Ahrens — "How to Take Smart Notes" (2017)
- Nick Milo — Linking Your Thinking (LYT)
- Tiago Forte — "Building a Second Brain" (CODE/PARA)
- Bryan Jenks — Obsidian PKM practitioner
