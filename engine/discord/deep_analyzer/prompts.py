"""Prompt templates for each artifact type.

All prompts ask the model to respond with strict JSON so handlers can parse
structured fields reliably. The summary field is always required.
"""

from __future__ import annotations

TEXT_SYSTEM = """\
You analyze short text snippets that a futures/options trader saved as a Discord bookmark.
Respond with strict JSON only. No prose outside the JSON object.

Fields:
- summary (string): one-paragraph summary of what the text is about and why it might matter to a trader.
- tickers (list[str]): any explicit ticker symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tag-like topics.
- sentiment ("bullish" | "bearish" | "neutral" | "mixed"): direction implied by the text.
- has_action_item (bool): true if it implies the user should DO something.
- priority (1-5): trader-relevance, where 5 = "look at this before market open".
"""

X_POST_SYSTEM = """\
You analyze an X.com (Twitter) post that a futures/options trader saved.
The post has already been fetched via the fxtwitter API — you have the
author handle, full text/raw_text, engagement counters, and (for long-form
posts) the article title + content blocks. Use ALL of it when summarizing.
Respond with strict JSON only. No prose outside the JSON object.

Fields:
- summary (string): one-paragraph summary of what the post says and why it
  might matter to a trader. If the post has an article, prioritize the
  article content over the short tweet body.
- tickers (list[str]): explicit ticker symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- sentiment ("bullish" | "bearish" | "neutral" | "mixed"): direction implied.
- has_action_item (bool): true if it implies the user should DO something.
- source_kind: always "x_post".
- author (string|null): the @screen_name of the post author.
- priority (1-5): trader-relevance, where 5 = "look at this before market open".
"""


URL_SYSTEM = """\
You analyze the contents of a web page or social media post that a futures/options trader saved.
The user already extracted the readable body — you do not need to fetch anything else.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary of the page or post.
- tickers (list[str]): explicit ticker symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- sentiment ("bullish" | "bearish" | "neutral" | "mixed"): direction implied.
- has_action_item (bool): true if it implies the user should DO something.
- source_kind ("x_post" | "github" | "article" | "video" | "other"): best fit.
- author (string|null): who wrote/posted it, if recoverable.
- priority (1-5): trader-relevance.
"""

IMAGE_SYSTEM = """\
You analyze an image that a futures/options trader saved as a Discord attachment.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph description.
- ocr_text (string): any text visible in the image.
- is_chart (bool): true if this is a price chart.
- ticker (string|null): if a chart, what symbol.
- timeframe (string|null): if a chart, what timeframe (e.g. "5m", "1h", "1d").
- topics (list[str]): 1-4 short tags.
- priority (1-5): trader-relevance.
"""

AUDIO_SYSTEM = """\
You analyze a transcribed voice memo that the user dictated and saved as a Discord attachment.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary of the memo.
- tickers (list[str]): symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- has_action_item (bool): true if the user said they intend to DO something.
- priority (1-5): trader-relevance.
"""

DOCUMENT_SYSTEM = """\
You analyze the extracted text of a PDF or document a futures/options trader saved.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary.
- tickers (list[str]): symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- has_action_item (bool): true if it implies the user should DO something.
- key_points (list[str]): up to 5 salient points.
- priority (1-5): trader-relevance.
"""
