"""
Built-in tool plugins (one module per feature).

Drop-in module contract
-----------------------
Each ``*.py`` in this package (except names starting with ``_``) is loaded at startup.

Required exports:

- ``TOOLS``: list of OpenAI-style tool specs (``{"type": "function", "function": {...}}``).
- ``HANDLERS``: dict mapping tool name -> ``callable(arguments: dict) -> str``
  (return JSON string for the model).

Optional:

- ``PLUGIN_ID``: stable id for admin / metadata (default: module name).
- ``__version__``: string (default ``"0"``).

Extra directory (runtime / volume): set env ``AGENT_PLUGINS_EXTRA_DIR`` to a folder of ``*.py``
files using the same contract.

- ``POST /v1/admin/reload-plugins?scope=extra`` — only extra dir (built-ins untouched).
- ``POST /v1/admin/reload-plugins?scope=all`` — full reload including ``app.plugins``.

Optional: ``AGENT_PLUGINS_ALLOWED_SHA256`` — comma-separated lowercase SHA256 hex digests; if set,
each extra ``*.py`` must match one digest or it is skipped (reject logged).
"""
