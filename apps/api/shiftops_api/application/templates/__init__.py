"""Template management use cases — admin-only.

Why use cases live here and not in `api/v1/templates.py`
-------------------------------------------------------
The HTTP layer is allowed to depend on these; nothing else should reach in
the other direction. The aiogram handler that someday lets owners "duplicate
template via TG button" will reuse the exact same `CreateTemplate` class.
"""
