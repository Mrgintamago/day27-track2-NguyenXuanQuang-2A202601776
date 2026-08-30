# AI Agent Decision Log

Ghi lại những quyết định mình thấy đáng ghi trong lúc làm lab, không chép lại cả hội thoại.
Đa số là những lần mình không đồng ý với đề xuất của agent, hoặc tự phát hiện mình sai.

## Decision 1. Baseline báo anomaly: fault thật hay báo động giả?

- Hypothesis: make baseline trên state healthy báo row-count anomaly = True (z=29.98).
  Giả thuyết A là make reset không sạch, giả thuyết B là detector báo động giả.
- Prompt: "Chạy REL-00 baseline, giải thích vì sao anomaly=True trên state healthy."
- Agent proposal: loại giả thuyết A trước bằng contract (0 failed check, 0 critical), rồi so
  data/incoming/orders.csv với data/history/metrics_history.csv nhóm theo day_of_week.
- Evidence: contract 0 failed / 0 critical, freshness 5.1' nên data không hỏng.
  pytest tests_public -q ra 10 passed. Groupby day_of_week cho T2-T6 mean 593-617,
  T7 mean 250.8, CN mean 259.7. Incoming cố định 600 rows, ngày chạy 2026-08-30 là Chủ nhật,
  nên baseline segment 259.7 và z=29.98.
- Kết luận: reject A, accept B. Coi đây là false positive do seasonality.
- Why: nếu tin ngay cái alert này thì sẽ đi điều tra một incident không tồn tại. Quan trọng hơn
  là kết quả detector phụ thuộc ngày chạy, T2-T6 thì xanh còn T7/CN thì đỏ, không dùng làm mốc
  so sánh cho các phase sau được. Chốt làm acceptance criteria cho REL-05: sau khi auto
  context-aware thì healthy phải ra is_anomaly=False bất kể ngày chạy, mà vẫn bắt được
  volume_drop.

Bổ sung sau: kết luận này của mình sai, xem Decision 6.

## Decision 2. Bật freshness làm vỡ public test: sửa validator hay sửa fixture?

- Hypothesis: LAB_GUIDE bắt buộc thêm freshness validation. Vừa implement xong thì
  test_healthy_contract_passes_starter_checks fail.
- Prompt: "Implement type + freshness + severity/action cho contract validator, giữ nguyên
  interface validate_orders."
- Agent proposal: hai hướng. A là hạ freshness xuống không emit failure để test xanh. B là coi
  fixture là test-data hỏng và sửa sang timestamp tương đối.
- Evidence: healthy_df() hardcode updated_at = 2026-08-28T10:05:00Z trong khi contract cho
  phép 30 phút. Đo lag thực tế lúc chạy ra 2447 phút, tức là vi phạm thật và validator báo đúng.
  docs/STUDENT_API.md nói rõ hidden test có kiểm tra freshness, mà muốn test được cả fresh lẫn
  stale thì fixture buộc phải tính theo now, không hardcode ngày cố định được.
- Kết luận: reject A, accept B. Sửa fixture sang _iso(5) / _iso(4).
- Why: chọn A là tự làm mù detector chỉ để test xanh, đúng cái kiểu "test xanh, hệ thống hỏng"
  mà lab này đang dạy. Fixture hardcode ngày thì kiểu gì cũng mục theo thời gian; sửa sang tương
  đối thì "healthy" còn nghĩa là "fresh" bất kể chạy ngày nào. Mình có cân nhắc rủi ro hidden
  eval cũng dùng fixture cũ, nhưng đánh giá thấp vì lý do ở trên. Kết quả 14/14 pass, và
  inject_fault duplicate_pk cho [critical] unique order_id action=block.

## Decision 3. GX suite: hardcode expectation hay sinh từ contract YAML?

- Hypothesis: starter hardcode 4 expectation rời rạc. Nếu viết tay cả suite thì
  contracts/orders_contract.yaml và GX suite sẽ drift khỏi nhau sau vài lần sửa.
- Prompt: "Nâng gx/validate_orders.py thành Suite, ValidationDefinition, Checkpoint, Actions,
  có severity."
- Agent proposal: build_expectations(contract) compile YAML thành GX expectations, severity đi
  kèm qua meta. Thêm SeverityRoutingAction map fail sang action sang exit code.
- Evidence: healthy 21/21 pass, routed=allow, exit 0. duplicate_pk fail
  expect_column_values_to_be_unique(order_id) với unexpected=6, routed=block, exit 1.
  status="shipped" (severity warning) fail nhưng routed=warn và exit 0, tức không chặn pipeline.
  Batch rỗng thì expect_table_row_count_to_be_between fail, routed=block.
- Kết luận: accept, có revise. Ban đầu định dùng kwarg severity của GX nhưng nó không sống sót
  vào expectation_config.meta khi đọc lại result, nên phải carry qua meta.
- Why: một nguồn sự thật duy nhất. Thêm cột vào contract YAML là GX tự có expectation mới, không
  ai phải nhớ sửa hai chỗ. Còn exit code theo severity mới làm make gx thành cái gate thật;
  nếu mọi fail đều exit 1 thì đội sẽ tắt nó sau lần false alarm thứ ba.

## Decision 4. Test fan-out: bắt nguyên nhân hay bắt hậu quả?

- Hypothesis: fct_daily_revenue join vào active_customers. Nếu dimension có 2 dòng active cùng
  customer_id thì revenue phồng lên mà không có lỗi SQL nào.
- Prompt: "Thêm ít nhất 2 generic data test hợp lý và 1 singular business test cho dbt project."
- Agent proposal: ban đầu chỉ đề xuất unique trên stg_customers.customer_id.
- Evidence: kiểm tra data thật thấy 81 dòng customer trên 75 distinct customer_id, nghĩa là
  dimension historised và customer_id trùng là hợp lệ. Test unique sẽ fail ngay trên dữ liệu
  khoẻ. Inject 1 dòng active trùng thì mart ra 19332.24 so với source 18961.04, tức +371.20 USD
  (+1.96%) và +4 dòng. Trong khi đó unique_fct_daily_revenue_order_date PASS, not_null_* PASS,
  dbt báo SUCCESS.
- Kết luận: reject đề xuất unique trên customer_id. Revise thành 2 test:
  assert_one_active_row_per_customer (unique trong nhóm is_active = true) bắt nguyên nhân,
  và assert_revenue_reconciles_with_source bắt hậu quả.
- Why: một test chạy đúng trên fixture nhưng false-positive trên dữ liệu thật thì sẽ bị disable
  ngay tuần đầu. Và cần cả hai lớp: test nguyên nhân chỉ bắt đúng kiểu vỡ đã biết, còn test
  reconciliation bắt mọi kiểu vỡ làm lệch tổng tiền, kể cả kiểu chưa ai nghĩ ra. Cũng phải thêm
  tolerance 0.01 vì tổng DOUBLE lệch khoảng 1e-11, test = chặt sẽ báo động giả mãi mãi.

## Decision 5. Fix fan-out: bỏ join hay dedupe dimension?

- Hypothesis: unit test đã chứng minh 2 dòng active cùng customer_id làm revenue nhân đôi.
  Cần sửa fct_daily_revenue.sql, nhưng sửa kiểu nào.
- Prompt: "Viết unit test nhỏ nhất expose revenue inflation, chạy RED trước, rồi fix model."
- Agent proposal: hai hướng. A là bỏ hẳn join vì model không dùng cột nào của customer, join chỉ
  toàn gây hại. B là dedupe dimension về 1 dòng mỗi customer rồi giữ LEFT JOIN.
- Evidence: RED cho daily_revenue 100.0 -> 200.0 và completed_order_rows 1 -> 2 trên fixture
  sạch. GREEN sau fix B: unit test 2/2 PASS, make dbt PASS=25, không regress. Re-inject dòng
  active trùng vào data thật thì lệch mart so với source còn 0.00 USD, trước fix là +371.20 USD.
  Và assert_one_active_row_per_customer vẫn FAIL, tức lỗi data vẫn được báo.
- Kết luận: chọn B, reject A.
- Why: A đúng về kết quả hôm nay nhưng xoá mất ý định của model. Người sau muốn thêm country
  hay tier vào mart sẽ join lại và tái tạo đúng con bug này. B giữ chỗ join tồn tại nhưng an
  toàn sẵn. Quan trọng hơn là mình đã kiểm tra fix không nuốt lỗi data: model cho ra số đúng,
  đồng thời test nguyên nhân vẫn kêu. Nếu fix mà làm test im luôn thì là đang đổi một bug hiện
  lấy một bug ẩn. Mình giữ thêm unit test happy-path làm chốt chống over-correct, fix bằng inner
  join hoặc dedupe theo order_date sẽ làm nó gãy.

## Decision 6. F-00 có thật sự là false positive không?

- Hypothesis: ở REL-00 mình kết luận row_count_anomaly=True trên healthy là false positive và
  đặt acceptance "sau REL-05 phải is_anomaly=False bất kể ngày chạy".
- Prompt: "Làm auto context-aware, robust, xử lý seasonality."
- Agent proposal: segment theo weekday, dùng median/MAD, suppress known_event.
- Evidence: đọc scripts/generate_data.py thấy history sinh theo weekday
  (weekday>=5 -> base*0.43). Đọc scripts/reset_lab.py thấy incoming chỉ được dịch lại
  timestamp, số dòng luôn là 600. Nghĩa là 600 dòng vào Chủ nhật lệch thật so với baseline CN
  khoảng 255.
- Kết luận: revise chính kết luận cũ của mình. Detector không sai, cái sai là acceptance mình
  đặt ở REL-00. Thay bằng: healthy phải ra direction="spike" và volume_drop phải ra
  direction="drop". Cả hai đều đạt, 22.80 so với 7.55.
- Why: nếu ép detector trả False cho healthy thì phải làm nó bỏ qua segment weekday, mà chính
  segment đó là thứ giúp bắt volume_drop sớm. Mình kiểm chứng thử: dùng full history với
  mean 506 và std 162 thì volume_drop 150 dòng chỉ được z=2.2, dưới ngưỡng 3.0, không bắt
  được. Tức là "sửa" false positive theo hướng đó sẽ làm mất một cái thật. Cách đúng là sửa
  fixture, mình đã ghi vào Action Items.

## Decision 7. PSI báo động giả trên dữ liệu rời rạc

- Hypothesis: thay mean-ratio bằng PSI và KS để bắt được shape change.
- Prompt: "Distribution drift tốt hơn mean ratio."
- Agent proposal: PSI với quantile bins, epsilon 1e-6 cho bin rỗng, đúng cách phổ biến hay
  thấy trên mạng.
- Evidence: public test mình vừa viết (test_same_distribution_is_not_flagged) fail ngay. Hai
  mẫu gần như giống hệt nhau (n=32, 7 giá trị phân biệt) cho PSI=2.47 trong khi ngưỡng là 0.25,
  còn KS=0.10 nói rõ chẳng có gì dịch chuyển. Nguyên nhân là bin rỗng một bên cộng epsilon 1e-6
  làm log(1e-6/0.1) nổ tung.
- Kết luận: revise 3 chỗ. Floor thành continuity correction 1/(2n); số bin bị chặn bởi số giá
  trị phân biệt và MIN_SAMPLES_PER_BIN; và PSI không được tự bắn một mình, phải có KS >= 0.15
  chứng thực. Sau sửa thì case đó ra psi=0.32, ks=0.10 -> not firing.
- Why: một detector chống false positive mà bản thân nó lại false-positive thì vô nghĩa. Bài học
  ở đây đúng bằng bài học của cả lab: PSI là công thức chuẩn, chép đúng công thức vẫn sai nếu
  không kiểm tra trên dạng dữ liệu thật. Test bắt được nó là test mình tự viết, nên mình nghĩ
  phải viết test cho cả trường hợp "không được báo động", chứ không chỉ trường hợp "phải báo động".

## Decision 8. Quarantine bị vô hiệu hoá bởi thứ tự chạy make target

- Hypothesis: quarantine đã chạy đúng (600/603 promoted) nên coi như downstream an toàn.
- Prompt: "Automatic quarantine on critical breach."
- Agent proposal: run_baseline.py ghi clean partition thẳng vào dbt_project/seeds/.
- Evidence: chạy make baseline (quarantine bắt, 3 dòng bị park) rồi make dbt thì ra
  stg_orders rows: 603, duplicate PK: 3, tức quarantine bị ghi đè. Nguyên nhân là make dbt
  gọi sync_dbt_seeds.py, script này copy thẳng từ data/incoming đè lên clean partition.
  Trước đó mình test bằng dbt build trực tiếp chứ không qua make nên không thấy.
- Kết luận: revise. Chuyển việc thực thi quarantine vào chính sync_dbt_seeds.py. Sau sửa, chạy
  make dbt một mình cho 600/603 promoted và duplicate PK: 0.
- Why: quarantine mà phụ thuộc vào thứ tự chạy hai make target thì không phải quarantine, nó chỉ
  đúng trong kịch bản mình tự test. Đặt guarantee ở điểm cuối cùng trước khi data vào warehouse
  thì nó thành vô điều kiện. Bài học riêng cho mình: test bằng đường tắt (dbt build trực tiếp)
  thay vì đường thật (make dbt) đã giấu con bug này khỏi mình một lượt. Mình kiểm chứng thêm
  là quarantine không được làm im cảnh báo, và xác nhận contract vẫn báo block, GX vẫn exit 1,
  SLO vẫn burn 30.3, chỉ riêng dbt là chạy tiếp được.

## Decision 9. Làm nốt bonus hay hardening cho hidden eval?

- Hypothesis: còn 3 bonus chưa làm (Soda +5, Elementary +5, OpenLineage +5), tổng 15 điểm.
- Prompt: "làm p2".
- Agent proposal: làm nốt 3 bonus đó.
- Evidence: docs/SCORING.md dòng 3 ghi "100 điểm + tối đa 15 bonus". Mình đã đạt 7 hạng mục
  bonus có evidence, cộng lại 3+3+3+3+7+7+7 = 33 nominal, vượt cap từ lâu. Nên 3 bonus còn lại
  cộng đúng 0 điểm. Trong khi đó docs/STUDENT_API.md nói hidden eval có 20 test case khó gọi
  thẳng 9 hàm.
- Kết luận: reject. Đổi sang hardening student_api (REL-17).
- Why: làm thêm bonus là công việc trống. Rủi ro thật nằm ở 100 điểm chính. Quyết định này được
  chứng minh đúng gần như ngay lập tức vì probe tìm ra 2 bug thật. Một là detect_metric(nan)
  trả is_anomaly=False do nan > threshold là False, nghĩa là metric collection hỏng mà
  detector báo khoẻ mạnh. Hai là same_segment_history truyền vào dạng numpy array thì crash ở
  or []. Cả hai đều nằm đúng trên đường hidden test sẽ đi. Nếu đi làm Soda thì hai bug này vẫn
  còn nguyên.
