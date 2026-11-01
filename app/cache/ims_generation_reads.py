"""Small source-ID memo scoped to one sequential read-model generation."""
from contextlib import contextmanager
from contextvars import ContextVar


_reads = ContextVar("ims_generation_reads", default=None)


def generation_reads():
    return _reads.get()


@contextmanager
def isolated_generation_reads():
    # Never share ORM instances, sessions or answers with another publication.
    token = _reads.set({})
    try:
        yield
    finally:
        _reads.reset(token)
