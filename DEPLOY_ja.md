# デプロイガイド

## デプロイ手順

> [!IMPORTANT]
> このリポジトリでは、デフォルトで米国西部 (オレゴン) リージョン (us-west-2) の Amazon Nova Pro モデル (クロスリージョンインファレンスプロファイル) を利用する設定になっています。[Model access 画面 (us-west-2)](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2#/modelaccess)を開き、Amazon Nova Pro にチェックして Save changes してください。

### Webhook URL の取得

通知に必要となる Webhook URL の払い出しを行います。

#### Slack の設定

[こちらのドキュメント](https://slack.com/intl/ja-jp/help/articles/360041352714-%E3%83%AF%E3%83%BC%E3%82%AF%E3%83%95%E3%83%AD%E3%83%BC%E3%82%92%E4%BD%9C%E6%88%90%E3%81%99%E3%82%8B---Slack-%E5%A4%96%E9%83%A8%E3%81%A7%E9%96%8B%E5%A7%8B%E3%81%95%E3%82%8C%E3%82%8B%E3%83%AF%E3%83%BC%E3%82%AF%E3%83%95%E3%83%AD%E3%83%BC%E3%82%92%E4%BD%9C%E6%88%90%E3%81%99%E3%82%8B)を参考にして Webhook URL を取得してください。「変数を追加する」を選び、次の 5 つの変数をすべてテキストデータタイプで作成します。

- `rss_time`: 記事の投稿時間
- `rss_link`: 記事の URL
- `rss_title`: 記事のタイトル
- `summary`: 記事の要約
- `detail`: 記事の箇条書き説明

### AWS Systems Manager Parameter Store を作成

Parameter Store を使って 通知用の URL をセキュアに格納します。

#### パラメータストア登録 (AWS CLI)

```bash
aws ssm put-parameter \
  --name "/WhatsNew/URL" \
  --type "SecureString" \
  --value "<Webhook URL を入力>"
```

特定のAWSプロファイルを使用している場合は、`--profile`オプションを追加してください：

```bash
aws ssm put-parameter \
  --name "/WhatsNew/URL" \
  --type "SecureString" \
  --value "<Webhook URL を入力>" \
  --profile your-profile-name
```

### 言語設定の変更 (オプション)

このアセットはデフォルトで日本語の要約を出力するように設定されています。英語等の他言語の出力を行う場合は、`cdk.json` を開き、`context` 内の `notifiers` 内の `summarizerName` を `AwsSolutionsArchitectJapanese` から `AwsSolutionsArchitectEnglish` などに書き換えてください。その他の設定オプションについては[設定オプション](#設定オプション)を参照してください。

### デプロイの実行

**デプロイ先リージョン**

デプロイ先リージョンは `CDK_DEFAULT_REGION` で指定します。`.env.example` を `.env` にコピーし、リージョン（例: `CDK_DEFAULT_REGION=us-east-1`）を設定してください。未設定の場合は `us-east-1` が使われます。

AWS プロファイルのデフォルトリージョンがデプロイ先と異なる場合、CDK の bootstrap 参照がプロファイルのリージョンを参照してしまいます。その場合は `AWS_DEFAULT_REGION` もあわせて指定してください。

**初期化**

このリージョンで CDK を使用したことがない場合は、次のコマンドを実行します。

```bash
cdk bootstrap
```

特定のAWSプロファイルを使用している場合は、`--profile`オプションを追加してください：

```bash
cdk bootstrap --profile your-profile-name
```

**エラーがないことを確認**

```bash
cdk synth
```

特定のAWSプロファイルを使用している場合は、`--profile`オプションを追加してください：

```bash
cdk synth --profile your-profile-name
```

**デプロイの実行**

```bash
cdk deploy
```

特定のAWSプロファイルを使用している場合や、プロファイルのリージョンがデプロイ先と異なる場合は、以下のように指定してください：

```bash
AWS_DEFAULT_REGION=us-east-1 cdk deploy --profile your-profile-name
```

## スタックの削除

不要になった場合は以下のコマンドを実行しスタックを削除します。

```bash
cdk destroy
```

特定のAWSプロファイルを使用している場合は、`--profile`オプションを追加してください：

```bash
cdk destroy --profile your-profile-name
```

デフォルトでは Amazon DynamoDB テーブルなど一部のリソースが削除されず残る設定となっています。
完全な削除が必要な場合は、残存したリソースにアクセスし、手動で削除を行ってください。

## トラブルシューティング

### 依存関係の競合

デプロイ中に依存関係の競合が発生した場合、システムが自動的に互換性のあるバージョンを解決します。requirements.txtファイルは、自動依存関係解決を可能にするように設定されています。

### Dockerビルドの問題

- CDKコマンドを実行する前にDockerが実行されていることを確認してください
- ビルドプロセスは自動的にダウンロードされるAWS SAMビルドイメージを使用します
- ビルドが失敗した場合は、まず`cdk synth`を実行して設定を確認してください

### よくある問題

1. **モデルアクセス**: AWSリージョンで必要なBedrockモデルが有効になっていることを確認してください
2. **プロファイル設定**: 名前付きAWSプロファイルを使用している場合は、常に`--profile`オプションを使用してください
3. **リージョンの一貫性**: すべてのリソースが同じAWSリージョンにデプロイされていることを確認してください

# 設定オプション

本アセットは、AWS CDK の context で設定を変更します。

[cdk.json](cdk.json) の `context` 以下の値を変更することで設定します。各設定項目についての説明は下記の通りです。

## 共通設定
* `modelRegion`: Amazon Bedrock を利用するリージョン。Amazon Bedrock を利用可能なリージョンの中から、利用したいリージョンのリージョンコードを入力してください。
* `modelId`: Amazon Bedrock で利用する基盤モデルの model ID。各モデルの model ID はドキュメントを参照ください。
* `modelApiMode`: モデルの呼び出し方式。`bedrock-runtime` エンドポイントの Converse API で提供されるモデルは `converse`、`bedrock-mantle` エンドポイントの Responses API でのみ提供されるモデルは `responses` を指定します。省略時は `converse` として扱われます。`modelId` と `modelApiMode` が対応していない場合、Lambda 関数は起動時にエラーになります。

### モデルの切り替え手順

下表の `modelId` はいずれも一方の API でしか呼び出せないため、`modelId` を変更したら対応する `modelApiMode` も合わせて確認します（同じ `modelApiMode` の別モデルへ移る場合は `modelId` の変更だけで済みます）。

| モデル | `modelId` | `modelApiMode` |
| --- | --- | --- |
| Amazon Nova Pro | `us.amazon.nova-pro-v1:0` | `converse` |
| OpenAI GPT-5.6 Terra | `openai.gpt-5.6-terra` | `responses` |
| OpenAI GPT-5.6 Luna | `openai.gpt-5.6-luna` | `responses` |

GPT-5.6 系のモデルは `bedrock-runtime` の Converse API でも提供されていますが、その場合はクロスリージョン推論プロファイル ID（`us.openai.gpt-5.6-luna` など）の指定が必須で、さらに `project/default` に対する `bedrock:InvokeModel` 権限が必要になります。本スタックはこの権限を付与しないため、上表のとおり素の model ID を `responses` で呼び出します。

1. [cdk.json](cdk.json) の `context` 内で該当する値を変更します。
2. `cdk deploy` でデプロイします。不正な `modelApiMode` は synth 時点で、`modelId` との不一致は Lambda 起動時に検出されるため、片方だけ変更した状態が本番に到達することはありません。
3. `NotifyNewEntry` の CloudWatch Logs で最初の数件を確認します。

`responses` のモデルへ切り替える場合の注意点は次のとおりです。

* スタックは `responses` のときにのみ `bedrock-mantle:CallWithBearerToken` と `bedrock-mantle:CreateInference` を付与します。両方が必要で、前者だけでは `AccessDeniedException` になります。
* 推論モデルは記事あたりの所要時間が長いため、`responses` のときは Lambda のタイムアウトを 180 秒から 600 秒に引き上げます。
* GPT-5.6 Terra のような推論モデルは `temperature` と `top_p` を受け付けません。指定すると HTTP 400 `unsupported_parameter` になるため、この経路では `max_output_tokens` と推論の effort のみを渡します。

元に戻す場合は、以前の `modelId` と `modelApiMode` の組み合わせに戻して `cdk deploy` を実行します。両方の呼び出し経路が関数内に残っているため、コードの変更は不要です。

## summarizers
生成 AI に入力する要約用プロンプトの設定を行います。

* `outputLanguage`: モデル出力の言語。
* `persona`: モデルに与える役割 (ペルソナ)。

## notifiers
アプリケーションへの配信設定を行います。

* `destination`: 投稿先のアプリケーション名。`slack`を設定してください。
* `summarizerName`: 配信に使用する summarizer の名前。
* `webhookUrlParameterName`: Webhook URL を格納している AWS Systems Manager Parameter Store のパラメータ名。
* `rssUrl`: 最新情報を取得したい Web サイトの RSS フィード URL。URL は複数指定する事が可能です。
* `schedule` (オプション): CRON 形式の RSS フィード取得間隔。本パラメータの指定がない場合は、毎時 00 分にフィードを取得します。下記の例の場合は、15 分に一度フィード取得が行われます。

```json
...
"schedule": {
  "minute": "0/15",
  "hour": "*",
  "day": "*",
  "month": "*",
  "year": "*"
}
```

# 操作環境の準備 (AWS Cloud9)
本手順では、AWS 上に必要なツールがインストールされた開発環境を作成します。環境構築には、AWS Cloud9 を使用します。
AWS Cloud9 についての詳細は、[AWS Cloud9 とは?](https://docs.aws.amazon.com/ja_jp/cloud9/latest/user-guide/welcome.html)を参照してください。

1. [CloudShell](https://console.aws.amazon.com/cloudshell/home) を開いてください。
2. 以下のコマンドでリポジトリをクローンしてください。
```bash
git clone https://github.com/aws-samples/cloud9-setup-for-prototyping
```
3. ディレクトリに移動してください。
```bash
cd cloud9-setup-for-prototyping
```
4. コスト最適化のため必要に応じてボリュームの容量を変更します。
```bash
cat <<< $(jq  '.volume_size = 20'  params.json )  > params.json
```
5. スクリプトを実行してください。
```bash
./bin/bootstrap
```
6. [Cloud9](https://console.aws.amazon.com/cloud9/home) に移動し、"Open IDE" をクリックします。

> [!NOTE]
> 本手順で作成した AWS Cloud9 環境は、利用時間に応じて EC2 料金が従量課金で発生します。
> 30 分未操作の場合は自動停止する設定になっていますが、インスタンスボリューム (Amazon EBS) の課金は継続して発生するため、
> 料金発生を最小限にしたい場合は、アセットのデプロイ後に [AWS Cloud9 で環境を削除する](https://docs.aws.amazon.com/ja_jp/cloud9/latest/user-guide/delete-environment.html)に従って環境の削除を行ってください。
