# スタックプロファイル: Laravel（リファレンス例）

> **これはリファレンス例です。権威ではありません。** 自分の Laravel/PHP バージョンで通用するか
> 必ず確認し、食い違えば更新すること（適用先の Claude Code が腐敗に気づいたら直す前提）。

## メタ情報
- 対象スタック: Laravel / PHP（Sail 想定。素の環境でも読み替え可）
- 最終確認日: 2026-06-21
- 出典: Laravel 公式ドキュメント（HTTP Tests / Mocking / Queues / Mail）

## 1. 起動・動作確認
- 起動: `docker compose up -d`（Sail なら `./vendor/bin/sail up -d`）
- 動作確認: `curl -i http://localhost/`、ルート確認は `php artisan route:list`
- 対話確認: `php artisan tinker`（モデル操作・ジョブ dispatch を手で試せる）
- キューワーカー: `php artisan queue:work`（ジョブを処理する。起動していないと滞留）

## 2. テスト実行
- 実行: `php artisan test`（PHPUnit / Pest）。コンテナ内なら `docker compose exec app php artisan test`
- 特定テスト: `php artisan test --filter=メソッド名`
- カバレッジ: `php artisan test --coverage`（Xdebug/PCOV が必要）

## 3. インターフェース種別ごとの動作確認
- HTTP API: `curl` or テストの `$this->postJson('/api/xxx', [...])`。APIドキュメントUIは標準では無い
- 非同期ジョブ / キュー: `dispatch(new SomeJob(...))`（tinker可）→ `php artisan queue:work` で処理。
  メールはジョブ経由のことが多いので **キュー接続とワーカー** を意識する
- イベント / リスナー: `event(new SomeEvent(...))` で発火
- CLIコマンド: `php artisan app:do-something`
- スケジュール: `php artisan schedule:run`（手動トリガ）／個別は対応コマンドを直接実行

## 4. テストダブル（外部作用の検証）
外部作用は **fake してから『呼ばれたこと』を assert** する（ステータスだけで成功と判定しない）。
```php
Mail::fake();
// ... 実行 ...
Mail::assertSent(ResetPasswordMail::class);     // 送信されたことまで検証
Mail::assertNothingSent();                       // 未実装なら「送られない」を固定

Queue::fake();      Queue::assertPushed(ProcessJob::class);
Bus::fake();        Bus::assertDispatched(SomeJob::class);
Notification::fake(); Notification::assertSentTo($user, InvoicePaid::class);
Event::fake();      Event::assertDispatched(OrderShipped::class);
Storage::fake('s3'); Storage::disk('s3')->assertExists('file.txt');
Http::fake();       Http::assertSent(fn ($r) => $r->url() === 'https://api.example.com/x');
```
- ローカルでの目視確認には **Mailpit**（Sail同梱、`http://localhost:8025`）でメールを受信確認できる

## 5. 依存・必要サービス
- 依存定義: `composer.json` / `composer.lock`（PHP）、フロントがあれば `package.json`
- 必要サービス: DB（migrate: `php artisan migrate`）、キュー（`QUEUE_CONNECTION`）、メール（Mailpit 等）
- テストは `RefreshDatabase` トレイトでDBを毎回リセットするのが定石

## 6. よくある落とし穴・トラブルシュート
- メールが届かない → ジョブがキューに積まれたまま。`queue:work` 起動 or `QUEUE_CONNECTION=sync` を確認
- テストで外部作用が実発火 → `fake()` の呼び忘れ
- `.env` と `.env.testing` の差異（DB/キュー/メール接続）
- マイグレーション未実行 → `php artisan migrate`（テストは `RefreshDatabase`）
- `419`（CSRF）/ `Bearer null` 等は認証前提の崩れ。トークン未取得のまま叩いていないか
