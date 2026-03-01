# セキュリティ要件

このファイルはコードや設定を変更する際に必ず遵守すべきセキュリティ要件を記述する。

## CDK nag (AwsSolutionsChecks)

`bin/cdk_test.ts` は CDK スタックの synth 時に AwsSolutionsChecks を実行する。

- nag で検出されたルール違反は必ず対処すること
- AWS のベストプラクティスから意図的に逸脱する場合は `NagSuppressions` で理由を明記して抑制する
- 抑制なしに警告を放置してはならない

```typescript
// 例: 意図的な逸脱に対する suppression
NagSuppressions.addResourceSuppressions(resource, [
  {
    id: 'AwsSolutions-IAM5',
    reason: 'Wildcard is required for dynamic DynamoDB table access',
  },
]);
```

## Slack Webhook URL の管理

Webhook URL は必ず SSM Parameter Store の SecureString として保存する。

- 平文での保存・コード内へのハードコードは禁止
- SSM パラメータ名は `cdk.json` の `notifiers.<name>.webhookUrlParameterName` で定義する (例: `/WhatsNew/URL`, `/WhatsNewF1/URL`)
- CDK スタックで `ssm.StringParameter.fromSecureStringParameterAttributes` を使って参照する
- Lambda 環境変数に URL を直接設定してはならない

## Bedrock モデルアクセス

Amazon Bedrock のモデルアクセスは `cdk.json` の `modelRegion` で指定したリージョン (現在 `us-west-2`) で有効化が必要。

- デプロイ前にモデルアクセス画面 (Bedrock コンソール) で `Amazon Nova Pro` が有効になっていることを確認する
- モデルアクセスが無効だと Lambda 実行時に `AccessDeniedException` が発生する
- `modelRegion` を変更する場合は、新しいリージョンでのモデルアクセス有効化を必ず先に行う

## IAM 最小権限

Lambda 実行ロールは最小権限の原則に従う。

- DynamoDB アクセスはテーブル ARN に限定する (ワイルドカードは nag suppression + 理由を必ず付ける)
- Bedrock の InvokeModel はモデル ARN で限定する
- SSM GetParameter はパラメータ ARN で限定する
- `*` リソースへのアクセスは原則禁止。やむを得ない場合は CDK nag suppression で理由を記載する
