"""Dashboard 6 panel cho Day 13, dựng theo contract config/dashboard.yaml.

Chạy:  streamlit run scripts/dashboard.py

Toàn bộ số liệu do app/dashboard_data.py tính (có test trong tests/test_dashboard_data.py);
file này chỉ là lớp hiển thị.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.dashboard_data import PanelResult, compute_panels, load_events

CONTRACT_PATH = REPO_ROOT / "config" / "dashboard.yaml"
LOG_PATH = REPO_ROOT / os.getenv("LOG_PATH", "data/logs.jsonl")

OPERATOR_LABEL = {"lte": "≤", "gte": "≥"}


def load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def format_value(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:,.4f}"
    if unit == "percent":
        return f"{value:,.2f}%"
    if unit == "score_0_to_1":
        return f"{value:,.3f}"
    if unit == "requests_per_minute":
        return f"{value:,.2f}"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.1f}"


def render_headline(panel: PanelResult) -> None:
    scalars = {
        name: value
        for name, value in panel.values.items()
        if isinstance(value, (int, float))
    }
    if scalars:
        for column, (name, value) in zip(st.columns(len(scalars)), scalars.items()):
            column.metric(f"{name} ({panel.unit})", format_value(value, panel.unit))

    for name, value in panel.values.items():
        if not isinstance(value, dict) or not value:
            continue
        if name == "sum_by_minute":
            continue  # đã có biểu đồ theo phút bên dưới
        breakdown = pd.DataFrame(
            {name: list(value.keys()), panel.unit: list(value.values())}
        )
        st.dataframe(breakdown, hide_index=True, width="stretch")


def render_chart(panel: PanelResult) -> None:
    if not panel.series:
        st.caption("Chưa có dữ liệu trong cửa sổ thời gian.")
        return

    frame = pd.DataFrame(
        {
            "minute": [point.minute for point in panel.series],
            f"{panel.threshold_aggregation} ({panel.unit})": [
                point.value for point in panel.series
            ],
            f"threshold {panel.threshold_value}": [panel.threshold_value] * len(panel.series),
        }
    ).set_index("minute")
    st.line_chart(frame, height=200)


def render_panel(panel: PanelResult) -> None:
    status = "🚨 BREACH" if panel.breached else "✅ OK"
    st.markdown(f"#### {panel.title}")
    st.caption(
        f"{status} · SLO: {panel.threshold_aggregation} "
        f"{OPERATOR_LABEL[panel.threshold_operator]} {panel.threshold_value} · đơn vị: {panel.unit}"
    )
    render_headline(panel)
    render_chart(panel)


def main() -> None:
    contract = load_contract()
    dashboard = contract["dashboard"]
    window_minutes = dashboard["time_range_minutes"]
    refresh_seconds = dashboard["refresh_seconds"]

    st.set_page_config(page_title=dashboard["title"], layout="wide")
    st.title(dashboard["title"])
    st.caption(
        f"Nguồn: {LOG_PATH.relative_to(REPO_ROOT).as_posix()} · "
        f"Time range: {window_minutes} phút · Auto-refresh: {refresh_seconds}s"
    )

    @st.fragment(run_every=refresh_seconds)
    def body() -> None:
        events = load_events(LOG_PATH, window_minutes=window_minutes)
        panels = compute_panels(events, contract)

        breached = [panel.title for panel in panels.values() if panel.breached]
        if breached:
            st.error(f"Đang vi phạm threshold: {', '.join(breached)}")
        else:
            st.success("Tất cả panel trong ngưỡng SLO.")

        order = [panel["id"] for panel in dashboard["panels"]]
        for row_start in range(0, len(order), 2):
            for column, panel_id in zip(st.columns(2), order[row_start : row_start + 2]):
                with column:
                    render_panel(panels[panel_id])

        st.caption(
            f"Cập nhật lúc {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC · "
            f"{len(events)} log line trong cửa sổ"
        )

    body()


main()
