"""Bounded early polling, never a substitute for completion evidence."""


def poll_delay(poll_count, maximum):
    return min(maximum, 0.05 if poll_count < 2 else 0.1 if poll_count < 5 else 0.2)
