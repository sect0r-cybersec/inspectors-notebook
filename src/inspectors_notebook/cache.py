"""Which cached cases to delete (FR-29 to FR-32).

The newest cases by last activity are kept up to the limit. Older ones are deleted,
oldest first, except the active case and pinned cases, which are never deleted. A case
that was never exported is only deleted once the analyst confirms (when warning is on).
"""


def plan(metas: list[dict], active_id: str | None, limit: int, warn_unexported: bool = True) -> tuple[list[str], list[str]]:
    """(delete now, ask first) for cases listed newest first."""
    delete, confirm = [], []
    for meta in reversed(metas[limit:]):  # oldest first
        if meta["id"] == active_id or meta.get("pinned"):
            continue
        (delete if meta.get("exported") or not warn_unexported else confirm).append(meta["id"])
    return delete, confirm


def next_to_go(metas: list[dict], active_id: str | None, limit: int) -> str | None:
    """The case that will be deleted when the next new case starts."""
    with_new = [{"id": None}] + metas
    candidates = [m for m in with_new[limit:] if m["id"] not in (None, active_id) and not m.get("pinned")]
    return candidates[-1]["id"] if candidates else None
