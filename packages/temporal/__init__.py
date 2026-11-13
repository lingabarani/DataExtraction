# DataExtraction — packages\temporal
try:
    import temporalio  # noqa: F401
except ImportError:
    from packages.temporal.shims import ensure_temporal_shims
    ensure_temporal_shims()
