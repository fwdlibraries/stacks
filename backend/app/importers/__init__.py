from app.importers.z3950 import Z3950Handler
from app.importers.manual import ManualEntryHandler

def get_handler(source: str):
    handlers = {
        "z3950": Z3950Handler,
        "manual": ManualEntryHandler,
    }
    handler_class = handlers.get(source)
    if not handler_class:
        raise ValueError(f"Unknown import source: {source}")
    return handler_class()
