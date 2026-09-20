# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("WEBHOOK_URL_PARAMETER_NAME", "/Test/AlertURL")
os.environ.setdefault("LOG_GROUP_NAMES", json.dumps(["/aws/lambda/NotifyNewEntry"]))

import index

ALARM = {
    "alarmData": {
        "alarmName": "NotifyNewEntrySwallowedExceptionAlarm",
        "state": {
            "value": "ALARM",
            "reason": "Threshold Crossed: 1 datapoint [1.0] was greater than 1.0.",
            "timestamp": "2026-09-20T01:00:00.000+0000",
        },
    }
}


class TestBuildMessage:
    def test_includes_the_alarm_state_and_a_log_group_link(self):
        text = index.build_message(ALARM["alarmData"])
        assert "NotifyNewEntrySwallowedExceptionAlarm" in text
        assert "ALARM" in text
        assert "Threshold Crossed" in text
        # The console fragment is doubly encoded; a single %2F opens nothing.
        assert "$252Faws$252Flambda$252FNotifyNewEntry" in text
        assert "%2Faws" not in text

    def test_recovery_reads_differently_from_a_failure(self):
        ok = dict(
            ALARM["alarmData"], state={"value": "OK", "reason": "", "timestamp": ""}
        )
        assert index.build_message(ok) != index.build_message(ALARM["alarmData"])

    def test_missing_fields_do_not_raise(self):
        assert index.build_message({})


class TestHandler:
    def _run(self, event):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {
            "Parameter": {"Value": "https://hooks.example/x"}
        }
        opened = MagicMock()
        opened.__enter__.return_value = MagicMock(status=200)
        with (
            patch.object(index, "ssm", ssm),
            patch("index.urllib.request.urlopen", return_value=opened) as urlopen,
        ):
            index.handler(event, None)
        return ssm, urlopen

    def test_posts_the_alarm_to_the_webhook(self):
        ssm, urlopen = self._run(ALARM)
        ssm.get_parameter.assert_called_once_with(
            Name="/Test/AlertURL", WithDecryption=True
        )
        request = urlopen.call_args[0][0]
        assert request.full_url == "https://hooks.example/x"
        assert (
            "NotifyNewEntrySwallowedExceptionAlarm" in json.loads(request.data)["text"]
        )

    def test_falls_back_to_the_event_itself_when_alarm_data_is_absent(self):
        _, urlopen = self._run(ALARM["alarmData"])
        assert (
            "NotifyNewEntrySwallowedExceptionAlarm"
            in json.loads(urlopen.call_args[0][0].data)["text"]
        )
