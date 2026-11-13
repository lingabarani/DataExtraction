"""
DataExtraction — Temporal Fallback Shims for Non-Cluster / Development Environments
===================================================================================
Provides robust mock interfaces when the temporalio SDK is not installed or when
running in lightweight direct-saga execution mode, preventing import crashes
while maintaining exact interface parity for testability and local development.
"""

import sys
import types
from contextlib import nullcontext


def ensure_temporal_shims() -> None:
    """Ensure temporalio modules exist in sys.modules with proper stub interfaces."""
    if "temporalio" in sys.modules:
        return

    try:
        import temporalio  # noqa: F401
        return
    except ImportError:
        pass

    # Create synthetic temporalio module hierarchy
    mod_temporalio = types.ModuleType("temporalio")
    mod_workflow = types.ModuleType("temporalio.workflow")
    mod_activity = types.ModuleType("temporalio.activity")
    mod_common = types.ModuleType("temporalio.common")
    mod_exceptions = types.ModuleType("temporalio.exceptions")
    mod_client = types.ModuleType("temporalio.client")
    mod_worker = types.ModuleType("temporalio.worker")

    # Activity decorators
    class _MockActivity:
        @staticmethod
        def defn(name=None, **kwargs):
            return lambda fn: fn

    mod_activity.defn = _MockActivity.defn
    mod_temporalio.activity = mod_activity

    # Workflow decorators & safe context
    class _Unsafe:
        @staticmethod
        def imports_passed_through():
            return nullcontext()

    class _MockWorkflow:
        unsafe = _Unsafe

        @staticmethod
        def defn(name=None, **kwargs):
            return lambda cls: cls

        @staticmethod
        def run(*args, **kwargs):
            return lambda fn: fn

        @staticmethod
        def signal(name=None, **kwargs):
            return lambda fn: fn

        @staticmethod
        def query(name=None, **kwargs):
            return lambda fn: fn

        @staticmethod
        async def execute_activity(*args, **kwargs):
            return {}

        @staticmethod
        async def execute_child_workflow(*args, **kwargs):
            return {}

        @staticmethod
        def now():
            from datetime import datetime, timezone
            return datetime.now(timezone.utc)

        @staticmethod
        async def sleep(seconds):
            import asyncio
            await asyncio.sleep(seconds)

    for k, v in _MockWorkflow.__dict__.items():
        if not k.startswith("__"):
            setattr(mod_workflow, k, v)
    mod_temporalio.workflow = mod_workflow

    # Common
    class RetryPolicy:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    mod_common.RetryPolicy = RetryPolicy
    mod_temporalio.common = mod_common

    # Exceptions
    class ActivityError(Exception): pass
    class FailureError(Exception): pass
    class ApplicationError(Exception): pass

    mod_exceptions.ActivityError = ActivityError
    mod_exceptions.FailureError = FailureError
    mod_exceptions.ApplicationError = ApplicationError
    mod_temporalio.exceptions = mod_exceptions

    # Client
    class TLSConfig:
        def __init__(self, *args, **kwargs): pass

    class Client:
        @staticmethod
        async def connect(*args, **kwargs):
            return Client()

        async def start_workflow(self, *args, **kwargs):
            class _Handle:
                id = "mock-handle"
                async def result(self): return {}
            return _Handle()

        def get_workflow_handle(self, *args, **kwargs):
            class _Handle:
                id = "mock-handle"
                async def query(self, *a, **k): return {}
                async def signal(self, *a, **k): return None
            return _Handle()

    class Schedule:
        def __init__(self, *args, **kwargs): pass

    class ScheduleActionStartWorkflow:
        def __init__(self, *args, **kwargs): pass

    class ScheduleSpec:
        def __init__(self, *args, **kwargs): pass

    class ScheduleIntervalSpec:
        def __init__(self, *args, **kwargs): pass

    class ScheduleAlreadyRunningError(Exception): pass
    class ScheduleNotFoundError(Exception): pass

    mod_client.Client = Client
    mod_client.TLSConfig = TLSConfig
    mod_client.Schedule = Schedule
    mod_client.ScheduleActionStartWorkflow = ScheduleActionStartWorkflow
    mod_client.ScheduleSpec = ScheduleSpec
    mod_client.ScheduleIntervalSpec = ScheduleIntervalSpec
    mod_client.ScheduleAlreadyRunningError = ScheduleAlreadyRunningError
    mod_client.ScheduleNotFoundError = ScheduleNotFoundError
    mod_temporalio.client = mod_client

    # Worker
    class Worker:
        def __init__(self, *args, **kwargs): pass
        async def run(self): pass

    mod_worker.Worker = Worker
    mod_temporalio.worker = mod_worker

    sys.modules["temporalio"] = mod_temporalio
    sys.modules["temporalio.workflow"] = mod_workflow
    sys.modules["temporalio.activity"] = mod_activity
    sys.modules["temporalio.common"] = mod_common
    sys.modules["temporalio.exceptions"] = mod_exceptions
    sys.modules["temporalio.client"] = mod_client
    sys.modules["temporalio.worker"] = mod_worker


# Auto-apply when imported
ensure_temporal_shims()
