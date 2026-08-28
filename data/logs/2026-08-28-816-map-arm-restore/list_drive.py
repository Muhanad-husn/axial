import sys, pathlib
sys.path.insert(0, "data/logs/2026-08-28-816-map-arm-restore")
from _journal import emit
from axial.drive import _load_drive_secrets, DriveClient, _list_all_records

secrets = _load_drive_secrets(pathlib.Path("secrets/secrets.toml"))
emit("drive_secrets_ok", books_folder_id=secrets["books_folder_id"])
client = DriveClient(secrets["service_account_json"])
records = _list_all_records(client, secrets["books_folder_id"])
emit("drive_listed", count=len(records))
for r in sorted(records, key=lambda x: (x.get("name") or "")):
    print(f'{r.get("name")!r}  id={r.get("id")}  md5={r.get("md5Checksum")}  mime={r.get("mimeType")}  size={r.get("size")}  mtime={r.get("modifiedTime")}')
