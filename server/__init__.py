"""Core API for AI Personal OS (W1, ADR-017).

The client-facing boundary of the platform: a local service that *wraps* the
frozen engine (``aipos``) and exposes its existing capabilities to clients
(web, desktop, mobile). The architectural boundary is the **Core API
contract** — the operations and payload shapes in ``server.schemas`` — and
HTTP (REST) is only its *first transport* (ADR-017): a future transport can
sit behind the same contract without changing clients.

This package adds no intelligence and owns no storage: it writes no SQL
(``aipos.storage`` remains the only SQL owner), never imports ``lancedb``
(``aipos.vector_store`` remains the only LanceDB owner), and never becomes a
second write coordinator — the only write paths it exposes (retry, workspace
import) delegate to ``aipos.ingest`` and ``aipos.backup`` exactly as the CLI
does. The CLI and the folder watcher remain valid peers of the same engine
(ADR-006); this package sits alongside them, not above them.

Offline-first (ADR-001): the server binds to loopback only. Nothing here
makes, or enables, an off-device connection.
"""

__version__ = "0.1.0"
