# docs/delivery/ — 納品ドキュメント

顧客に渡す成果物を集約するフォルダ。**開発者向けの設計書・整合性レポート**（`docs/design/`,
`docs/consistency_report/` 等）とは分け、ここには**顧客向けに要約・整形したもの**だけを置く。

`delivery` スキルで一括生成する（個別に `quality-report` / `security-report` を実行してもよい）。

| ファイル | 内容 | 生成スキル |
|---|---|---|
| `index.md` | 納品物一覧・品質/セキュリティの担保方法の要約 | `delivery` |
| `design_summary.md` | 顧客向け設計サマリー（提供機能・構成） | `delivery` |
| `quality_report_YYYY-MM-DD.md` | テスト・バグ・ゲート通過状況 | `quality-report` |
| `security_report_YYYY-MM-DD.md` | セキュリティ検査内容と証跡 | `security-report` |

SBOM・ライセンスレポート・SARIF はCIの成果物（`sca-evidence` / `sast-semgrep-sarif`）として
別途ダウンロードし、納品時に添付する（[`../security/LEVEL2_SECURITY.md`](../security/LEVEL2_SECURITY.md) 参照）。

> このリポジトリ（テンプレート）では本フォルダは空。生成プロジェクトで上記が出力される。
> 現時点で Gamma 等でのスライド化は手動（本フォルダのMarkdownを元データとする）。
