"""Button pagination helper.

WhatsApp's interactive ``buttons`` type only supports up to 3 buttons per
message. The ``list`` (single_select) type used to be the fallback for
larger menus, but it does not render reliably on iOS, so the project no
longer uses it. Instead, sets of more than 3 options are split across
multiple button messages, with a "Ver más" pagination button when there
are too many to fit in two back-to-back messages.

Pagination model
----------------
- ``N <= 3``: 1 message with N buttons. No pagination state.
- ``4 <= N <= 6``: 2 messages back-to-back. First has 3 buttons, second
  has the remaining 1-3. No pagination state.
- ``N >= 7``: First message holds the first 3 buttons. Second message
  holds the next 2 buttons plus a "Ver más" pagination button (3 total).
  Tapping "Ver más" emits another message using the same logic; the
  remaining options live in ``session.context['_pending_button_pages']``
  and are consumed on subsequent taps.

The helper writes only the *pagination* state. Callers are responsible
for writing ``last_options`` (or any other resolution map) so that taps
on real option buttons still resolve to their original meaning.
"""

from __future__ import annotations

SHOW_MORE_BUTTON_ID = "_show_more"
PENDING_PAGES_KEY = "_pending_button_pages"


def _make_buttons_response(
    content: str,
    buttons: list[dict],
    typing_delay_ms: int = 0,
) -> dict:
    resp = {"type": "buttons", "content": content, "buttons": buttons}
    if typing_delay_ms > 0:
        resp["metadata"] = {"typing_delay_ms": typing_delay_ms}
    return resp


def is_show_more_input(user_message) -> bool:
    """True when the user just tapped a "Ver más" pagination button."""
    if user_message is None:
        return False
    return str(user_message).strip() == SHOW_MORE_BUTTON_ID


def has_pending_pages(session) -> bool:
    return bool((session.context or {}).get(PENDING_PAGES_KEY))


def clear_pending_pages(session) -> None:
    ctx = dict(session.context or {})
    if PENDING_PAGES_KEY in ctx:
        ctx.pop(PENDING_PAGES_KEY, None)
        session.write({"context": ctx})


def _save_pending_pages(session, pending: list[dict]) -> None:
    ctx = dict(session.context or {})
    ctx[PENDING_PAGES_KEY] = list(pending)
    session.write({"context": ctx})


def _get_pending_pages(session) -> list[dict]:
    return list((session.context or {}).get(PENDING_PAGES_KEY) or [])


def build_paginated_buttons(
    session,
    all_options: list[dict],
    prompt: str,
    more_text: str,
    show_more_label: str,
    first_typing_delay_ms: int = 0,
) -> list[dict]:
    """Build a list of button responses for any number of options.

    Args:
        session: hospital.chatbot.session record. Used to persist
            pagination state in ``session.context``.
        all_options: full list of ``{"id", "label"}`` option dicts.
            Labels longer than 20 chars are not truncated here; callers
            should pre-trim if needed (WhatsApp ignores buttons whose
            label exceeds the limit).
        prompt: text shown above the FIRST button message.
        more_text: short text shown above continuation messages.
        show_more_label: label for the "Ver más" pagination button.
        first_typing_delay_ms: typing delay applied to the first message
            only (continuation messages send immediately).

    Returns: list of response dicts (1 or 2 entries on the first call).
    """
    if not all_options:
        return []

    options = list(all_options)
    n = len(options)

    # Case 1: <= 3 options — single message, no pagination state.
    if n <= 3:
        clear_pending_pages(session)
        return [_make_buttons_response(prompt, options, first_typing_delay_ms)]

    # Case 2: 4-6 options — split into two back-to-back messages, no
    # pagination state needed (the user sees everything immediately).
    if n <= 6:
        clear_pending_pages(session)
        return [
            _make_buttons_response(prompt, options[:3], first_typing_delay_ms),
            _make_buttons_response(more_text, options[3:], 0),
        ]

    # Case 3: >= 7 options — first message has the first 3 buttons; the
    # second message has 2 buttons plus a "Ver más" pagination button.
    # The remaining options are stashed for the next tap.
    first_page = options[:3]
    second_real = options[3:5]
    pending = options[5:]
    second_page = list(second_real) + [
        {"id": SHOW_MORE_BUTTON_ID, "label": show_more_label}
    ]
    _save_pending_pages(session, pending)
    return [
        _make_buttons_response(prompt, first_page, first_typing_delay_ms),
        _make_buttons_response(more_text, second_page, 0),
    ]


def consume_next_page(
    session,
    more_text: str,
    show_more_label: str,
) -> list[dict]:
    """Build the next paginated batch when the user taps "Ver más".

    Returns a single-element list with the next button message, or an
    empty list if there is no pending state (defensive — should not
    happen during normal flow).
    """
    pending = _get_pending_pages(session)
    if not pending:
        return []

    # <= 3 left → emit all remaining, end of pagination.
    if len(pending) <= 3:
        clear_pending_pages(session)
        return [_make_buttons_response(more_text, list(pending), 0)]

    # > 3 left → emit 2 + "Ver más", keep paginating.
    next_real = pending[:2]
    new_pending = pending[2:]
    page = list(next_real) + [
        {"id": SHOW_MORE_BUTTON_ID, "label": show_more_label}
    ]
    _save_pending_pages(session, new_pending)
    return [_make_buttons_response(more_text, page, 0)]
