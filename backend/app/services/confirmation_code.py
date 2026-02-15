from __future__ import annotations

import secrets


def make_confirmation_code() -> str:
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(chars) for _ in range(6))
