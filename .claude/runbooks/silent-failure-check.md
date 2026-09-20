# 取りこぼしの定期検査

notify-to-app と rss-crawler は失敗をログに出して処理を続ける。記事が 1 本 Slack に届かなくても、DynamoDB には行が残り、リトライも起きず、Lambda の `Errors` メトリクスも増えない（#46）。この手順はその取りこぼしを拾うためのもの。

アラートは `#whats-new-alerts` に自動で届く。この検査はその補完で、アラート経路そのものが壊れていた場合に気づくためにある。月次のコスト集計と同じタイミングで実施する。

## 1. メトリクスを見る

過去 2 週間の件数を数える。両方 0 なら取りこぼしは無い。

```bash
for metric in NotifyNewEntrySwallowedExceptions NewsCrawlerWriteFailures; do
  echo "== ${metric}"
  aws cloudwatch get-metric-statistics --profile production \
    --namespace WhatsNewSummaryNotifier --metric-name "${metric}" \
    --start-time "$(date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%SZ)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --period 86400 --statistics Sum \
    --query 'sort_by(Datapoints,&Timestamp)[?Sum>`0`].[Timestamp,Sum]' --output text
done
```

CloudWatch Logs の保持期間は 2 週間なので、これより古い期間は調べられない。

## 2. 該当したログを読む

件数が 1 以上なら、その日時のログを引く。

```bash
aws logs filter-log-events --profile production \
  --log-group-name /aws/lambda/NotifyNewEntry \
  --start-time "$(date -u -d '14 days ago' +%s000)" \
  --filter-pattern '"NOTIFY_TO_APP_UNHANDLED_EXCEPTION"' \
  --query 'events[].[timestamp,logStreamName]' --output text
```

crawler 側は `--log-group-name /aws/lambda/newsCrawler --filter-pattern '"DynamoDB error writing"'`。

`logStreamName` が分かったら、その前後を読んで記事と例外を特定する。

```bash
aws logs get-log-events --profile production \
  --log-group-name /aws/lambda/NotifyNewEntry \
  --log-stream-name '<logStreamName>' \
  --query 'events[].message' --output text
```

`rss_title` と `rss_link` を含む行が対象の記事、`raise ValueError` 以降が原因。

## 3. 投稿されていないことを確かめる

同じ記事が別の機会に投稿されている可能性はある。URL のスラッグで確認する。

```bash
aws logs filter-log-events --profile production \
  --log-group-name /aws/lambda/NotifyNewEntry \
  --start-time "$(date -u -d '14 days ago' +%s000)" \
  --filter-pattern '"push_msg" "<URL のスラッグ>"' \
  --query 'length(events)' --output text
```

`0` なら失われている。

## 4. 手当て

再処理の仕組みは無い。必要なら DynamoDB の該当行を消してから次のクロールを待つ。削除すると次の `put_item` が `INSERT` になり、Stream 経由で再び処理される。ただし rss-crawler は公開から 7 日以内の記事しか拾わないため、それを過ぎていれば手動で投稿するしかない。

```bash
aws dynamodb delete-item --profile production \
  --table-name "$(aws cloudformation describe-stack-resource --profile production \
    --stack-name WhatsNewSummaryNotifierStack --logical-resource-id WhatsNewRSSHistory2BF2A5DD \
    --query 'StackResourceDetail.PhysicalResourceId' --output text)" \
  --key '{"url":{"S":"<記事 URL>"},"notifier_name":{"S":"F1WhatsNew"}}'
```

同じ原因が繰り返すなら #46 に記録して、リトライと DLQ の導入を検討する。

## 5. アラート経路そのものの確認

アラート用 Lambda が落ちても誰も通知しない。SSM の Webhook が失効していないかを、検査のたびに 1 度だけ疎通させて確かめる。

```bash
URL=$(aws ssm get-parameter --name /WhatsNew/AlertURL --with-decryption --profile production \
  --query Parameter.Value --output text)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"text":"定期検査: アラート経路の疎通確認"}' "$URL"
```

`ok` が返り、`#whats-new-alerts` にメッセージが届けば正常。

## 関連

- Issue #46 — 取りこぼしの経路と、リトライを入れない判断の理由
- `lambda/notify-to-app/index.py` の `UNHANDLED_EXCEPTION_MARKER` — メトリクスフィルターが数えている文字列。変更するときは `lib/whats-new-summary-notifier-stack.ts` のフィルターも同時に直す
