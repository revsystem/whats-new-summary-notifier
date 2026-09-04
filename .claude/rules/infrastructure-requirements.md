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
| `modelId` | `openai.gpt-5.6-luna` | 推論モデルの model ID |
| `modelApiMode` | `responses` | 呼び出し方式 (`converse` / `responses`) |

`modelId` と `modelApiMode` は対応していなければならない。`converse` は `bedrock-runtime` の Converse API、`responses` は `bedrock-mantle` の Responses API を使う。不正な `modelApiMode` は CDK synth 時に、`modelId` との不一致は Lambda 起動時 (`validate_model_config`) に検出される。Responses 経路の model ID は `lambda/notify-to-app/index.py` の `RESPONSES_ONLY_MODEL_IDS` に登録する。

`modelId` に `us.` プレフィックスが付く場合はクロスリージョン推論プロファイルを示す。CDK スタックは IAM ポリシー生成時にこのプレフィックスを除去してベースモデル ID を取得する。

`responses` 時はスタックが `bedrock-mantle:CallWithBearerToken` と `bedrock-mantle:CreateInference` を追加で付与し、notify-to-app のタイムアウトを 600 秒へ引き上げる。切り替え手順の詳細は `DEPLOY_ja.md` の「モデルの切り替え手順」を参照する。

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

## Cost Explorer でのモデルコスト集計

Bedrock Marketplace経由のサードパーティモデル(GPT-5.6 Terra等)の実コストは、AWS Cost Explorerで`SERVICE`ディメンションを`Amazon Bedrock`でフィルタしても捕捉できず`$0`と表示される。これらのモデルは`<モデル名> (Amazon Bedrock Edition)`という独立したサービス名(例: `OpenAI GPT-5.6 Terra (Amazon Bedrock Edition)`)で課金されるため。

コスト調査の手順:

1. まず`--group-by Type=DIMENSION,Key=SERVICE`でサービス名フィルタなしに集計し、実際のサービス名を確認する
2. 判明したサービス名で`--filter '{"Dimensions":{"Key":"SERVICE","Values":["<サービス名>"]}}'`を指定して日次コストを取得する
3. `USAGE_TYPE`でさらに group-by すると `cache_write_tokens_30m_standard` / `input_tokens_standard` / `output_tokens_standard` / `cache_read_tokens_standard` に分解できる。`UsageQuantity`は百万トークン単位の実数(例: `0.000858` = 858トークン)

## Lambda タイムアウト設定

| Lambda | タイムアウト |
|--------|-------------|
| notify-to-app | 600 秒 (`modelApiMode=responses` 時) / 180 秒 (`converse` 時) |
| rss-crawler | 60 秒 |

Bedrock の推論と Web スクレイピングを含むため notify-to-app のタイムアウトは長め。`responses` 経路は推論モデルで所要時間が伸びるためスタックが自動的に 600 秒へ引き上げる (`lib/whats-new-summary-notifier-stack.ts`)。変更する場合はレート制限との兼ね合いを考慮する。メモリは 512MB (OOM 対策で 256MB から引き上げ済み)。

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
