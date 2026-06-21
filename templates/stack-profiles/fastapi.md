# スタックプロファイル: FastAPI（リファレンス例）

> **これはリファレンス例です。権威ではありません。** 自分の Python/FastAPI バージョンで通用するか
> 必ず確認し、食い違えば更新すること。

## メタ情報
- 対象スタック: FastAPI / Python（Docker 想定）
- 最終確認日: 2026-06-21
- 出典: FastAPI 公式（Testing）/ pytest / respx

## 1. 起動・動作確認
- 起動: `docker compose up -d --build`
- 動作確認: `curl -i http://localhost:8000/`
- APIドキュメントUI: `http://localhost:8000/docs`（Swagger UI。"Try it out" で手動実行可）

## 2. テスト実行
- 実行: `docker compose exec app pytest -v`
- 特定テスト: `pytest -k テスト名`
- カバレッジ: `pytest --cov=src`

## 3. インターフェース種別ごとの動作確認
- HTTP API: `curl` or Swagger UI（`/docs`）。テストは `TestClient`（`from fastapi.testclient import TestClient`）
- 非同期ジョブ / キュー: Celery等なら `task.delay(...)`。テストは eager 実行（`task_always_eager`）or `task.apply()`
- イベント: アプリ実装の発火関数を直接呼ぶ
- CLIコマンド: エントリポイント（Typer/Click 等）を `python -m ...` で実行
- スケジュール: スケジューラ（APScheduler/cron）対象の関数を直接呼ぶ

## 4. テストダブル（外部作用の検証）
外部作用は **mock してから『呼ばれたこと』を assert** する（ステータスだけで成功と判定しない）。
```python
from unittest.mock import patch

with patch("src.services.mailer.send_reset_email") as m:
    # ... 実行 ...
    m.assert_called_once()          # 送信処理が呼ばれたことまで検証
    # 未実装なら m.assert_not_called() で「送られない」を固定 or 501 を検証

# 外部HTTP は respx でモック
import respx, httpx
@respx.mock
def test_x():
    respx.get("https://api.example.com/x").mock(return_value=httpx.Response(200))

# 依存の差し替えは app.dependency_overrides[dep] = fake_dep
```
- ローカルのメール目視確認は MailHog / Mailpit 等のキャッチャを docker-compose に足す

## 5. 依存・必要サービス
- 依存定義: `requirements.txt` / `requirements-dev.txt`（or pyproject.toml）
- 必要サービス: DB、（あれば）キュー/ブローカ、メールキャッチャ
- async テストは `pytest-asyncio`、HTTPは `httpx`/`TestClient`

## 6. よくある落とし穴・トラブルシュート
- `ModuleNotFoundError` → 依存が requirements に無い／未インストール
- async テストが動かない → `pytest-asyncio` 未導入 or マーカー漏れ
- 外部HTTPが実発火 → `respx`/mock の対象URL/パス不一致
- `Connection refused` → コンテナ未起動（`docker compose up -d`）
- `Bearer null` 等 → 認証トークン未取得のまま叩いている（前提崩れ）
