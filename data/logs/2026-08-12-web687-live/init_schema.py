"""Create the service schemas for the #687 live validation."""
import sys
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.quotas import QuotaStore

dsn = sys.argv[1]
for cls in (JobStore, QuotaStore, PaperCache):
    cls(dsn).create_schema()
    print(f"{cls.__name__} schema ready", flush=True)
