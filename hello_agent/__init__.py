"""hello-agent — personal Windows Python agent."""
__version__ = "0.2.0"

# Apply profile-aware path overrides BEFORE any submodule imports Path constants.
# This is critical: get_hello_agent_home() must read the right env var at import time.
from hello_agent.core.paths import _apply_profile_override

_apply_profile_override()
