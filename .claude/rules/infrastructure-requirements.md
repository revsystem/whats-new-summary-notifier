# インフラ要件

このファイルはインフラ操作・設定変更時に必ず参照すべき固定値と制約を記述する。

## AWS プロファイル

- 本番: `production` (Account ID: 531713114752)
- サンドボックス: `sandbox` (Account ID: 722326486642)
- SSO ログイン: `aws sso login --profile production`
- AWS CLI / CDK コマンドは常に `--profile production` を付ける

## CDK コンテキスト設定 (cdk.json)

| キー | 現在値 | 説明 |
|------|--------|------|
| `modelRegion` | `us-west-2` | Bedrock 推論リージョン |
| `modelId` | `us.amazon.nova-pro-v1:0` | クロスリージョン推論プロファイル ID |

`modelId` の `us.` プレフィックスはクロスリージョン推論プロファイルを示す。CDK スタックは IAM ポリシー生成時にこのプレフィックスを除去してベースモデル ID を取得する。

## SSM パラメータ

Slack Webhook URL は SSM Parameter Store に SecureString として登録する。

現在登録済みのパラメータ名:
- `/WhatsNew/URL` — AwsWhatsNew notifier 用
- `/WhatsNewF1/URL` — F1WhatsNew notifier 用

新しい notifier を追加する場合:
1. SSM に SecureString でパラメータを作成する
2. `cdk.json` の `notifiers.<name>.webhookUrlParameterName` に同じパラメータ名を記載する
3. CDK スタックが自動的に Lambda の IAM ロールに GetParameter 権限を付与する

## CloudWatch Logs

Lambda のロググループ名は CDK で固定値として設定されている:
- NotifyNewEntry: `/aws/lambda/NotifyNewEntry`
- NewsCrawler: `/aws/lambda/newsCrawler`
- 保持期間: 2 週間 (`RetentionDays.TWO_WEEKS`)

## Lambda タイムアウト設定

| Lambda | タイムアウト |
|--------|-------------|
| notify-to-app | 180 秒 |
| rss-crawler | 60 秒 |

Bedrock の推論と Web スクレイピングを含むため notify-to-app のタイムアウトは長め。変更する場合はレート制限との兼ね合いを考慮する。

## cdk.json の notifier 設定構造

```json
{
  "notifiers": {
    "<NotifierName>": {
      "destination": "slack",
      "summarizerName": "<SummarizerName>",
      "webhookUrlParameterName": "<SSM パラメータ名>",
      "rssUrl": {
        "<フィード名>": "<RSS URL>"
      },
      "schedule": {
        "minute": "<分>",
        "hour": "*",
        "day": "*",
        "month": "*",
        "year": "*"
      }
    }
  }
}
```

`schedule` を省略した場合はデフォルト (毎時 00 分) が適用される。
