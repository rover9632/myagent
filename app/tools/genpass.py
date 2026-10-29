"""Random password generator (agent tool).

Pure computation — no workspace access and no files, so nothing is uploaded
to cloud storage; the passwords are returned to the model directly.

Charsets:
  numeric  digits only
  alpha    letters only (both cases)
  alnum    letters + digits (default)
  all      letters + digits + symbols
"""

from __future__ import annotations

import json
import secrets
import string

from langchain.tools import tool

CHARSETS = {
    "numeric": string.digits,
    "alpha": string.ascii_letters,
    "alnum": string.ascii_letters + string.digits,
    "all": string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.?/",
}

MIN_LENGTH = 1
MAX_LENGTH = 256
MAX_COUNT = 50


def genpass(length: int, charset: str = "alnum") -> str:
    if length < MIN_LENGTH:
        raise ValueError(f"length must be >= {MIN_LENGTH}")
    if charset not in CHARSETS:
        raise ValueError(f"charset must be one of {sorted(CHARSETS)}")
    chars = CHARSETS[charset]
    return "".join(secrets.choice(chars) for _ in range(length))


def build_genpass_tools():
    @tool("genpass")
    async def genpass_tool(length: int = 16, charset: str = "alnum", count: int = 1) -> str:
        """Generate cryptographically random passwords.

        charset: "numeric" (digits), "alpha" (letters), "alnum" (letters+digits,
        default), or "all" (letters+digits+symbols). length ranges 1-256
        (default 16); count ranges 1-50 (default 1).
        """
        if not MIN_LENGTH <= length <= MAX_LENGTH:
            raise ValueError(f"length must be between {MIN_LENGTH} and {MAX_LENGTH}")
        if not 1 <= count <= MAX_COUNT:
            raise ValueError(f"count must be between 1 and {MAX_COUNT}")
        if charset not in CHARSETS:
            raise ValueError(f"charset must be one of {sorted(CHARSETS)}")

        passwords = [genpass(length, charset) for _ in range(count)]
        return json.dumps({"passwords": passwords}, ensure_ascii=False)

    return [genpass_tool]
