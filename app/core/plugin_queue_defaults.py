"""The concurrency the stack's plugins ask for, by queue.

Rendered from the plugins in ``.copier-answers.yml``: a queue's number lives
in the plugin that ships it, not here, so `aegis add`/`aegis remove` rewrite
this file and nobody edits it by hand. ``app/core/queue_workers.py`` merges
it into ``DEFAULT_QUEUES``; ``WORKER_QUEUES`` in the environment still
replaces the whole mapping for a project that wants something else.
"""

from app.core.queue_workers import QueueWorker

PLUGIN_QUEUE_DEFAULTS: dict[str, QueueWorker] = {}
