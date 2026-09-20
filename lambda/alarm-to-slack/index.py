# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Post a CloudWatch alarm to Slack.

Invoked directly by the alarms defined in the CDK stack. The failures these
alarms watch are silent otherwise: notify-to-app swallows its exceptions, so a
dropped article leaves nothing behind but a log line (#46).
"""

import json
import os
import urllib.parse
import urllib.request

import boto3

WEBHOOK_URL_PARAMETER_NAME = os.environ["WEBHOOK_URL_PARAMETER_NAME"]
LOG_GROUP_NAMES = json.loads(os.environ["LOG_GROUP_NAMES"])

ssm = boto3.client("ssm")

# CloudWatch sends the alarm as a JSON string in Records[].Sns.Message for SNS,
# but as the event body itself for a direct Lambda action.
STATE_EMOJI = {"ALARM": ":rotating_light:", "OK": ":white_check_mark:"}


def build_message(alarm):
    """Turn an alarm payload into Slack text with a link to the matching logs."""

    name = alarm.get("alarmName", "unknown alarm")
    state = alarm.get("state", {})
    value = state.get("value", "UNKNOWN")
    reason = state.get("reason", "")
    changed_at = state.get("timestamp", "")

    lines = [
        f"{STATE_EMOJI.get(value, ':grey_question:')} *{name}* — {value}",
        changed_at,
        reason,
    ]
    for log_group in LOG_GROUP_NAMES:
        lines.append(f"<{console_url(log_group)}|{log_group} を開く>")
    return "\n".join(line for line in lines if line)


def console_url(log_group):
    """Link to the log group. Retention is two weeks, so look within that.

    The console escapes the fragment twice: "/" becomes "%2F", and the "%" is
    then written as "$25". A singly encoded name lands on an empty page.
    """

    region = os.environ["AWS_REGION"]
    escaped = urllib.parse.quote(log_group, safe="").replace("%", "$25")
    return (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:log-groups/log-group/{escaped}"
    )


def handler(event, context):
    """Post the alarm to Slack.

    Exceptions propagate on purpose. Nothing else watches this function, so a
    failure has to reach the Lambda Errors metric to be visible at all.
    """

    print(json.dumps(event))
    webhook_url = ssm.get_parameter(
        Name=WEBHOOK_URL_PARAMETER_NAME, WithDecryption=True
    )["Parameter"]["Value"]

    payload = json.dumps({"text": build_message(event.get("alarmData", event))})
    request = urllib.request.Request(
        webhook_url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Without a timeout a hung webhook would hold the function until its own
    # 30 second limit, and the alarm's async retry would start over from there.
    with urllib.request.urlopen(request, timeout=10) as response:
        print(f"Slack responded {response.status}")
