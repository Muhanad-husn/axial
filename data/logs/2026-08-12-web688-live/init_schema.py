"""Create the service schemas for the #688 live validation."""
import sys
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.profiles import ProfileStore
from axial.service.quotas import QuotaStore

dsn = sys.argv[1]
for cls in (JobStore, QuotaStore, PaperCache, ProfileStore):
    cls(dsn).create_schema()
    print(f"{cls.__name__} schema ready", flush=True)
