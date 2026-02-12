from __future__ import annotations

import secrets

def make_confirmation_code(prefix: str = "DEMO") -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{prefix}-" + "".join(secrets.choice(chars) for _ in range(10))
