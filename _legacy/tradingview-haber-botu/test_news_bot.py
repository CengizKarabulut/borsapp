import os
import tempfile
import unittest

os.environ["DRY_RUN"] = "1"

import news_bot


class NewsBotTests(unittest.TestCase):
    def test_bloomberg_cards_are_parsed_and_deduplicated(self):
        page = """
        <main>
          <div data-type="news-card-type1"><a href="/ornek-123" title="Örnek Haber">
            <p>Türkçe kısa özet.</p></a></div>
          <div data-type="news-card-type2"><a href="/ornek-123" title="Örnek Haber"></a></div>
        </main>
        """
        items = news_bot.fetch_bloomberght(_Session(_Response(text=page)))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "Türkçe kısa özet.")

    def test_first_run_bootstraps_without_old_messages(self):
        items = [
            news_bot.blank_item("kap", "Yeni", "https://www.kap.org.tr/tr/Bildirim/2", id="2"),
            news_bot.blank_item("kap", "Eski", "https://www.kap.org.tr/tr/Bildirim/1", id="1"),
        ]
        selected, keys = news_bot.select_new(items, {"last_seen_key": "", "seen_keys": []})
        self.assertEqual(selected, [])
        self.assertEqual(len(keys), 2)

    def test_new_items_are_sent_oldest_first(self):
        items = [
            news_bot.blank_item("kap", "En yeni", "https://kap/3", id="3"),
            news_bot.blank_item("kap", "Yeni", "https://kap/2", id="2"),
            news_bot.blank_item("kap", "Görüldü", "https://kap/1", id="1"),
        ]
        old_key = news_bot.item_key(items[-1])
        selected, _ = news_bot.select_new(items, {"last_seen_key": old_key, "seen_keys": [old_key]})
        self.assertEqual([item["id"] for item in selected], ["2", "3"])

    def test_message_is_escaped_and_within_telegram_limit(self):
        item = news_bot.blank_item(
            "kap", "A&B <Bildirim>", "https://kap/1", id="1",
            summary="x" * 5000, published="15.08.2026 01:00",
        )
        message = news_bot.build_message(item)
        self.assertIn("A&amp;B &lt;Bildirim&gt;", message)
        self.assertLessEqual(len(message), 3900)
        self.assertTrue(message.endswith("</a>"))


class _Response:
    def __init__(self, text="", payload=None):
        self.text = text
        self.encoding = "utf-8"
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


if __name__ == "__main__":
    unittest.main()
