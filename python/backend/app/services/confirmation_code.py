from __future__ import annotations

import random


def make_confirmation_code(prefix: str = "DEMO") -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{prefix}-" + "".join(random.choice(chars) for _ in range(6))
