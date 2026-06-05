# Saxo 現金口座 (外国株式特定) の取引制約

円建て現金口座 (T126816 / P120136 等) で米国株/ETF を売買する際の制約。
**注文設計・sizing の前に必ず参照する** (ADR-026)。

> この文書は「現金がいつ・いくら使えるか」を軸にする。2026-06 セッションで
> 「同一銘柄を売って即買い直せない＝同一銘柄ロック」という規則を仮定したが、
> **Saxo 公式に該当規則は無く、実体は現金の予約不足だった**ことが判明した (後述)。

## 確度の記号

- **【確実】** API/実機で確認 ＋ Saxo 公式と一致
- **【公式】** Saxo 公式文書に記載 (実機未測定)
- **【未解明】** 根拠が取れていない

関連: [K-031](#) (現金予約と同一銘柄事象、knowledge)、[balance-fields.md](balance-fields.md)、
[cost-fields.md](cost-fields.md)、[ADR-026](../../adr/026-external-api-field-discipline.md)。

---

## 1. 受渡とお金が使えるまで (T+1)

- **株を売っても代金は翌営業日 (value date = T+1) まで未決済**で、それまで利用可能現金に入らない。**【確実】**
  - API 実証 (2026-06-04, `get_trade_reports`): 直近4約定すべて `value_date = trade_date + 1営業日`。

    | trade_date | 取引 | value_date |
    |---|---|---|
    | 2026-06-01 | SOXL buy 3@$218 | 2026-06-02 (+1) |
    | 2026-06-02 | SOXL sell 3@$243.18 | 2026-06-03 (+1) |
    | 2026-06-03 | SOXL buy 3@$267 | 2026-06-04 (+1) |
    | 2026-06-03 | SOXL sell 3@$258.925 | 2026-06-04 (+1) |

- 公式 (ルールの存在): [Can I use my funds before the value date?](https://www.help.saxo/hc/en-us/articles/360001281946)
  = 売却資金は決済 (value date) 後にのみ使える。**【公式】**

---

## 2. 「いま使える現金」の計算 ← 取引可否の核心

**利用可能現金 = 現金残高 −（未決済 ＋ 未約定注文の予約現金[市場オープン時] ＋ buffer）**

- **未決済の売却代金は利用可能現金から減算**される (transactions not booked)。**【確実】**
  - 実機: 損切り round-trip 後 `TransactionsNotBooked = −¥4,848`、
    `CashBalance ¥319,224 − SpendingPower ¥314,376 = ¥4,848` と一致。
  - 公式: [How much cash available](https://www.help.saxo/hc/en-us/articles/13062483999517) /
    [Breakdown of transactions not booked](https://www.help.saxo/hc/en-us/articles/360046506672)。

- **未約定の買い注文は、市場オープン中に約定必要額を予約 (ブロック) する。クローズ中はしない。** **【公式】**
  - 原文: "When the market is open, the orders block the cash necessary to be executed for cash
    products like stocks." / "The working orders will not block the cash when the market is closed."
    ([13062483999517](https://www.help.saxo/hc/en-us/articles/13062483999517))
  - 買い注文時の判定: "the system checks the cash balance available **plus cash reserved for any
    pending Buy order(s)**" ([Why insufficient cash](https://www.help.saxo/hc/en-us/articles/360027506271))
  - 実機補足: クローズ中に $228 買い注文 (5株) が Working でも `CashBlocked = ¥0` を確認 (=クローズ中は予約しない)。
    **オープン中の予約は実機未測定 (次回確認)。**

- **クローズ中の成行買いには追加 buffer (銘柄レーティングに応じ 10〜50%) が要求される。** **【公式】**
  ([360027506271](https://www.help.saxo/hc/en-us/articles/360027506271))。指値推奨。

- sizing には `SpendingPower` / `CashAvailableForTrading` を使う (settled `CashBalance` でない)。
  詳細: [balance-fields.md](balance-fields.md)。

---

## 3. 為替コスト (円口座で米国株)

- 円口座で USD 建て商品を売買すると約定ごとに JPY⇄USD 変換 (片道 0.25% / 往復 0.5%)。
  SOXL 往復 break-even ≈ **0.72〜0.87%**。**【確実】** (`get_trade_cost` で実測、ADR-029 / K-040)
- 公式料金: [Commissions, Charges and Margin Schedule](https://www.home.saxo/rates-and-conditions/commissions-charges-and-margin-schedule)。**【公式】**
- **USD 口座運用なら per-trade 為替が 0 になり break-even を最大 ~0.5% 下げられる** (方針判断は保留、検討課題)。

---

## 4. 「同じ銘柄を売って即・買い直せなかった」事象の分析

### 観測 (2026-06-03)
- SOXL を $258.925 で売却 → 同日 SOXL 再買付が**拒否**。**【確実】**
- 同日 TQQQ (1株 ≈$86) は**通った**。**【確実】**

### 結論: 原因は現金の予約不足。「同一銘柄ロック」ではない
- **拒否は現金不足系の問題**。SOXL は KID あり・ロング・市場オープン中で、他の拒否理由も該当せず、
  残るのは現金不足のみ。**Saxo 公式の "insufficient cash" 3理由・注文拒否理由・キャンセル理由の
  いずれにも「同一銘柄を買い直せない」規則は存在しない** (記事3本を精読)。**【確実】**
- **現金を圧迫していたメカニズムも特定済み**: $228 の未約定買い注文 (5株 ≈ $1,140 ＝口座の約半分) が
  市場オープン中に予約現金として差し引かれていた (§2 の公式理由が作動)。$228 注文が 6/3 市場時間中に
  Working だったことは API で確認済み。**＝原因は「未約定注文の予約 ＋ 未決済 ＋ buffer で利用可能
  現金が不足」**。**【確実】**(メカニズム)
- TQQQ が通ったのは「別銘柄だから」でなく「**小額で残額に収まったから**」と解釈すれば全観測と整合。

### 残骸 (原因の本筋ではない) **【未解明】**
- **正確な算数**: 拒否瞬間の `CashAvailableForTrading` と試した SOXL 注文サイズを未記録 → 「いくら足りなかったか」は再現不能。
- **エラー文言**: 記録の "Transactions not booked cannot be used to buy more of the same security" は
  公式3理由のどれとも一致しない。誤記録か、Saxo の未文書メッセージか不明。

### 実務上の扱い
同日の反転・再エントリーを計画する時は、**未約定注文の予約現金＋未決済を引いた"実際に使える現金"で判断**する。
縛りは銘柄でなく現金。資金を空けたいなら未約定注文を MODIFY/キャンセルしてから。

---

## 5. wash trading (同時の対向注文) ← §4 とは別物

- 同一銘柄の**売り注文と買い注文を同時に市場に出す**と、取引所でマッチして wash trading (自己取引) になりうる。**【公式】**
  ([記事](https://www.help.saxo/hc/en-us/articles/10757755481373))。対策: portfolio transfer / 指値 / 対向注文を同時に出さない。
- これは「**注文が同時にマッチ**」する話で、§4 の「売却完了後に再買付」とは別シナリオ。混同しない。

---

## 6. 空売り・市場時間

- 保有していない株の空売りは不可 (現金口座)。**【公式】**
- 市場クローズ中に成行注文は出せない。**【公式】**
- 既存注文 (IFD-OCO 等) の MODIFY は可能 (実機確認)。**【確実】**

---

## 未検証 / 残課題

- **§2 オープン中の現金予約を実機で測定** (working order ありの状態で市場オープン中の `CashBlocked`)。
- **§4 の算数と文言の確定**: 拒否再現時に「エラー文言スクショ＋`CashAvailableForTrading`＋注文サイズ」を記録。
- buffer の具体割合 (§2)、売り指値/stop の予約挙動 (§2 は買い指値のみ)。
- **§3 為替コストの projection vs realized 不一致【要検証】**: #14 往復 (2026-06-04, SOXL 5株 $232→$266) を `account_transactions` で確認すると、両レグの `amount_jpy` が ほぼ同一 fx (160.009) で計上され **FX スプレッドが台帳上に顕在化しない** (realized 手数料は $5.65 = USD 手数料のみ)。`get_trade_cost` の projection (為替 0.501% / 往復 break-even 0.72-0.87%, K-040) と矛盾。FX が ①price に内包 ②別 booking ③当口座で非課金 のどれか未確定。再現時に `amount_jpy`・別 fee booking・約定価格の内訳を突合して確定する。
- 同方向逆銘柄 (SOXL 売り→SOXS 買い) の扱い (未実証)。
- USD 口座ベース移行の検討 (§3)。

## 誤帰属の経緯 (再発防止)

§4 の原因について、2026-06 セッションで **T+1差金決済 → wash trading → freeriding → 同一銘柄ロック**
と4回誤った断定をして撤回した。教訓:
- 「公式記事の URL を引用 = 精査した」ではない。**記事の中身が自分の遭遇シナリオと一致するか**まで読む。
- **観測 (TQQQ可・SOXL不可) を1つの仮説で説明できても、別の単純な説明 (現金予約不足) を排除していない**と原因は確定しない。
- 確定できるのは「現金不足系」までで、正確な算数・文言は記録が無ければ未解明、と正直に区別する (ADR-026 と同根)。
