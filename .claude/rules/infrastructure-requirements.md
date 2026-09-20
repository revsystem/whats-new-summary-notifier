# インフラ要件

このファイルはインフラ操作・設定変更時に必ず参照すべき固定値と制約を記述する。

## AWS プロファイル

- 本番: `production`
- サンドボックス: `sandbox`
- SSO ログイン: `aws sso login --profile production`
- AWS CLI / CDK コマンドは常に `--profile production` を付ける

このリポジトリは public のため、アカウント ID は記載しない。ID が必要な場面では `aws sts get-caller-identity --profile <name> --query Account --output text` で解決する。操作前にこのコマンドで対象アカウントを確認する運用は従来どおり。

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
- `/WhatsNew/AlertURL` — CloudWatch アラームの通知用 (`#whats-new-alerts`)。`cdk.json` の context キー `alertWebhookUrlParameterName` で指定する。記事配信用とは分けてあり、アラート用 Lambda は配信用パラメータを読めない

新しい notifier を追加する場合:
1. SSM Parameter Store に SecureString でパラメータを作成する
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

`UsageQuantity` の単位はサービスによって違う。Marketplace 系 (`USW2-MP:...-Units`) は百万トークン単位だが、`Amazon Bedrock` として課金されるモデル (`USW2-NovaPro-input-tokens` など) は千トークン単位。モデルの単価で換算してサービス全体の Usage と一致するか確かめること。

### クレジットの扱い

`RECORD_TYPE` を分けずに集計すると Usage と Credit が相殺され、`Amazon Bedrock` サービスが `$0` に見える。使っていないのではなく、全額クレジットで消えている。

```bash
aws ce get-cost-and-usage --time-period Start=<from>,End=<to> --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE \
  --filter '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Usage"]}}' --profile production
```

`Values` を `["Credit"]` にして 2 回引き、突き合わせる。2025-09 〜 2026-09 の実績では、クレジットは `Amazon Bedrock` の Usage とほぼ一致して適用される一方、`(Amazon Bedrock Edition)` の Marketplace 課金には適用されていない。2026-08-06 の Terra 移行は、モデル単価の上昇だけでなく推論コストがクレジットの対象外へ移る変更だった。クレジット残高は Cost Explorer からは分からないため Billing コンソールの Credits で確認する。

### アカウント内の他プロジェクトの費用

production アカウントには当プロジェクト以外の LLM 費用（Claude 各モデル、Cohere Embed）が乗っている。プロジェクト単位で見るには `SERVICE` を `OpenAI GPT-5.6 Luna (Amazon Bedrock Edition)` / `OpenAI GPT-5.6 Terra (Amazon Bedrock Edition)` / `Amazon Bedrock` に絞る。絞らずに「LLM 費用」として報告してはならない。

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
