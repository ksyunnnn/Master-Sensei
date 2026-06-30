# 作業トラッカー運用（GDR-003）

セッションをまたいで残す「開いている作業」の正本。**condition.md に代わる handoff の置き場**。

- **場所**: GitHub Project #2（owner `ksyunnnn`）= https://github.com/users/ksyunnnn/projects/2
- **アイテム**: `ksyunnnn/Master-Sensei` の**実 Issue**を Project に載せる（公開。GDR-003 で許容決定）。
- **入れるもの**: 「次の一手」「生きている仮説」＝**セッションをまたいで残すべき開いた作業**。
- **入れないもの**: 既に DB/フックが渡すもの（予測・regime・trades・knowledge）。期限切れ予測の resolve は SessionStart が surface するので**二重起票しない**。

## 設計の要点

- **「開いている作業」= OPEN な Issue**。完了/取り下げは **Issue を close** して表現する（Issue 本来の意味＝起票→解決に合致）。よって開始時の読み取りは `--query "is:open"` で済み、堅牢。
- **フィールド名は ASCII**（`state`/`kind`/`result`/`review`）。理由: jq で日本語の**キー**を参照すると encoding 不整合で null になる。**値は日本語のまま**（人間可読）。
- **優先度フィールドは置かない**（陳腐化するため・GDR-003）。緊急度は `review`(再評価日) と件数の少なさで捌く。
- 参照（ADR番号・予測ID・K番号）は Issue 本文にテキストで書く。最後に触った日は native の `updatedAt`。
- 標準英語 `Status`(Todo/In Progress/Done) は削除不可のため残骸として無視し、必ず `state` を使う。

## フィールド

| field(ASCII) | 型 | 値 |
|---|---|---|
| state | 単一選択 | 未着手 / 対応中 / 完了 / 取り下げ（完了・取り下げは Issue close でも表現） |
| kind | 単一選択 | 次の一手 / 仮説 |
| result | 単一選択 | 当たり / 外れ / 判定不能（仮説のクローズ時） |
| review | 日付 | 任意（カタリスト紐付け＆「先送り」兼用） |

## ID キャッシュ（書き込みに必要・固定値）

```
PROJECT_NUMBER = 2          OWNER = @me (ksyunnnn)
PROJECT_ID     = PVT_kwHOATs9I84BcExW

state  field = PVTSSF_lAHOATs9I84BcExWzhWwRAA   未着手=c3c16154 対応中=2cd1743b 完了=4db0b61d 取り下げ=5a2fc2a9
kind   field = PVTSSF_lAHOATs9I84BcExWzhWwRAE   次の一手=b5537181 仮説=73852785
result field = PVTSSF_lAHOATs9I84BcExWzhWwRAI   当たり=48815bc2 外れ=927d994d 判定不能=244fe8c9
review field = PVTF_lAHOATs9I84BcExWzhWwRAM     (DATE; item-edit --date YYYY-MM-DD)
```

field/option-id を引き直したい時: `gh project field-list 2 --owner @me --format json`

## セッション開始時に読む（OPEN のみ・ASCIIキーで安定）

```
gh project item-list 2 --owner @me --query "is:open" --format json --jq \
  '[.items[] | {number: .content.number, title, url: .content.url, state, kind, review}]'
```

## 新規作成（Issue → Project 追加 → フィールド設定）

```
url=$(gh issue create -R ksyunnnn/Master-Sensei --title "<件名>" --body "<本文・参照>")
itemid=$(gh project item-add 2 --owner @me --url "$url" --format json --jq .id)
gh project item-edit --id "$itemid" --project-id PVT_kwHOATs9I84BcExW --field-id PVTSSF_lAHOATs9I84BcExWzhWwRAE --single-select-option-id b5537181   # kind=次の一手
gh project item-edit --id "$itemid" --project-id PVT_kwHOATs9I84BcExW --field-id PVTSSF_lAHOATs9I84BcExWzhWwRAA --single-select-option-id c3c16154   # state=未着手
```

仮説を起票する時は kind=仮説(73852785)。item-id は `gh project item-list 2 --owner @me --format json --jq '.items[]|select(.content.number==<N>).id'` で取得。

## 進める / 閉じる

```
gh project item-edit --id <itemid> --project-id PVT_kwHOATs9I84BcExW --field-id PVTSSF_lAHOATs9I84BcExWzhWwRAA --single-select-option-id 2cd1743b   # state=対応中
gh issue close <番号> --reason completed       # 完了（=state 完了相当。Issueをcloseすれば開始時readから外れる）
gh issue close <番号> --reason "not planned"   # 取り下げ
```

仮説のクローズは `result`（当たり=48815bc2 / 外れ=927d994d / 判定不能=244fe8c9）も設定してから close する。
item-edit は **1回1フィールド**。project/field/option-id は上のキャッシュを使い回す（item-id だけ毎回取る）。

## 注意

- 同一 Issue の同一フィールドを複数セッションが同時編集した場合は後勝ち（公式に競合検出なし）。別 Issue なら競合しない。本文は上書きでなく必要なら追記コメントで。
- `project` スコープが要る（`gh auth status` で確認、無ければ `gh auth refresh -s project`）。
- jq では**日本語キーを使わない**（`."状態"` 等は null になる）。フィールド名は必ず ASCII。
