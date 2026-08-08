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
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
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
  }
}
