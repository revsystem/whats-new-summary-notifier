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

期待値: `production` プロファイルのアカウント ID が返ること。失効している場合は再ログインする。

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
eval "$(aws configure export-credentials --profile production --format env)"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" npx cdk deploy --require-approval never
```

- `--require-approval never`: IAM や セキュリティグループの変更を自動承認する
- 初回またはブートストラップ未実施の場合は、同じ環境変数を与えて先に実行する:

```bash
eval "$(aws configure export-credentials --profile production --format env)"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" \
  npx cdk bootstrap "aws://${CDK_DEFAULT_ACCOUNT}/${CDK_DEFAULT_REGION}"
```

コマンドの形が込み入っているのは、次の 3 点がいずれも必要なため。省略すると失敗する。

`npx cdk` で `package.json` の `aws-cdk` 依存を使う。グローバルの `cdk`（mise 管理の npm-aws-cdk）は古く、`aws-cdk-lib` が出力する cloud assembly の schema を読めないため `Cloud assembly schema version mismatch: Maximum schema version supported is 43.x.x, but found 52.0.0` で止まる。

`aws configure export-credentials` で認証情報を環境変数へ展開する。同梱 CLI は `--profile production` を渡しても SSO の認証情報を解決できず、`Need to perform AWS calls for account <アカウント ID>, but no credentials have been configured` になる。`aws sts get-caller-identity --profile production` が通っていてもこの症状は出る。

`CDK_DEFAULT_ACCOUNT` と `CDK_DEFAULT_REGION` を明示する。`bin/whats-new-summary-notifier.ts` がスタックの `env` をこの環境変数から読んでおり、未設定だと `Unable to resolve AWS account to use.` で synth 後に止まる。

本番の `cdk deploy` は auto mode の `soft_deny` 対象として `~/.claude/settings.json` に登録されている。セッションから直接叩くと `[Production Deploy]` で拒否されるため、このスキル経由で実行する。

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
eval "$(aws configure export-credentials --profile production --format env)"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin" npx cdk deploy --require-approval never
git checkout -
```

## トラブルシューティング

Lambda タイムアウト (`modelApiMode=responses` の現行設定では 600 秒) が続く場合: CloudWatch Logs で Bedrock の呼び出しエラーを確認する。`modelRegion` (us-west-2) でモデルアクセスが有効になっているか確認する。

`ExpiredTokenException`: `aws sso login --profile production` で再ログインする。`eval "$(aws configure export-credentials ...)"` で展開した認証情報は再ログイン後に展開し直す。

Docker credential エラー (`docker-credential-desktop.exe not found`): PATH に `/mnt/c/Program Files/Docker/Docker/resources/bin` を追加する。
