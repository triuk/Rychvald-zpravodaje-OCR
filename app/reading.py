"""Source-first visual reading; candidates remain unpublished until validation."""
from .context import ContextJobs


class ReadingJobs(ContextJobs):
    namespace = 'reading-attempts'
    step_id = 'visual_reading'
