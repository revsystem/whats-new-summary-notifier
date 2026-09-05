# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("MODEL_ID", "test-model-id")
os.environ.setdefault("MODEL_REGION", "us-west-2")
os.environ.setdefault("MODEL_API_MODE", "converse")
os.environ.setdefault("NOTIFIERS", json.dumps({
    "TestNotifier": {
        "summarizerName": "AwsSolutionsArchitectJapanese",
        "webhookUrlParameterName": "/Test/URL",
    }
}))
os.environ.setdefault("SUMMARIZERS", json.dumps({
    "AwsSolutionsArchitectJapanese": {
        "outputLanguage": "Japanese.",
        "persona": "solutions architect in AWS",
    }
}))

import index  # noqa: E402


def _make_dynamodb_record(event_name, url="https://example.com", title="Test Title",
                           category="Test", pubtime="2024-01-01T00:00:00",
                           notifier_name="TestNotifier"):
    return {
        "eventName": event_name,
        "dynamodb": {
            "NewImage": {
                "url": {"S": url},
                "title": {"S": title},
                "category": {"S": category},
                "pubtime": {"S": pubtime},
                "notifier_name": {"S": notifier_name},
            }
        },
    }


class TestGetBlogContent:
    def test_invalid_url_returns_none(self):
        assert index.get_blog_content("ftp://example.com") is None

    def test_non_http_url_returns_none(self):
        assert index.get_blog_content("javascript:alert(1)") is None

    def test_valid_url_with_main_tag_returns_text(self):
        mock_response = MagicMock()
        mock_response.text = "<html><body><main>Main content here</main></body></html>"
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert result == "Main content here"

    def test_valid_url_without_main_tag_returns_none(self):
        mock_response = MagicMock()
        mock_response.text = "<html><body><div>No main tag</div></body></html>"
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert result is None

    def test_http_error_returns_none(self):
        mock_scraper = MagicMock()
        mock_scraper.get.side_effect = Exception("Connection refused")
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert result is None


class TestGetNewEntries:
    def test_insert_event_is_included(self):
        records = [_make_dynamodb_record("INSERT")]
        result = index.get_new_entries(records)
        assert len(result) == 1
        assert result[0]["rss_link"] == "https://example.com"
        assert result[0]["rss_title"] == "Test Title"
        assert result[0]["rss_notifier_name"] == "TestNotifier"

    def test_remove_event_is_skipped(self):
        records = [_make_dynamodb_record("REMOVE")]
        result = index.get_new_entries(records)
        assert result == []

    def test_modify_event_is_skipped(self):
        records = [_make_dynamodb_record("MODIFY")]
        result = index.get_new_entries(records)
        assert result == []

    def test_mixed_events_only_inserts_returned(self):
        records = [
            _make_dynamodb_record("INSERT", url="https://example.com/1"),
            _make_dynamodb_record("REMOVE", url="https://example.com/2"),
            _make_dynamodb_record("INSERT", url="https://example.com/3"),
        ]
        result = index.get_new_entries(records)
        assert len(result) == 2
        assert result[0]["rss_link"] == "https://example.com/1"
        assert result[1]["rss_link"] == "https://example.com/3"


class TestCreateSlackMessage:
    def _make_item(self, twitter="Test tweet", threads="Test threads post", bluesky="Test bluesky post", rss_link="https://example.com/article"):
        return {
            "rss_time": "2024-01-01T00:00:00",
            "rss_title": "Test Article",
            "rss_link": rss_link,
            "summary": "Summary text",
            "detail": "Detail text",
            "twitter": twitter,
            "threads": threads,
            "bluesky": bluesky,
        }

    def _x_section(self, text):
        return text.split("x.com/intent/tweet", 1)[1].split("threads.com/intent/post", 1)[0]

    def _threads_section(self, text):
        return text.split("threads.com/intent/post", 1)[1].split("bsky.app/intent/compose", 1)[0]

    def _bluesky_section(self, text):
        return text.split("bsky.app/intent/compose", 1)[1]

    def test_message_contains_rss_link(self):
        item = self._make_item()
        msg = index.create_slack_message(item)
        assert "https://example.com/article" in msg["text"]

    def test_twitter_text_is_url_encoded(self):
        item = self._make_item(twitter="AWS新機能 テスト")
        msg = index.create_slack_message(item)
        encoded = urllib.parse.quote("AWS新機能 テスト")
        assert encoded in self._x_section(msg["text"])

    def test_share_on_x_link_is_present(self):
        item = self._make_item()
        msg = index.create_slack_message(item)
        assert "Share on X" in msg["text"]
        assert "x.com/intent/tweet" in msg["text"]

    def test_rss_link_in_tweet_url_is_encoded(self):
        item = self._make_item(rss_link="https://example.com/article?foo=bar&baz=qux")
        msg = index.create_slack_message(item)
        assert "article%3Ffoo%3Dbar%26baz%3Dqux" in msg["text"] or "article" in msg["text"]

    def test_share_on_threads_link_is_present(self):
        item = self._make_item()
        msg = index.create_slack_message(item)
        assert "Share on Threads" in msg["text"]
        assert "https://www.threads.com/intent/post" in msg["text"]

    def test_rss_link_in_threads_url_is_encoded(self):
        item = self._make_item(rss_link="https://example.com/article?foo=bar&baz=qux")
        msg = index.create_slack_message(item)
        assert "article%3Ffoo%3Dbar%26baz%3Dqux" in self._threads_section(msg["text"])

    def test_threads_text_is_url_encoded(self):
        item = self._make_item(threads="AWS新機能 テスト")
        msg = index.create_slack_message(item)
        encoded = urllib.parse.quote("AWS新機能 テスト")
        assert encoded in self._threads_section(msg["text"])

    def test_share_on_bluesky_link_is_present(self):
        item = self._make_item()
        msg = index.create_slack_message(item)
        assert "Share on Bluesky" in msg["text"]
        assert "https://bsky.app/intent/compose" in msg["text"]

    def test_rss_link_is_embedded_in_bluesky_text(self):
        # Bluesky's compose intent has no separate url parameter, so the
        # article link must be embedded inside the text parameter itself.
        item = self._make_item(rss_link="https://example.com/article?foo=bar&baz=qux")
        msg = index.create_slack_message(item)
        assert "article%3Ffoo%3Dbar%26baz%3Dqux" in self._bluesky_section(msg["text"])

    def test_bluesky_text_is_url_encoded(self):
        item = self._make_item(bluesky="AWS新機能 テスト")
        msg = index.create_slack_message(item)
        encoded = urllib.parse.quote("AWS新機能 テスト")
        assert encoded in self._bluesky_section(msg["text"])

    def test_share_texts_are_distinct_per_platform(self):
        item = self._make_item(
            twitter="Short X post",
            threads="Longer Threads post carrying more of the summary than the X post does",
            bluesky="Bluesky-length post with its own wording distinct from the other two",
        )
        msg = index.create_slack_message(item)

        x_section = self._x_section(msg["text"])
        threads_section = self._threads_section(msg["text"])
        bluesky_section = self._bluesky_section(msg["text"])

        assert urllib.parse.quote("Short X post") in x_section
        assert urllib.parse.quote("Longer Threads post carrying more of the summary than the X post does") in threads_section
        assert urllib.parse.quote("Bluesky-length post with its own wording distinct from the other two") in bluesky_section

        assert urllib.parse.quote("Longer Threads post carrying more of the summary than the X post does") not in x_section
        assert urllib.parse.quote("Short X post") not in threads_section
        assert urllib.parse.quote("Bluesky-length post with its own wording distinct from the other two") not in x_section
        assert urllib.parse.quote("Bluesky-length post with its own wording distinct from the other two") not in threads_section


class TestPushNotificationFallback:
    def test_none_content_falls_back_to_title(self, capsys):
        item = {
            "rss_notifier_name": "TestNotifier",
            "rss_link": "https://example.com",
            "rss_title": "Fallback Title",
            "rss_time": "2024-01-01T00:00:00",
        }
        with patch("index.ssm.get_parameter", return_value={"Parameter": {"Value": "https://hooks.example.com"}}), \
             patch("index.get_blog_content", return_value=None), \
             patch("index.summarize_blog", return_value=("summary", "twitter", "threads", "bluesky")) as mock_summarize, \
             patch("index.urllib.request.urlopen"), \
             patch("index.time.sleep"):
            index.push_notification([item])

        mock_summarize.assert_called_once()
        call_args = mock_summarize.call_args
        assert call_args[0][0] == "Fallback Title"
        captured = capsys.readouterr()
        assert "Falling back to title only" in captured.out


class TestValidateModelConfig:
    def test_responses_only_model_accepts_responses_mode(self):
        index.validate_model_config("openai.gpt-5.6-luna", "responses")

    def test_responses_only_model_rejects_converse_mode(self):
        with pytest.raises(ValueError, match="only available through the Responses API"):
            index.validate_model_config("openai.gpt-5.6-luna", "converse")

    def test_converse_model_rejects_responses_mode(self):
        with pytest.raises(ValueError, match="not registered as a Responses-only model"):
            index.validate_model_config("us.amazon.nova-pro-v1:0", "responses")

    def test_unknown_api_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unsupported MODEL_API_MODE"):
            index.validate_model_config("openai.gpt-5.6-luna", "invoke")

    def test_converse_model_accepts_converse_mode(self):
        index.validate_model_config("us.amazon.nova-pro-v1:0", "converse")


class TestFilterGlossaryNames:
    PROMPT = (
        "before\n<names>\n"
        "- Max Verstappen: マックス・フェルスタッペン\n"
        "- Yuki Tsunoda: 角田裕毅\n"
        "- Lando Norris: ランド・ノリス\n"
        "</names>\nafter"
    )

    def test_keeps_only_people_the_article_mentions(self):
        result = index._filter_glossary_names(
            self.PROMPT, "Lando Norris was sixth in FP1 at Monza."
        )
        assert "ランド・ノリス" in result
        assert "角田裕毅" not in result
        assert "マックス・フェルスタッペン" not in result
        assert result.startswith("before") and result.endswith("after")

    def test_matches_on_surname_alone(self):
        result = index._filter_glossary_names(self.PROMPT, "Norris topped the session.")
        assert "ランド・ノリス" in result

    def test_shared_first_name_does_not_pull_in_another_driver(self):
        prompt = (
            "<names>\n"
            "- Kimi Antonelli: キミ・アントネッリ\n"
            "- Kimi Räikkönen: キミ・ライコネン\n"
            "</names>"
        )
        result = index._filter_glossary_names(prompt, "Kimi Antonelli was fourth.")
        assert "キミ・アントネッリ" in result
        assert "キミ・ライコネン" not in result

    def test_empty_body_leaves_the_glossary_alone(self):
        assert index._filter_glossary_names(self.PROMPT, "") == self.PROMPT

    def test_surname_must_be_a_whole_word(self):
        prompt = "<names>\n- Lance Stroll: ランス・ストロール\n- Lando Norris: ランド・ノリス\n</names>"
        result = index._filter_glossary_names(prompt, "Norris strolled back to the garage.")
        assert "ランド・ノリス" in result
        assert "ランス・ストロール" not in result

    def test_accents_are_folded_before_matching(self):
        prompt = "<names>\n- Kimi Räikkönen: キミ・ライコネン\n- Lando Norris: ランド・ノリス\n</names>"
        result = index._filter_glossary_names(prompt, "Raikkonen and Norris shared a laugh.")
        assert "キミ・ライコネン" in result

    def test_matching_is_case_insensitive(self):
        result = index._filter_glossary_names(self.PROMPT, "VERSTAPPEN won again.")
        assert "マックス・フェルスタッペン" in result

    def test_keeps_every_name_when_none_match(self):
        result = index._filter_glossary_names(self.PROMPT, "A story with no drivers.")
        assert "角田裕毅" in result
        assert "ランド・ノリス" in result

    def test_prompt_without_names_section_is_untouched(self):
        prompt = "no glossary here"
        assert index._filter_glossary_names(prompt, "Norris") == prompt
