# Doc Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** README.md/README_ja.md に DEPLOY.md/DEPLOY_ja.md の内容を吸収し、CLAUDE.md に research.md の技術知見を追加して、不要ファイルを削除することで認知負荷を下げる。

**Architecture:** DEPLOY.md の CDK context 設定リファレンスと Cloud9 セットアップを README の「Configuration Reference」「Appendix」セクションとして取り込む。research.md のエラーハンドリング戦略・データフロー・設計上の注意点を CLAUDE.md に追記する。

**Tech Stack:** Markdown のみ（コードなし）

---

### Task 1: README.md を更新する

**Files:**
- Modify: `README.md`

**Step 1: Change Log セクションを削除する**

`## Change Log` から始まり `## Third Party Services` の直前まで（"### Migration Notes" の3項目含む）を削除する。

削除対象:
```
## Change Log

### Recent Updates

- **Strands Agent SDK Integration**: ...
- **Dependency Management**: ...
- **Documentation**: ...
- **Profile Support**: ...

### Migration Notes

If you're upgrading from a previous version:
1. The Lambda functions now use Strands Agent SDK ...
2. Dependencies are automatically resolved ...
3. All CDK commands now support AWS profile specification
```

**Step 2: "Delete Stack" セクションの直後に Configuration Reference セクションを挿入する**

`## Delete Stack` セクションの末尾（"manually delete them." の行）の直後に以下を挿入する:

```markdown

## Configuration Reference

The application is configured via the `context` section in `cdk.json`.

### Common Settings

- `modelRegion`: AWS region for Amazon Bedrock. Enter the region code of an available Bedrock region.
- `modelId`: Bedrock model ID. Refer to the AWS documentation for model IDs.

### summarizers

Configure the prompt and persona used for AI summarization.

- `outputLanguage`: The language of the model output.
- `persona`: The role (persona) to assign to the model.

### notifiers

Configure delivery destinations and RSS sources.

- `destination`: The application to post to. Set to `slack`.
- `summarizerName`: The name of the summarizer to use.
- `webhookUrlParameterName`: The SSM Parameter Store parameter name storing the Webhook URL.
- `rssUrl`: RSS feed URLs to monitor. Multiple URLs can be specified.
- `schedule` (optional): RSS polling interval in cron format. Defaults to every hour at minute 00.

```json
"schedule": {
  "minute": "0/15",
  "hour": "*",
  "day": "*",
  "month": "*",
  "year": "*"
}
```

### Appendix: Setting Up the Environment (AWS Cloud9)

Use this procedure if you need a Unix environment with the required tools pre-installed.

1. Open [CloudShell](https://console.aws.amazon.com/cloudshell/home).
2. Clone the setup repository:
```bash
git clone https://github.com/aws-samples/cloud9-setup-for-prototyping
```
3. Move to the directory:
```bash
cd cloud9-setup-for-prototyping
```
4. Adjust volume size if needed:
```bash
cat <<< $(jq  '.volume_size = 20'  params.json )  > params.json
```
5. Run the setup script:
```bash
./bin/bootstrap
```
6. Open [Cloud9](https://console.aws.amazon.com/cloud9/home) and click "Open IDE".

> [!NOTE]
> The Cloud9 environment incurs EC2 charges based on usage. It auto-stops after 30 minutes of inactivity, but EBS volume charges continue. Delete the environment after deployment to minimize costs: [Deleting an environment in AWS Cloud9](https://docs.aws.amazon.com/cloud9/latest/user-guide/delete-environment.html).
```

**Step 3: DEPLOY.md への参照を README 内の新しいセクションへ張り替える**

変更箇所 1 (line 48付近):
```
- Old: Please refer to [Preparing the Operating Environment (AWS Cloud9)](DEPLOY.md).
- New: Please refer to [Setting Up the Environment (AWS Cloud9)](#appendix-setting-up-the-environment-aws-cloud9).
```

変更箇所 2 (line 88付近, "Changing the Language Setting" セクション):
```
- Old: For more information on other configuration options, please refer to the [Deployment Guide](DEPLOY.md). For more information on other configuration options, please refer to the [Deployment Guide](DEPLOY.md).
- New: For more information on configuration options, see [Configuration Reference](#configuration-reference).
```

**Step 4: 変更結果を確認する**

```bash
grep -n "DEPLOY" README.md
```
期待: 出力なし（DEPLOY.md への参照が残っていないこと）

```bash
grep -n "## Configuration Reference\|## Appendix\|## Change Log" README.md
```
期待: Configuration Reference と Appendix が存在し、Change Log は存在しないこと

**Step 5: コミットする**

```bash
git add README.md
git commit -m "docs: absorb DEPLOY.md content into README.md"
```

---

### Task 2: README_ja.md を更新する

**Files:**
- Modify: `README_ja.md`

**Step 1: 変更履歴セクションを削除する**

`## 変更履歴` から `## Third Party Services` の直前まで（"### 移行ノート" の3項目含む）を削除する。

**Step 2: "スタックの削除" セクションの直後に Configuration Reference セクションを挿入する**

`## スタックの削除` セクションの末尾（"手動で削除を行ってください。" の行）の直後に以下を挿入する:

```markdown

## 設定リファレンス

アプリケーションは `cdk.json` の `context` セクションで設定します。

### 共通設定

- `modelRegion`: Amazon Bedrock を利用するリージョンコード。
- `modelId`: Amazon Bedrock で利用する基盤モデルの model ID。各モデルの ID はドキュメントを参照してください。

### summarizers

生成 AI の要約プロンプトとペルソナを設定します。

- `outputLanguage`: モデル出力の言語。
- `persona`: モデルに与える役割 (ペルソナ)。

### notifiers

通知先および RSS ソースを設定します。

- `destination`: 投稿先のアプリケーション名。`slack` を設定してください。
- `summarizerName`: 配信に使用する summarizer の名前。
- `webhookUrlParameterName`: Webhook URL を格納している SSM Parameter Store のパラメータ名。
- `rssUrl`: 監視する RSS フィードの URL。複数指定可能。
- `schedule` (オプション): CRON 形式の RSS フィード取得間隔。未指定時は毎時 00 分に実行されます。

```json
"schedule": {
  "minute": "0/15",
  "hour": "*",
  "day": "*",
  "month": "*",
  "year": "*"
}
```

### 付録: 操作環境の準備 (AWS Cloud9)

必要なツールがインストールされた Unix 環境が必要な場合に使用します。

1. [CloudShell](https://console.aws.amazon.com/cloudshell/home) を開いてください。
2. 以下のコマンドでリポジトリをクローンしてください。
```bash
git clone https://github.com/aws-samples/cloud9-setup-for-prototyping
```
3. ディレクトリに移動してください。
```bash
cd cloud9-setup-for-prototyping
```
4. コスト最適化のため必要に応じてボリューム容量を変更します。
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
> 料金発生を最小限にしたい場合は、アセットのデプロイ後に [AWS Cloud9 で環境を削除する](https://docs.aws.amazon.com/cloud9/latest/user-guide/delete-environment.html) に従って環境の削除を行ってください。
```

**Step 3: DEPLOY_ja.md への参照を README_ja.md 内の新しいセクションへ張り替える**

変更箇所 1 (line 46付近):
```
- Old: [操作環境の準備 (AWS Cloud9)](DEPLOY_ja.md)
- New: [操作環境の準備 (AWS Cloud9)](#付録-操作環境の準備-aws-cloud9)
```

変更箇所 2 (line 96付近, "言語設定の変更" セクション):
```
- Old: その他の設定オプションについては[デプロイガイド](DEPLOY_ja.md)を参照してください。
- New: その他の設定オプションについては[設定リファレンス](#設定リファレンス)を参照してください。
```

**Step 4: 変更結果を確認する**

```bash
grep -n "DEPLOY" README_ja.md
```
期待: 出力なし

**Step 5: コミットする**

```bash
git add README_ja.md
git commit -m "docs: absorb DEPLOY_ja.md content into README_ja.md"
```

---

### Task 3: CLAUDE.md を更新する

**Files:**
- Modify: `CLAUDE.md`

**Step 1: エラーハンドリング戦略テーブルを追加する**

`## Gotchas` セクションの末尾（現在の最後の箇条書き）の直後に以下を追加する:

```markdown

## Error Handling Strategy

| Situation | Behavior |
|-----------|----------|
| DynamoDB duplicate write | `ClientError` is caught and logged; processing continues |
| Article scraping fails (`get_blog_content` returns None) | Falls back to RSS entry title as content for summarization |
| Bedrock `AccessDeniedException` | Logged with troubleshooting hint; exception re-raised |
| Missing XML tags in model output (`<summary>`, `<thinking>`, `<twitter>`) | `ValueError` raised with partial response text |
| General exception in notify handler | `traceback.print_exc()` logs full stack to CloudWatch |
```

**Step 2: エンドツーエンドのデータフローを追加する**

`## Error Handling Strategy` の直後に以下を追加する:

```markdown

## End-to-End Data Flow

```
EventBridge Cron
  → RSS Crawler Lambda
      feedparser fetches each RSS URL
      filters entries to last 7 days
      writes to DynamoDB (url + notifier_name as composite key, natural dedup via overwrite)
  → DynamoDB Stream (NEW_IMAGE, INSERT only)
  → Notify-to-App Lambda (concurrency=1)
      fetches Slack Webhook URL from SSM Parameter Store (WithDecryption=True)
      scrapes article body via cloudscraper + BeautifulSoup (<main> tag)
      falls back to title if scraping fails
      calls Strands Agent SDK → Bedrock (temperature=0.1, max_tokens=4096)
      parses <thinking>, <summary>, <twitter> tags from response via regex
      POSTs to Slack Webhook
      sleeps 0.5s (rate limit guard)
```
```

**Step 3: 設計上の注意点を追加する**

既存の `## Gotchas` セクション内の最後の項目の直後に以下を追加する（Error Handling より前）:

```markdown
- **`event.values()` unpacking**: `rss-crawler/index.py` handler uses `event["notifierName"]` and `event["notifier"]` — these keys come from `RuleTargetInput.fromObject({ notifierName, notifier })` in the CDK stack. If the event structure changes, update both sides.
- **Strands SDK concurrency**: The notification Lambda is limited to concurrency=1. This is intentional — do not increase without testing Slack and Bedrock rate limit behavior.
```

**Step 4: 変更結果を確認する**

```bash
wc -l CLAUDE.md
```
期待: 140行以下（Claude Code のコンテキストとして適切なサイズ）

**Step 5: コミットする**

```bash
git add CLAUDE.md
git commit -m "docs: add error handling strategy and data flow to CLAUDE.md from research.md"
```

---

### Task 4: 不要ファイルを削除する

**Files:**
- Delete: `DEPLOY.md`
- Delete: `DEPLOY_ja.md`
- Delete: `doc/improvement-plan.md`
- Delete: `doc/research.md`

**Step 1: DEPLOY.md と DEPLOY_ja.md を削除する**

```bash
git rm DEPLOY.md DEPLOY_ja.md
```

**Step 2: doc/ 内の不要ファイルを削除する**

```bash
git rm doc/improvement-plan.md doc/research.md
```

**Step 3: doc/ ディレクトリの残存物を確認する**

```bash
ls doc/
```
期待: `architecture.png`, `example_en.png`, `example_ja.png` のみ残っていること

**Step 4: プロジェクト内に DEPLOY.md への残存参照がないことを確認する**

```bash
grep -r "DEPLOY" --include="*.md" .
```
期待: `docs/plans/` 以下の古い計画ファイルのみ（`docs/plans/2026-02-25-switch-model-to-nova-pro.md`）に参照が残る。これは歴史的な計画ドキュメントなので修正不要。

**Step 5: コミットする**

```bash
git commit -m "docs: delete DEPLOY.md, DEPLOY_ja.md, improvement-plan.md, research.md"
```

---

### Task 5: 最終確認

**Step 1: Markdown のリンク切れを確認する**

```bash
grep -n "\[.*\](DEPLOY" README.md README_ja.md CLAUDE.md
```
期待: 出力なし

**Step 2: research.md への参照がないことを確認する**

```bash
grep -rn "research\.md\|improvement-plan" --include="*.md" . | grep -v "docs/plans/"
```
期待: 出力なし

**Step 3: ファイル一覧を確認する**

```bash
ls *.md doc/*.png
```
期待: `README.md`, `README_ja.md`, `CLAUDE.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md` と `doc/` の3画像ファイルのみ

**Step 4: 最終コミット（必要な場合のみ）**

Task 1〜4 でコミット済みのため、変更なければスキップ。
