"""Serve the map prototype and a local chat API backed by historical haul data."""

from __future__ import annotations

import csv
import json
import math
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CHAT_URL = "https://api.x.ai/v1/chat/completions"
MAX_QUESTION_LENGTH = 2_000
MAX_CONTEXT_FILE_SIZE = 100 * 1024 * 1024
KRILL_COLUMN = "NUMBER_OF_KRILL_UNDER_1M2"
ENVIRONMENT_COLUMNS = ("SST", "SIA", "SIM", "SIT", "SSS", "SAP", "SLP")


def find_haul_file() -> Optional[Path]:
    configured_path = os.environ.get("FISHCAST_HAUL_DATA")
    if configured_path:
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return path if path.is_file() else None

    path = ROOT / "data" / "krillcast_merged.csv"
    return path if path.is_file() else None


def build_historical_context(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_CONTEXT_FILE_SIZE:
        raise ValueError("The historical haul CSV is larger than the 100 MB chat limit.")

    groups: dict[str, dict[str, Any]] = {}
    date_range = {"first": None, "last": None}
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("The historical haul CSV has no header row.")
        required_columns = {"DATE", KRILL_COLUMN}
        missing_columns = required_columns.difference(reader.fieldnames)
        if missing_columns:
            raise ValueError(f"The historical haul CSV is missing required columns: {', '.join(sorted(missing_columns))}.")
        numeric_columns = [column for column in (KRILL_COLUMN, *ENVIRONMENT_COLUMNS) if column in reader.fieldnames]

        row_count = 0
        for row in reader:
            date = row.get("DATE", "").strip()
            year = date[:4] if len(date) >= 4 and date[:4].isdigit() else "unknown"
            if date and (date_range["first"] is None or date < date_range["first"]):
                date_range["first"] = date
            if date and (date_range["last"] is None or date > date_range["last"]):
                date_range["last"] = date
            group = groups.setdefault(
                year,
                {
                    "hauls": 0,
                    "nonzero_krill_hauls": 0,
                    "metrics": {column: {"count": 0, "sum": 0.0, "min": math.inf, "max": -math.inf} for column in numeric_columns},
                    "highest_catch_hauls": [],
                },
            )
            group["hauls"] += 1
            row_count += 1

            for column in numeric_columns:
                try:
                    value = float(row.get(column, ""))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue

                metric = group["metrics"][column]
                metric["count"] += 1
                metric["sum"] += value
                metric["min"] = min(metric["min"], value)
                metric["max"] = max(metric["max"], value)
                if column == KRILL_COLUMN and value > 0:
                    group["nonzero_krill_hauls"] += 1

            try:
                catch = float(row.get(KRILL_COLUMN, ""))
            except (TypeError, ValueError):
                catch = math.nan
            if math.isfinite(catch):
                haul: dict[str, Any] = {"date": date, "krill_per_m2": catch}
                for column, key in (("LATITUDE", "latitude"), ("LONGITUDE", "longitude")):
                    try:
                        haul[key] = float(row[column])
                    except (KeyError, TypeError, ValueError):
                        pass
                group["highest_catch_hauls"].append(haul)
                group["highest_catch_hauls"].sort(key=lambda item: item["krill_per_m2"], reverse=True)
                del group["highest_catch_hauls"][3:]

    if row_count == 0:
        raise ValueError("The historical haul CSV contains no data rows.")

    summaries = []
    for year in sorted(groups, key=lambda item: float(item) if item != "unknown" else -math.inf):
        group = groups[year]
        metrics = {}
        for column, metric in group["metrics"].items():
            if metric["count"] == 0:
                continue
            metrics[column] = {
                "count": metric["count"],
                "mean": metric["sum"] / metric["count"],
                "min": metric["min"],
                "max": metric["max"],
            }
        summaries.append(
            {
                "year": year,
                "hauls": group["hauls"],
                "nonzero_krill_hauls": group["nonzero_krill_hauls"],
                "nonzero_krill_fraction": group["nonzero_krill_hauls"] / group["hauls"],
                "observed_field_summaries": metrics,
                "highest_catch_hauls": group["highest_catch_hauls"],
            }
        )

    return {
        "source_file": path.name,
        "data_type": "historical observed krill haul records; not model predictions",
        "date_range": date_range,
        "total_hauls": row_count,
        "overall": summaries[0] if len(summaries) == 1 else {
            "hauls": row_count,
            "nonzero_krill_hauls": sum(item["nonzero_krill_hauls"] for item in summaries),
            "observed_field_summaries": {
                column: {
                    "count": sum(item["observed_field_summaries"].get(column, {}).get("count", 0) for item in summaries),
                    "mean": (
                        sum(
                            item["observed_field_summaries"].get(column, {}).get("mean", 0)
                            * item["observed_field_summaries"].get(column, {}).get("count", 0)
                            for item in summaries
                        )
                        / sum(item["observed_field_summaries"].get(column, {}).get("count", 0) for item in summaries)
                    ),
                    "min": min(item["observed_field_summaries"][column]["min"] for item in summaries if column in item["observed_field_summaries"]),
                    "max": max(item["observed_field_summaries"][column]["max"] for item in summaries if column in item["observed_field_summaries"]),
                }
                for column in numeric_columns
                if any(column in item["observed_field_summaries"] for item in summaries)
            },
        },
        "by_year": summaries,
    }


def call_grok(question: str, context: dict[str, Any]) -> str:
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set on the chat server.")

    payload = {
        "model": os.environ.get("FISHCAST_GROK_MODEL", "grok-3-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the FishCast historical-data assistant. The supplied context summarizes "
                        "historical KRILLBASE haul observations, not model predictions. Answer only "
                        "from the supplied data. If a question needs a detail not present in the "
                        "summary, say so plainly instead of guessing. Describe this as haul data, not "
                        "as a complete census of krill abundance. Do not infer causation or invent units."
                ),
            },
            {
                "role": "user",
                "content": f"Historical haul data context (JSON):\n{json.dumps(context, separators=(',', ':'))}\n\nQuestion:\n{question}",
            },
        ],
        "temperature": 0.2,
    }
    request = Request(
        CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"Grok API returned HTTP {error.code}. Check the API key and model configuration.") from None
    except URLError as error:
        raise RuntimeError(f"Could not connect to the Grok API: {error.reason}") from None

    try:
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Grok returned an unexpected response.") from None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Grok returned an empty answer.")
    return answer.strip()


class ChatHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/api/status":
            super().do_GET()
            return

        haul_file = find_haul_file()
        self._json_response(
            200,
            {
                "historical_file": haul_file.name if haul_file else None,
                "has_api_key": bool(os.environ.get("XAI_API_KEY")),
                "ready": haul_file is not None and bool(os.environ.get("XAI_API_KEY")),
            },
        )

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._json_response(404, {"error": "Not found."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(400, {"error": "Invalid request size."})
            return
        if content_length < 1 or content_length > 16_384:
            self._json_response(400, {"error": "Request must be between 1 byte and 16 KB."})
            return

        try:
            request_body = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_response(400, {"error": "Request body must be valid JSON."})
            return
        question = request_body.get("question") if isinstance(request_body, dict) else None
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_LENGTH:
            self._json_response(400, {"error": f"Question must be 1-{MAX_QUESTION_LENGTH} characters."})
            return

        haul_file = find_haul_file()
        if haul_file is None:
            self._json_response(
                503,
                {
                    "error": (
                        "Historical haul data was not found. Add data/krillcast_merged.csv or set "
                        "FISHCAST_HAUL_DATA to its CSV path."
                    )
                },
            )
            return
        if not os.environ.get("XAI_API_KEY"):
            self._json_response(503, {"error": "Set XAI_API_KEY in the terminal running this server."})
            return

        try:
            context = build_historical_context(haul_file)
            answer = call_grok(question.strip(), context)
        except (OSError, ValueError, RuntimeError) as error:
            self._json_response(502, {"error": str(error)})
            return
        self._json_response(200, {"answer": answer, "source_file": haul_file.name})


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ChatHandler)
    print(f"FishCast historical-data chat running at http://127.0.0.1:{port}/viz/prototype/polar_map.html")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FishCast chat server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
