---
name: deploy-production
description: Use when deploying the whats-new-summary-notifier stack to production, running cdk deploy, or verifying a deployment. Covers WSL2 Docker credential setup, CDK deploy, post-deploy Lambda testing, and rollback.
user-invocable: true
---

# deploy-production

本番環境 (production プロファイル) へのデプロイ手順。

## 前提条件チェック

デプロイ前に以下を確認する。

1. AWS SSO ログイン状態を確認する:

```bash
aws sts get-caller-identity --profile production
```

期待値: SSO プロファイルに設定されたアカウントと一致すること。次のコマンドが同じ値を 2 行返せば一致している。

```bash
aws configure get sso_account_id --profile production
aws sts get-caller-identity --profile production --query Account --output text
```

失効している場合は再ログインする。

```bash
aws sso login --profile production
```

2. Docker が起動していることを確認する:

```bash
docker info
```

エラーが出た場合は Docker Desktop を起動してから再試行する。

## WSL2 固有の設定 (必須)

WSL2 環境では Docker Desktop の認証ヘルパー (`docker-credential-desktop.exe`) を PATH に追加しなければ `cdk deploy` が失敗する。

```bash
export PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin"
```

この export を毎回実行するか、デプロイセッションの冒頭で確認すること。

## CDK デプロイ

```bash
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" npx cdk deploy --require-approval never --profile production
```

- `--require-approval never`: IAM や セキュリティグループの変更を自動承認する
- 初回またはブートストラップ未実施の場合は先に実行する: `npx cdk bootstrap --profile production`

`cdk` ではなく `npx cdk` と書くのは、`package.json` の `aws-cdk` 依存を使うため。グローバルに入った `cdk` が `aws-cdk-lib` の出力する cloud assembly を読めないバージョンだと、`Cloud assembly schema version mismatch: Maximum schema version supported is 43.x.x, but found 52.0.0` で何もせずに止まる。現に npm の `aws-cdk@3.0.0`（2025 年 4 月に誤って公開され deprecated 扱い）が入っていた環境でこれが起きた。semver 上は 3.0.0 がすべての 2.x を上回るため、バージョン解決の仕方によっては選ばれてしまう。

本番の `cdk deploy` は auto mode の `soft_deny` 対象として `~/.claude/settings.json` に登録されている。セッションから直接叩くと `[Production Deploy]` で拒否されるため、このスキル経由で実行する。

### 認証情報が解決できないとき

`Need to perform AWS calls for account <アカウント ID>, but no credentials have been configured` や `Unable to resolve AWS account to use.` で止まる場合は、認証情報を環境変数へ展開してから実行する。`--profile` で解決できるのが通常なので、これは回避策として使う。

```bash
eval "$(aws configure export-credentials --profile production --format env)"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" npx cdk deploy --require-approval never
```

## デプロイ後の確認

### Lambda ログの確認

```bash
aws logs tail /aws/lambda/NotifyNewEntry --follow --profile production
```

### Lambda のテスト invoke

`/tmp/test_event.json` にテストイベントを用意して実行する:

```json
{
  "Records": [
    {
      "eventName": "INSERT",
      "dynamodb": {
        "NewImage": {
          "url": {"S": "https://example.com/test-article"},
          "notifier_name": {"S": "AwsWhatsNew"},
          "title": {"S": "Test Article"},
          "category": {"S": "Test"},
          "pubtime": {"S": "2024-01-01T00:00:00Z"}
        }
      }
    }
  ]
}
```

```bash
aws lambda invoke \
  --function-name "$(aws lambda list-functions --profile production --query 'Functions[?starts_with(FunctionName, `WhatsNewSummaryNotifierStac-NotifyNewEntry`)].FunctionName' --output text)" \
  --payload file:///tmp/test_event.json \
  --cli-binary-format raw-in-base64-out \
  --profile production \
  /tmp/lambda_response.json && cat /tmp/lambda_response.json
```

## ロールバック

直前のコミットに戻す場合:

```bash
git checkout <前のコミット SHA>
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" npx cdk deploy --require-approval never --profile production
git checkout -
```

## トラブルシューティング

Lambda タイムアウト (`modelApiMode=responses` の現行設定では 600 秒) が続く場合: CloudWatch Logs で Bedrock の呼び出しエラーを確認する。`modelRegion` (us-west-2) でモデルアクセスが有効になっているか確認する。

`ExpiredTokenException`: `aws sso login --profile production` で再ログインする。回避策として認証情報を環境変数へ展開していた場合は、再ログイン後に展開し直す。

Docker credential エラー (`docker-credential-desktop.exe not found`): PATH に `/mnt/c/Program Files/Docker/Docker/resources/bin` を追加する。
