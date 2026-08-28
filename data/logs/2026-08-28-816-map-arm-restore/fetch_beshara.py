import sys, pathlib, hashlib
sys.path.insert(0, "data/logs/2026-08-28-816-map-arm-restore")
from _journal import emit
from axial.drive import _load_drive_secrets, DriveClient

FILE_ID = "<beshara-2011-drive-file-id>"
EXPECTED_SHA256 = "8410a9059300a22b883d8816d3e5104fa3a1967b5c6ffa3ed33c36dd117bc2ac"
EXPECTED_MD5 = "064df9385cb189d12cf31e95946911d8"
OUT = pathlib.Path(sys.argv[1])

secrets = _load_drive_secrets(pathlib.Path("secrets/secrets.toml"))
client = DriveClient(secrets["service_account_json"])
emit("download_start", file_id=FILE_ID, name="beshara-2011.pdf")
blob = client.download(FILE_ID)
sha = hashlib.sha256(blob).hexdigest()
md5 = hashlib.md5(blob).hexdigest()
emit("download_done", bytes=len(blob), sha256=sha, md5=md5,
     sha256_matches=sha == EXPECTED_SHA256, md5_matches=md5 == EXPECTED_MD5)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(blob)
emit("staged", path=str(OUT), bytes=len(blob))
if sha != EXPECTED_SHA256:
    emit("VERIFY_FAILED", expected=EXPECTED_SHA256, got=sha)
    sys.exit(2)
emit("verify_ok", sha256=sha)
