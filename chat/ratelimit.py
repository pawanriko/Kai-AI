"""Tiny fixed-window rate limiting on Django's cache (Phase 1 Step 4).

The default cache backend is per-process memory — on the single
free Render instance that is exactly the process that matters. If
KAI ever runs multiple workers, point CACHES at Redis and this
module keeps working unchanged.

Limits are deliberately generous for one owner and useless for a
script: chat 30/min, login 10 per 5 min, setup 5 per 5 min, all
per client IP.
"""

import time
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(name, limit, window_seconds):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            bucket = int(time.time()) // window_seconds
            key = f"ratelimit:{name}:{_client_ip(request)}:{bucket}"
            try:
                count = cache.incr(key)
            except ValueError:
                cache.add(key, 1, timeout=window_seconds + 5)
                count = 1
            if count > limit:
                return JsonResponse(
                    {"error": "Too many requests — please slow down."},
                    status=429,
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
