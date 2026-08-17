"""WhatsApp export parsing tests.

Built against the real format of MORICE's own exports. The failures that
matter here are quiet ones: if system notices are counted as writing, ARIA
concludes his average message is "<Media omitted>", and nothing about the
resulting profile looks obviously wrong.
"""

from __future__ import annotations

from src.communication.whatsapp_export import (
    is_usable_sample,
    own_messages,
    parse_export,
    senders,
)

# The exact shape of his exports, including the noise.
REAL_SHAPE = """30/06/2025, 11:05 - Messages and calls are end-to-end encrypted. Only people in this chat can read, listen to, or share them. *Learn more*
29/06/2025, 23:51 - Morice Magnus: hey bro, sawa see you at 5
29/06/2025, 23:52 - Bro Kittah: sawa niko njiani
30/06/2025, 21:16 - The message timer was updated. New messages will disappear from this chat 7 days after they're sent, except when kept. Change timer
04/07/2025, 19:06 - Morice Magnus: <Media omitted>
09/11/2025, 13:41 - Morice Magnus: just checking if you got the file
13/11/2025, 08:11 - Bro Kittah: yeah got it
14/11/2025, 09:00 - Morice Magnus: asante sana
"""


def test_messages_are_separated_from_system_notices() -> None:
    messages = parse_export(REAL_SHAPE)
    # The encryption notice and the timer change have no sender.
    assert [m.sender for m in messages] == [
        "Morice Magnus",
        "Bro Kittah",
        "Morice Magnus",
        "Morice Magnus",
        "Bro Kittah",
        "Morice Magnus",
    ]


def test_only_his_side_is_extracted() -> None:
    """The other person's messages are their voice, not his."""
    messages = parse_export(REAL_SHAPE)
    mine = own_messages(messages, "Morice Magnus")
    assert "sawa niko njiani" not in mine
    assert "yeah got it" not in mine
    assert "hey bro, sawa see you at 5" in mine


def test_media_placeholders_are_not_writing() -> None:
    """Otherwise ARIA learns his average message is '<Media omitted>'."""
    mine = own_messages(parse_export(REAL_SHAPE), "Morice Magnus")
    assert "<Media omitted>" not in mine
    assert len(mine) == 3


def test_sender_counts_identify_who_is_who() -> None:
    counts = senders(parse_export(REAL_SHAPE))
    assert counts["Morice Magnus"] == 4
    assert counts["Bro Kittah"] == 2


def test_multiline_messages_are_joined() -> None:
    """Splitting them would chop his longer messages into fragments and skew
    every length statistic downward."""
    export = """01/01/2025, 10:00 - Morice Magnus: first line
second line
third line
01/01/2025, 10:01 - Kibira: reply
"""
    messages = parse_export(export)
    assert len(messages) == 2
    assert messages[0].body == "first line\nsecond line\nthird line"


def test_ios_bracket_format_is_handled() -> None:
    export = "[30/06/2025, 11:05:22] Morice Magnus: hey bro\n"
    messages = parse_export(export)
    assert messages[0].sender == "Morice Magnus"
    assert messages[0].body == "hey bro"


def test_twelve_hour_clocks_are_handled() -> None:
    export = "30/06/2025, 11:05 PM - Morice Magnus: sawa\n"
    assert parse_export(export)[0].body == "sawa"


def test_invisible_marks_do_not_break_parsing() -> None:
    """WhatsApp wraps some entries in U+200E, which is invisible and breaks
    naive prefix matching."""
    export = "‎30/06/2025, 11:05 - Morice Magnus: ‎hey there\n"
    messages = parse_export(export)
    assert len(messages) == 1
    assert "hey there" in messages[0].body


def test_timestamps_are_parsed_day_first() -> None:
    messages = parse_export("13/11/2025, 08:11 - Morice Magnus: hi\n")
    assert messages[0].sent_at is not None
    assert messages[0].sent_at.day == 13
    assert messages[0].sent_at.month == 11


def test_an_unparseable_timestamp_does_not_lose_the_message() -> None:
    """Failing soft: a wrong date costs ordering, never content."""
    messages = parse_export("99/99/9999, 25:99 - Morice Magnus: still mine\n")
    assert messages and messages[0].body == "still mine"
    assert messages[0].sent_at is None


# ---------- what counts as a writing sample ----------

def test_deleted_and_placeholder_messages_are_rejected() -> None:
    for noise in (
        "<Media omitted>",
        "This message was deleted",
        "You deleted this message",
        "Waiting for this message",
        "null",
        "",
        "   ",
    ):
        assert not is_usable_sample(noise), noise


def test_a_bare_link_is_a_share_not_a_sentence() -> None:
    assert not is_usable_sample("https://example.com/article")
    # But a link with his own words around it is writing.
    assert is_usable_sample("check this out https://example.com/article")


def test_very_long_messages_are_excluded() -> None:
    """A forwarded article is not an example of how he writes a message."""
    assert not is_usable_sample("x" * 500)
    assert is_usable_sample("x" * 100)


def test_normal_messages_are_kept() -> None:
    for good in ("hey", "sawa, tutaonana kesho", "asante sana bro"):
        assert is_usable_sample(good)


# ---------- sampling ----------

def test_recent_messages_are_preferred_when_capped() -> None:
    """Style drifts. How he writes now beats how he wrote two years ago."""
    export = "".join(
        f"0{i}/01/2025, 10:00 - Morice Magnus: message {i}\n" for i in range(1, 6)
    )
    mine = own_messages(parse_export(export), "Morice Magnus", limit=2)
    assert mine == ["message 5", "message 4"]


def test_repeated_messages_count_once_when_capped() -> None:
    """'ok' sent two hundred times is one fact about his vocabulary."""
    export = "".join(
        f"01/01/2025, 10:0{i} - Morice Magnus: ok\n" for i in range(5)
    ) + "02/01/2025, 10:00 - Morice Magnus: sawa bro\n"
    mine = own_messages(parse_export(export), "Morice Magnus", limit=10)
    assert mine.count("ok") == 1
    assert "sawa bro" in mine


def test_an_uncapped_import_keeps_everything_he_wrote() -> None:
    export = "".join(
        f"01/01/2025, 10:0{i} - Morice Magnus: ok\n" for i in range(3)
    )
    assert len(own_messages(parse_export(export), "Morice Magnus")) == 3
