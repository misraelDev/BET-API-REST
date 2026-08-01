from math import ceil

from fastapi import Response


def set_pagination_headers(
    response: Response,
    *,
    total: int,
    page: int,
    page_size: int,
) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    response.headers["X-Total-Pages"] = str(ceil(total / page_size) if total else 0)

