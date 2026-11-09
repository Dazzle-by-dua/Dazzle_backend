"""
Shared, distributed rate limiter for Dazzle by Dua.
Uses MongoDB persistent storage with TTL expiration when available,
ensuring consistent rate limiting across multiple server instances/workers.
Gracefully falls back to thread-safe in-memory sliding window when database is unavailable.
"""

import time
import logging
import datetime
from typing import Optional
from fastapi import Request, HTTPException, status
from app.database import get_database

try:
    from pymongo import ReturnDocument
    RETURN_DOCUMENT_AFTER = ReturnDocument.AFTER
except ImportError:
    RETURN_DOCUMENT_AFTER = True

logger = logging.getLogger("dazzle.ratelimit")

# In-memory fallback dictionary: { key: [timestamps] }
_in_memory_store: dict = {}


def _get_client_ip(request: Request) -> str:
    """Safely extract client IP, respecting trusted proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int, key_prefix: str = "rl"):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    async def __call__(self, request: Request):
        return await self.check_request(request)

    async def check_request(self, request: Request):
        client_ip = _get_client_ip(request)
        now_ts = int(time.time())
        window_bucket = now_ts // self.window_seconds
        rate_key = f"{self.key_prefix}:{client_ip}:{window_bucket}"

        db = None
        try:
            db = get_database()
        except Exception:
            pass

        # Use MongoDB persistent rate limit collection if database is connected
        if db is not None:
            try:
                expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self.window_seconds * 2)
                res = await db.rate_limits.find_one_and_update(
                    {"key": rate_key},
                    {
                        "$inc": {"count": 1},
                        "$setOnInsert": {
                            "key": rate_key,
                            "ip": client_ip,
                            "prefix": self.key_prefix,
                            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "expires_at": expires_at
                        }
                    },
                    upsert=True,
                    return_document=RETURN_DOCUMENT_AFTER
                )
                current_count = res.get("count", 1) if res else 1
                if current_count > self.max_requests:
                    retry_after = self.window_seconds - (now_ts % self.window_seconds)
                    logger.warning(f"Rate limit exceeded for IP {client_ip} on '{self.key_prefix}'. Retry in {retry_after}s.")
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Too many requests. Please wait {max(1, retry_after)} seconds before trying again.",
                        headers={"Retry-After": str(max(1, retry_after))}
                    )
                return
            except HTTPException:
                raise
            except Exception as db_err:
                logger.debug(f"MongoDB rate limit update error, falling back to in-memory: {db_err}")

        # In-memory fallback
        cutoff = now_ts - self.window_seconds
        if rate_key not in _in_memory_store:
            _in_memory_store[rate_key] = []

        # Filter out expired timestamps
        _in_memory_store[rate_key] = [t for t in _in_memory_store[rate_key] if t > cutoff]
        if len(_in_memory_store[rate_key]) >= self.max_requests:
            retry_after = self.window_seconds - (now_ts - _in_memory_store[rate_key][0])
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please wait {max(1, retry_after)} seconds before trying again.",
                headers={"Retry-After": str(max(1, retry_after))}
            )
        _in_memory_store[rate_key].append(now_ts)

    async def reset_request(self, request: Request):
        """Reset rate limit counter for the requesting client upon successful action."""
        client_ip = _get_client_ip(request)
        now_ts = int(time.time())
        window_bucket = now_ts // self.window_seconds
        rate_key = f"{self.key_prefix}:{client_ip}:{window_bucket}"

        try:
            db = get_database()
            if db is not None:
                await db.rate_limits.delete_many({
                    "$or": [
                        {"key": rate_key},
                        {"prefix": self.key_prefix, "ip": client_ip}
                    ]
                })
        except Exception:
            pass

        keys_to_del = [k for k in _in_memory_store if k.startswith(f"{self.key_prefix}:{client_ip}")]
        for k in keys_to_del:
            _in_memory_store.pop(k, None)
