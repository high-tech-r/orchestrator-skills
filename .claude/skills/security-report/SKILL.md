# Skill: security-report（ステークホルダー向けセキュリティ証跡レポート生成）

## いつ使うか
- リリース時・納品時に、ステークホルダーへ渡すセキュリティ証跡をまとめるとき
- 「セキュリティレポートを作って」「証跡を出して」と指示されたとき
- 定期報告（月次・スプリント末）でセキュリティ状況を提示するとき

このスキルは機能単位のパイプライン（requirements〜review-guide）の**外**にある。
求められたときに単発で実行する。

## 入力（証跡の取得元）
最新のセキュリティCI（`Security (Level 2)`）が生成した成果物を使う。

1. **CI成果物をダウンロード**（GitHub Actionsの最新成功runから）:
   ```bash
   gh run download -n sca-evidence   -D .evidence   # sbom.cdx.json / license-report.txt / trivy.sarif
   gh run download -n sast-semgrep-sarif -D .evidence # semgrep.sarif
   ```
   取得できない場合（ローカル実行等）は、リポジトリ内の最新スキャン出力を使うか、
   その旨をレポートに明記する（証跡は「取得できた範囲」を正直に書く）。
2. **CIの合否**: 最新の `Security (Level 2)` run の各ジョブ結果（pass/fail）。
3. **Gate 2 の整合性レポート**: `docs/consistency_report/*_gate2.md`（実装の誠実性チェック結果を含む）。

## 出力ファイル
`docs/delivery/security_report_YYYY-MM-DD.md`（ステークホルダーがそのまま読める日本語・実日付）。
納品ドキュメントは `docs/delivery/` に集約する（`delivery` スキル参照）。

```markdown
# セキュリティ証跡レポート

- 対象: （プロジェクト名 / リリース or コミットSHA）
- 作成日: YYYY-MM-DD
- 検査ツール構成: レベル2（無料・言語非依存）

## 1. 総合判定
✅ 全品質ゲート通過 / ⚠️ 指摘あり（対応状況を後述）

## 2. 検査結果サマリー
| 検査 | ツール | 結果 | 指摘 |
|------|--------|------|------|
| 秘密情報 | TruffleHog/Gitleaks | ✅ なし | 0件 |
| 既知の脆弱性 | Trivy/OSV | ✅ / ⚠️ | CRITICAL n / HIGH n |
| 静的解析 | Semgrep | ✅ / ⚠️ | n件（内訳） |
| ライセンス | Trivy | ✅ | 違反 0件 |
| 実装の誠実性 | Gate 2 | ✅ | 偽の成功/握り潰し 0件 |
| 動的解析(DAST) | OWASP ZAP | 実施/未実施 | n件 |

## 3. 脆弱性の内訳（あれば）
| ID(CVE等) | 深刻度 | 対象 | 状態（対応済/許容/未対応） |

## 4. SBOM・ライセンス
- SBOM: `sbom.cdx.json`（CycloneDX、別添）。コンポーネント総数 N。
- ライセンス: `license-report.txt`（別添）。要注意ライセンス（GPL等）の有無を明記。

## 5. 残存リスクと対応方針
（許容したCRITICAL/HIGHや未対応項目があれば、理由と対応予定を正直に記載）

## 6. 添付
- スキャン結果（SARIF）/ SBOM / ライセンスレポート / CI実行記録へのリンク
```

## 重要なルール（誠実性）
- **取得できなかった証跡を「問題なし」と書かない。** 未取得・未実施は「未取得」「未実施」と明記する。
- 数値（脆弱性件数等）は成果物の実データから転記する。推測で埋めない。
- 許容したリスク（CRITICAL/HIGHを残してリリース等）は隠さず「残存リスク」に理由付きで書く。
- ステークホルダーが読む前提で、専門用語には1行の補足を付ける（SBOM＝ソフトウェア部品表 等）。
- 本レポートの構成・表現は `SECURITY.md`（ステークホルダー向け説明）と整合させる。
