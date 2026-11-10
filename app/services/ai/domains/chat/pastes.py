"""A pasted wall of text, stored once and read on demand.

People paste pages. An order listing, a log, a spreadsheet dump: 9,000
to 17,000 characters at a time, and every one of them went into the
message text. That is wrong twice over.

It is wrong on screen, where the transcript becomes the paste and the
conversation disappears into it. And it is wrong in the model call,
because history is REPLAYED: the same page rides every later turn until
the budget pushes it out. Measured on one real session - twelve pasted
pages, 144,196 characters - the pages alone accounted for 1,422,367
characters of replayed history across 102 turns, about ten times over,
and they still fell out of the window by the end.

So a big paste stops being message text. The bytes go to the object
store (content-addressed, so pasting the same page twice is free), a
one-line MARKER goes in the message, and the agent reads the text back
with ``pasted`` when it actually needs it. Twelve pages then cost twelve
lines of history instead of 144k characters, and nothing evicts them.

The index lives beside the saved facts and readings in
``agent_user_memory``: one row per user, so a paste is still reachable
from the next conversation - the same reason readings moved there.

An ATTACHED DOCUMENT lands in the same index. A PDF is read by the
documents service (its text layer per page, a vision model over the
pages that have none) and the entry points at the document rather than
at a blob, so the text has ONE home and the agent has one way to ask for
it. The marker, the tool and the chip do not care which kind it is.

A PICTURE shared in chat lands here too. Its bytes ride the one model
call, and what it showed is read once on the worker (``read_photo``) and
kept beside it, so ``pasted`` answers a screenshot in every later turn
as it answers a page.
"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.storage import get_storage
from app.core.tools import register_tool
from app.services.ai.domains.chat.user_memory import (
    current_user_id,
    load_user_pastes,
    store_user_pastes,
)
from app.services.documents.service import PAGE_HEADING

# What counts as "a wall of text" rather than a long question. Below it
# the paste is just what someone typed and belongs in the message; above
# it, it is a document they brought.
PASTE_THRESHOLD = 2_000

# The index is a line each; the blobs live in storage. Bounded anyway,
# so a year of pasting cannot grow the row without limit.
MAX_PASTES_PER_USER = 50

# Short enough for a model to quote back without fumbling it, long
# enough that two pastes will not collide.
ID_LENGTH = 8

# Stands in the message where a wall of text was, until the paste is
# stored and knows its own id.
PLACEHOLDER = "\x00paste\x00"


# The id inside a marker this module wrote.
_MARKER_ID = re.compile(r"\[pasted text #([0-9a-f]+)")


# What a picture's handle is for, said in its marker. Most pictures are
# a screen to talk about, not paper to keep: filing is the exception.
IMAGE_HINT = (
    "file one with document.file and its paste_id only if it is paper to "
    "keep, like a receipt, statement or letter"
)

# What ``pasted`` says of a picture before its reading has landed. The
# turn that carries the picture names it too, and there the bytes are
# right beside the marker: asking again would only cost a round trip.
PICTURE_UNREAD = (
    "(no reading on file yet: it is read just after it is shared. If the "
    "picture is attached to this turn, look at it directly; do not ask "
    "for it again in this turn)"
)

# How a shared picture is read (``read_photo``), and where its usage is
# recorded: apart from paper read for the documents service.
PICTURE_SURFACE = "chat:picture"
PICTURE_READING = (
    "You are shown a picture someone shared in a conversation: a "
    "screenshot, a photo of paper, or something on their screen. Start "
    "with one sentence saying what it is. Then give every piece of legible "
    "text on it in reading order, keeping amounts, dates, names and numbers "
    "exactly as shown; a table one row per line, cells separated by ' | '. "
    "Do not interpret or add anything that is not in the picture."
)


def paste_id(key: str) -> str:
    """The handle the agent uses, from the storage key.

    The key is ``sha256/ab/cd/<64 hex>`` - 78 characters, and asking a
    model to reproduce one exactly is asking for a hallucinated id. The
    digest's first bytes are as unique as they need to be here.
    """
    return key.rsplit("/", 1)[-1][:ID_LENGTH]


def marker(paste: dict[str, Any]) -> str:
    """The line that stands in for the paste in the message text.

    It says what the paste IS and how to read it, because a marker the
    agent cannot act on is just a hole in the conversation.
    """
    return (
        f"[pasted text #{paste['id']}"
        f"{': ' + paste['title'] if paste.get('title') else ''}"
        f" - {paste['chars']:,} characters."
        f' Read it with pasted("{paste["id"]}")]'
    )


def ids_in(text: str) -> list[str]:
    """The paste ids a message already names.

    The composer stores a paste the moment it is pasted and puts the
    marker in the box, so by the time a message arrives its walls are
    already lifted. The markers are then the record of WHICH pastes the
    message carries - the chips under it are drawn from these.
    """
    return _MARKER_ID.findall(text)


async def named_pastes(user_id: str, text: str) -> list[dict[str, Any]]:
    """The descriptors for every paste a message's markers name."""
    wanted = ids_in(text)
    if not wanted:
        return []
    index = {p["id"]: p for p in await load_user_pastes(user_id)}
    return [index[i] for i in wanted if i in index]


def title_of(block: str) -> str:
    """A name for a wall of text: its first line that says anything.

    The reader has to recognise the paste in a chip, and the agent has
    to recognise it in a marker, so the name comes from the text rather
    than a counter. Pages open with navigation furniture - "All", "Cart",
    "Home" - so a line of one short word is skipped, but the threshold
    stays low enough that a real heading ("Your Orders") still wins.
    """
    for line in block.splitlines():
        line = line.strip()
        if len(line) > 8:
            return line[:60]
    return "pasted text"


def split_blocks(text: str) -> list[str]:
    """The message, cut where a paste is likely to start and end.

    A page almost never arrives alone: it comes with the sentence that
    introduces it ("here is another page"), and lifting the whole
    message would take the question with it. Blank lines are where a
    paste joins what someone actually wrote.
    """
    return text.split("\n\n")


def lift(text: str) -> tuple[str, list[str]]:
    """Pull the walls of text out of a message, in place.

    Returns the message with a placeholder where each wall was, and the
    walls themselves. A message that is only a long question comes back
    untouched with nothing lifted - the threshold is about size, but the
    UNIT is a block, so a single paragraph someone really typed is left
    alone unless it is itself enormous.
    """
    if len(text) <= PASTE_THRESHOLD:
        return text, []
    kept: list[str] = []
    lifted: list[str] = []
    for block in split_blocks(text):
        if len(block) > PASTE_THRESHOLD:
            kept.append(PLACEHOLDER)
            lifted.append(block)
        else:
            kept.append(block)
    return "\n\n".join(kept), lifted


async def store_document(
    user_id: str,
    document_id: int,
    title: str,
    chars: int,
    session: Any = None,
) -> dict[str, Any]:
    """Index an already-read document so the agent can ask for it.

    The text stays where extraction put it - one home - and the entry
    is the handle: the same marker, the same tool, the same chip as a
    pasted page, because from the conversation's side they are the same
    thing.
    """
    return await _index(
        user_id,
        {
            "id": f"{document_id:08x}"[-ID_LENGTH:],
            "document_id": document_id,
            "title": title,
            "chars": chars,
        },
        session,
    )


async def store_image(
    user_id: str,
    key: str,
    media_type: str,
    title: str,
    session: Any = None,
) -> dict[str, Any]:
    """Index a chat photo, already in the store, so it has a handle (#285).

    The bytes rode one model call and were kept (``persist_attachments``);
    without an entry nothing could name the photo again, so a photographed
    statement could not be filed - "I don't have a PDF, just the real
    copy". ``document.file`` turns the entry into a document."""
    return await _index(
        user_id,
        {"id": paste_id(key), "key": key, "media_type": media_type, "title": title},
        session,
    )


async def _index(
    user_id: str, entry: dict[str, Any], session: Any = None
) -> dict[str, Any]:
    """Keep ``entry`` in the user's index, newest last, one per id: the
    same bytes again are the same entry, not a second row, and keep what
    was learned of them (a picture's reading)."""
    index = await load_user_pastes(user_id, session)
    known = next((p for p in index if p.get("id") == entry["id"]), {})
    entry = {**known, **entry, "at": datetime.now(UTC).isoformat()}
    index = [p for p in index if p.get("id") != entry["id"]]
    index.append(entry)
    await store_user_pastes(user_id, index[-MAX_PASTES_PER_USER:], session)
    return entry


async def store_paste(
    user_id: str,
    text: str,
    title: str | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """Keep the text, index it for this user, and describe it.

    Returns the descriptor the message carries. Storage failing is not
    the user losing their paste: the caller falls back to sending it as
    message text, which is what used to happen to every paste.
    """
    data = text.encode("utf-8")
    storage = get_storage()
    key = await storage.put(data, content_type="text/plain")
    # Re-pasting the same page is the same bytes and so the same id;
    # ``_index`` keeps one entry rather than a row per paste of it.
    return await _index(
        user_id,
        {
            "id": paste_id(key),
            "key": key,
            "title": title or "pasted text",
            "chars": len(text),
        },
        session,
    )


async def read_paste(user_id: str, paste_id: str) -> tuple[dict[str, Any], str] | None:
    """The descriptor and the text, or None when there is no such paste.

    The one lookup. ``pasted`` is the agent's door onto it and the
    viewer route is the reader's; neither re-implements the search, and
    neither has to know whether the text came off the clipboard or out
    of a PDF.
    """
    match = await _entry(user_id, paste_id)
    if match is None:
        return None
    if match.get("document_id"):
        text = await document_text(int(match["document_id"]))
        if text is None:
            logger.warning("paste index points at an unread document", id=paste_id)
            return None
        return match, text
    if is_picture(match):
        reading = match.get("reading_key") and await _blob(
            str(match["reading_key"]), paste_id
        )
        return match, reading or PICTURE_UNREAD
    data = await _blob(str(match["key"]), paste_id)
    return None if data is None else (match, data)


async def _entry(user_id: str, paste_id: str) -> dict[str, Any] | None:
    return next(
        (p for p in await load_user_pastes(user_id) if p.get("id") == paste_id), None
    )


async def _blob(key: str, paste_id: str) -> str | None:
    """The text a paste's key holds, or None (logged) when it is gone."""
    data = await get_storage().get(key)
    if data is None:
        logger.warning("paste index points at missing bytes", paste_id=paste_id)
        return None
    return data.decode("utf-8", errors="replace")


def is_picture(entry: dict[str, Any]) -> bool:
    """Whether an index entry is a picture kept from chat: the one test,
    for every reader of the index."""
    return str(entry.get("media_type", "")).startswith("image/")


async def read_photo(user_id: str, paste_id: str) -> bool:
    """Read what a shared picture showed and keep it (``read_photo_task``).

    On the worker, after the turn: the turn that carried the picture saw
    its bytes, and every later one reads this instead. False when there
    is nothing to read: the entry or its bytes are gone."""
    from app.services.documents import service as documents

    entry = await _entry(user_id, paste_id)
    if entry is None or not is_picture(entry):
        return False
    image = await get_storage().get(str(entry["key"]))
    if image is None:
        logger.warning("paste index points at missing bytes", paste_id=paste_id)
        return False
    text, _model = await documents.look(
        image,
        str(entry["media_type"]),
        instructions=PICTURE_READING,
        ask="What does this picture show?",
        surface=PICTURE_SURFACE,
    )
    await keep_reading(user_id, entry, text)
    return True


async def keep_reading(user_id: str, entry: dict[str, Any], text: str) -> None:
    """Store a picture's reading and point its entry at it, through the
    index's one writer."""
    key = await get_storage().put(text.encode("utf-8"), content_type="text/plain")
    await _index(user_id, {**entry, "reading_key": key})


async def document_text(
    document_id: int, session: AsyncSession | None = None
) -> str | None:
    """Every read page of a document, in order, as one body of text.

    A page that could not be read is a row too, with its reason, so it
    is named here rather than silently skipped: the agent must be able
    to tell a page that said nothing from one nobody could read.
    """
    from app.services.ai.domains.chat.user_memory import session_or
    from app.services.documents.service import pages_for

    async with session_or(session) as db:
        pages = await pages_for(db, document_id)
    if not pages:
        return None
    parts = [
        PAGE_HEADING.format(number=page.page_number)
        + (
            page.text.strip()
            if page.status == "read" and page.text
            else f"[page {page.page_number} could not be read: "
            f"{page.detail or 'no text'}]"
        )
        for page in pages
    ]
    return "\n\n".join(parts).strip() or None


async def pasted(paste_id: str) -> str:
    """Read back a block of text the user pasted earlier, or what a
    picture they shared showed.

    A pasted page - an order listing, a log, a statement - is stored
    once and stands in the conversation as a one-line marker naming its
    id, because replaying the whole page into every later turn is what
    pushes the rest of the conversation out of your context. Call this
    with the id from the marker the moment you need the CONTENT, and
    call it again in a later turn rather than trying to remember it: the
    text does not change, and the stored copy outlives the conversation
    it was pasted into.
    """
    user_id = current_user_id.get()
    if not user_id:
        return "No user context available; cannot read that paste."
    found = await read_paste(user_id, paste_id)
    if found is None:
        known = ", ".join(p["id"] for p in await load_user_pastes(user_id)) or "none"
        return f"No paste with id {paste_id!r}. Pastes on file: {known}."
    return found[1]


# Built-in registration: importing this module makes the tool grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "pasted",
    pasted,
    description="Read back a pasted block of text, or what a shared picture showed",
    effect="read",
    replace=True,
)
