# Alert và Runbook

Mỗi alert dưới đây bám một SLI trong [config/slo.yaml](../config/slo.yaml) và dùng đúng
field của [config/dashboard.yaml](../config/dashboard.yaml). Alert đặt tên theo triệu chứng
người dùng gặp phải, không theo tên incident nội bộ (`rag_slow`, `tool_fail`, `cost_spike`) —
người trực ca không biết trước nguyên nhân khi chuông reo.

Luồng điều tra chung cho cả bốn alert: **Metrics → Traces → Logs**. Xác định cửa sổ thời gian
trên dashboard, mở trace bất thường trong cửa sổ đó, rồi lọc log theo `correlation_id` để chứng minh.

## Alert 1

- Tên: `ChatAnswerTooSlow`
- Severity: P2
- SLI/SLO liên quan: `latency_p95_ms`, objective 3000ms, target 99.0%
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms)` trên cửa sổ 10 phút vượt 3000ms trong 2 cửa sổ liên tiếp (≈20 phút). Hai cửa sổ để một đợt burst ngắn không đánh thức người trực.
- Ảnh hưởng tới người dùng: người dùng chờ quá lâu, phần lớn sẽ bỏ ngang phiên chat.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Latency percentiles*: P95 tách khỏi P50 hay cả hai cùng tăng? Tách nhau nghĩa là chỉ một nhánh request bị chậm.
  2. Panel *Request traffic*: latency tăng có đi kèm traffic tăng không? Nếu không, nguyên nhân nằm trong hệ thống chứ không phải tải.
  3. Mở một trace chậm trong Langfuse, so thời lượng span retrieve với span generation để khoanh vùng.
- Mitigation tạm thời: hạ timeout của bước retrieve để trả lời bằng fallback thay vì để người dùng chờ; nếu vừa đổi prompt thì rollback label `production` về version trước.
- Owner: Vai trò Dashboard, SLO & Alert

## Alert 2

- Tên: `ChatRequestsFailing`
- Severity: P1
- SLI/SLO liên quan: `error_rate_pct`, objective 2%, target 99.0%
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received)` trên cửa sổ 10 phút vượt 2%, và cửa sổ phải có tối thiểu 5 request. Ngưỡng số lượng tối thiểu tránh việc 1 lỗi trên 2 request thành 50% error rate lúc đêm ít tải.
- Ảnh hưởng tới người dùng: request trả về 500, người dùng không nhận được câu trả lời nào.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Error rate and breakdown*: xem `error_type` nào chiếm đa số.
  2. Lọc log `event == "request_failed"` lấy `correlation_id` của một lỗi đại diện.
  3. Mở trace tương ứng, xác định span nào ném lỗi (`RuntimeError: Vector store timeout` chỉ về vector store).
- Mitigation tạm thời: cho bước retrieve fail-open sang câu trả lời fallback thay vì ném lỗi ra người dùng; tắt incident đang bật nếu đây là môi trường lab.
- Owner: Vai trò Dashboard, SLO & Alert

## Alert 3

- Tên: `ChatAnswerQualityDrop`
- Severity: P3
- SLI/SLO liên quan: `quality_score_avg`, objective 0.75, target 95.0%
- Điều kiện và thời gian duy trì: `mean(response_sent.quality_score)` trên cửa sổ 15 phút dưới 0.75 trong 2 cửa sổ liên tiếp. Cửa sổ dài hơn hai alert trên vì quality là số trung bình, nhiễu mạnh khi ít mẫu.
- Ảnh hưởng tới người dùng: hệ thống vẫn trả lời nhanh và không lỗi, nhưng nội dung sai hoặc thiếu ngữ cảnh — dạng hỏng nguy hiểm nhất vì không hiện trên latency hay error rate.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Quality proxy*: điểm giảm dần hay rơi đột ngột? Rơi đột ngột thường trùng một lần đổi prompt hoặc deploy.
  2. Đối chiếu thời điểm rơi với `prompt_version` trong metadata trace; so hai trace trước/sau mốc đó.
  3. Kiểm tra `doc_count` trong metadata generation: bằng 0 nghĩa là retrieve không trả về tài liệu và mô hình đang trả lời chay.
- Mitigation tạm thời: rollback label `production` về version prompt trước bằng `python scripts/setup_prompts.py rollback --version <n>`, rồi xác nhận trace mới ghi đúng version.
- Owner: Vai trò Tracing & Prompt Version

## Alert 4

- Tên: `ChatCostBudgetBurn`
- Severity: P3
- SLI/SLO liên quan: `daily_cost_usd`, objective 2.5 USD/ngày, target 96.0%
- Điều kiện và thời gian duy trì: `sum(response_sent.cost_usd)` cộng dồn trong ngày UTC vượt 2.5 USD. Không cần cửa sổ duy trì vì đây là ngưỡng tích luỹ, không phải giá trị tức thời.
- Ảnh hưởng tới người dùng: chưa ảnh hưởng ngay, nhưng nếu bị chặn ngân sách thì dịch vụ dừng phục vụ toàn bộ.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Cost over time*: chi phí tăng đều theo traffic hay nhảy bậc? Nhảy bậc nghĩa là chi phí trên mỗi request đã đổi.
  2. Panel *Input and output tokens*: `tokens_out` tăng trong khi traffic đứng yên là dấu hiệu câu trả lời dài bất thường.
  3. Đối chiếu với `prompt_version`: một prompt mới yêu cầu câu trả lời dài hơn sẽ đội `tokens_out`.
- Mitigation tạm thời: rollback prompt về version rẻ hơn, hoặc đặt trần `max_tokens` cho câu trả lời.
- Owner: Vai trò Dashboard, SLO & Alert
