# アーキテクチャ制約ルール

このファイルはコードを編集する際に必ず遵守すべきアーキテクチャ上の制約を記述する。

## Lambda アーキテクチャ

データフロー: EventBridge → rss-crawler Lambda → DynamoDB → (Stream) → notify-to-app Lambda → Slack

- rss-crawler: EventBridge のスケジュールトリガーで起動し、RSS を取得して DynamoDB に書き込む
- notify-to-app: DynamoDB Stream のトリガーで起動し、Bedrock で要約して Slack に投稿する
- 2 つの Lambda は直接呼び出し関係にない。DynamoDB Stream が唯一の連結点

## DynamoDB 設計

テーブル名: `WhatsNewRSSHistory` (CDK で生成される物理名は異なる)

キー構造:
- パーティションキー: `url` (STRING)
- ソートキー: `notifier_name` (STRING)

重複排除は `put_item` の上書き動作で自然に解決される。明示的な重複チェックは不要で、行わない。

アイテムに含まれるフィールド: `url`, `notifier_name`, `title`, `category`, `pubtime`

## DynamoDB Stream

- StreamViewType: `NEW_IMAGE`
- batchSize: `1`（CDK: `DynamoEventSource` の設定値）
- startingPosition: `LATEST`
- notify-to-app は `eventName == "INSERT"` のレコードのみ処理する。`REMOVE` / `UPDATE` はスキップする
- Stream イベント内の DynamoDB 属性アクセスパスは厳密に一致させること:
  ```python
  entry["dynamodb"]["NewImage"]["category"]["S"]
  entry["dynamodb"]["NewImage"]["pubtime"]["S"]
  entry["dynamodb"]["NewImage"]["title"]["S"]
  entry["dynamodb"]["NewImage"]["url"]["S"]
  entry["dynamodb"]["NewImage"]["notifier_name"]["S"]
  ```

## Lambda 同時実行数制限 (変更禁止)

notify-to-app の `reservedConcurrentExecutions` は `1` に固定されている。

変更禁止の理由: Slack の Incoming Webhook と Bedrock の InvokeModel API のレート制限対策。並列実行すると両方のエンドポイントでエラーが発生する。この値を増やしてはならない。

CDK での設定箇所: `lib/whats-new-summary-notifier-stack.ts` の `PythonFunction` コンストラクタ内 `reservedConcurrentExecutions: 1`

## EventBridge → Lambda イベント構造

CDK 側 (`lib/whats-new-summary-notifier-stack.ts`) で以下のキー名でペイロードを構築している:

```typescript
RuleTargetInput.fromObject({ notifierName, notifier })
```

Lambda 側 (`lambda/rss-crawler/index.py`) で以下のキー名で読み取る:

```python
notifier_name = event["notifierName"]   # キャメルケース
notifier = event["notifier"]
rss_urls = notifier["rssUrl"]           # cdk.json の notifier オブジェクト内フィールド
```

CDK 側のキー名と Lambda 側のキー名は必ず一致させること。変更する場合は両ファイルを同時に変更する。

## Bedrock パラメータ

ライブラリ: `strands-agents`。モデルの生成は `lambda/notify-to-app/index.py` の `build_model()` に集約され、`MODEL_API_MODE` で 2 経路に分岐する。

```python
# responses: bedrock-mantle の Responses API（現行の本番設定）
OpenAIResponsesModel(
    model_id=MODEL_ID,
    bedrock_mantle_config={"region": MODEL_REGION},
    params={"max_output_tokens": max_tokens, "reasoning": {"effort": "medium"}},
)

# converse: bedrock-runtime の Converse API
BedrockModel(
    model_id=MODEL_ID,
    region_name=MODEL_REGION,
    temperature=0.1,
    top_p=0.1,
    max_tokens=max_tokens,
    streaming=False,
)
```

- 現行モデル: `openai.gpt-5.6-luna`（`modelApiMode=responses`）。リージョンは `us-west-2`（`cdk.json` の `modelRegion`）
- `max_tokens` は 4096（`summarize_blog()` 内）。Responses 経路では `max_output_tokens` という名前で渡す
- GPT-5.6 系の推論モデルは `temperature` と `top_p` を受け付けない（HTTP 400 `unsupported_parameter`）。Responses 経路にこれらを追加してはならない
- `streaming=False` は Converse 経路で固定。True にするとレスポンスのパースロジックが壊れる
- Lambda 環境変数 `MODEL_ID` / `MODEL_REGION` / `MODEL_API_MODE` から読み込む（cdk.json の context 値がスタックで注入される）
- モデルを追加・変更する手順は `.claude/rules/infrastructure-requirements.md` と `DEPLOY_ja.md` を参照する

レスポンスのパース方法: モデル出力の XML タグから regex で抽出する。`summary` / `twitter` / `threads` / `bluesky` の 4 タグすべてが必要で、1 つでも欠けると `ValueError` を送出する（リトライ処理は持たない）。

```python
summary_matches = re.findall(r"<summary>([\s\S]*?)</summary>", outputText)
twitter_matches = re.findall(r"<twitter>([\s\S]*?)</twitter>", outputText)
# threads / bluesky も同じ形で抽出する
```

## F1 グロッサリー

場所: `lambda/notify-to-app/index.py` の `summarizer_name == "Formula1ProfessionalJapanese"` ブランチ内、`<glossary>` タグ内

含まれる内容:
- `<names>`: 現役・元ドライバー名、チーム代表名（例: Max Verstappen → マックス・フェルスタッペン、角田裕毅はそのまま）
- `<teams>`: 全 F1 チーム名（例: McLaren → マクラーレン、Alpine → アルピーヌ）
- `<technical_terms>`: F1 技術用語（例: Safety Car → セーフティカー、Qualifying → 予選）

変更禁止の理由: プロンプト全体が「グロッサリーに記載の日本語表記を必ず使え」という強制ルールで動作している。エントリを削除・変更すると Slack 投稿の表記が揺れ、ユーザー体験が壊れる。

新しいドライバーやチームを追加する場合は `<names>` または `<teams>` に追記する。既存エントリの日本語表記は変更しない。
