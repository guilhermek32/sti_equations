import json
import logging

logger = logging.getLogger("sti_equations.http")


def log_request(request_id: str, method: str, path: str, status_code: int) -> None:
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
            },
            separators=(",", ":"),
        )
    )
