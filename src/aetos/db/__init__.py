from .models import Base, Episode, KPI

__all__ = [
    "Base",
    "Episode",
    "KPI",
    "AsyncSessionLocal",
    "get_session",
    "init_db",
    "persist_workflow_run",
]


def __getattr__(name: str):
    if name == "persist_workflow_run":
        from .history import persist_workflow_run

        return persist_workflow_run
    if name in ("AsyncSessionLocal", "get_session", "init_db"):
        from . import session as session_mod

        return getattr(session_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
