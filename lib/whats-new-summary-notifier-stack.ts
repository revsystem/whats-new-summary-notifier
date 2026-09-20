import { Construct } from 'constructs';
import { Stack, StackProps, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Table, AttributeType, BillingMode, StreamViewType } from 'aws-cdk-lib/aws-dynamodb';
import { Rule, Schedule, RuleTargetInput, CronOptions } from 'aws-cdk-lib/aws-events';
import { LambdaFunction } from 'aws-cdk-lib/aws-events-targets';
import { Role, Policy, ServicePrincipal, PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { Runtime, StartingPosition } from 'aws-cdk-lib/aws-lambda';
import { DynamoEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';
import type { BundlingOptions } from '@aws-cdk/aws-lambda-python-alpha/lib/types';
import { FilterPattern, LogGroup, MetricFilter, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Alarm, ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import { LambdaAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
import { NagSuppressions } from 'cdk-nag';
import * as path from 'path';

/** Keep local `.venv` out of the bundling rsync step; otherwise pip -t duplicates deps (~590MB unzipped). */
const pythonLambdaBundling: BundlingOptions = {
  assetExcludes: ['.venv', 'venv', '.pytest_cache', '__pycache__'],
};

export class WhatsNewSummaryNotifierStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const region = Stack.of(this).region;
    const accountId = Stack.of(this).account;

    const modelRegion = this.node.tryGetContext('modelRegion');
    const modelId = this.node.tryGetContext('modelId');
    // Cross-region inference profile IDs (e.g. "us.amazon.nova-pro-v1:0") have a regional
    // prefix. Strip it to obtain the underlying foundation model ID for IAM policy ARNs.
    const baseModelId = modelId.replace(/^(us|eu|ap)\./, '');

    // "converse" calls bedrock-runtime; "responses" calls the bedrock-mantle
    // endpoint, which some models (e.g. GPT-5.6 Terra) require exclusively.
    const modelApiMode = this.node.tryGetContext('modelApiMode') ?? 'converse';
    if (modelApiMode !== 'converse' && modelApiMode !== 'responses') {
      throw new Error(`modelApiMode must be "converse" or "responses", got: ${modelApiMode}`);
    }
    const usesResponsesApi = modelApiMode === 'responses';

    const notifiers: [] = this.node.tryGetContext('notifiers');
    const summarizers: [] = this.node.tryGetContext('summarizers');

    // Role for Lambda Function to post new entries written to DynamoDB to Slack
    const notifyNewEntryRole = new Role(this, 'NotifyNewEntryRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
    });
    notifyNewEntryRole.attachInlinePolicy(
      new Policy(this, 'AllowNotifyNewEntryLogging', {
        statements: [
          new PolicyStatement({
            actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
            effect: Effect.ALLOW,
            resources: [`arn:aws:logs:${region}:${accountId}:log-group:*`],
          }),
          new PolicyStatement({
            actions: ['bedrock:InvokeModel'],
            effect: Effect.ALLOW,
            resources: [
              // Allow cross-region access to the underlying foundation model.
              // The region is "*" because cross-region inference may route to any region.
              `arn:aws:bedrock:*::foundation-model/${baseModelId}`,
              `arn:aws:bedrock:${modelRegion}:${accountId}:inference-profile/*`,
            ],
          }),
          // The bedrock-mantle path mints a short-lived bearer token from the
          // execution role's credentials, then creates an inference against the
          // project. Both actions are required; CallWithBearerToken alone fails.
          // Resource scoping follows the AWS managed policy
          // AmazonBedrockMantleInferenceAccess: CallWithBearerToken is not
          // resource-scopable and must use "*", CreateInference targets projects.
          ...(usesResponsesApi
            ? [
                new PolicyStatement({
                  actions: ['bedrock-mantle:CallWithBearerToken'],
                  effect: Effect.ALLOW,
                  resources: ['*'],
                }),
                new PolicyStatement({
                  actions: ['bedrock-mantle:CreateInference'],
                  effect: Effect.ALLOW,
                  resources: [`arn:aws:bedrock-mantle:${modelRegion}:${accountId}:project/*`],
                }),
              ]
            : []),
        ],
      })
    );

    // Role for Lambda function to fetch RSS and write to DynamoDB
    const newsCrawlerRole = new Role(this, 'NewsCrawlerRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
    });
    newsCrawlerRole.attachInlinePolicy(
      new Policy(this, 'AllowNewsCrawlerLogging', {
        statements: [
          new PolicyStatement({
            actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
            effect: Effect.ALLOW,
            resources: [`arn:aws:logs:${region}:${accountId}:log-group:*`],
          }),
        ],
      })
    );

    // DynamoDB to store RSS data
    const rssHistoryTable = new Table(this, 'WhatsNewRSSHistory', {
      partitionKey: { name: 'url', type: AttributeType.STRING },
      sortKey: { name: 'notifier_name', type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      stream: StreamViewType.NEW_IMAGE,
    });

    // Lambda Function to post new entries written to DynamoDB to Slack
    const notifyNewEntryLogGroup = new LogGroup(this, 'NotifyNewEntryLogGroup', {
      logGroupName: '/aws/lambda/NotifyNewEntry',
      retention: RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const notifyNewEntry = new PythonFunction(this, 'NotifyNewEntry', {
      runtime: Runtime.PYTHON_3_12,
      entry: path.join(__dirname, '../lambda/notify-to-app'),
      bundling: pythonLambdaBundling,
      handler: 'handler',
      index: 'index.py',
      // Reasoning models on the Responses path spend far longer per article;
      // 180s was observed to time out, 600s leaves headroom.
      timeout: Duration.seconds(usesResponsesApi ? 600 : 180),
      // Default 128MB was permanently pegged at its ceiling (127-128MB used
      // on every successful invocation) and caused a Runtime.OutOfMemory
      // error in production; 512MB gives headroom for web scraping plus the
      // boto3/strands/openai SDKs.
      memorySize: 512,
      logGroup: notifyNewEntryLogGroup,
      role: notifyNewEntryRole,
      reservedConcurrentExecutions: 1,
      environment: {
        MODEL_ID: modelId,
        MODEL_REGION: modelRegion,
        MODEL_API_MODE: modelApiMode,
        NOTIFIERS: JSON.stringify(notifiers),
        SUMMARIZERS: JSON.stringify(summarizers),
      },
    });

    notifyNewEntry.addEventSource(
      new DynamoEventSource(rssHistoryTable, {
        startingPosition: StartingPosition.LATEST,
        batchSize: 1,
      })
    );

    // Allow writing to DynamoDB
    rssHistoryTable.grantWriteData(newsCrawlerRole);

    // Lambda Function to fetch RSS and write to DynamoDB
    const newsCrawlerLogGroup = new LogGroup(this, 'NewsCrawlerLogGroup', {
      logGroupName: '/aws/lambda/newsCrawler',
      retention: RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const newsCrawler = new PythonFunction(this, `newsCrawler`, {
      runtime: Runtime.PYTHON_3_12,
      entry: path.join(__dirname, '../lambda/rss-crawler'),
      bundling: pythonLambdaBundling,
      handler: 'handler',
      index: 'index.py',
      timeout: Duration.seconds(60),
      logGroup: newsCrawlerLogGroup,
      role: newsCrawlerRole,
      environment: {
        DDB_TABLE_NAME: rssHistoryTable.tableName,
        NOTIFIERS: JSON.stringify(notifiers),
      },
    });

    for (const notifierName in notifiers) {
      const notifier = notifiers[notifierName];
      // const cron is a cronOption defined in a notifier. if it is not defined, set default schedule (every hour)
      const schedule: CronOptions = notifier['schedule'] || {
        minute: '0',
        hour: '*',
        day: '*',
        month: '*',
        year: '*',
      };
      const webhookUrlParameterName = notifier['webhookUrlParameterName'];
      const webhookUrlParameterStore = StringParameter.fromSecureStringParameterAttributes(
        this,
        `webhookUrlParameterStore-${notifierName}`,
        {
          parameterName: webhookUrlParameterName,
        }
      );

      // add permission to Lambda Role
      webhookUrlParameterStore.grantRead(notifyNewEntryRole);

      // Scheduled Rule for RSS Crawler
      // Run every hour, 24 hours a day
      // see https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html#CronExpressions
      const rule = new Rule(this, `CheckUpdate-${notifierName}`, {
        schedule: Schedule.cron(schedule),
        enabled: true,
      });

      rule.addTarget(
        new LambdaFunction(newsCrawler, {
          event: RuleTargetInput.fromObject({ notifierName, notifier }),
          retryAttempts: 2,
        })
      );
    }

    // Both functions log their failures and carry on, so an article can go
    // missing without anything else showing it. These alarms are what makes
    // that visible; see .claude/docs/runbooks/silent-failure-check.md.
    const alertWebhookUrlParameterName = this.node.tryGetContext('alertWebhookUrlParameterName');
    if (!alertWebhookUrlParameterName) {
      throw new Error('Context value "alertWebhookUrlParameterName" is required for the alarm notifier');
    }

    const alarmToSlackLogGroup = new LogGroup(this, 'AlarmToSlackLogGroup', {
      logGroupName: '/aws/lambda/AlarmToSlack',
      retention: RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const alarmToSlackRole = new Role(this, 'AlarmToSlackRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
    });
    const alarmToSlackPolicy = new Policy(this, 'AlarmToSlackPolicy', {
      statements: [
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
          resources: [alarmToSlackLogGroup.logGroupArn, `${alarmToSlackLogGroup.logGroupArn}:*`],
        }),
      ],
    });
    alarmToSlackRole.attachInlinePolicy(alarmToSlackPolicy);

    const alarmToSlack = new PythonFunction(this, 'AlarmToSlack', {
      runtime: Runtime.PYTHON_3_12,
      entry: path.join(__dirname, '../lambda/alarm-to-slack'),
      bundling: pythonLambdaBundling,
      handler: 'handler',
      index: 'index.py',
      timeout: Duration.seconds(30),
      role: alarmToSlackRole,
      logGroup: alarmToSlackLogGroup,
      environment: {
        WEBHOOK_URL_PARAMETER_NAME: alertWebhookUrlParameterName,
        LOG_GROUP_NAMES: JSON.stringify([
          notifyNewEntryLogGroup.logGroupName,
          newsCrawlerLogGroup.logGroupName,
        ]),
      },
    });

    StringParameter.fromSecureStringParameterAttributes(this, 'alertWebhookUrlParameterStore', {
      parameterName: alertWebhookUrlParameterName,
    }).grantRead(alarmToSlackRole);

    NagSuppressions.addResourceSuppressions(
      alarmToSlackPolicy,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason:
            'Log streams are created per invocation, so their names cannot be enumerated ahead of time. The wildcard stays inside this function own log group.',
        },
      ],
      true
    );
    NagSuppressions.addResourceSuppressions(alarmToSlack, [
      {
        id: 'AwsSolutions-L1',
        reason:
          'Python 3.12 matches the other two functions in this stack and the runtime this repository documents. Moving one function ahead of the rest would fragment the deployment.',
      },
    ]);

    // Two alarms share this function, and without a unique id the second
    // one collides on the Lambda permission construct.
    const alarmAction = new LambdaAction(alarmToSlack, { useUniquePermissionId: true });

    // The marker notify-to-app prints before swallowing an exception. Matching
    // on "Traceback" instead would also count stack traces our dependencies log.
    const swallowedExceptions = new MetricFilter(this, 'NotifyNewEntrySwallowedExceptionFilter', {
      logGroup: notifyNewEntryLogGroup,
      filterPattern: FilterPattern.literal('"NOTIFY_TO_APP_UNHANDLED_EXCEPTION"'),
      metricNamespace: 'WhatsNewSummaryNotifier',
      metricName: 'NotifyNewEntrySwallowedExceptions',
      metricValue: '1',
      defaultValue: 0,
    });

    // rss-crawler logs and moves on when a write fails, and the entry then
    // never reaches the stream at all.
    const crawlerWriteFailures = new MetricFilter(this, 'NewsCrawlerWriteFailureFilter', {
      logGroup: newsCrawlerLogGroup,
      filterPattern: FilterPattern.literal('"DynamoDB error writing"'),
      metricNamespace: 'WhatsNewSummaryNotifier',
      metricName: 'NewsCrawlerWriteFailures',
      metricValue: '1',
      defaultValue: 0,
    });

    for (const [id, metricFilter] of [
      ['NotifyNewEntrySwallowedExceptionAlarm', swallowedExceptions],
      ['NewsCrawlerWriteFailureAlarm', crawlerWriteFailures],
    ] as const) {
      // defaultValue 0 keeps the alarm returning to OK between failures, so the
      // next one is a state change and fires the action again.
      const alarm = new Alarm(this, id, {
        metric: metricFilter.metric({ statistic: 'Sum', period: Duration.minutes(5) }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });
      alarm.addAlarmAction(alarmAction);
    }
  }
}
