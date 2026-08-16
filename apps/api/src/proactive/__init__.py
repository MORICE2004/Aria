"""Proactive ARIA — noticing things without being asked.

Until now ARIA has been entirely reactive: everything she does starts with
MORICE clicking something. This package is the part that speaks first.

The design problem with a proactive assistant is not building one. It is
building one that stays worth listening to. An assistant that surfaces
everything it notices trains you to ignore it, and an ignored assistant is
strictly worse than a silent one — it costs attention and returns nothing.

So three rules govern everything here:

  1. **Only surface what MORICE can act on.** "Your queue has 3 pending
     messages" is a status readout, not an observation. "A message from Grace
     failed 5 times and is stuck" is something he can fix.

  2. **Say it once.** Every insight has a stable key and a cooldown. Nagging
     is how a notification channel dies.

  3. **Never act — only raise.** The proactive engine has no send path, no
     gateway calls, and no autonomy. It notices and reports. Anything it
     wanted done still goes through the normal decision layer, where MORICE's
     policies apply. A component that both decides what matters AND acts on
     it has no supervision left in it.
"""

from src.proactive.engine import (  # noqa: F401
    Insight,
    ProactiveEngine,
    Severity,
    get_engine,
)
