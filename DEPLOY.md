# Deployment Guide

## Deployment Steps

> [!IMPORTANT]
> This repository is configured to use the Amazon Nova Pro model (cross-region inference profile) in the US West (Oregon) region (us-west-2) by default. Please open the [Model access screen (us-west-2)](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2#/modelaccess), check the Amazon Nova Pro option, and click Save changes.

### Create Webhook URL

Create the Webhook URL required for the notifications.

#### For Slack

Refer to [this documentation](https://slack.com/help/articles/17542172840595-Build-a-workflow--Create-a-workflow-in-Slack) to create the Webhook URL. Select "Add a Variable" and create the following 5 variables, all with the Text data type:

- `rss_time`: The time the article was posted
- `rss_link`: The URL of the article
- `rss_title`: The title of the article
- `summary`: A summary of the article
- `detail`: A bulleted description of the article

### Create AWS Systems Manager Parameter Store

Use Parameter Store to securely store the notification URL.

#### Put into Parameter Store (AWS CLI)

```
aws ssm put-parameter \
  --name "/WhatsNew/URL" \
  --type "SecureString" \
  --value "<Input your Webhook URL >"
```

### Changing the Language Setting (Optional)

This asset is set up to output summaries in Japanese (日本語) by default. If you want to generate output in other languages such as English, open the `cdk.json` file and change the `summarizerName` value inside the `notifiers` object within the `context` section from `AwsSolutionsArchitectJapanese` to `AwsSolutionsArchitectEnglish` or another language. For more information on other configuration options, see [Configuration Options](#configuration-options).

### Execute the deployment

**Deploy region**

The deploy target region is read from `CDK_DEFAULT_REGION`. Copy `.env.example` to `.env` and set the region (e.g. `CDK_DEFAULT_REGION=us-east-1`). If unset, the stack defaults to `us-east-1`.

If your AWS profile's default region differs from the deploy target, the CDK CLI will use the profile region for bootstrap lookups and fail. In that case, also set `AWS_DEFAULT_REGION` explicitly (see deploy command below).

**Initialize**

If you haven't used CDK in this region before, run the following command:

```bash
cdk bootstrap
```

If you are using a specific AWS profile, add the `--profile` option:

```bash
AWS_DEFAULT_REGION=us-east-1 cdk bootstrap --profile your-profile-name
```

**Verify no errors**

```bash
cdk synth
```

**Execute Deployment**

```bash
cdk deploy
```

If your AWS profile region differs from the deploy target, specify both variables:

```bash
AWS_DEFAULT_REGION=us-east-1 cdk deploy --profile your-profile-name
```

## Delete Stack

If no longer needed, run the following command to delete the stack:

```bash
cdk destroy
```

If you are using a specific AWS profile, add the `--profile` option:

```bash
cdk destroy --profile your-profile-name
```

By default, some resources such as the Amazon DynamoDB table are set to not be deleted.
If you need to completely delete everything, you will need to access the remaining resources and manually delete them.

## Troubleshooting

### Dependency Conflicts

If you encounter dependency conflicts during deployment, the system automatically resolves compatible versions. The requirements.txt files are configured to allow automatic dependency resolution.

### Docker Build Issues

- Ensure Docker is running before executing CDK commands
- The build process uses AWS SAM build images which are automatically downloaded
- If builds fail, try running `cdk synth` first to verify the configuration

### Common Issues

1. **Model Access**: Ensure you have enabled the required Bedrock models in your AWS region
2. **Profile Configuration**: Always use the `--profile` option if you're using named AWS profiles
3. **Region Consistency**: Ensure all resources are deployed in the same AWS region

# Configuration Options

This asset uses the AWS CDK context to configure the settings.

You can change the settings by modifying the values under the `context` section in the [cdk.json](cdk.json) file. The details of each configuration item are as follows:

## Common Settings
* `modelRegion`: The region to use Amazon Bedrock. Enter the region code of the region you want to use from among the regions where Amazon Bedrock is available.
* `modelId`: The model ID of the base model to be used with Amazon Bedrock. Refer to the documentation for the model ID of each model.
* `modelApiMode`: How the model is invoked. Set `converse` for models served by the Converse API on the `bedrock-runtime` endpoint, or `responses` for models served only by the Responses API on the `bedrock-mantle` endpoint. Defaults to `converse` when omitted. `modelId` and `modelApiMode` must agree, otherwise the Lambda function raises an error on startup.

### Switching the model

`modelId` and `modelApiMode` are always changed together, because a model is reachable through only one of the two APIs.

| Model | `modelId` | `modelApiMode` |
| --- | --- | --- |
| Amazon Nova Pro | `us.amazon.nova-pro-v1:0` | `converse` |
| OpenAI GPT-5.6 Terra | `openai.gpt-5.6-terra` | `responses` |

1. Edit both values in the `context` section of [cdk.json](cdk.json).
2. Deploy with `cdk deploy`. The CDK app rejects an unknown `modelApiMode` at synth time, and the Lambda function rejects a mismatched pair at startup, so a half-finished edit fails fast rather than reaching production.
3. Check CloudWatch Logs for the first few invocations of `NotifyNewEntry`.

Notes when moving to a `responses` model:

* The stack grants `bedrock-mantle:CallWithBearerToken` and `bedrock-mantle:CreateInference` only in `responses` mode. Both are required; granting only the former returns `AccessDeniedException`.
* The Lambda timeout is raised from 180 to 600 seconds in `responses` mode, because reasoning models spend considerably longer per article.
* Reasoning models such as GPT-5.6 Terra reject `temperature` and `top_p`. Sending either returns HTTP 400 `unsupported_parameter`, so only `max_output_tokens` and the reasoning effort are passed on that path.

To roll back, restore the previous `modelId` and `modelApiMode` pair and run `cdk deploy` again. No code change is needed, because both call paths remain in the function.

## summarizers
Configure the prompt for summarizing the input to the generative AI.

* `outputLanguage`: The language of the model output.
* `persona`: The role (persona) to be given to the model.

## notifiers
Configure the delivery settings to the application.

* `destination`: The name of application to post to. Set `slack` according to the destination.
* `summarizerName`: The name of the summarizer to use for delivery.
* `webhookUrlParameterName`: The name of the AWS Systems Manager Parameter Store parameter that stores the Webhook URL.
* `rssUrl`: The RSS feed URL of the website from which you want to get the latest information. Multiple URLs can be specified.
* `schedule` (optional): The interval for retrieving the RSS feed in CRON format. If this parameter is not specified, the feed will be retrieved at 00 minutes every hour. In the example below, the feed will be retrieved every 15 minutes.

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

# Preparing the Deployment Environment (AWS Cloud9)
This procedure creates a development environment on AWS with the necessary tools installed.
The environment is built using AWS Cloud9.
For more details on AWS Cloud9, please refer to [What is AWS Cloud9?](https://docs.aws.amazon.com/cloud9/latest/user-guide/welcome.html).

1. Open [CloudShell](https://console.aws.amazon.com/cloudshell/home).
2. Clone this repository.
```bash
git clone https://github.com/aws-samples/cloud9-setup-for-prototyping
```
3. Move to the directory
```bash
cd cloud9-setup-for-prototyping
```
4. Change volume capacities as needed for cost optimization.
```bash
cat <<< $(jq  '.volume_size = 20'  params.json )  > params.json
```
5. Run the script.
```bash
./bin/bootstrap
```
6. Move to [Cloud9](https://console.aws.amazon.com/cloud9/home), and click "Open IDE ".

> [!NOTE]
> The AWS Cloud9 environment created in this procedure will incur pay-per-use EC2 charges based on usage time.
> It is set to automatically stop after 30 minutes of inactivity, but the charges for the instance volume (Amazon EBS) will continue to accrue.
> If you want to minimize charges, please delete the environment after deployment of the asset, following the instructions in [Deleting an environment in AWS Cloud9](https://docs.aws.amazon.com/cloud9/latest/user-guide/delete-environment.html).
