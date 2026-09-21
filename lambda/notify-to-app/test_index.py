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

    def test_headline_lists_around_the_prose_are_dropped(self):
        # racingnews365 puts "Most read" and related-article lists inside
        # <main>. Their driver names reached the model and the summary of an
        # Antonelli article called him マックス・アントネッリ, borrowing the first
        # name of a Verstappen headline in the sidebar.
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main>"
            "<article><p>Kimi Antonelli has denied that he is the number one "
            "driver at Mercedes, after extending his championship lead over "
            "George Russell to 81 points this season.</p>"
            "<p>The Italian said the team gives both drivers the same "
            "opportunities, and that no one holds priority inside it.</p>"
            "</article>"
            "<section><h2>Most read</h2><ul>"
            "<li><a href='/a'>Max Verstappen reacts to major Lando Norris "
            "career announcement</a></li>"
            "<li><a href='/b'>Lewis Hamilton issues strong denial</a></li>"
            "</ul></section>"
            "</main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "Antonelli" in result
        assert "Russell" in result
        assert "Verstappen" not in result
        assert "Hamilton" not in result

    def test_bullet_lists_in_the_article_are_kept(self):
        # AWS blog posts explain a feature in headings and bullet lists as
        # much as in paragraphs. Keeping only <p> would cost such a post a
        # third of its text, so the rule is link density, not the tag.
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main>"
            "<h2>Solution overview</h2>"
            "<ul><li>Instruction-driven detection: the detection logic lives "
            "entirely in the instructions and a thin parsing layer.</li>"
            "<li>Configurable backend: the model is reached through a uniform "
            "inference interface, so the detector is agnostic to the "
            "backend.</li></ul>"
            "</main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "Solution overview" in result
        assert "Instruction-driven detection" in result
        assert "Configurable backend" in result

    def test_a_short_article_beside_a_long_sidebar_survives(self):
        # On a video page the sidebar outweighs the article, so the wrapper
        # holding both is link-dense. Dropping it returned nothing at all and
        # the notifier fell back to the title.
        headlines = "".join(
            f"<li><a href='/{i}'>Lewis Hamilton issues strong denial as Max "
            f"Verstappen gains momentum</a></li>"
            for i in range(10)
        )
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main><div class='wrapper'>"
            "<article><p>Take a look at the new Madrid circuit, called the "
            "Madring. The street circuit is 5.474 kilometres long and has "
            "twenty corners.</p></article>"
            f"<div class='sidebar'><ul>{headlines}</ul></div>"
            "</div></main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "Madring" in result
        assert "Verstappen" not in result

    def test_a_link_inside_a_sentence_does_not_drop_the_sentence(self):
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main><p>The detector resolves credentials through "
            "the standard AWS credential chain, and you also need "
            "<a href='/x'>model access enabled</a> in the Amazon Bedrock "
            "console for the model that you choose.</p></main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "standard AWS credential chain" in result
        assert "model access enabled" in result

    def test_wordpress_content_class_wins_over_the_rest_of_main(self):
        # racefans.net runs WordPress, whose theme wraps the post body in
        # .entry-content. Taking it leaves the comment section behind, which
        # is prose and so survives the link-density pass.
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main><article>"
            "<div class='entry-content'><p>Mercedes team principal Toto Wolff "
            "has revealed details of his conversations with former race "
            "director Michael Masi before the 2021 title decider, and said he "
            "urged him to listen to the drivers rather than push a decision "
            "through on his own.</p></div>"
            "</article>"
            "<div class='comments-area'><p>A reader writes: this is exactly "
            "why Lewis Hamilton was robbed of an eighth title, and nobody at "
            "the FIA wants to talk about it any more.</p></div>"
            "</main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "Michael Masi" in result
        assert "A reader writes" not in result

    def test_an_empty_content_class_falls_back_to_main(self):
        mock_response = MagicMock()
        mock_response.text = (
            "<html><body><main>"
            "<div class='entry-content'></div>"
            "<div><p>The article body is rendered outside the theme container "
            "on this page, and it is the only text worth summarizing here.</p>"
            "</div></main></body></html>"
        )
        mock_scraper = MagicMock()
        mock_scraper.get.return_value = mock_response
        with patch("index.cloudscraper.create_scraper", return_value=mock_scraper):
            result = index.get_blog_content("https://example.com")
        assert "The article body is rendered outside" in result

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


class TestSummarizeBlogTrimsOutput:
    RESPONSE = (
        "<thinking>x</thinking>"
        "<summary>  \n要約本文。\n  </summary>"
        "<twitter>\n  Xの文。 </twitter>"
        "<threads>  Threadsの文。\n</threads>"
        "<bluesky>\tBlueskyの文。  </bluesky>"
    )

    def _run(self):
        agent = MagicMock()
        agent.return_value.message = {"content": [{"text": self.RESPONSE}]}
        with patch("index.Agent", return_value=agent), patch("index.build_model"):
            return index.summarize_blog("body", "Japanese.", "persona", "AwsSolutionsArchitectJapanese")

    def test_each_section_is_trimmed(self):
        summary, twitter, threads, bluesky = self._run()
        assert summary == "要約本文。"
        assert twitter == "Xの文。"
        assert threads == "Threadsの文。"
        assert bluesky == "Blueskyの文。"


class TestMultiParagraphSummary:
    """A multi-topic summary carries a blank line; it has to survive to Slack.

    The trim added for #39 strips the padding around a tag, so the paragraph
    break inside the summary must not be collapsed along with it.
    """

    SUMMARY = "第1トピック。\n\n一方、第2トピック。"
    RESPONSE = (
        "<thinking>x</thinking>"
        f"<summary>\n  {SUMMARY}\n</summary>"
        "<twitter>Xの文。</twitter>"
        "<threads>Threadsの文。</threads>"
        "<bluesky>Blueskyの文。</bluesky>"
    )

    def test_parse_keeps_the_paragraph_break(self):
        agent = MagicMock()
        agent.return_value.message = {"content": [{"text": self.RESPONSE}]}
        with patch("index.Agent", return_value=agent), patch("index.build_model"):
            summary, _, _, _ = index.summarize_blog(
                "body", "Japanese.", "persona", "Formula1ProfessionalJapanese"
            )
        assert summary == self.SUMMARY

    def test_slack_message_keeps_the_paragraph_break(self):
        item = {
            "rss_time": "2026-09-17 00:00",
            "rss_link": "https://example.com/a",
            "rss_title": "Title",
            "summary": self.SUMMARY,
            "twitter": "X",
            "threads": "T",
            "bluesky": "B",
        }
        assert self.SUMMARY in index.create_slack_message(item)["text"]

    def test_f1_prompt_asks_for_a_paragraph_per_topic(self):
        """The paragraph rule is the whole change; nothing else pins it down."""
        agent = MagicMock()
        agent.return_value.message = {"content": [{"text": self.RESPONSE}]}
        with patch("index.Agent", return_value=agent) as agent_cls, patch("index.build_model"):
            index.summarize_blog("body", "Japanese.", "persona", "Formula1ProfessionalJapanese")
        prompt = agent_cls.call_args.kwargs["system_prompt"]
        assert "split the summary into 2-3 paragraphs" in prompt
        assert "separated by a blank line" in prompt
        # The withdrawn bullet format must stay withdrawn (34dcbb7).
        assert "do not use bullet points, numbered lists, or sub-headings" in prompt


STREAM_RECORD = {
    "eventName": "INSERT",
    "dynamodb": {
        "NewImage": {
            "url": {"S": "https://example.com/a"},
            "notifier_name": {"S": "TestNotifier"},
            "title": {"S": "Title"},
            "category": {"S": "Cat"},
            "pubtime": {"S": "2026-09-20T00:00:00"},
        }
    },
}


class TestHandlerMarksSwallowedExceptions:
    """The handler keeps swallowing exceptions; the marker is what makes the
    resulting dropped article visible to CloudWatch (#46)."""

    def test_marker_is_printed_and_nothing_is_raised(self, capsys):
        with patch("index.push_notification", side_effect=ValueError("boom")):
            index.handler({"Records": [STREAM_RECORD]}, None)
        captured = capsys.readouterr()
        # The marker goes to stdout; print_exc writes the trace to stderr.
        assert index.UNHANDLED_EXCEPTION_MARKER in captured.out
        assert "ValueError: boom" in captured.err

    def test_marker_is_absent_on_success(self, capsys):
        with patch("index.push_notification"):
            index.handler({"Records": [STREAM_RECORD]}, None)
        assert index.UNHANDLED_EXCEPTION_MARKER not in capsys.readouterr().out


class TestMarkerMatchesTheMetricFilter:
    """The marker lives in two files. Change one and detection stops silently:
    the metric reads zero, which the runbook would report as "no failures"."""

    def test_the_stack_filters_on_the_same_string(self):
        stack = os.path.join(
            os.path.dirname(__file__), "..", "..", "lib", "whats-new-summary-notifier-stack.ts"
        )
        with open(stack) as f:
            source = f.read()
        assert f"'\"{index.UNHANDLED_EXCEPTION_MARKER}\"'" in source
