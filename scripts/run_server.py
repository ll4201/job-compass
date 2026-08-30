import atexit
import json
import os
import secrets

import uvicorn

from app.settings import ROOT
from build_static_bundle import build_bundle

PID_FILE = ROOT / "data" / "job_compass.pid"


def remove_own_pid_file() -> None:
    try:
        metadata = json.loads(PID_FILE.read_text(encoding="utf-8")) if PID_FILE.exists() else {}
        if metadata.get("pid") == os.getpid():
            PID_FILE.unlink()
    except (OSError, json.JSONDecodeError):
        pass


def main() -> None:
    build_bundle()
    PID_FILE.parent.mkdir(exist_ok=True)
    stop_token = secrets.token_urlsafe(32)
    # 8001 avoids colliding with the private local system on port 8000.
    port = int(os.getenv("JOB_COMPASS_PORT", "8001"))
    os.environ["JOB_COMPASS_STOP_TOKEN"] = stop_token
    PID_FILE.write_text(
        json.dumps({"pid": os.getpid(), "port": port, "stop_token": stop_token}),
        encoding="utf-8",
    )
    atexit.register(remove_own_pid_file)
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
