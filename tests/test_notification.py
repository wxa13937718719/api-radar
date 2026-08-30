from api_radar.notification import render_notification_html


def test_notification_html_is_styled_and_escapes_untrusted_text() -> None:
    report = {
        "generated_at": "2026-08-22T03:12:18+00:00",
        "scans": [{"return_code": 0}, {"return_code": 0}],
        "intelligence": {"successful": 8, "changed": 2},
        "recommendations": {"briefing": {
            "source": "llm",
            "model": "local-model",
            "text": "今天有 **值得关注的新变化**。\n\n[官方说明](https://example.test/offer) <script>alert(1)</script>",
        }},
    }
    rendered = render_notification_html(report)
    assert "DAILY API INTELLIGENCE" in rendered
    assert "<strong>值得关注的新变化</strong>" in rendered
    assert 'href="https://example.test/offer"' in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered
    assert "本地模型 · local-model" in rendered
