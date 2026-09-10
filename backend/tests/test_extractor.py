import pytest

from app.errors import ApiError
from app.ingest.extractor import extract

ARTICLE = """
<html><head><title>Kafka Rebalancing Explained</title></head>
<body>
  <nav>Home About Careers Newsletter Subscribe</nav>
  <article>
    <h1>Kafka Rebalancing Explained</h1>
    <p>A rebalance is triggered when consumer group membership changes.</p>
    <p>The group coordinator revokes partitions and reassigns them to members.</p>
  </article>
  <footer>Copyright 2026 Example Corp. All rights reserved.</footer>
</body></html>
"""


def test_extracts_the_title_and_body_text():
    title, text = extract(ARTICLE, "https://example.com/kafka")

    assert title == "Kafka Rebalancing Explained"
    assert "membership changes" in text
    assert "group coordinator" in text


def test_strips_navigation_and_footer_boilerplate():
    _, text = extract(ARTICLE, "https://example.com/kafka")

    assert "Newsletter Subscribe" not in text
    assert "All rights reserved" not in text


def test_falls_back_to_the_url_when_there_is_no_title():
    html = "<html><body><article><p>" + "Body sentence here. " * 20 + "</p></article></body></html>"

    title, _ = extract(html, "https://example.com/untitled")

    assert title == "https://example.com/untitled"


def test_a_page_with_no_readable_text_is_rejected():
    with pytest.raises(ApiError) as caught:
        extract("<html><body><nav>Menu</nav></body></html>", "https://example.com/empty")

    assert caught.value.code == "extraction_empty"
