# Switch Model to Amazon Nova Pro Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bedrock モデルを `openai.gpt-oss-120b-1:0` から `amazon.nova-pro-v1:0` に切り替え、Nova Pro で動作するよう API パラメーターを修正する。

**Architecture:** `cdk.json` でモデル ID を変更し、Lambda 関数内の `BedrockModel` 初期化から Nova Pro 非対応のパラメーター（`reasoning_effort`、`max_completion_tokens`）を除去・修正する。IAM ポリシーはすでに `foundation-model/*` と `inference-profile/*` の両方を許可しているため変更不要。

**Tech Stack:** Python 3.12 (Lambda)、Strands Agents SDK (`strands-agents>=1.25.0`)、AWS CDK v2 (TypeScript)

---

## 変更箇所の全体像

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `cdk.json` | 機能変更 | `modelId` 値を Nova Pro に変更 |
| `lambda/notify-to-app/index.py` | 機能変更 | `reasoning_effort` 削除、`max_completion_tokens` → `max_tokens` |
| `CLAUDE.md` | ドキュメント | モデル ID 記述更新 |
| `DEPLOY.md` | ドキュメント | モデル対応範囲の記述更新 |
| `DEPLOY_ja.md` | ドキュメント | モデル対応範囲の記述更新 |

---

### Task 1: Lambda BedrockModel パラメーターを Nova Pro 対応に修正

Nova Pro は OpenAI 系モデル固有の `reasoning_effort` パラメーターをサポートしない。
また `max_completion_tokens` は OpenAI API の命名で、Bedrock Converse API の正しいパラメーター名は `max_tokens` である。

**Files:**
- Modify: `lambda/notify-to-app/index.py:223-237`

**Step 1: 現在の `BedrockModel` 初期化を確認する**

```bash
grep -n "BedrockModel\|reasoning_effort\|max_completion_tokens\|max_tokens" lambda/notify-to-app/index.py
```

Expected output (抜粋):
```
225:    model = BedrockModel(
226:        params={
227:            "temperature": 0.1,
228:            "top_p": 0.1,
229:            "max_completion_tokens": max_tokens
230:        },
231:        additional_request_fields={
232:            "reasoning_effort": "medium"
233:        },
234:        model_id=MODEL_ID,
235:        region_name=MODEL_REGION,
236:        streaming=False,
237:    )
```

**Step 2: `BedrockModel` 初期化を Nova Pro 対応に書き換える**

`lambda/notify-to-app/index.py` の `BedrockModel(...)` ブロックを以下に書き換える:

```python
    model = BedrockModel(
        params={
            "temperature": 0.1,
            "top_p": 0.1,
            "max_tokens": max_tokens
        },
        model_id=MODEL_ID,
        region_name=MODEL_REGION,
        streaming=False,
    )
```

変更点:
- `additional_request_fields={"reasoning_effort": "medium"}` を削除（Nova Pro 非対応）
- `max_completion_tokens` → `max_tokens`（Bedrock Converse API の正式パラメーター名）

**Step 3: 変更後のコードが正しく書かれているか確認する**

```bash
grep -n "BedrockModel\|reasoning_effort\|max_completion_tokens\|max_tokens" lambda/notify-to-app/index.py
```

Expected output:
```
225:    model = BedrockModel(
229:            "max_tokens": max_tokens
230:        },
231:        model_id=MODEL_ID,
```

`reasoning_effort` と `max_completion_tokens` が出力に含まれないこと。

**Step 4: ruff でリントを実行する**

```bash
ruff check lambda/notify-to-app/index.py
```

Expected: エラーなし（出力なし）

**Step 5: コミット**

```bash
git add lambda/notify-to-app/index.py
git commit -m "fix(lambda): replace OpenAI-specific params with Nova Pro compatible ones

Remove reasoning_effort (OpenAI-only) and rename max_completion_tokens
to max_tokens (Bedrock Converse API standard) in BedrockModel init."
```

---

### Task 2: `cdk.json` のモデル ID を Nova Pro に変更する

**Files:**
- Modify: `cdk.json:22`

**Step 1: 現在の値を確認する**

```bash
grep -n "modelId" cdk.json
```

Expected:
```
22:        "modelId": "openai.gpt-oss-120b-1:0",
```

**Step 2: モデル ID を書き換える**

`cdk.json` の 22 行目を変更:

```json
        "modelId": "amazon.nova-pro-v1:0",
```

**Step 3: `cdk synth` を実行してスタック合成が成功するか確認する**

```bash
npm run build && npx cdk synth --no-staging 2>&1 | head -20
```

Expected: エラーなし、CloudFormation テンプレートの冒頭数行が出力される。

IAM ポリシーのリソース ARN が新しいモデル ID を反映していることも確認:

```bash
npx cdk synth --no-staging 2>&1 | grep "nova-pro"
```

Expected:
```
arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-pro-v1:0
```

**Step 4: コミット**

```bash
git add cdk.json
git commit -m "chore(config): change model to amazon.nova-pro-v1:0"
```

---

### Task 3: ドキュメントを更新する

**Files:**
- Modify: `CLAUDE.md:57`
- Modify: `DEPLOY.md:8`
- Modify: `DEPLOY_ja.md:8`

**Step 1: `CLAUDE.md` のモデル ID 記述を更新する**

対象行:
```
- **modelId**: Bedrock model ID (currently openai.gpt-oss-120b-1:0)
```

変更後:
```
- **modelId**: Bedrock model ID (currently amazon.nova-pro-v1:0)
```

**Step 2: `DEPLOY.md` のモデル対応説明を更新する**

対象行:
```
* `modelId`: The model ID of the base model to be used with Amazon Bedrock. It supports Anthropic Claude 3 and earlier versions. Refer to the documentation for the model ID of each model.
```

変更後:
```
* `modelId`: The model ID of the base model to be used with Amazon Bedrock. Refer to the documentation for the model ID of each model.
```

（"It supports Anthropic Claude 3 and earlier versions." は現状では不正確なため削除する）

**Step 3: `DEPLOY_ja.md` の対応説明を更新する**

対象行:
```
* `modelId`: Amazon Bedrock で利用する基盤モデルの model ID。Anthropic Claude 3 およびそれ以前のバージョンに対応をしています。各モデルの model ID はドキュメントを参照ください。
```

変更後:
```
* `modelId`: Amazon Bedrock で利用する基盤モデルの model ID。各モデルの model ID はドキュメントを参照ください。
```

**Step 4: コミット**

```bash
git add CLAUDE.md DEPLOY.md DEPLOY_ja.md
git commit -m "docs: update model ID references to amazon.nova-pro-v1:0"
```

---

## 変更しない箇所（理由付き）

- `lib/whats-new-summary-notifier-stack.ts` — IAM ポリシーは `foundation-model/${modelId}` のテンプレートと `inference-profile/*` ワイルドカードを使用しており、Nova Pro にも適用可能。変更不要。
- プロンプト内の `<thinking></thinking>` タグ — これはモデルへの出力フォーマット指示であり、モデル固有の拡張思考機能とは別物。Nova Pro もテキストで XML タグを出力できるため変更不要。
- `lambda/notify-to-app/requirements.txt` — `strands-agents>=1.25.0` は Nova Pro を含む Bedrock モデルを標準でサポート。変更不要。
