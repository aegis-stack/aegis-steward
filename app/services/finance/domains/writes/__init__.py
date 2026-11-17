"""Steward's change types (FW-05), on the template's queue (``change_queue``).

Importing this package registers them (``executors``) and the announcement
of every approval that lands (``announce``): an executor that is never
imported does not exist to the queue, the same rule the tool registry lives
by. ``finance/change_types.py`` is what imports it.
"""

from app.services.finance.domains.writes import announce as announce
from app.services.finance.domains.writes import executors as executors
