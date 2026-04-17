# ADR-001: Scheduler — Leitner 5-box

- Status: accepted
- Date: 2026-04-16

## Context and Problem Statement

ドリルアプリは忘却曲線に沿って出題タイミングを決める必要がある。50-200 問規模の日本語金融用語を対象に、mastery を Leitner / SM-2 / FSRS / 自己実装 のいずれで管理するか。

## Decision Drivers

- MVP のシンプルさ (実装規模 < 100 行)
- 50-200 問規模で noise に埋もれない性能
- ML training や parameter tuning を MVP では導入しない
- 質問バンクが成長したら algorithm を差し替え可能な抽象化

## Considered Options

- **Leitner 5-box**: 5 段階の fixed interval (1d/2d/4d/8d/16d)、正解 → box+1、誤答 → box 1
- **SM-2** (SuperMemo 2, 1988): Interval × Ease Factor、response quality 0-5
- **FSRS** (2022+): 3-component memory model、17 parameters を ML で tune
- **Anki 統合**: 既存アプリに問題集を流し込む

## Decision Outcome

**Leitner 5-box を採用**。

根拠: PNAS 2019 (Tabibian et al.) の大規模実験で、fixed-interval spacing でも distributed practice による retention 向上は統計的に有意。FSRS の優位は 1000+ cards の regime で顕著で、Expertium benchmark によれば 50-200 問では log loss の差が noise に埋もれる。MVP には Leitner が合理的、成長したら ADR-NNN で FSRS に差し替える。

Anki 統合は独立性を損ねる (別アプリで CLI とは統合不能) ため不採用。

### Consequences

- 良い面: 実装 ~80 行、決定論的挙動でデバッグ容易、test が簡単
- 悪い面: ユーザー個別の forgetting rate に適応しない
- 見直しトリガー: 質問バンクが 200 問超えた時、ADR-NNN で FSRS 移行検討

## Pros and Cons of the Options

### Leitner 5-box
- Pros: シンプル、deterministic、well-validated、依存ゼロ
- Cons: fixed interval、performance adaptive でない

### SM-2
- Pros: Anki 互換、個別適応
- Cons: Ease Factor の初期値 tuning が難しい、Leitner より実装 2-3 倍

### FSRS (2022+)
- Pros: 最も精密、3-component memory model (R/S/D)
- Cons: 17 params、ML training 必要、少データ時に不安定、実装 500+ 行

### Anki 統合
- Pros: ecosystem 活用
- Cons: CLI 統合不能、independence 要件違反

## References

- [Enhancing Human Learning via Spaced Repetition Optimization (Tabibian et al., PNAS 2019)](https://www.pnas.org/doi/10.1073/pnas.1815156116)
- [FSRS vs SM-2 Benchmark (Expertium)](https://expertium.github.io/Benchmark.html)
- [Leitner System (Wikipedia)](https://en.wikipedia.org/wiki/Leitner_system)
