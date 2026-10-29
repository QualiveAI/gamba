import random


def jitter_seconds() -> int:
    return random.randint(0, 300)


def can_post_now(last_post_at, now):
    if last_post_at is None:
        return True
    return (now - last_post_at).total_seconds() > 3600
