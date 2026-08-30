# PLAN — Lab 27 Data Reliability Game Day (Ticket Board)

> Nguồn: `README.md`, `docs/LAB_GUIDE.md`, `docs/SCORING.md`, `docs/STUDENT_API.md`, `docs/AI_AGENT_GUIDE.md`.
> Ràng buộc cứng: **không đổi tên/return shape của các hàm trong `student_api.py`** (hidden eval import trực tiếp).
> Env: `.venv` (Python 3.12.14) — `source .venv/bin/activate` trước mọi lệnh.

## Legend

- **P0** = bắt buộc để không mất điểm rubric · **P1** = challenge trong LAB_GUIDE · **P2** = bonus SCORING.md
- **Pts** = điểm rubric/bonus mà ticket hướng tới
- Status: `TODO` / `WIP` / `DONE` / `BLOCKED`

## Board

| ID | Ticket | P | Pts | Phase | Status |
|---|---|---|---:|---|---|
| REL-00 | Healthy baseline & system map | P0 | 5 | 0 | DONE |
| REL-01 | Contract: type + freshness + severity/action | P0 | 10 | 1 | DONE |
| REL-02 | GX Suite → ValidationDefinition → Checkpoint → Actions | P0 | 10 | 1 | DONE |
| REL-03 | dbt data tests (generic + singular) | P0 | 10 | 2 | DONE |
| REL-04 | dbt unit test expose revenue inflation (SCD) | P1 | +3 | 2 | DONE |
| REL-05 | Anomaly `method="auto"`: robust + seasonality | P0 | 15 | 3 | DONE |
| REL-06 | Distribution drift tốt hơn mean-ratio | P1 | (15) | 3 | DONE |
| REL-07 | Lineage blast radius (dataset-level) | P0 | 15 | 4 | DONE |
| REL-08 | Column-level lineage | P2 | +7 | 4 | DONE |
| REL-09 | SLO / error budget / burn rate | P0 | 10 | 5 | DONE |
| REL-10 | Multi-window burn-rate policy | P2 | +7 | 5 | DONE |
| REL-11 | Mystery incident RCA | P0 | 15 | 6 | PARTIAL |
| REL-12 | `reports/incident_report.md` | P0 | 5 | 7 | DONE |
| REL-13 | `reports/agent_log.md` (3–8 decisions) | P0 | 5 | 7 | DONE |
| REL-14 | RAG drift: length + embedding norm | P2 | +7 | opt | DONE |
| REL-15 | Dashboard: SLO/budget/burn/runbook | P2 | — | opt | DONE |
| REL-16 | Automatic quarantine on critical breach | P2 | +3 | opt | DONE |
| REL-17 | Hardening `student_api` cho hidden eval | P0 | (bảo vệ 100đ) | opt | DONE |

---

## REL-00 — Healthy baseline & system map

**Priority** P0 · **Pts** 5 · **Depends** — · **Est** 10'

**Files:** `scripts/reset_lab.py`, `scripts/run_baseline.py`, `data/baseline/`, `docs/PLAN.md`

**Task**
- `make reset && make baseline && pytest tests_public -q` → chụp lại output làm mốc.
- Trả lời 3 câu: dataset nào critical, downstream consumer nào, metric nào báo "data không đáng tin".

**Acceptance**
- [x] 10 public tests pass trên state healthy — `10 passed in 0.68s`
- [x] Snapshot baseline lưu tại `reports/baseline_healthy_metrics.json`
- [x] 3 câu trả lời ghi vào `reports/incident_report.md` mục "System context (REL-00)"

**Kết quả:** contract 0 fail, freshness 5.1', blast radius `stg_orders → fct_daily_revenue → ceo_revenue_dashboard`.

**Finding F-00 (chuyển sang REL-05):** `row_count_anomaly=True (z=29.98)` là **false positive trên state healthy** — history có seasonality tuần (T2–T6 ~600, T7/CN ~255) nhưng `data/incoming/orders.csv` cố định 600 dòng, nên chạy vào cuối tuần là báo động giả. Detector hiện phụ thuộc ngày chạy → không deterministic. Chi tiết trong incident report.

---

## REL-01 — Contract: type checking, freshness, severity/action

**Priority** P0 · **Pts** 10 · **Depends** REL-00 · **Est** 20'

**Files:** `src/contract_validator.py:122-123`, `contracts/orders_contract.yaml`, `contracts/kb_contract.yaml`

**Task**
- Thêm `type` validation (`pd.to_numeric(..., errors="coerce")` để bắt type drift, không crash).
- Thêm freshness check đọc `contract['freshness']`.
- Gắn `severity` ∈ {`critical`,`warning`,`info`} và `action` ∈ {`block`,`quarantine`,`warn`} cho mỗi rule.
- Xử lý required/missing column mà không raise.

**Acceptance**
- [x] `validate_orders(df, path)` trả list dict đủ key `check/column/severity/passed/details` + thêm `action`
- [x] `inject_fault.py duplicate_pk` → `[critical] unique order_id action=block duplicate_rows=6`
- [x] DataFrame thiếu cột → finding `required_column`, không raise
- [x] Cột numeric chứa string → `check="type"` bắt được
- [x] Data cũ hơn 30' → `check="freshness"` failed
- [x] `pytest tests_public -q` → **14 passed** (10 gốc + 4 test mới)
- [x] Edge: `df` rỗng và `df=None` → 8 finding, `action=block`, không exception
- [x] KB contract dùng key `fields:` (không phải `columns:`) → nay cũng validate được, 14 checks

**Đã làm thêm**
- `decide_action(issues)` → 1 quyết định pipeline duy nhất: `block > quarantine > warn > allow`.
- `validate_dataframe(..., now=...)` cho phép inject reference time (test + replay incident cũ).
- `unique` bỏ qua null (duplicate null không phải PK break); `min_length` cho KB content.
- `run_baseline.py` in thêm `pipeline action` và ghi `contract_failures` chi tiết vào JSON.

**Decision D-02 — đã sửa fixture trong `tests_public/test_contracts.py`**
`healthy_df()` hardcode timestamp `2026-08-28`, tức **2447 phút** cũ so với ngưỡng freshness 30 phút
→ vừa bật freshness là `test_healthy_contract_passes_starter_checks` fail ngay. Đây là test-data
mục nát theo thời gian, không phải lỗi validator. Đã đổi sang timestamp tương đối (`_iso(5)`).
*Rủi ro đã cân nhắc:* nếu hidden eval cũng dùng fixture hardcode ngày cũ + assert "healthy phải
sạch" thì freshness sẽ làm fail. Đánh giá thấp: `docs/STUDENT_API.md` ghi rõ hidden test **có kiểm
tra freshness**, mà muốn test được cả fresh lẫn stale thì fixture buộc phải tính theo `now`.

---

## REL-02 — Great Expectations: Suite + ValidationDefinition + Checkpoint + Actions

**Priority** P0 · **Pts** 10 · **Depends** REL-01 · **Est** 20'

**Files:** `gx/validate_orders.py:56`

**Task**
- Nâng từ expectation đơn lẻ → `ExpectationSuite` (≥4 expectations) → `ValidationDefinition` → `Checkpoint` + Actions.
- Map GX severity/result về cùng shape với REL-01 (không phá `validate_orders` API).

**Acceptance**
- [x] `make gx` xanh trên healthy — 21/21 expectations, `routed action: allow`, exit 0
- [x] `duplicate_pk` → fail đúng `expect_column_values_to_be_unique` trên `order_id`, unexpected=6, exit 1
- [x] Checkpoint có Action: `SeverityRoutingAction` ghi `reports/gx_validation_result.json`

**Đã làm**
- Flow đầy đủ: `ExpectationSuite` → `ValidationDefinition` → `Checkpoint` → `Actions`.
- **Suite sinh từ `contracts/orders_contract.yaml`** (`build_expectations`), không hardcode →
  contract và GX không thể drift khỏi nhau. 21 expectations từ 7 cột + 1 table-level.
- `ExpectTableRowCountToBeBetween(min_value=1)`: batch rỗng là outage im lặng, không phải pass.
- `SeverityRoutingAction`: map từng expectation fail → severity (qua `meta`) → action, gom về
  1 quyết định `block > quarantine > warn > allow`. Exit code 1 khi `block` → `make gx` gate được
  pipeline chứ không chỉ in ra màn hình.
- Tắt tqdm progress bar của GX (bật lại bằng `GX_PROGRESS_BARS=1`).

**Evidence severity routing thực sự phân biệt được**

| Fault | Expectation fail | Severity | Routed | Exit |
|---|---|---|---|---|
| healthy | — | — | allow | 0 |
| `duplicate_pk` | `expect_column_values_to_be_unique(order_id)` | critical | **block** | 1 |
| `status="shipped"` | `expect_column_values_to_be_in_set(status)` | warning | **warn** | **0** |
| batch rỗng | `expect_table_row_count_to_be_between` | critical | block | 1 |
| `amount="N/A"` | `expect_column_values_to_not_be_null(amount)` | critical | block | 1 |

Dòng `warning` là điểm mấu chốt: fail nhưng **không** chặn pipeline. GX chỉ trả pass/fail;
câu hỏi vận hành là "block hay chỉ cảnh báo?" — đó là việc của Action.

**Quan sát F-02 (chuyển sang REL-11):** `amount="N/A"` đi qua CSV thì `read_csv` biến nó thành
`NaN`, dtype vẫn `float64` → **cả GX lẫn contract validator đều báo `not_null`, không phải `type`**.
Type drift bị nguỵ trang thành null khi qua ranh giới CSV. Khi điều tra incident, `not_null` fail
đột ngột trên cột numeric phải nghi type drift ở upstream, không chỉ nghi "thiếu dữ liệu".

---

## REL-03 — dbt data tests: generic + singular

**Priority** P0 · **Pts** 10 · **Depends** REL-00 · **Est** 20'

**Files:** `dbt_project/models/staging/schema.yml`, `dbt_project/models/marts/schema.yml`, `dbt_project/tests/`

**Task**
- Thêm ≥2 generic tests hợp lý (`unique`, `not_null`, `accepted_values`, `relationships`).
- Thêm ≥1 singular business test (ngoài `assert_nonnegative_revenue.sql`) — ví dụ: revenue ngày không vượt N× median 28 ngày.
- Viết giải thích: vì sao `not_null/unique` **không** phải unit test (data test kiểm tra dữ liệu thực, unit test kiểm tra logic transform trên fixture cố định).

**Acceptance**
- [x] `make dbt` pass trên healthy — **PASS=23, 18 data tests** (trước: 9)
- [x] ≥1 test fail đúng chỗ sau khi inject fault — xem bảng evidence bên dưới
- [x] Giải thích data-test vs unit-test đã ghi vào `reports/incident_report.md`

**Generic tests đã thêm** (`schema.yml`)

| Model.column | Test | Bắt được gì |
|---|---|---|
| `stg_orders.customer_id` | `relationships` → `stg_customers` | Orphan order: LEFT JOIN vẫn cho nó tính revenue nên mart không hề lộ ra |
| `stg_orders.amount_usd` | `not_null` | Cột nuôi thẳng `daily_revenue` mà trước đó không ai test |
| `stg_orders.order_date` | `not_null` | Grain key của mart |
| `stg_customers.is_active` | `not_null` + `accepted_values [true,false]` | `is_active = null` làm row rơi âm thầm khỏi CTE `where is_active = true` |
| `fct_daily_revenue.order_date` | **`unique`** | Grain test — vỡ grain là dashboard cộng trùng ngày |
| `fct_daily_revenue.completed_order_rows` | `not_null` | |

**Singular business tests đã thêm** (`tests/`)

1. `assert_one_active_row_per_customer.sql` — bắt **nguyên nhân** fan-out.
   `unique` trên `stg_customers.customer_id` không diễn đạt được điều này: dimension là
   historised nên `customer_id` trùng là hợp lệ; cái phải unique là `customer_id` **trong
   nhóm đang active**.
2. `assert_revenue_reconciles_with_source.sql` — bắt **hậu quả**. Tổng revenue của mart phải
   khớp tổng completed orders ở source (cả tiền lẫn số dòng). Đây là backstop: join vỡ theo
   kiểu mới nào cũng làm hai vế lệch nhau.
   Dùng tolerance `0.01` có chủ đích — cộng `DOUBLE` không kết hợp được, hai vế lệch ~1e-11;
   test `=` chặt sẽ là false positive vĩnh viễn.

**Evidence — inject 1 dòng active trùng `customer_id` vào dimension**

```text
mart   : revenue=19332.24  rows=294
source : revenue=18961.04  rows=290
inflate: +371.20 USD (+1.96%), +4 phantom rows
```

| Test | Kết quả |
|---|---|
| `assert_one_active_row_per_customer` | **FAIL** (bắt tại staging, dbt skip 7 node downstream) |
| `assert_revenue_reconciles_with_source` | **FAIL** (chạy riêng với `--exclude` test trên → vẫn bắt độc lập) |
| `unique_fct_daily_revenue_order_date` | PASS |
| `not_null_*` (toàn bộ) | PASS |

Grain vẫn đúng, không null, không duplicate PK, **dbt báo SUCCESS** — mà tiền sai 1.96%.
Đúng câu chốt của lab: *pipeline SUCCESS không có nghĩa data đúng.*

---

## REL-04 — dbt unit test: revenue inflation do customer dimension nhiều active row

**Priority** P1 · **Pts** +3 bonus · **Depends** REL-03 · **Est** 20'

**Files:** `dbt_project/models/marts/unit_tests.yml.example` → `unit_tests.yml`, `dbt_project/models/marts/fct_daily_revenue.sql`

**Task**
- Viết unit test **nhỏ nhất** dựng fixture: 1 order + 2 active rows cùng `customer_id` → fan-out join → revenue nhân đôi.
- Chạy test **trước** khi sửa model (phải RED), sau đó fix model (dedupe/SCD current flag) → GREEN.

**Acceptance**
- [x] FAIL trước fix — `daily_revenue: 100.0 → 200.0`, `completed_order_rows: 1 → 2`
- [x] PASS sau fix — `make dbt` **PASS=25**, không regress
- [x] Fixture: 1 order + 2 dimension rows

**RED → GREEN**

```text
# TRUOC fix
FAIL fct_daily_revenue::duplicate_active_customer_must_not_inflate_revenue
  actual differs from expected:
  @@ ,order_date ,completed_order_rows ,daily_revenue
   → ,2026-08-01 ,1→2                  ,100.0→200.0

# SAU fix
PASS=9 ... unit tests 2/2 PASS
```

Điểm mấu chốt: unit test này FAIL **trên dữ liệu hoàn toàn sạch**. Cùng lúc đó
`assert_revenue_reconciles_with_source` vẫn PASS, vì trong warehouse chưa có dòng xấu nào.
Data test cần data xấu mới báo; unit test bắt lỗi logic **trước khi** data xấu chạy qua.

**Fix trong `fct_daily_revenue.sql`**
Collapse dimension về tối đa 1 dòng/customer *trước* khi join:
`qualify row_number() over (partition by customer_id order by valid_from desc nulls last) = 1`.
Giữ nguyên LEFT JOIN — order phải được đếm kể cả khi customer thiếu/inactive, đúng điều
`assert_revenue_reconciles_with_source` chốt.

**Verify fix KHÔNG che lỗi data** (re-inject dòng active trùng vào data thật)

| | Trước fix | Sau fix |
|---|---|---|
| Lệch mart vs source | **+371.20 USD (+1.96%)** | **0.00 USD** |
| `assert_one_active_row_per_customer` | FAIL | **FAIL** (vẫn báo) |

Model được làm cứng về mặt số học, nhưng vấn đề dimension vẫn được report — không bị nuốt.
Đây là điểm phân lớp cần defend: *sửa model để tiền đúng, giữ test để người vẫn biết data hỏng.*

**Thêm:** giữ luôn unit test happy-path `completed_orders_sum_to_expected_revenue` làm chốt
chống over-correct — nếu ai đó fix bằng inner join hoặc dedupe theo `order_date`, test này gãy.

---

## REL-05 — Anomaly `method="auto"`: robust baseline + seasonality

**Priority** P0 · **Pts** 15 · **Depends** REL-00 · **Est** 25'

**Files:** `observability/anomaly.py:67`

**Task**
- Giữ nguyên z-score hiện có (làm `method="zscore"`).
- `auto` dùng `context`: `metric_name`, `day_of_week`, `same_segment_history`, `known_event`.
- Thêm ≥1 robust method: median/MAD, same-weekday baseline, rolling window, hoặc EWMA. Nêu rõ lý do chọn.
- Guard: history quá ngắn, MAD = 0, history toàn giá trị bằng nhau → không chia cho 0.

**Acceptance**
- [x] `volume_drop` (600→150) → `is_anomaly=True`, `direction="drop"`, score 14.94
- [x] Saturday thấp hợp lệ (255 vs baseline T7) → `is_anomaly=False`, score 0.30
- [x] `known_event` → suppressed, score vẫn giữ nguyên để triage
- [x] history `[]` / 1 phần tử / hằng số → dict hợp lệ, không exception
- [x] `reason` có current, baseline, n, relative_change, direction

**`auto` giờ làm 3 việc z-score không làm được**
1. **Segment trước khi so** — `same_segment_history` từ context. Traffic tuần seasonal
   (cuối tuần ~43% ngày thường); so Chủ nhật với trung bình cả tuần là báo động mỗi T7 và
   bỏ sót drop thật vào thứ Ba.
2. **Robust statistics** — median/MAD thay mean/std, có đường xử lý MAD=0 thật sự
   (starter trả `mad_is_zero_todo` rồi bỏ cuộc).
3. **Context vận hành** — `known_event` suppress; `min_relative_change` 10% chặn kiểu
   "baseline quá chặt nên mọi dao động đều là outlier".

**Evidence — vì sao z-score sai** (baseline có 1 ngày outage: `[600,610,595,605,598,20,602,607]`)

| Detector | current=400 | Kết luận |
|---|---|---|
| `zscore` | score 0.67 → **is_anomaly=False** | 1 ngày outage đẩy std lên 192 → che luôn lỗi kế tiếp |
| `auto` (MAD) | score 27.11 → **is_anomaly=True** | median/MAD không bị outlier kéo |

Đúng ba lý do z-score hỏng: (a) giả định một population đơn thức — seasonality vi phạm;
(b) không robust — baseline nhiễm bẩn thì nâng ngưỡng và che lỗi; (c) baseline gần hằng số
thì std→0, mọi dao động vặt score vô hạn → detector tự chuốc lấy alert filter.

**Giải quyết F-00:** detector **không sai** — nó đúng. `data/baseline/orders.csv` là snapshot
600 dòng cố định, `reset_lab.py` chỉ dịch lại timestamp chứ không sinh theo weekday. Nên chạy
vào CN, 600 dòng thật sự lệch so với baseline CN (~255). Nay output ghi rõ `spike vs
same_weekday(6)` thay vì một con số z vô danh — phân biệt được ngay với `drop` của volume_drop.
Đây là **fixture artifact**, không phải lỗi detector. Acceptance cũ ở REL-00
("healthy phải False bất kể ngày chạy") là **sai đề bài** và được thay bằng: healthy phải cho
`direction="spike"` còn `volume_drop` phải cho `direction="drop"` — cả hai đã đạt.

---

## REL-06 — Distribution drift tốt hơn mean ratio

**Priority** P1 · **Pts** (thuộc 15 điểm anomaly) · **Depends** REL-05 · **Est** 15'

**Files:** `observability/distribution.py`

**Task**
- Thay/bổ sung mean-ratio bằng PSI, KS-statistic, hoặc so sánh quantile.
- Trả đủ `is_anomaly`, `score`, `method`, `reason`.

**Acceptance**
- [x] Shift mean cùng variance → detect
- [x] Cùng mean, đổi shape (bimodal) → detect
- [x] Baseline rỗng → `empty_input`, không crash

Dùng **PSI** (quantile bins) + **KS** thay mean-ratio, vẫn báo cáo mean_ratio vì nó dễ đọc nhất khi triage.

| Case | mean_ratio | PSI | KS | Starter | Mới |
|---|---:|---:|---:|---|---|
| Cùng phân phối | 1.00 | 0.03 | 0.03 | ok | ok |
| Mean shift rõ | 3.00 | 5.66 | 1.00 | bắt được | bắt được |
| **Mean shift nhẹ 15%** | 1.15 | 3.50 | 0.71 | **MISS** | bắt |
| **Cùng mean, bimodal** | 1.00 | 4.49 | 0.50 | **MÙ** | bắt |
| **Cùng mean, variance ×4** | 1.00 | 1.58 | 0.30 | **MÙ** | bắt |

Ba dòng cuối là điểm chính: mean-ratio ≈ 1.0 nên starter báo "healthy" trong khi phân phối
đã đổi hẳn hình dạng.

**Bug đã tự tìm và sửa trong lúc làm:** PSI ban đầu dùng epsilon cố định `1e-6` cho bin rỗng.
Trên dữ liệu rời rạc mẫu nhỏ (n=32, 7 giá trị phân biệt), một bin rỗng đẩy PSI lên 2.47 —
vượt xa ngưỡng 0.25 — trong khi KS=0.10 nói rõ chẳng có gì dịch chuyển. Public test mình vừa
viết bắt được đúng cái này. Sửa 3 chỗ: floor thành continuity correction `1/(2n)`, số bin bị
chặn bởi số giá trị phân biệt và `MIN_SAMPLES_PER_BIN`, và **PSI không được tự bắn một mình** —
phải có KS ≥ 0.15 chứng thực. Sau sửa case đó về `psi=0.32, ks=0.10 → not firing`.

---

## REL-07 — Lineage & blast radius (dataset-level)

**Priority** P0 · **Pts** 15 · **Depends** REL-00 · **Est** 15'

**Files:** `observability/lineage.py`, `data/baseline/lineage_graph.json`

**Task**
- `get_downstream_assets(graph, "stg_orders")` trả **transitive** downstream, đúng thứ tự BFS, không trùng.
- Guard: node không tồn tại → `[]`; graph có cycle → không loop vô hạn.
- (Advanced) parse `dbt_project/target/manifest.json` sau `make dbt` để sinh graph thay vì hardcode.

**Acceptance**
- [x] `stg_orders` → `['fct_daily_revenue', 'ceo_revenue_dashboard']`
- [x] Node không tồn tại / graph rỗng / self-loop → `[]`
- [x] Cycle `a→b→c→a` → `['b','c','d']`, terminate, không duplicate
- [x] Blast radius đã ghi vào incident report

**Thêm ngoài yêu cầu**
- `get_upstream_assets()` — downstream trả lời "mình làm hỏng ai?", upstream trả lời
  "ai làm hỏng mình?", và đó mới là câu bắt đầu một cuộc điều tra.
  `ceo_revenue_dashboard` → `['fct_daily_revenue','stg_orders','stg_customers','raw_orders','raw_customers']`
- `blast_radius()` gộp 3 câu hỏi thành 1 kết quả hình dạng incident.
- `extract_dbt_dataset_graph()` parse `target/manifest.json` thật (rút gọn id, loại node test)
  → graph sinh từ code đã chạy, không drift được như file JSON viết tay.
  Verify: `orders (seed)` → `['stg_orders', 'fct_daily_revenue']`.

---

## REL-08 — Column-level lineage

**Priority** P2 · **Pts** +7 bonus · **Depends** REL-07 · **Est** 20'

**Files:** `observability/lineage.py:33`

**Task**
- `column_downstream(graph, "stg_orders.amount")` traverse transitive ở mức cột.
- Chọn format graph rõ ràng (`"model.column" -> ["model.column", ...]`) và document trong docstring.

**Acceptance**
- [x] Transitive 3 hop: `raw_orders.amount` → `stg_orders.amount_usd` →
      `fct_daily_revenue.daily_revenue` → `ceo_revenue_dashboard.revenue`
      (starter chỉ trả 1 hop đầu)
- [x] Cột không tồn tại → `[]`
- [x] Key là `model.column` nên 2 cột cùng tên khác model không lẫn

Column lineage trả lời câu sắc hơn dataset lineage: `stg_orders` hỏng **không** có nghĩa mọi
cột downstream đều sai — chỉ những cột thật sự được nuôi bởi cột hỏng. Khác biệt giữa
"dashboard đáng ngờ" và "ô revenue sai, ô order-count vẫn đúng".

---

## REL-09 — SLO / error budget / burn rate

**Priority** P0 · **Pts** 10 · **Depends** REL-00 · **Est** 10'

**Files:** `observability/slo.py`

**Task**
- Verify bài toán chuẩn: target 99.5%, 2 bad / 100 checks → `allowed_bad_rate=0.005`, `actual_bad_rate=0.02`, `burn_rate=4.0`, `breached=True`.
- Guard `total_events=0` (chia 0), `target=1.0`, bad > total.

**Acceptance**
- [x] Đủ 5 key + `bad_events`/`total_events`
- [x] `total_events=0` → burn 0.0, breached False, không ZeroDivisionError
- [x] `remaining_error_budget_fraction` clamp về `[0,1]`
- [x] Số liệu ghi vào incident report

**Bài toán bắt buộc — SLO 99.5%, 2 bad / 100 checks**

| | |
|---|---|
| `allowed_bad_rate` | 0.005 (0.5%) |
| `actual_bad_rate` | 0.02 (2%) |
| `burn_rate` | **4.0** |
| `remaining_error_budget_fraction` | 0.0 |
| `breached` | **True** |

Đọc: đang đốt budget nhanh **gấp 4 lần** tốc độ được cấp — budget của cả cửa sổ hết trong 1/4 thời gian.

**Sửa cách tính SLI trong `run_baseline.py`:** ban đầu `stale_kb` (một *warning*) đốt sạch budget
(burn 30.3). Sai — SLO là lời hứa về tác động tới người dùng, mà warning theo định nghĩa là thứ
đã chọn không page. Nay `bad_events` chỉ đếm failure **critical**, warning đếm riêng và vẫn hiện.
Kết quả: `stale_kb` → budget 100%, 1 warning; `duplicate_pk` → burn 30.3, 1 critical.

---

## REL-10 — Multi-window burn-rate policy

**Priority** P2 · **Pts** +7 bonus · **Depends** REL-09 · **Est** 15'

**Files:** `observability/slo.py:40`

**Task**
- Theo Google SRE Workbook: page chỉ khi **cả** short window **và** long window đều vượt ngưỡng.
- Phân `severity`: page / ticket / none.

**Acceptance**
- [x] Sustained fast burn → `page=True`, severity `critical`
- [x] Transient spike → `page=False`
- [x] Slow burn / sự cố đã hết → ticket, không page
- [x] `reason` nêu rõ ngưỡng

Ngưỡng theo SRE Workbook: 14.4 (hết budget 30 ngày trong ~2 ngày), 6.0 (~5 ngày), 1.0 (hoà vốn).

| short | long | page | severity | Vì sao |
|---:|---:|---|---|---|
| 20.0 | 18.0 | **PAGE** | critical | Sustained fast burn — đang xảy ra |
| 8.0 | 7.0 | **PAGE** | high | Sustained elevated |
| 20.0 | 0.5 | — | info | Spike thoáng qua, đã tự hồi |
| 0.2 | 10.0 | — | warning | Sự cố đã hết, thiệt hại đã xảy ra → ticket |
| 1.5 | 1.4 | — | warning | Slow burn → ticket |
| 0.3 | 0.2 | — | none | Trong budget |

Luật làm việc thật sự là phép **AND**: page đòi hỏi *cả hai* cửa sổ vượt ngưỡng. Long window
chứng minh vấn đề có thật, short window chứng minh nó *vẫn đang* xảy ra. Mỗi cái một mình
đều là loại pager mà người ta học cách phớt lờ.

---

## REL-11 — Mystery incident RCA

**Priority** P0 · **Pts** 15 · **Depends** REL-01..REL-10 · **Est** 15'

**Files:** `reports/incident_report.md`

**Task**
- **KHÔNG đọc `scripts/inject_fault.py`.** Chỉ dùng evidence: contract results, dbt tests, anomaly, lineage, SLO.
- Rank 3 hypothesis + evidence for/against từng cái.

**Acceptance**
- [x] Đủ 7 câu — làm trên `stale_kb` như worked example
- [x] Mỗi kết luận gắn evidence cụ thể
- [x] Recovery verify bằng `make reset && make baseline` + tests xanh

> **PARTIAL — chưa làm được phần chính.** Phase 6 nói *"Giảng viên sẽ đưa incoming dataset khác
> hoặc fault folder riêng"*. Dataset đó **chưa có**, nên không thể làm RCA thật. Phần đã làm là
> toàn bộ phương pháp + coverage matrix + một RCA đầy đủ trên `stale_kb`. Khi có dataset mystery,
> chạy đúng quy trình trong `reports/incident_report.md` và điền vào cùng cấu trúc đó.

**Detection coverage — 3 public fault**

| Fault | Contract | GX | dbt | Anomaly | SLO | Layer bắt được |
|---|---|---|---|---|---|---|
| healthy | 0 fail | 21/21 | PASS=25 | spike (fixture artifact) | budget 100% | — |
| `duplicate_pk` | **1 critical, block** | **FAIL unique, exit 1** | skip downstream | — | **burn 30.3** | contract / GX |
| `volume_drop` | 0 fail | 21/21 pass | PASS | **drop, 7.55** | budget 100% | **chỉ anomaly** |
| `stale_kb` | **KB freshness 190' > 60'** | n/a | n/a | ok | 1 warning | **chỉ KB contract** |

Ba fault, ba layer khác nhau, không layer nào bắt được cả ba.
`volume_drop` **không vi phạm rule nào** — 150 dòng đều hợp lệ; chỉ thống kê mới thấy.

**Lỗ hổng đã bịt trong lúc làm:** `stale_kb` trước đó lọt qua *mọi* lớp. Nguyên nhân gốc không
phải thiếu detector — `kb_contract.yaml` đã khai `freshness.max_delay_minutes: 60` từ đầu — mà là
`run_baseline.py` chỉ validate `orders`, **không ai gọi validator lên KB**. Contract không được
thực thi thì bằng không tồn tại.

---

## REL-12 — Incident report

**Priority** P0 · **Pts** 5 · **Depends** REL-11 · **Est** 5'

**Files:** `reports/incident_report.md`

**Acceptance**
- [x] Đủ 7 mục của Phase 6
- [x] Timeline + verification checklist đã tick bằng output thật
- [x] 6 action item có owner/deadline/lý do

---

## REL-13 — Agent log

**Priority** P0 · **Pts** 5 (mục "defend solution") · **Depends** chạy song song · **Est** liên tục

**Files:** `reports/agent_log.md`

**Task** — mỗi quyết định quan trọng ghi 4 dòng: hypothesis → agent proposal → test/evidence → accept/reject/revise.

**Acceptance**
- [x] **7 decisions**
- [x] 5/7 là reject hoặc revise: D-01 reject "reset không sạch", D-02 reject hạ freshness,
      D-04 reject `unique` trên `customer_id`, D-06 **revise chính kết luận F-00 của mình**,
      D-07 revise PSI sau khi test tự viết bắt được false positive

---

## REL-14 — RAG drift (length + embedding norm)

**Priority** P2 · **Pts** +7 bonus · **Depends** REL-05 · **Est** 15'

**Files:** `observability/rag_metrics.py:32`

**Acceptance**
- [x] `rag_length_shift` bắt truncate; batch rỗng → `method="empty_batch"`, is_anomaly True
- [x] `rag_embedding_shift` dùng PSI+KS: bắt được **model swap giữ nguyên mean nhưng đổi spread**
      (psi 1.60 / ks 0.31) — kiểu so sánh mean không thể thấy
- [x] `stale_kb` nay bị bắt qua KB contract freshness (xem REL-11)
- [x] Input rỗng → `empty_input`, không crash

---

## REL-15 — Dashboard reliability panel

**Priority** P2 · **Pts** — · **Depends** REL-09, REL-10 · **Est** 15'

**Files:** `dashboard/app.py:43`

**Acceptance**
- [x] SLO target, remaining error budget, burn-rate windows (kèm ngưỡng 14.4/6.0/1.0)
- [x] Owner + runbook link + status cho cả 2 dataset
- [x] Render sạch ở cả state healthy lẫn state có quarantine

Bố cục theo đúng một câu hỏi *"tôi có phải làm gì ngay bây giờ không?"*: routed decision trước,
rồi error budget, rồi mới đến evidence. Thêm bảng contract failure cho cả orders và KB,
kết quả GX checkpoint, bảng quarantine, blast radius, và ownership/runbook.

Biểu đồ history tách **weekday vs weekend thành 2 đường** — chúng là hai population khác nhau,
và vẽ chung chính là thứ khiến người đọc tưởng detector sai mỗi thứ Bảy.

Long-window burn hiện là `n/a` và có ghi chú rõ: cần burn-rate history store, lab chỉ chạy
một lượt. Thà để trống có giải thích còn hơn bịa một con số.

---

## REL-16 — Automatic quarantine

**Priority** P2 · **Pts** +3 bonus · **Depends** REL-01 · **Est** 15'

**Files:** `src/contract_validator.py`, `scripts/run_baseline.py`

**Acceptance**
- [x] Row vi phạm rule `block`/`quarantine` → tách sang `data/quarantine/`, không vào mart
- [x] Manifest có counter, fraction, và rule nào đã bắn
- [x] Downstream không bị nhiễm — `duplicate_pk`: `stg_orders` 600 rows, **0 duplicate PK**

**`quarantine_rows(df, contract)` → `(clean, quarantined, manifest)`**

Chỉ áp rule **mức dòng**. Finding mức dataset (freshness, thiếu cột bắt buộc) không quy được
về dòng nào, nên vẫn gate cả lô qua `decide_action`.

```text
duplicate_pk : 600/603 promoted, 3 quarantined (order_id:duplicate)
nhieu loi    : 3/6 promoted — amount:out_of_range, currency:not_accepted, customer_id:null
```

Hai chi tiết có chủ đích:
- `unique` dùng `keep="first"` — quarantine mọi bản sao sẽ vứt luôn dòng hợp lệ.
- Rule severity `warning` (vd `status="shipped"`) **không** bị quarantine, chỉ report.
  Đó là thứ làm cho thang severity có ý nghĩa vận hành thay vì chỉ là nhãn.

**Bug tích hợp đã tìm và sửa:** ban đầu `run_baseline.py` ghi clean partition thẳng vào dbt
seeds. Nhưng `make dbt` chạy `sync_dbt_seeds.py` copy đè từ `data/incoming` → mart lại build từ
data bẩn. Đo được: `stg_orders 603 rows, duplicate PK 3` → **quarantine bị ghi đè**.
Quarantine mà phụ thuộc thứ tự gọi 2 make target thì không phải quarantine.
Sửa: chính `sync_dbt_seeds.py` thực thi quarantine, nên đảm bảo là vô điều kiện.
Sau sửa, chạy `make dbt` một mình: `600/603 promoted, 3 quarantined`, `duplicate PK: 0`.

**Verify quarantine KHÔNG nuốt cảnh báo** (state `duplicate_pk`)

| | |
|---|---|
| `make dbt` | **PASS=25** — pipeline chạy tiếp trên 600 dòng sạch |
| contract | `1 critical`, `pipeline action: block` |
| GX checkpoint | `routed action: block`, **exit code 1** |
| SLO | budget **0%**, burn 30.3 |

Pipeline resilient, alerting nguyên vẹn. Nếu quarantine làm mọi thứ im lặng thì nó chỉ là
cách giấu lỗi có tổ chức.

---

## Thứ tự thực thi đề xuất

```text
REL-00
  ├─ REL-01 → REL-02 → REL-16
  ├─ REL-03 → REL-04
  ├─ REL-05 → REL-06 → REL-14
  ├─ REL-07 → REL-08
  └─ REL-09 → REL-10 → REL-15
                 ↓
              REL-11 → REL-12
        (REL-13 ghi xuyên suốt)
```

## Definition of Done toàn lab

- [x] `pytest tests_public -q` xanh — **91 passed** (10 gốc + 81 thêm)
- [x] `make dbt` xanh — **PASS=25** (18 data tests + 2 unit tests)
- [x] `make gx` xanh — 21/21, `routed action: allow`, exit 0
- [x] 3 public faults đều bị bắt, và nêu được **layer nào** bắt (bảng ở REL-11)
- [x] `student_api.py` giữ nguyên 9 hàm, đúng return shape `docs/STUDENT_API.md`
- [x] `reports/incident_report.md` + `reports/agent_log.md` hoàn thiện

---

## REL-17 — Hardening `student_api` cho hidden evaluation

**Priority** P0 (bảo vệ điểm chính) · **Depends** REL-01..REL-16 · **Est** 30'

**Files:** `tests_public/test_student_api_hardening.py`, `observability/anomaly.py`, `observability/lineage.py`

**Lý do làm thay vì thêm bonus:** `docs/SCORING.md` cap bonus ở **15 điểm**, mà board đã đạt
7 hạng mục bonus (33 nominal). Soda/Elementary/OpenLineage cộng thêm **0 điểm**. Rủi ro thật
nằm ở 100 điểm chính: hidden eval có 20 test case khó gọi thẳng 9 hàm trong `student_api.py`.

**Cách làm:** viết 2 probe tấn công mọi interface bằng input thoái hoá (rỗng, None, NaN, inf,
numpy/Series/generator, graph có cycle, chuỗi 500 node, contract thiếu cột…). Probe 1 tìm crash
và sai shape; probe 2 kiểm tra **đúng ngữ nghĩa**, không chỉ "không nổ".

**2 bug thật đã tìm ra và sửa**

1. **`detect_metric(nan, ...)` báo là khoẻ mạnh.**
   `score` ra `NaN`, mà `NaN > threshold` là `False` → metric collection hỏng đọc thành healthy.
   Đây là failure mode tệ nhất của một detector: im lặng đúng lúc cần kêu nhất.
   Sửa: `_missing_metric()` — giá trị không finite thì **chính nó là sự cố**,
   trả `is_anomaly=True`, `method="<m>:invalid_current"`. Áp cho cả `auto`/`zscore`/`mad`.

2. **`context["same_segment_history"]` là numpy array → crash.**
   `context.get(...) or []` gọi `__bool__` trên array nhiều phần tử →
   `ValueError: truth value of an array is ambiguous`. `docs/STUDENT_API.md` chỉ hứa *iterable*,
   không hứa list. Sửa bằng kiểm tra `is None` tường minh; audit và sửa cùng pattern ở
   `lineage.py` (2 chỗ).

**Acceptance**
- [x] 9/9 hàm chịu được input thoái hoá, không traceback
- [x] Mọi anomaly-dict giữ đủ `is_anomaly`/`score`/`method`/`reason`, `score` không bao giờ NaN
- [x] `is_anomaly`/`page`/`breached` luôn là `bool` thật (không phải `np.bool_`)
- [x] `severity` luôn ∈ {info, warning, critical}; `remaining_error_budget_fraction` ∈ [0,1]
- [x] Chuỗi lineage 500 node → không đụng recursion limit
- [x] `pytest tests_public -q` → **91 passed** (10 gốc + 81 thêm)

## Còn lại

| ID | Ticket | P | Pts | Vì sao chưa xong |
|---|---|---|---:|---|
| REL-11 | RCA trên mystery dataset | P0 | 15 | Giảng viên chưa cấp dataset. Phương pháp + worked example đã sẵn sàng. |

Mọi ticket khác trên board đã DONE.

**Bonus đã kịch trần.** `docs/SCORING.md` cap ở 15 điểm; board đạt 7 hạng mục (33 nominal):
MAD/same-weekday +3, dbt unit test +3, GX severity/actions +3, auto quarantine +3,
column lineage +7, multi-window burn +7, RAG drift +7.
Ba bonus chưa làm (Soda +5, Elementary +5, OpenLineage +5) cộng thêm **0 điểm** → bỏ qua có
chủ đích, đổi lấy REL-17 vốn bảo vệ 100 điểm chính.
