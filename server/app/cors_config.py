"""Explicit browser origins; an empty allowlist keeps same-origin deployments."""
from urllib.parse import urlsplit


def cors_origins(raw: str) -> list[str]:
    origins = []
    for entry in raw.split(","):
        origin = entry.strip()
        if not origin:
            continue
        try:
            parsed = urlsplit(origin)
            _ = parsed.port  # Validate malformed/out-of-range ports.
        except ValueError as exc:
            raise ValueError("CORS_ALLOWED_ORIGINS requires exact http(s) origins") from exc
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or "*" in origin or any(char.isspace() for char in origin)
            or origin.endswith(":")
        ):
            raise ValueError("CORS_ALLOWED_ORIGINS requires exact http(s) origins without paths or wildcards")
        if origin not in origins:
            origins.append(origin)
    return origins
