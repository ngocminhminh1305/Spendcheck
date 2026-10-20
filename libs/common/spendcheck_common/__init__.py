"""Code shared by all Spendcheck microservices.

Kept deliberately small: each service must still build and run on its own.
Install inside a service image with:  pip install /opt/spendcheck-common      (or [llm] for the LLM client)
"""

from .middleware import configure_logging, install_common_middleware, require_user_id

__all__ = ["configure_logging", "install_common_middleware", "require_user_id"]
