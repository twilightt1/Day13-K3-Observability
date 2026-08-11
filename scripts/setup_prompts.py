"""Thao tác prompt versioning trên Langfuse theo docs/PROMPT_VERSIONING.md.

Script chỉ gọi API thật của Langfuse (tạo version, đổi label, chạy agent) rồi in trace ID
để dán vào submission/REPORT.md. Không tự ghi version giả — xem RULES.md.

Thứ tự chạy (mỗi lệnh là một tiến trình riêng để không dính prompt cache 60s):

    python scripts/setup_prompts.py create
    python scripts/setup_prompts.py run --label baseline
    python scripts/setup_prompts.py run --label candidate
    python scripts/setup_prompts.py promote --version 2
    python scripts/setup_prompts.py run --label production
    python scripts/setup_prompts.py rollback --version 1
    python scripts/setup_prompts.py show
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")
# .env của lab có thể dùng LANGFUSE_BASE_URL; SDK v3 chỉ đọc LANGFUSE_HOST.
if not os.getenv("LANGFUSE_HOST") and os.getenv("LANGFUSE_BASE_URL"):
    os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]

from langfuse import get_client, observe  # noqa: E402

from app.agent import LabAgent  # noqa: E402
from app.cli import configure_utf8_stdio  # noqa: E402

PROMPT_NAME = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
KNOWN_LABELS = ("production", "baseline", "candidate", "latest")

V1_TEXT = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
V2_TEXT = (
    "Feature={{feature}}\n"
    "Docs={{docs}}\n"
    "Question={{message}}\n"
    "\n"
    "Answer in at most 3 sentences and name the doc you used."
)

SAMPLE_QUERY = {
    "user_id": "student-cp2",
    "session_id": "cp2-prompt-version",
    "feature": "monitoring",
    "message": "How do metrics, traces and logs work together?",
}


def _fetch(client, label: str):
    try:
        return client.get_prompt(PROMPT_NAME, label=label, type="text", cache_ttl_seconds=0)
    except Exception:
        return None


def cmd_create(client, _args) -> int:
    if _fetch(client, "baseline") or _fetch(client, "candidate"):
        print(f"Prompt '{PROMPT_NAME}' đã có version. Bỏ qua create; chạy 'show' để xem.")
        return 0

    v1 = client.create_prompt(
        name=PROMPT_NAME, prompt=V1_TEXT, type="text", labels=["baseline", "production"]
    )
    print(f"Đã tạo version {v1.version} với labels baseline + production")
    v2 = client.create_prompt(
        name=PROMPT_NAME, prompt=V2_TEXT, type="text", labels=["candidate"]
    )
    print(f"Đã tạo version {v2.version} với label candidate")
    return 0


def cmd_show(client, _args) -> int:
    print(f"Prompt: {PROMPT_NAME}")
    for label in KNOWN_LABELS:
        prompt = _fetch(client, label)
        if prompt is None:
            print(f"  {label:<11} -> (chưa gắn)")
        else:
            first_line = prompt.prompt.splitlines()[0] if prompt.prompt else ""
            print(f"  {label:<11} -> version {prompt.version} | dòng đầu: {first_line}")
    return 0


def _move_production(client, version: int, action: str) -> int:
    client.update_prompt(name=PROMPT_NAME, version=version, new_labels=["production"])
    print(f"{action}: label 'production' -> version {version}")
    current = _fetch(client, "production")
    if current is None:
        print("CẢNH BÁO: không đọc lại được label production")
        return 1
    print(f"Xác nhận: production đang trỏ tới version {current.version}")
    return 0


def cmd_promote(client, args) -> int:
    return _move_production(client, args.version, "Promote")


def cmd_rollback(client, args) -> int:
    return _move_production(client, args.version, "Rollback")


@observe(name="cp2-prompt-version-check")
def _run_agent(label: str) -> tuple[str | None, str | None]:
    client = get_client()
    trace_id = client.get_current_trace_id()
    client.update_current_trace(name=f"cp2-prompt-{label}")
    LabAgent().run(**SAMPLE_QUERY)
    return trace_id, client.get_trace_url(trace_id=trace_id)


def cmd_run(client, args) -> int:
    os.environ["LANGFUSE_PROMPT_LABEL"] = args.label
    trace_id, url = _run_agent(args.label)
    client.flush()

    prompt = _fetch(client, args.label)
    version = prompt.version if prompt else "?"
    print(f"label={args.label} | prompt_version={version}")
    print(f"trace_id={trace_id}")
    print(f"trace_url={url}")
    if trace_id is None:
        print("CẢNH BÁO: không lấy được trace ID; kiểm tra LANGFUSE_* trong .env")
        return 1
    return 0


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("create", help="Tạo version 1 (baseline+production) và version 2 (candidate)")
    sub.add_parser("show", help="In version đang gắn với từng label")

    run_parser = sub.add_parser("run", help="Chạy một request với label chỉ định, in trace ID")
    run_parser.add_argument("--label", required=True, help="baseline | candidate | production")

    promote_parser = sub.add_parser("promote", help="Chuyển label production sang version khác")
    promote_parser.add_argument("--version", type=int, required=True)

    rollback_parser = sub.add_parser("rollback", help="Rollback label production về version cũ")
    rollback_parser.add_argument("--version", type=int, required=True)

    args = parser.parse_args()

    client = get_client()
    if not client.auth_check():
        print("Không xác thực được Langfuse. Kiểm tra LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST.")
        return 1

    handlers = {
        "create": cmd_create,
        "show": cmd_show,
        "run": cmd_run,
        "promote": cmd_promote,
        "rollback": cmd_rollback,
    }
    exit_code = handlers[args.command](client, args)
    client.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
