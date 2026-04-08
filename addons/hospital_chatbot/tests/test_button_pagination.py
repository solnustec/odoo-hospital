"""Tests for button_pagination helper.

Covers the pagination state machine in isolation using a fake session
that mimics the parts of hospital.chatbot.session that the helper uses.
The pagination logic does not need a real Odoo cursor.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.hospital_chatbot.services.button_pagination import (
    PENDING_PAGES_KEY,
    SHOW_MORE_BUTTON_ID,
    build_paginated_buttons,
    consume_next_page,
    has_pending_pages,
    is_show_more_input,
)


class _FakeSession:
    """Minimal stand-in for hospital.chatbot.session.

    The pagination helper only needs ``session.context`` reads and a
    ``session.write({'context': ...})`` for persistence.
    """

    def __init__(self, context=None):
        self.context = dict(context or {})

    def write(self, vals):
        if "context" in vals:
            self.context = dict(vals["context"])


def _make_options(n):
    return [{"id": f"opt_{i}", "label": f"Option {i}"} for i in range(1, n + 1)]


@tagged("post_install", "-at_install")
class TestButtonPagination(TransactionCase):

    def test_is_show_more_input(self):
        self.assertTrue(is_show_more_input(SHOW_MORE_BUTTON_ID))
        self.assertTrue(is_show_more_input(f"  {SHOW_MORE_BUTTON_ID}  "))
        self.assertFalse(is_show_more_input("opt_1"))
        self.assertFalse(is_show_more_input(""))
        self.assertFalse(is_show_more_input(None))

    def test_empty_options_returns_empty(self):
        session = _FakeSession()
        self.assertEqual(
            build_paginated_buttons(session, [], "prompt", "more", "Ver más"),
            [],
        )

    def test_three_or_fewer_one_message(self):
        for n in (1, 2, 3):
            session = _FakeSession({PENDING_PAGES_KEY: ["stale"]})
            opts = _make_options(n)
            resp = build_paginated_buttons(session, opts, "prompt", "more", "Ver más")
            self.assertEqual(len(resp), 1, f"n={n}")
            self.assertEqual(resp[0]["type"], "buttons")
            self.assertEqual(len(resp[0]["buttons"]), n)
            # Stale pagination state must be cleared.
            self.assertFalse(has_pending_pages(session))

    def test_four_to_six_two_messages_no_pagination(self):
        for n in (4, 5, 6):
            session = _FakeSession({PENDING_PAGES_KEY: ["stale"]})
            opts = _make_options(n)
            resp = build_paginated_buttons(session, opts, "prompt", "more", "Ver más")
            self.assertEqual(len(resp), 2, f"n={n}")
            self.assertEqual(len(resp[0]["buttons"]), 3)
            self.assertEqual(len(resp[1]["buttons"]), n - 3)
            # No "Ver más" button anywhere.
            for r in resp:
                ids = [b["id"] for b in r["buttons"]]
                self.assertNotIn(SHOW_MORE_BUTTON_ID, ids)
            self.assertFalse(has_pending_pages(session))

    def test_seven_options_first_call(self):
        session = _FakeSession()
        opts = _make_options(7)
        resp = build_paginated_buttons(session, opts, "prompt", "more", "Ver más")
        self.assertEqual(len(resp), 2)
        # First message: first 3 real options.
        self.assertEqual(
            [b["id"] for b in resp[0]["buttons"]],
            ["opt_1", "opt_2", "opt_3"],
        )
        # Second message: 2 real + Ver más.
        self.assertEqual(
            [b["id"] for b in resp[1]["buttons"]],
            ["opt_4", "opt_5", SHOW_MORE_BUTTON_ID],
        )
        # 2 options pending.
        self.assertEqual(len(session.context[PENDING_PAGES_KEY]), 2)

    def test_seven_options_consume_finishes_pagination(self):
        session = _FakeSession()
        opts = _make_options(7)
        build_paginated_buttons(session, opts, "prompt", "more", "Ver más")

        # 2 pending → tap Ver más → both shown, no more pagination.
        next_resp = consume_next_page(session, "more", "Ver más")
        self.assertEqual(len(next_resp), 1)
        self.assertEqual(
            [b["id"] for b in next_resp[0]["buttons"]],
            ["opt_6", "opt_7"],
        )
        self.assertFalse(has_pending_pages(session))

    def test_ten_options_full_pagination(self):
        session = _FakeSession()
        opts = _make_options(10)
        # First call: msg1=[1,2,3], msg2=[4,5,more], pending=[6..10]
        first = build_paginated_buttons(session, opts, "prompt", "more", "Ver más")
        self.assertEqual(
            [b["id"] for b in first[1]["buttons"]],
            ["opt_4", "opt_5", SHOW_MORE_BUTTON_ID],
        )
        self.assertEqual(len(session.context[PENDING_PAGES_KEY]), 5)

        # Tap Ver más #1: pending=[6..10], 5 left, >3 → emit [6,7,more], pending=[8,9,10]
        page2 = consume_next_page(session, "more", "Ver más")
        self.assertEqual(len(page2), 1)
        self.assertEqual(
            [b["id"] for b in page2[0]["buttons"]],
            ["opt_6", "opt_7", SHOW_MORE_BUTTON_ID],
        )
        self.assertEqual(len(session.context[PENDING_PAGES_KEY]), 3)

        # Tap Ver más #2: pending=[8,9,10], 3 left → emit all, no more.
        page3 = consume_next_page(session, "more", "Ver más")
        self.assertEqual(len(page3), 1)
        self.assertEqual(
            [b["id"] for b in page3[0]["buttons"]],
            ["opt_8", "opt_9", "opt_10"],
        )
        self.assertFalse(has_pending_pages(session))

    def test_consume_with_empty_pending_returns_empty(self):
        session = _FakeSession()
        self.assertEqual(consume_next_page(session, "more", "Ver más"), [])

    def test_no_response_emits_list_type(self):
        """Pagination must NEVER produce a list-type message (iOS bug)."""
        session = _FakeSession()
        for n in (1, 3, 4, 6, 7, 12, 25):
            session.context = {}
            resp = build_paginated_buttons(
                session, _make_options(n), "prompt", "more", "Ver más"
            )
            for r in resp:
                self.assertEqual(r["type"], "buttons", f"n={n}")
            # And drain pagination too.
            while has_pending_pages(session):
                more = consume_next_page(session, "more", "Ver más")
                for r in more:
                    self.assertEqual(r["type"], "buttons", f"n={n} (paged)")
