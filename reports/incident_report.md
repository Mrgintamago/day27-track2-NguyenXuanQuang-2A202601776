# Incident Report, Lab 27

Nguyễn Xuân Quang. Báo cáo này gồm ba phần: bối cảnh hệ thống lúc còn khoẻ, bảng tổng kết
xem lớp nào bắt được fault nào, và một incident làm đầy đủ theo mẫu (stale_kb). Mấy chỗ
mình kết luận sai lúc đầu rồi phải sửa thì để ở phụ lục cuối.

## Bối cảnh hệ thống

Chạy make reset rồi make baseline trên Python 3.12.14 trong .venv. Số liệu snapshot lại
ở reports/baseline_healthy_metrics.json.

```text
orders rows              : 600
contract failed checks   : 0
critical contract fails  : 0
row-count anomaly        : True (auto:mad, score=22.80, spike vs same_weekday(6))
freshness minutes        : 5.0
KB length anomaly        : False
KB contract failed       : 0 (action: allow)
error budget remaining   : 100.0% (burn_rate=0.0, 0 critical / 33 checks, 0 warning)
sample blast radius      : fct_daily_revenue, ceo_revenue_dashboard
```

pytest tests_public -q ra 91 passed. Dòng row-count anomaly trông như báo động nhưng
không phải, giải thích ở phụ lục A.

### Dataset nào critical

raw_orders (data/incoming/orders.csv) là nguồn duy nhất của revenue, hỏng ở đây là hỏng
cả nhánh tiền.

raw_customers được join vào fct_daily_revenue. Nếu có nhiều active row cùng customer_id
thì join fan-out và revenue phồng lên, trong khi pipeline vẫn báo SUCCESS.

kb_documents nuôi rag_index. Sai hoặc cũ ở đây thì Support Agent trả policy refund cũ cho
khách thật.

Hai nhánh này độc lập nhau và không dùng chung detector: nhánh tiền là orders đi tới revenue,
nhánh answer là kb đi tới support agent.

### Downstream consumer

Đọc từ data/baseline/lineage_graph.json:

```text
raw_orders    -> stg_orders    -+
                                 +-> fct_daily_revenue -> ceo_revenue_dashboard
raw_customers -> stg_customers -+

kb_documents -> kb_active_docs -> rag_index -> support_agent
```

Verify bằng code từ stg_orders ra ["fct_daily_revenue", "ceo_revenue_dashboard"].

Điểm mình thấy đáng nhớ nhất khi vẽ cái này ra: consumer cuối cùng không phải một cái bảng mà
là người, CEO nhìn dashboard và khách hàng chat với support agent. Nên "pipeline SUCCESS"
không nói lên được gì cả.

### Metric nào cho biết data không đáng tin

Contract cho failed_contract_checks và critical_contract_failures, bắt mấy thứ xác định
được trước: null, duplicate PK, ngoài range, sai kiểu.

freshness_minutes bắt trường hợp pipeline đứng im mà vẫn báo SUCCESS.

row_count_anomaly.score bắt volume drop, loại lỗi không có rule nào viết sẵn.

kb_text_length_signal bắt KB bị cắt cụt hoặc thay nội dung.

contract_slo.burn_rate với remaining_error_budget_fraction không bắt lỗi mới, chúng quyết
định lỗi nào đáng đánh thức người dậy.

Cách mình nhớ ba lớp này: contract bắt cái đã biết, anomaly bắt cái chưa biết, SLO quyết định
cái nào đáng page.

## Detection coverage cho 3 public fault

Chạy make reset rồi inject từng fault, đọc kết quả của make baseline, make gx và make dbt.

| Fault | Contract | GX | dbt | Anomaly | SLO | Lớp bắt được |
|---|---|---|---|---|---|---|
| healthy | 0 fail, allow | 21/21, allow | PASS=25 | spike vs baseline T7 (xem phụ lục A) | budget 100% | - |
| duplicate_pk | 1 critical, block | FAIL unique, block, exit 1 | skip downstream | - | burn 30.3, budget 0% | contract / GX |
| volume_drop | 0 fail | 21/21 pass | PASS | drop, score 7.55 | budget 100% | chỉ anomaly |
| stale_kb | KB freshness lag 190' > 60' | n/a (suite chỉ phủ orders) | n/a | KB length ok | 1 warning | chỉ KB contract |

Ba fault rơi vào ba lớp khác nhau và không lớp nào bắt được cả ba. Đó là lý do phải xếp tầng
chứ không thể chọn một công cụ tốt nhất rồi thôi.

volume_drop là ví dụ rõ nhất. Nó không vi phạm rule nào hết: không null, không duplicate,
không sai kiểu, không quá hạn. 150 dòng còn lại đều hợp lệ. Chỉ có detector thống kê mới thấy
là thiếu 450 dòng.

## Incident: stale_kb

Mình chọn fault này để làm đầy đủ vì trước khi sửa, nó lọt qua toàn bộ hệ thống. LAB_GUIDE có
ghi đây là TODO cố ý.

### Severity

P2. Không mất tiền, nhưng ảnh hưởng trực tiếp tới câu trả lời gửi tới khách.

### Summary

KB documents quá hạn 190 phút so với ngưỡng 60 phút trong hợp đồng. Support Agent phục vụ bằng
policy cũ. Nhánh revenue không bị ảnh hưởng.

### Detection

Signal: check="freshness" trên kb_documents.published_at, severity warning, action warn.
Ra từ make baseline sau khi mình nối KB contract vào run_baseline.py.

First observed: lúc chạy baseline, với lag_minutes=190.0 và latest=2026-08-30T00:35:45Z.

### Root cause

Feed KB dừng publish nhưng pipeline vẫn báo SUCCESS.

Chỗ này mình mất một lúc mới nhìn ra, vì lỗi không nằm ở chỗ thiếu detector.
contracts/kb_contract.yaml đã khai freshness.max_delay_minutes: 60 ngay từ đầu. Vấn đề là
run_baseline.py chỉ gọi validator lên orders, không ai gọi nó lên KB. Hợp đồng có mà không
được thực thi thì cũng như không có.

### Evidence

1. lag_minutes=190.0; max_delay_minutes=60; latest=2026-08-30T00:35:45.408246+00:00, ra từ
   contract validator chạy trên data/incoming/kb_documents.jsonl.
2. Khoảng thời gian published_at của toàn bộ batch nằm gọn trong 8 phút
   (00:27:45 tới 00:35:45), tức là cả lô cùng bị đẩy lùi chứ không phải vài document lẻ.
3. Trước khi sửa run_baseline.py, chạy baseline trên đúng state này cho ra 0 failed check.
   Fault có thật mà không lớp nào báo.

### Blast radius

Tính bằng blast_radius() chứ không đoán:

```text
kb_documents -> kb_active_docs -> rag_index -> support_agent

column:
kb_documents.content -> kb_active_docs.content -> rag_index.embedding -> support_agent.answer
```

Nhánh tiền (orders tới revenue tới CEO dashboard) không bị ảnh hưởng vì hai nhánh độc lập.

Đây là chỗ column lineage có ích thật sự: nó chỉ ra đúng cái gì sai thay vì để cả hệ thống
thành nghi phạm.

### Mitigation

Chặn không cho promote KB batch quá hạn sang kb_active_docs. Giữ index cũ vẫn hơn là phục vụ
policy sai.

Severity hiện tại là warning với action warn, nghĩa là không chặn gì cả. Nếu xác nhận được
Support Agent thật sự trả sai policy cho khách thì phải nâng lên critical và block.

### Recovery

```text
make reset && make baseline
KB contract failed : 0 (action: allow)
error budget remaining : 100.0%
```

### Verification

- [x] Contract healthy: orders 0 fail, KB 0 fail, action allow
- [x] dbt tests healthy: make dbt ra PASS=25 (18 data test + 2 unit test)
- [x] Anomaly về lại mức bình thường: không còn drop, chỉ còn spike do fixture
- [x] SLO healthy: budget 100%, burn 0.0
- [x] Downstream verify: make gx 21/21, pytest tests_public -q 91 passed

### Prevention / Action Items

| Action | Owner | Deadline | Why |
|---|---|---|---|
| Chạy contract validator lên mọi dataset, không chỉ orders | data-platform | ngay | Đây đúng là nguyên nhân gốc của stale_kb. Hợp đồng không được thực thi thì bằng không tồn tại |
| Nâng KB freshness lên critical/block nếu xác nhận ảnh hưởng khách | support-ai | 1 tuần | Warning không chặn gì. Policy sai đến tay khách là P1 chứ không phải P2 |
| Thêm freshness SLI riêng cho KB, không gộp vào SLO của orders | support-ai | 1 tuần | Hai nhánh độc lập, gộp budget làm mờ tín hiệu |
| Mở rộng GX suite sang kb_documents | data-platform | 2 tuần | Suite hiện chỉ phủ orders, nhánh RAG không có lớp GX nào |
| Sinh lineage graph từ manifest.json trong CI thay vì file JSON viết tay | data-platform | 2 tuần | extract_dbt_dataset_graph() đã viết xong rồi, file viết tay kiểu gì cũng drift |
| Làm data/baseline/orders.csv sinh theo weekday | lab-maintainer | - | Xoá gốc cái F-00 ở phụ lục A, thay vì phải giải thích lại mỗi lần chạy cuối tuần |

## SLO và error budget

Bài toán bắt buộc, SLO 99.5% với 2 bad trên 100 checks:

| | |
|---|---|
| allowed_bad_rate | 0.005 (0.5%) |
| actual_bad_rate | 0.02 (2%) |
| burn_rate | 4.0 |
| remaining_error_budget_fraction | 0.0 |
| breached | True |

Đọc ra là đang đốt budget nhanh gấp 4 lần tốc độ được cấp, tức budget của cả cửa sổ sẽ hết
trong 1/4 thời gian.

Về multi-window (multiwindow_burn), luật là page chỉ khi cả hai cửa sổ cùng vượt ngưỡng.
short=20 long=18 thì PAGE critical. short=20 long=0.5 thì không page vì spike đã tự hồi.
short=0.2 long=10 thì mở ticket, sự cố hết rồi, không đánh thức ai lúc 3h sáng.

## Phụ lục A: F-00, cái mình tưởng là false positive

Lúc chạy baseline đầu tiên ở REL-00, row_count_anomaly ra True với score=29.98 trên state
khoẻ mạnh, không có fault nào. Mình ghi ngay là false positive của detector.

Bằng chứng lúc đó:

```text
history row_count theo day_of_week (data/history/metrics_history.csv, 42 ngày):
  Mon-Fri (0-4): mean 593-617
  Sat (5)      : mean 250.8
  Sun (6)      : mean 259.7

data/incoming/orders.csv : 600 rows, cố định, không theo weekday
ngày chạy                : 2026-08-30 = Chủ nhật (weekday=6)
=> segment baseline mean=259.7, std=11.35, current=600 -> z = 29.98
```

Sau khi làm REL-05 và đọc kỹ scripts/generate_data.py với scripts/reset_lab.py thì mình
thấy kết luận ban đầu sai. History được sinh theo weekday, nhưng incoming chỉ được dịch lại
timestamp chứ số dòng luôn là 600. Nên 600 dòng vào Chủ nhật lệch thật so với baseline Chủ nhật
khoảng 255. Đó là một spike có thật so với segment đó. Lỗi nằm ở fixture, không nằm ở thuật toán.

Tiêu chí mình đặt ra ở REL-00 ("healthy phải ra is_anomaly=False bất kể ngày chạy") cũng sai
luôn. Mình kiểm tra thử: nếu ép detector dùng full history (mean 506, std 162) cho healthy ra
False, thì volume_drop với 150 dòng chỉ được z=2.2, dưới ngưỡng 3.0, không bắt được. Sửa theo
hướng đó là đổi một báo động giả lấy một lần bỏ sót thật.

Tiêu chí thay thế là phân biệt được hướng:

```text
healthy      -> spike vs same_weekday(6), score 22.80
volume_drop  -> drop  vs same_weekday(6), score  7.55
```

Cả hai đều đạt. Cách xoá tận gốc thì nằm ở bảng Action Items: sinh incoming batch theo weekday.

## Phụ lục B: vì sao not_null/unique không phải dbt unit test

| | data test | unit test |
|---|---|---|
| Kiểm tra cái gì | dữ liệu thật trong warehouse | logic SQL của model |
| Input | bảng thực tế, đổi mỗi lần build | fixture cố định do mình viết |
| Trả lời câu hỏi | "Dữ liệu hôm nay có đúng không?" | "Model này tính có đúng không?" |
| Khi fail nghĩa là | upstream gửi data xấu | code SQL viết sai |
| Chạy được khi chưa có data? | Không | Có |

not_null với unique là data test. dbt dịch chúng thành câu SELECT đếm row vi phạm trên bảng
thật. Chúng không biết gì về logic join trong fct_daily_revenue.sql. Đổi model đó thành
sum(amount_usd) * 2 thì cả hai vẫn PASS.

Bằng chứng mình dựng ở REL-03, thêm đúng 1 dòng active trùng customer_id vào dimension:

```text
mart   : revenue=19332.24  rows=294
source : revenue=18961.04  rows=290
inflate: +371.20 USD (+1.96%), +4 phantom rows

unique_fct_daily_revenue_order_date  -> PASS   <-- grain vẫn đúng
not_null_fct_daily_revenue_*         -> PASS
assert_revenue_reconciles_with_source-> FAIL   <-- chỉ test này bắt được
```

Grain vẫn đúng, không null, không duplicate PK, dbt báo SUCCESS, mà số tiền sai 1.96%. Đó là
lý do cần reconciliation test, và cũng là lý do cần unit test ở REL-04: unit test bắt được lỗi
join này trước khi có bất kỳ dữ liệu xấu nào chạy qua.
