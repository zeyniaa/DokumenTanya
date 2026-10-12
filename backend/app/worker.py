"""Run with python -m backend.app.worker (Linux container/WSL)."""
from redis import Redis
from rq import Worker

from . import store
from .config import settings

if __name__ == "__main__":
    store.initialize()
    Worker(["documents"], connection=Redis.from_url(settings().redis_url)).work()
