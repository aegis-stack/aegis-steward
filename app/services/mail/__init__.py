"""Mail read the way the shelf reads paper.

It arrives two ways and is read one way: a Google Takeout ``.mbox`` or
a saved ``.eml`` uploaded like any other document, or a pull over IMAP
with an app password (``pull``: read-only, no OAuth). After the
messages exist the pipeline is the same - the sender is matched to a
contact by address, and every attachment becomes a document on the
shelf, which already names, dates and files it.

Distinct from ``comms``, which SENDS. Steward-shaped only in that
steward has the shelf; the reader belongs upstream once it has proved
itself here (backport ledger).
"""

from app.core.constants import ServiceName

# Part of documents: mail read into the shelf (``ownership``).
PART_OF = ServiceName.DOCUMENTS
