"""HTTP probe контейнера; не выводит тело ответа, URL, токены или исключения."""

import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    if mode not in {"live", "ready"}:
        return 2
    try:
        # Только loopback, без прокси из окружения и без auth headers.
        with build_opener(ProxyHandler({})).open(
            f"http://127.0.0.1:8000/health/{mode}", timeout=3
        ) as response:
            return 0 if response.status == 200 else 1
    except (HTTPError, URLError, TimeoutError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
