"""
Pytest configuration for DataExtraction test suite.
Automatically applies environment shims for Temporal, Prometheus, Jinja2,
and PyArrow when running outside cluster/container environments.
"""

import os
import sys
import types
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Apply Temporal shims if temporalio is not installed
try:
    import temporalio  # noqa: F401
except ImportError:
    from packages.temporal.shims import ensure_temporal_shims
    ensure_temporal_shims()

# Apply Jinja2 stub if not installed
if "jinja2" not in sys.modules:
    try:
        import jinja2  # noqa: F401
    except ImportError:
        mod_jinja2 = types.ModuleType("jinja2")
        class Environment:
            def __init__(self, *args, **kwargs): pass
            def get_template(self, *args, **kwargs): return None
        class Template:
            def __init__(self, *args, **kwargs): pass
            def render(self, *args, **kwargs): return ""
        mod_jinja2.Environment = Environment
        mod_jinja2.Template = Template
        mod_jinja2.pass_context = lambda f: f
        mod_jinja2.contextfunction = lambda f: f
        sys.modules["jinja2"] = mod_jinja2

