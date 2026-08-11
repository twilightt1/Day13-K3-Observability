# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: The Quants
- Repository URL: https://github.com/twilightt1/Day13-K3-Observability
- Commit SHA cuối:81954c4efec96317d3550450b1cd3fc84b2bcefe
- Thành viên và vai trò:
  - 2A202601047 — Phạm Văn Tâm — Checkpoint 3 (giảm thiểu challenge)
  - 2A202601309 — Nguyễn Quang Khải — Checkpoint 1 (logging & PII)
  - 2A202601039 — Nguyễn Tiến Đạt — Checkpoint 2 (tracing, prompt versioning, dashboard, SLO & alert)

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100 — 52 records, 11 unique correlation IDs, 0 PII leak (kết quả chạy trên `data/logs.jsonl`)
- Tổng số traces: 56 trace trong project Langfuse `cmso1vrrz03p0ad0cmluaw5ai`, trong đó **21 trace dùng prompt managed thật** (`prompt_source=langfuse`). 35 trace còn lại là `local-fallback` từ các lần chạy trước khi prompt `day13-chat` được tạo. Bảng thống kê: [evidence/cp2-prompt-traces.txt](evidence/cp2-prompt-traces.txt), ảnh danh sách trace tại `evidence/trace-list.png`
- Số PII leak còn lại: 0 — validator báo `Potential PII leaks detected: 0`
- Link/đường dẫn dashboard: `streamlit run scripts/dashboard.py` → http://localhost:8501 (nguồn dữ liệu `data/logs.jsonl`)

## 3. Logging và tracing

- Evidence correlation ID: `req-trace001` — cùng ID xuyên suốt `request_received` → `response_sent` trong `data/logs.jsonl`, kết nối log của một request thành chuỗi sự kiện
- Evidence PII redaction: input chứa email/phone/số thẻ bị scrub thành `[REDACTED_EMAIL]`, `[REDACTED_PHONE]`, `[REDACTED_CARD]` trước khi ghi log — xem [app/pii.py](../app/pii.py) và test trong [tests/test_pii.py](../tests/test_pii.py)
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

- **Challenge ID:** `day13-k3-observability-v1` (cohort K3), incident `rag_slow` ảnh hưởng feature `refund`, ngưỡng độ trễ `latency_threshold_ms: 2000`.
- **Triệu chứng từ metrics:** trước khi giảm thiểu, 5 request chính thức đều trả HTTP 200 nhưng `latency_p95` đạt **3826 ms** — vượt ngưỡng 2000 ms — trong khi `error_rate_pct` vẫn là 0.0% và `quality_avg` là 0.86. Chi tiết tại [evidence/cp3-before-metrics.txt](evidence/cp3-before-metrics.txt) và [evidence/cp3-before-dashboard.png](evidence/cp3-before-dashboard.png).
- **Trace ID liên quan (trước fix):** trace đại diện `a66c41006e848fa7eabc27640b1230c5` ([xem trên Langfuse](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/a66c41006e848fa7eabc27640b1230c5), ảnh tại [evidence/cp3-slow-trace.png](evidence/cp3-slow-trace.png)). Trong trace, span `retrieve-docs` mất ~2.50 giây trong khi span `llm-generate` chỉ ~0.15 giây — độ trễ tập trung ở bước truy hồi tài liệu, không phải ở sinh câu trả lời.
- **Log line/correlation ID liên quan:** hai sự kiện `retrieval_completed` và `response_sent` cùng mang correlation ID `req-03476ea5` ([evidence/cp3-root-cause-log.txt](evidence/cp3-root-cause-log.txt)): `retrieval_completed` ghi `retrieval_duration_ms=2500, doc_count=1, degraded=false`, còn `response_sent` ghi `latency_ms=3826`. Cùng một correlation ID trải qua hai sự kiện này chứng minh thời gian truy hồi chiếm phần lớn độ trễ end-to-end của request.
- **Root cause:** dependency RAG (bước `retrieve-docs`) vượt ngân sách độ trễ của nó — không phải do tăng traffic (chỉ 5 request, error rate 0%) và cũng không phải do khâu sinh LLM (span `llm-generate` vẫn ~0.15 giây như bình thường). Đây là lỗi dependency bên ngoài, không phải lỗi logic trong app.
- **Fix action:** áp dụng ngưỡng timeout dependency `RETRIEVAL_TIMEOUT_MS=1500`: nếu truy hồi không hoàn thành trong 1500 ms, request tiếp tục xử lý với fallback danh sách tài liệu rỗng (`degraded=true`). Sau fix, 5 request vẫn đều HTTP 200, `latency_p95` giảm xuống **1653 ms** (dưới 2000 ms) — xem [evidence/cp3-after-metrics.txt](evidence/cp3-after-metrics.txt) và [evidence/cp3-after-dashboard.png](evidence/cp3-after-dashboard.png). Trace đại diện sau fix `1a86098ba73f18f4014b1d6aa8f21d50` ([xem trên Langfuse](https://cloud.langfuse.com/project/cmso1vrrz03p0ad0cmluaw5ai/traces/1a86098ba73f18f4014b1d6aa8f21d50), ảnh tại [evidence/cp3-timeout-trace.png](evidence/cp3-timeout-trace.png)): span truy hồi ghi `doc_count=0, degraded=true, retrieval_duration_ms=1500, timeout_ms=1500`, và log sự kiện `retrieval_timed_out` tương ứng cũng ghi `degraded=true`.
- **Đánh đổi chất lượng:** `quality_avg` giảm từ 0.86 xuống **0.66** sau fix. Đây là đánh đổi có chủ đích: trong lúc dependency gặp sự cố, hệ thống ưu tiên tính sẵn sàng và độ trễ có giới hạn (P95 dưới SLO) hơn là chờ đợi context truy hồi đầy đủ. Fix làm giảm chất lượng câu trả lời tạm thời chứ không cải thiện chất lượng — nó khôi phục độ trễ và khả năng phục vụ.
- **Preventive measure:** (1) timeout dependency `RETRIEVAL_TIMEOUT_MS` chặn một RAG dependency chậm kéo dài độ trễ end-to-end; (2) sự kiện duration theo từng giai đoạn có cấu trúc (`retrieval_completed`, `retrieval_timed_out`) giúp lần sau khoanh vùng nhanh; (3) alert `ChatAnswerTooSlow` có sẵn (P2, p95 latency > 3000 ms) cảnh báo khi vượt SLO; (4) giữ liên kết correlation ID xuyên suốt metrics, traces và logs để truy vết từ triệu chứng tới root cause.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| 2A202601039 — Nguyễn Tiến Đạt | Checkpoint 2 — Tracing, prompt versioning, dashboard, SLO & alert: `app/dashboard_data.py`, `scripts/dashboard.py`, `scripts/setup_prompts.py`, hai span con trong `app/agent.py`, `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`, `tests/test_dashboard_data.py` | `65928d1` (complete checkpoint 2 deliverables) | Metrics chỉ nói "có gì đó chậm"; phải có span con thì trace mới chỉ được chậm ở đâu. Trace một span phẳng là trace vô dụng khi điều tra. |
| 2A202601047 — Phạm Văn Tâm | Checkpoint 3 — Giảm thiểu challenge: thêm ranh giới timeout `RETRIEVAL_TIMEOUT_MS` trong `app/mock_rag.py`, fallback degrade graceful khi truy hồi timeout trong `app/agent.py`, test bảo vệ trong `tests/test_mock_rag.py`, `tests/test_agent_prompt_trace.py`, `tests/test_chat_observability.py`, thu thập evidence chính thức trước/sau, chẩn đoán incident, viết báo cáo | `7f7aefa` (retrieval timeout boundary), `ab67378` (degrade graceful), `d1cca5b` (evidence), `81954c4` (report) | Timeout dependency + fallback degrade giữ P95 dưới SLO khi dependency hỏng, nhưng phải trả giá bằng chất lượng câu trả lời — availability và bounded latency được chọn hơn context đầy đủ trong lúc incident. |
| 2A202601309 — Nguyễn Quang Khải | Checkpoint 1 — Logging & PII: structured logging (`app/logging_config.py`), correlation ID middleware, PII redaction, `scripts/validate_logs.py` | `a27a6f5` (complete checkpoint 1) | Log là dữ liệu nhạy cảm chứ không phải chỗ để in mọi thứ — phải scrub PII ngay tại tầng logging và gắn correlation ID cho từng request thì log mới dùng được để truy vết. |
