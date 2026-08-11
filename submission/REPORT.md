# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm:
- Repository URL:
- Commit SHA cuối:
- Thành viên và vai trò:

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: *(vai trò Logging & PII điền — Checkpoint 1)*
- Tổng số traces: 56 trace trong project Langfuse `cmso1vrrz03p0ad0cmluaw5ai`, trong đó **21 trace dùng prompt managed thật** (`prompt_source=langfuse`). 35 trace còn lại là `local-fallback` từ các lần chạy trước khi prompt `day13-chat` được tạo. Bảng thống kê: [evidence/cp2-prompt-traces.txt](evidence/cp2-prompt-traces.txt), ảnh danh sách trace tại `evidence/trace-list.png`
- Số PII leak còn lại: *(vai trò Logging & PII điền — Checkpoint 1)*
- Link/đường dẫn dashboard: `streamlit run scripts/dashboard.py` → http://localhost:8501 (nguồn dữ liệu `data/logs.jsonl`)

## 3. Logging và tracing

- Evidence correlation ID: *(vai trò Logging & PII điền — Checkpoint 1)*
- Evidence PII redaction: *(vai trò Logging & PII điền — Checkpoint 1)*
- Evidence trace waterfall: trace `f309496b9af894b0483c32762b6ff253` — [xem trên Langfuse](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/f309496b9af894b0483c32762b6ff253), ảnh tại `evidence/trace-waterfall.png`, số liệu tại [evidence/cp2-dashboard-incident.txt](evidence/cp2-dashboard-incident.txt) phần 2.
- Giải thích một span đáng chú ý: span `retrieve-docs` chiếm **2.501s / 2.656s = 94.2%** thời lượng trace, trong khi span `llm-generate` vẫn giữ 0.151s đúng bằng lúc chạy bình thường. Đây là căn cứ để kết luận độ trễ đến từ bước truy hồi tài liệu chứ không phải từ mô hình. Trước Checkpoint 2, trace chỉ có một span `run` phẳng nên không khoanh vùng được; hai span con `retrieve-docs` và `llm-generate` được bổ sung trong [app/agent.py](../app/agent.py) và có test bảo vệ trong [tests/test_agent_prompt_trace.py](../tests/test_agent_prompt_trace.py).

## 4. Prompt versioning

- Prompt name: `day13-chat` (text prompt, giữ ba biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- Version/label baseline: **version 1**, labels `baseline` + `production`
- Version/label candidate: **version 2**, label `candidate` (thêm một dòng yêu cầu trả lời trong tối đa 3 câu và nêu tên tài liệu đã dùng). Ảnh danh sách hai version tại `evidence/prompt-versions.png`.
- Trace ID của mỗi version:

  | Label khi chạy | Prompt version | Trace ID | promptId trên generation |
  |---|---|---|---|
  | `baseline` | 1 | [`ce0ae6594e560ddf4b71ddd7a37b5901`](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/ce0ae6594e560ddf4b71ddd7a37b5901) | `e7eb2d83-c67b-439c-8301-e3d5b59f13e2` |
  | `candidate` | 2 | [`6d83514afe672ac641b7f37cd9266439`](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/6d83514afe672ac641b7f37cd9266439) | `0bd4a37d-5926-42da-a527-2c951e574d8c` |
  | `production` sau promote | 2 | [`3e8f9ed5f24b227c0097b8027ec08fa7`](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/3e8f9ed5f24b227c0097b8027ec08fa7) | `0bd4a37d-5926-42da-a527-2c951e574d8c` |

  Cả ba trace đều có `prompt_source=langfuse`, tức app lấy prompt managed thật chứ không rơi về template local. Hai `promptId` khác nhau chứng minh trace `baseline` và `candidate` trỏ tới hai bản prompt khác nhau, không chỉ khác nhãn metadata.

- Bằng chứng đổi label hoặc rollback: promote `production` → version 2, chạy một request (trace thứ ba ở trên), sau đó rollback `production` → version 1 và đọc lại để xác nhận. Toàn bộ thao tác chạy qua [scripts/setup_prompts.py](../scripts/setup_prompts.py); output đầy đủ tại [evidence/cp2-prompt-traces.txt](evidence/cp2-prompt-traces.txt), trạng thái label cuối tại [evidence/prompt_versions_after_rollback.txt](evidence/prompt_versions_after_rollback.txt), ảnh trước/sau tại `evidence/prompt-label-rollback.png`.

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: `HỢP LỆ: 6/6 panel có trong dashboard contract.` — [evidence/validate_dashboard.txt](evidence/validate_dashboard.txt)
- Evidence dashboard: `streamlit run scripts/dashboard.py`, ảnh tại `evidence/dashboard-6-panel.png` và `evidence/dashboard-incident.png`. Sáu panel đọc trực tiếp `data/logs.jsonl` theo [config/dashboard.yaml](../config/dashboard.yaml); mỗi panel hiển thị tên, đơn vị, đường threshold và trạng thái OK/BREACH. Time range 60 phút, auto-refresh 30 giây.

  Kiểm chứng runtime (chi tiết tại [evidence/cp2-dashboard-incident.txt](evidence/cp2-dashboard-incident.txt)): bật `rag_slow` rồi chạy lại cùng input làm **P95 tăng 1408ms → 3562ms**, vượt SLO 3000ms và panel chuyển sang BREACH; error rate, cost, token, quality gần như không đổi.

  Số liệu trên dashboard do [app/dashboard_data.py](../app/dashboard_data.py) tính và được khoá bằng 14 test trong [tests/test_dashboard_data.py](../tests/test_dashboard_data.py), nên biểu đồ trong ảnh không phải số vẽ tay.

- SLO đã chọn và lý do: xem [config/slo.yaml](../config/slo.yaml). Objective giữ đúng bằng threshold trong `dashboard.yaml` để dashboard và SLO không lệch nhau. Target chọn theo mức độ ảnh hưởng người dùng:
  - `latency_p95_ms` 3000ms / 99.0% — error budget 1% ≈ 6.7 giờ trong 28 ngày.
  - `error_rate_pct` 2% / 99.0% — lỗi là triệu chứng nặng nhất nên giữ cùng mức với latency.
  - `daily_cost_usd` 2.5 USD / 96.0% — cửa sổ 28 ngày chỉ có 28 mẫu, 96% tương đương cho phép đúng 1 ngày vượt ngân sách.
  - `quality_score_avg` 0.75 / 95.0% — quality là heuristic nên nới hơn ba SLI kia.

- Alert rules và runbook: 4 alert trong [config/alert_rules.yaml](../config/alert_rules.yaml), mỗi SLI đúng một alert, runbook đầy đủ trong [docs/alerts.md](../docs/alerts.md).

  | Alert | Severity | Điều kiện | SLI |
  |---|---|---|---|
  | `ChatAnswerTooSlow` | P2 | p95 latency > 3000ms, 2 cửa sổ 10 phút liên tiếp | `latency_p95_ms` |
  | `ChatRequestsFailing` | P1 | error rate > 2% trong 10 phút, tối thiểu 5 request | `error_rate_pct` |
  | `ChatAnswerQualityDrop` | P3 | mean quality < 0.75, 2 cửa sổ 15 phút liên tiếp | `quality_score_avg` |
  | `ChatCostBudgetBurn` | P3 | cost cộng dồn trong ngày UTC > 2.5 USD | `daily_cost_usd` |

  Alert đặt tên theo triệu chứng người dùng gặp, không theo tên incident nội bộ, vì người trực ca không biết trước nguyên nhân khi chuông reo. Điều kiện có thêm ràng buộc "tối thiểu 5 request" và "2 cửa sổ liên tiếp" để tránh báo động giả lúc ít tải.

## 6. Điều tra challenge

- Challenge ID:
- Triệu chứng từ metrics:
- Trace ID liên quan:
- Log line/correlation ID liên quan:
- Root cause:
- Fix action:
- Preventive measure:

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| *(điền tên)* | Checkpoint 2 — Tracing, prompt versioning, dashboard, SLO & alert: `app/dashboard_data.py`, `scripts/dashboard.py`, `scripts/setup_prompts.py`, hai span con trong `app/agent.py`, `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`, `tests/test_dashboard_data.py` | *(điền commit SHA)* | Metrics chỉ nói "có gì đó chậm"; phải có span con thì trace mới chỉ được chậm ở đâu. Trace một span phẳng là trace vô dụng khi điều tra. |
| | | | |
