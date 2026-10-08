import logging
import json
import os
from datetime import datetime, timezone

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "pipeline-smoke-test",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        })


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/pipeline-smoke-test.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("pipeline-smoke-test")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(handler)


def greeting(now=None):
    now = now or datetime.now(timezone.utc)
    return f"Hello from pipeline-smoke-test at {now.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def main():
    logger.info("pipeline-smoke-test starting")
    print(greeting())


if __name__ == "__main__":
    main()
