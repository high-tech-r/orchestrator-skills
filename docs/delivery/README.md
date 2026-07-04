# docs/delivery/ — 納品ドキュメント

ステークホルダーに渡す成果物を集約するフォルダ。**開発者向けの設計書・整合性レポート**（`docs/design/`,
`docs/consistency_report/` 等）とは分け、ここには**ステークホルダー向けに要約・整形したもの**だけを置く。

`delivery` スキルで一括生成する（個別に `quality-report` / `security-report` を実行してもよい）。

| ファイル | 内容 | 生成スキル |
|---|---|---|
| `index.md` | 納品物一覧・品質/セキュリティの担保方法の要約 | `delivery` |
| `design_summary.md` | ステークホルダー向け設計サマリー（提供機能・構成） | `delivery` |
| `quality_report_YYYY-MM-DD.md` | テスト・バグ・ゲート通過状況 | `quality-report` |
| `security_report_YYYY-MM-DD.md` | セキュリティ検査内容と証跡 | `security-report` |
| `presentation_YYYY-MM-DD.md` | ステークホルダー説明用スライド（**Gamma取り込み用Markdown**） | `delivery` |

SBOM・ライセンスレポート・SARIF はCIの成果物（`sca-evidence` / `sast-semgrep-sarif`）として
別途ダウンロードし、納品時に添付する（[`../security/LEVEL2_SECURITY.md`](../security/LEVEL2_SECURITY.md) 参照）。

## Gamma でスライド化（ステークホルダー説明用PPT）

`presentation_*.md` は [Gamma](https://gamma.app) に取り込んでスライド/PPTにする前提で生成される。

1. Gamma で「Import」→ Markdown を貼り付け or アップロード
2. `---`（水平線）ごとに1スライドに分割される（本ファイルはその規約で生成済み）
3. テーマを選び、必要なら微調整
4. PPT / PDF としてエクスポートしてステークホルダーに提示

> 元データの正は常に本フォルダのMarkdown。スライドは見せ方であり、数値・合否はレポートと一致させる。

> このリポジトリ（テンプレート）では本フォルダは空。生成プロジェクトで上記が出力される。
