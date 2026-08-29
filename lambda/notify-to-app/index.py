# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import re
import time
import traceback
import urllib.parse
import urllib.request

import boto3
import cloudscraper
import openai
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from strands import Agent
from strands.models import BedrockModel
from strands.models.openai_responses import OpenAIResponsesModel

MODEL_ID = os.environ["MODEL_ID"]
MODEL_REGION = os.environ["MODEL_REGION"]
# "converse" routes through bedrock-runtime; "responses" routes through the
# bedrock-mantle endpoint. Defaults to converse so existing deployments that
# predate this variable keep working unchanged.
MODEL_API_MODE = os.environ.get("MODEL_API_MODE", "converse")
NOTIFIERS = json.loads(os.environ["NOTIFIERS"])
SUMMARIZERS = json.loads(os.environ["SUMMARIZERS"])

ssm = boto3.client("ssm")

# Models that are only served through the Responses API on bedrock-mantle.
# Add new Responses-only model IDs here.
RESPONSES_ONLY_MODEL_IDS = frozenset({"openai.gpt-5.6-terra"})


def validate_model_config(model_id, model_api_mode):
    """Fail fast when the model ID and the API mode do not match."""

    if model_api_mode not in ("converse", "responses"):
        raise ValueError(f"Unsupported MODEL_API_MODE: {model_api_mode!r}")

    is_responses_only = model_id in RESPONSES_ONLY_MODEL_IDS
    if is_responses_only and model_api_mode != "responses":
        raise ValueError(
            f"Model {model_id!r} is only available through the Responses API; "
            f"set MODEL_API_MODE=responses (got {model_api_mode!r})"
        )
    if not is_responses_only and model_api_mode == "responses":
        raise ValueError(
            f"Model {model_id!r} is not registered as a Responses-only model; "
            f"set MODEL_API_MODE=converse (got {model_api_mode!r})"
        )


validate_model_config(MODEL_ID, MODEL_API_MODE)


def build_model(max_tokens):
    """Build the Strands model for the configured API mode."""

    if MODEL_API_MODE == "responses":
        # GPT-5.6 Terra rejects both top_p and temperature: as a reasoning
        # model it only accepts their defaults, and sending either returns
        # HTTP 400 unsupported_parameter. Determinism is instead influenced
        # through the reasoning effort level.
        return OpenAIResponsesModel(
            model_id=MODEL_ID,
            bedrock_mantle_config={"region": MODEL_REGION},
            params={
                "max_output_tokens": max_tokens,
                "reasoning": {"effort": "medium"},
            },
        )

    return BedrockModel(
        model_id=MODEL_ID,
        region_name=MODEL_REGION,
        temperature=0.1,
        top_p=0.1,
        max_tokens=max_tokens,
        streaming=False,
    )


def get_blog_content(url):
    """Retrieve the content of a blog post

    Args:
        url (str): The URL of the blog post

    Returns:
        str: The content of the blog post, or None if it cannot be retrieved.
    """

    if not url.lower().startswith(("http://", "https://")):
        print(f"Invalid URL: {url}")
        return None

    # create a cloudscraper instance
    scraper = cloudscraper.create_scraper()

    # dummy User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }

    try:
        response = scraper.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        print(f"Fetched {url}: status={response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.find("main")
        print(f"Parsed {url}: found_main={main is not None}")

        return main.text if main else None

    except Exception as e:
        print(f"Error accessing {url}: {e}")
        return None


def summarize_blog(
    blog_body,
    language,
    persona,
    summarizer_name,
):
    """Summarize the content of a blog post
    Args:
        blog_body (str): The content of the blog post to be summarized
        language (str): The language for the summary
        persona (str): The persona to use for the summary
        summarizer_name (str): The name of the summarizer to use

    Returns:
        tuple[str, str, str, str]: The summary, the X (Twitter) post, the Threads post, and the Bluesky post
    """

    print(f"Summarizing blog with summarizer: {summarizer_name}")

    if summarizer_name == "AwsSolutionsArchitectJapanese":
        prompt_data = f"""
<persona>You are a professional {persona} with deep expertise in cloud technologies and enterprise solutions. </persona>
<instruction>
Analyze the AWS update in <input></input> tags and provide structured insights focusing on:
- What specific new feature, service, or enhancement is being announced
- Which AWS services are involved or affected
- What technical benefits this provides (performance, cost, scalability, security, etc.)
- Who would benefit most from this update (enterprise users, developers, specific industries, etc.)
- Any important technical requirements, limitations, or prerequisites

IMPORTANT: When writing in Japanese, use consistent and accurate translations for all AWS service names and technical terms. Maintain professional terminology throughout.

Output your analysis in <thinking></thinking> tags using bullet points (each starting with "- " and ending with "\n").
Create a concise summary following <summaryRule></summaryRule> and format according to <outputFormat></outputFormat>.
Generate a post for the <twitter></twitter> section following <twitterRules></twitterRules>.
Generate a longer post for the <threads></threads> section following <threadsRules></threadsRules>.
Generate a post for the <bluesky></bluesky> section following <blueskyRules></blueskyRules>.
</instruction>
<outputLanguage>In {language}.</outputLanguage>
<summaryRule>The final summary must be 2-3 sentences that clearly explain the new AWS feature/update, its key benefits, and target audience in a professional yet accessible tone. When writing in Japanese, use the plain/literary style (だ・である調) of a news report, not the polite style (です・ます調).</summaryRule>
<twitterRules>
STRICT RULES for the X (Twitter) post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 120 characters, using as much of that limit as the content allows. X/Twitter counts Japanese characters at double weight against its 280-character weighted limit, and roughly 23 more weighted characters are consumed by the article link X appends automatically, so 120 actual Japanese characters is close to the real usable maximum.
- Use neutral, informative tone
- Focus on factual information only
- When writing in Japanese, use the plain/literary style (だ・である調) of a news report, not the polite style (です・ます調)
</twitterRules>
<threadsRules>
STRICT RULES for the Threads post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 480 characters, using as much of that limit as the content allows to cover more detail than the X post
- Use neutral, informative tone
- Focus on factual information only
- When writing in Japanese, use the plain/literary style (だ・である調) of a news report, not the polite style (です・ます調)
</threadsRules>
<blueskyRules>
STRICT RULES for the Bluesky post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 150 characters, using as much of that limit as the content allows. This post will have the article URL appended after it (observed RSS article URLs run up to ~170 characters), so leave that headroom within the 300-character Bluesky post limit.
- Use neutral, informative tone
- Focus on factual information only
- When writing in Japanese, use the plain/literary style (だ・である調) of a news report, not the polite style (です・ます調)
</blueskyRules>
<outputFormat><thinking>(detailed bullet point analysis of the AWS update)</thinking><summary>(concise professional summary of the update)</summary><twitter>(X-ready post within 120 characters following twitterRules strictly)</twitter><threads>(Threads-ready post within 480 characters following threadsRules strictly)</threads><bluesky>(Bluesky-ready post within 150 characters following blueskyRules strictly)</bluesky></outputFormat>
Follow the instructions carefully and focus on technical accuracy and practical implications. When outputting in Japanese, ensure consistent and professional translation of all technical terms and service names.
"""
    elif summarizer_name == "Formula1ProfessionalJapanese":
        prompt_data = f"""
<persona>You are a professional {persona} with extensive knowledge of F1 racing, teams, drivers, regulations, and the motorsport industry. </persona>

<glossary_compliance_priority>
CRITICAL - READ FIRST: When your output language is Japanese, every proper noun (driver names, team names, officials) and every technical term listed in <glossary> MUST appear in your <summary>, <twitter>, <threads>, and <bluesky> ONLY in the exact Japanese form given in the glossary. Using the English form or any other Japanese spelling in the final output is forbidden. This rule overrides any other preference; follow the glossary exactly.
</glossary_compliance_priority>

<instruction>
Analyze the Formula 1 or motorsport article in <input></input> tags using the following three steps.

STEP 1: Identify all categories present in the article. For each category below, state true or false:
- レース結果 (race result)
- 予選・フリー走行 (qualifying / practice)
- スプリント (sprint)
- 技術・レギュレーション (technical / regulation)
- ドライバー/チーム人事 (driver / team personnel)
- コメント・インタビュー (comment / interview)
- 次戦プレビュー (next race preview)
- その他 (other)

STEP 2: For each category marked true, extract key points:
- Involved driver names, team names, and circuit names
- Numeric results (position, time, points, lap times) where available
- Regulatory context or technical background
- One notable quote (one sentence max) if relevant

STEP 3: Select the single most important category for the short-form posts and briefly explain why it is the most newsworthy item.

Output your reasoning in <thinking></thinking> tags following the three steps above.
Create a summary following <summaryRule></summaryRule> and format according to <outputFormat></outputFormat>.
Generate a post for the <twitter></twitter> section following <twitterRules></twitterRules>.
Generate a longer post for the <threads></threads> section following <threadsRules></threadsRules>.
Generate a post for the <bluesky></bluesky> section following <blueskyRules></blueskyRules>.

When writing in Japanese: Use ONLY the Japanese translations from the <glossary> for names, teams, and technical terms. Do NOT use English names in <summary>, <twitter>, <threads>, or <bluesky>. Do NOT invent your own katakana; use the glossary form exactly.
</instruction>
<glossary>
MANDATORY TRANSLATION RULES - You MUST follow these translations exactly:
When translating to Japanese, you are REQUIRED to use the following proper nouns and technical terms exactly as specified. DO NOT use any other translations or variations:

<names>
- Max Verstappen: マックス・フェルスタッペン
- Yuki Tsunoda: 角田裕毅
- Lewis Hamilton: ルイス・ハミルトン
- Charles Leclerc: シャルル・ルクレール
- Lando Norris: ランド・ノリス
- Oscar Piastri: オスカー・ピアストリ
- George Russell: ジョージ・ラッセル
- Kimi Antonelli: キミ・アントネッリ
- Carlos Sainz: カルロス・サインツ
- Alex Albon: アレックス・アルボン
- Fernando Alonso: フェルナンド・アロンソ
- Lance Stroll: ランス・ストロール
- Pierre Gasly: ピエール・ガスリー
- Franco Colapinto: フランコ・コラピント
- Esteban Ocon: エスタバン・オコン
- Oliver Bearman: オリバー・ベアマン
- Nico Hulkenberg: ニコ・ヒュルケンベルグ
- Gabriel Bortoleto: ガブリエル・ボルトレート
- Isack Hadjar: アイザック・ハジャー
- Liam Lawson: リアム・ローソン
- Sergio Perez: セルジオ・ペレス
- Valtteri Bottas: バルテリ・ボッタス
- Sebastian Vettel: セバスチャン・ベッテル
- Kimi Räikkönen: キミ・ライックネン
- Christian Horner: クリスチャン・ホーナー
- Toto Wolff: トト・ウォルフ
- Frédéric Vasseur: フレデリック・バスール
- Ayao Komatsu: 小松礼雄
- Shintaro Orihara: 折原伸太郎
</names>

<teams>
- Red Bull Racing: レッドブル・レーシング
- Mercedes: メルセデス
- Ferrari: フェラーリ
- McLaren: マクラーレン
- Alpine: アルピーヌ
- Aston Martin: アストンマーチン
- Williams: ウィリアムズ
- Haas: ハース
- Alfa Romeo: アルファロメオ
- Racing Bulls: レーシング・ブルズ
- KICK Sauber: キックザウバー
- Cadillac: キャデラック
</teams>

<technical_terms>
- Qualifying: 予選
- Practice: フリー走行
- Sprint Race: スプリントレース
- Safety Car: セーフティカー
- Virtual Safety Car: バーチャルセーフティカー
- Undercut: アンダーカット
- Overcut: オーバーカット
- Slipstream: スリップストリーム
- Toe: トゥ
- Downforce: ダウンフォース
- Ground Effect: グラウンドエフェクト
- Porpoising: ポーポイジング
- Parc Fermé: パルクフェルメ
- Degrees of rake: 傾斜度
</technical_terms>

CRITICAL: If any of these terms appear in the content or in your reasoning, you MUST use the exact Japanese translation provided above in your <summary>, <twitter>, <threads>, and <bluesky>. Do NOT output the English form. Do NOT use a different katakana spelling. Using any other translation is strictly forbidden.
</glossary>
<outputLanguage>In {language}.</outputLanguage>
<summaryRule>
Write a flowing 4-6 sentence summary in the style of a professional F1 journalist.
Cover all significant topics present in the article—don't reduce a multi-topic article to a single angle.
Weave topics together naturally in prose—do not use bullet points or sub-headings.
The summary should be engaging enough that readers who follow F1 would want to share it.
Write as if reporting for a Japanese motorsport publication, using the plain/literary style (だ・である調) of Japanese news writing, not the polite style (です・ます調).
When writing in Japanese: use ONLY the Japanese forms from the glossary for all driver names, team names, and technical terms—no English names in the summary.
</summaryRule>
<twitterRules>
STRICT RULES for the X (Twitter) post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 120 characters, using as much of that limit as the content allows. X/Twitter counts Japanese characters at double weight against its 280-character weighted limit, and roughly 23 more weighted characters are consumed by the article link X appends automatically, so 120 actual Japanese characters is close to the real usable maximum.
- Use neutral, informative tone
- Focus on factual information only
- Avoid emotional language or superlatives
- When writing in Japanese: use ONLY glossary Japanese for names, teams, and terms—no English in the post; use the plain/literary style (だ・である調), not the polite style (です・ます調)
- If the article covers multiple topics, cover only the most important one (selected in STEP 3 of your reasoning). Do not attempt to cover all topics within the character limit.
- State the key fact (who, what, result or decision) in one tight sentence.
</twitterRules>
<threadsRules>
STRICT RULES for the Threads post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 480 characters, using as much of that limit as the content allows to cover more detail than the X post
- Use neutral, informative tone
- Focus on factual information only
- Avoid emotional language or superlatives
- When writing in Japanese: use ONLY glossary Japanese for names, teams, and terms—no English in the post; use the plain/literary style (だ・である調), not the polite style (です・ます調)
- The article's most important topic (selected in STEP 3 of your reasoning) must be the primary focus, but you may cover secondary topics if space allows.
- Lead with the key fact (who, what, result or decision), then add supporting detail.
</threadsRules>
<blueskyRules>
STRICT RULES for the Bluesky post:
- NEVER use exclamation marks or show excessive excitement
- State objective facts concisely and professionally
- NO hashtags whatsoever
- Keep within 150 characters, using as much of that limit as the content allows. This post will have the article URL appended after it (observed RSS article URLs run up to ~170 characters), so leave that headroom within the 300-character Bluesky post limit.
- Use neutral, informative tone
- Focus on factual information only
- Avoid emotional language or superlatives
- When writing in Japanese: use ONLY glossary Japanese for names, teams, and terms—no English in the post; use the plain/literary style (だ・である調), not the polite style (です・ます調)
- If the article covers multiple topics, cover only the most important one (selected in STEP 3 of your reasoning). Do not attempt to cover all topics within the character limit.
- State the key fact (who, what, result or decision) in one tight sentence.
</blueskyRules>
<outputFormat><thinking>(3-step reasoning: STEP 1 category list, STEP 2 key points per category, STEP 3 most important category for the short-form posts)</thinking><summary>(4-6 sentence journalist-style prose summary covering all significant topics; weave multiple topics naturally; no bullet points or sub-headings; all proper nouns and technical terms MUST use exact glossary forms; written in だ・である調)</summary><twitter>(X-ready post within 120 characters; if Japanese, all names/teams/terms MUST be in glossary Japanese only, written in だ・である調)</twitter><threads>(Threads-ready post within 480 characters covering more detail than the X post; if Japanese, all names/teams/terms MUST be in glossary Japanese only, written in だ・である調)</threads><bluesky>(Bluesky-ready post within 150 characters; if Japanese, all names/teams/terms MUST be in glossary Japanese only, written in だ・である調)</bluesky></outputFormat>

FINAL CHECK before you output: When output language is Japanese, scan your <summary>, <twitter>, <threads>, and <bluesky> for any English proper nouns (e.g. "Verstappen", "Ferrari", "Mercedes") or technical terms (e.g. "Qualifying", "Safety Car"). If found, replace them with the exact Japanese form from the glossary. Your response is only correct when every such term appears in the glossary form.
"""

    max_tokens = 4096

    model = build_model(max_tokens)

    agent = Agent(
        model=model,
        system_prompt=prompt_data,
        callback_handler=None,
    )
    try:
        response = agent(blog_body)

        outputText = None
        for content in response.message["content"]:
            if "text" in content:
                outputText = content["text"]
                break

        if outputText is None:
            raise ValueError("No text content found in response")

        summary_matches = re.findall(r"<summary>([\s\S]*?)</summary>", outputText)
        twitter_matches = re.findall(r"<twitter>([\s\S]*?)</twitter>", outputText)
        threads_matches = re.findall(r"<threads>([\s\S]*?)</threads>", outputText)
        bluesky_matches = re.findall(r"<bluesky>([\s\S]*?)</bluesky>", outputText)

        if not summary_matches or not twitter_matches or not threads_matches or not bluesky_matches:
            raise ValueError(f"Response missing required XML tags: {outputText[:300]}")

        summary = summary_matches[0]
        twitter = twitter_matches[0]
        threads = threads_matches[0]
        bluesky = bluesky_matches[0]
    except ClientError as error:
        if error.response["Error"]["Code"] == "AccessDeniedException":
            print(
                f"{error.response['Error']['Message']}"
                "\nTo troubeshoot this issue please refer to the following resources:\n"
                "https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html\n"
                "https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html\n"
            )
            raise
        else:
            raise error
    except openai.APIError as error:
        # The Responses path surfaces failures as openai SDK exceptions rather
        # than botocore ClientError.
        print(f"Responses API (bedrock-mantle) error: {error}")
        raise

    return summary, twitter, threads, bluesky


def push_notification(item_list):
    """Notify the arrival of articles

    Args:
        item_list (list): List of articles to be notified
    """

    for item in item_list:

        notifier = NOTIFIERS[item["rss_notifier_name"]]
        webhook_url_parameter_name = notifier["webhookUrlParameterName"]
        ssm_response = ssm.get_parameter(Name=webhook_url_parameter_name, WithDecryption=True)
        app_webhook_url = ssm_response["Parameter"]["Value"]

        item_url = item["rss_link"]

        # Get the blog context
        content = get_blog_content(item_url)
        if content is None:
            print(f"Content unavailable for {item_url}. Falling back to title only.")
            content = item["rss_title"]

        # Summarize the blog
        summarizer = SUMMARIZERS[notifier["summarizerName"]]
        summary, twitter, threads, bluesky = summarize_blog(content, language=summarizer["outputLanguage"], persona=summarizer["persona"], summarizer_name=notifier["summarizerName"])

        # Add the summary text to notified message
        item["summary"] = summary
        item["twitter"] = twitter
        item["threads"] = threads
        item["bluesky"] = bluesky

        item["twitter"] = item["twitter"].replace("\n", "")
        item["threads"] = item["threads"].replace("\n", "")
        item["bluesky"] = item["bluesky"].replace("\n", "")
        msg = create_slack_message(item)

        encoded_msg = json.dumps(msg).encode("utf-8")
        # print("push_msg:{}".format(item))
        print("push_msg:{}".format(msg))
        headers = {
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(app_webhook_url, encoded_msg, headers)
        with urllib.request.urlopen(req) as res:
            print(res.read())
        time.sleep(0.5)


def get_new_entries(blog_entries):
    """Determine if there are new blog entries to notify on Slack by checking the eventName

    Args:
        blog_entries (list): List of blog entries registered in DynamoDB
    """

    res_list = []
    for entry in blog_entries:
        print(entry)
        if entry["eventName"] == "INSERT":
            new_data = {
                "rss_category": entry["dynamodb"]["NewImage"]["category"]["S"],
                "rss_time": entry["dynamodb"]["NewImage"]["pubtime"]["S"],
                "rss_title": entry["dynamodb"]["NewImage"]["title"]["S"],
                "rss_link": entry["dynamodb"]["NewImage"]["url"]["S"],
                "rss_notifier_name": entry["dynamodb"]["NewImage"]["notifier_name"]["S"],
            }
            print(new_data)
            res_list.append(new_data)
        else:  # Do not notify for REMOVE or UPDATE events
            print("skip REMOVE or UPDATE event")
    return res_list


def create_slack_message(item):
    # URL encode the twitter text
    # encoded_twitter_text = urllib.parse.quote("🤖 < " + item["twitter"] + " (生成AIによる要約ポスト)")
    encoded_twitter_text = urllib.parse.quote(item["twitter"])

    # URL encode the threads text
    encoded_threads_text = urllib.parse.quote(item["threads"])

    # Bluesky's compose intent has no separate url parameter, so the article
    # link is appended to the post text before encoding.
    encoded_bluesky_text = urllib.parse.quote(f"{item['bluesky']} {item['rss_link']}")

    # URL encode the RSS link separately
    encoded_rss_link = urllib.parse.quote(item["rss_link"])

    message = {
        "text": f"{item['rss_time']}\n" \
                f"<{item['rss_link']}|{item['rss_title']}>\n" \
                f"{item['summary']}\n" \
                f"<https://x.com/intent/tweet?url={encoded_rss_link}&text={encoded_twitter_text}|Share on X>\n" \
                f"<https://www.threads.com/intent/post?url={encoded_rss_link}&text={encoded_threads_text}|Share on Threads>\n" \
                f"<https://bsky.app/intent/compose?text={encoded_bluesky_text}|Share on Bluesky>"
    }

    return message

def handler(event, context):
    """Notify about blog entries registered in DynamoDB

    Args:
        event (dict): Information about the updated items notified from DynamoDB
    """

    try:
        new_data = get_new_entries(event["Records"])
        if 0 < len(new_data):
            push_notification(new_data)
    except Exception:
        traceback.print_exc()
