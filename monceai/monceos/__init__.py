"""monceai.monceos — the OS layer.

New subpackage. Does not modify llm.py / matching.py / etc.
Composes existing primitives into brick-ready verbs for Field, Orders, Quotes.

    from monceai import MonceOS
    os = MonceOS(factory_id=4, tenant="riou")
"""

from .core import MonceOS

__all__ = ["MonceOS"]
