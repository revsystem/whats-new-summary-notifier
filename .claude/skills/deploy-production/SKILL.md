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

期待値: `"Account": "531713114752"` が含まれること。含まれない場合は再ログインする。

```bash
aws sso login --profile production
```

1. Docker が起動していることを確認する:

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
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" cdk deploy --require-approval never --profile production
```

- `--require-approval never`: IAM や セキュリティグループの変更を自動承認する
- 初回またはブートストラップ未実施の場合: `cdk bootstrap --profile production` を先に実行する

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
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" cdk deploy --require-approval never --profile production
git checkout -
```

## トラブルシューティング

Lambda タイムアウト (180 秒) が続く場合: CloudWatch Logs で Bedrock の呼び出しエラーを確認する。`modelRegion` (us-west-2) でモデルアクセスが有効になっているか確認する。

`ExpiredTokenException`: `aws sso login --profile production` で再ログインする。

Docker credential エラー (`docker-credential-desktop.exe not found`): PATH に `/mnt/c/Program Files/Docker/Docker/resources/bin` を追加する。
