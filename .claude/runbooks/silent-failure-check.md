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

再処理の仕組みは無い。DynamoDB の該当行を消すと次の `put_item` が `INSERT` になり、Stream 経由で再び処理される。

`notifier_name` はステップ 2 のログで確認する。Stream イベントの `Keys` に入っており、AWS 記事なら `AwsWhatsNew`、F1 記事なら `F1WhatsNew`。

```bash
aws dynamodb delete-item --profile production \
  --table-name "$(aws cloudformation describe-stack-resource --profile production \
    --stack-name WhatsNewSummaryNotifierStack --logical-resource-id WhatsNewRSSHistory2BF2A5DD \
    --query 'StackResourceDetail.PhysicalResourceId' --output text)" \
  --key '{"url":{"S":"<記事 URL>"},"notifier_name":{"S":"<notifier_name>"}}'
```

削除しても再処理されるとは限らない。rss-crawler は次の 2 つをどちらも満たすものしか書き込まない。RSS フィードがその記事をまだ配信していること、そして公開からの経過が 7 日を超えていないこと（`recently_published()` の判定は `elapsed_time.days > 7` なので、7 日 23 時間台までは通る）。フィードから落ちていれば削除しても何も起きないので、その場合は手動で投稿する。

同じ原因が繰り返すなら #46 に記録して、リトライと DLQ の導入を検討する。

## 5. アラート経路そのものの確認

アラート用 Lambda が落ちても誰も通知しない。検査のたびにアラームを 1 度発火させて、経路全体を通す。

アクションは ALARM への遷移でしか発火しない。すでに ALARM なら一度 OK に戻してから上げる。

```bash
ALARM_NAME=$(aws cloudwatch describe-alarms --profile production \
  --alarm-name-prefix WhatsNewSummaryNotifierStack \
  --query 'MetricAlarms[?contains(AlarmName,`NotifyNewEntrySwallowedException`)].AlarmName' \
  --output text)
aws cloudwatch set-alarm-state --profile production --alarm-name "$ALARM_NAME" \
  --state-value OK --state-reason '定期検査: 事前リセット'
aws cloudwatch set-alarm-state --profile production --alarm-name "$ALARM_NAME" \
  --state-value ALARM --state-reason '定期検査: 通知経路の確認'
```

`#whats-new-alerts` に投稿が届けば、アラーム、Lambda の権限、Parameter Store の Webhook、Slack への到達までがすべて生きている。届かない場合は Lambda 側のログを見る。

```bash
aws logs filter-log-events --profile production \
  --log-group-name /aws/lambda/AlarmToSlack \
  --start-time "$(($(date +%s) - 600))000" \
  --query 'events[].message' --output text
```

## 6. フィルターが生きていることの確認

ステップ 1 が 0 件なのは「失敗していない」か「フィルターが壊れている」かのどちらか。マーカー文字列は `lambda/notify-to-app/index.py` と `lib/whats-new-summary-notifier-stack.ts` の 2 箇所にあり、片方だけ変えると検出が静かに止まる。四半期に一度、意図的にマーカーを出して 1 が記録されることを確かめる。

```bash
aws logs put-log-events --profile production \
  --log-group-name /aws/lambda/NotifyNewEntry \
  --log-stream-name "runbook-check-$(date +%Y%m%d)" \
  --log-events "timestamp=$(date +%s)000,message=NOTIFY_TO_APP_UNHANDLED_EXCEPTION"
```

ログストリームが無ければ `aws logs create-log-stream` で先に作る。5 分ほど待ってステップ 1 のコマンドを実行し、1 が記録されていれば正常。この操作はアラームも発火させるので、ステップ 5 と兼ねてよい。

## 対象外

Lambda のタイムアウトと OOM は `AWS/Lambda` の `Errors` に出るため、この経路では通知されない。握りつぶしとは別のクラス（Stream のチェックポイントが進まずシャードが滞留する）なので、意図的に分けてある。必要ならコンソールか `Errors` メトリクスで別途確認する。

## 関連

- Issue #46 — 取りこぼしの経路と、リトライを入れない判断の理由
- `lambda/notify-to-app/index.py` の `UNHANDLED_EXCEPTION_MARKER` — メトリクスフィルターが数えている文字列。変更するときは `lib/whats-new-summary-notifier-stack.ts` のフィルターも同時に直す
