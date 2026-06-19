import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import unittest

from util import format_message


class TestFormatMessageWithPlaceholders(unittest.TestCase):
    def test_simple_placeholder(self):
        template = "Hello, {name}!"
        placeholders = {"name": "Alice"}
        result = format_message(template, placeholders, "any_channel")
        self.assertEqual(result, "Hello, Alice!")

    def test_multiple_placeholders(self):
        template = "{greeting}, {name}! Welcome to {channel}."
        placeholders = {"greeting": "Hello", "name": "Bob", "channel": "DataTalks"}
        result = format_message(template, placeholders, "any_channel")
        self.assertEqual(result, "Hello, Bob! Welcome to DataTalks.")

    def test_channel_specific_placeholder(self):
        template = "Check out this link: {link}"
        placeholders = {
            "link": {
                "channel1": "http://channel1.com",
                "channel2": "http://channel2.com",
            }
        }
        result = format_message(template, placeholders, "channel1")
        self.assertEqual(result, "Check out this link: http://channel1.com")

    def test_default_value(self):
        template = "Check out this link: {link}"
        placeholders = {
            "link": {
                "channel1": "http://channel1.com",
                "default": "http://default.com"
            }
        }
        result = format_message(template, placeholders, "channel2")
        self.assertEqual(result, "Check out this link: http://default.com")

    def test_missing_channel_and_default(self):
        template = "Check out this link: {link}"
        placeholders = {"link": {"channel1": "http://channel1.com"}}
        result = format_message(template, placeholders, "channel2")
        self.assertIsNone(result)

    def test_mixed_placeholders(self):
        template = "Hello, {name}! Check out {link} for {channel} info."
        placeholders = {
            "name": "Charlie",
            "link": {
                "channel1": "http://channel1.com",
                "channel2": "http://channel2.com",
                "default": "http://default.com",
            },
            "channel": "DataTalks",
        }
        result = format_message(template, placeholders, "channel1")
        self.assertEqual(
            result, "Hello, Charlie! Check out http://channel1.com for DataTalks info."
        )

    def test_multiline_quote_one_line(self):
        template = "hello, user!\n\n>{message}\n\nThank you!"
        placeholders = {"message": "This is a quote."}

        expected_result = "hello, user!\n\n>This is a quote.\n\nThank you!"
        result = format_message(template, placeholders, "any_channel")
        self.assertEqual(result, expected_result)

    def test_multiline_quote_three_lines(self):
        template = "hello, user!\n\n>{message}\n\nThank you!"
        placeholders = {"message": "Line1\nLine2\nLine3"}

        expected_result = "hello, user!\n\n>Line1\n>Line2\n>Line3\n\nThank you!"
        result = format_message(template, placeholders, "any_channel")
        self.assertEqual(result, expected_result)

if __name__ == "__main__":
    unittest.main()
