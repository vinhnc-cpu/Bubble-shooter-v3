-- Cách tạo country_tier.csv (cập nhật 2026-10-12)
--
-- Dữ liệu: user Android có first_open, cài 2026-02-01 -> 2026-09-06 (đủ 30 ngày theo dõi).
-- Chỉ số: doanh thu quảng cáo (paid_ad_impression, valuemicros) 30 ngày đầu sau cài / 1000 user (cột usd_1000u).
-- Quy tắc xếp tier:
--   users < 300            -> Z   (ít dữ liệu, client dùng mặc định tier_code = 3)
--   usd_1000u >= 60        -> T1
--   15 <= usd_1000u < 60   -> T2
--   usd_1000u < 15         -> T3
-- Quốc gia có trong bản cũ nhưng không còn user trong khoảng trên: giữ với users = 0, tier Z.
-- Kết quả: T1 17 nước, T2 34, T3 82, Z 91 (0.4% user).
-- Model dùng tier qua feature tier_code (T1 0, T2 1, T3 2, Z 3); gói model kèm country_tier.json sinh từ file này.

WITH cohort AS (
  SELECT user_pseudo_id AS uid, argMin(country, event_timestamp) AS country, min(event_timestamp) AS its
  FROM bubble_shooter_v3.bubble_shooter_v3_ga4_staging_flat
  WHERE event_name = 'first_open' AND platform = 'ANDROID' AND event_date BETWEEN '2026-02-01' AND '2026-09-06'
  GROUP BY uid
),
rev AS (
  SELECT e.user_pseudo_id AS uid, sum(e.ep_paid_ad_impression_valuemicros) / 1e6 AS usd
  FROM bubble_shooter_v3.bubble_shooter_v3_ga4_staging_flat AS e INNER JOIN cohort AS c ON e.user_pseudo_id = c.uid
  WHERE e.event_name = 'paid_ad_impression' AND e.event_date >= '2026-02-01'
    AND e.user_pseudo_id IN (SELECT uid FROM cohort) AND e.event_timestamp < c.its + toInt64(30 * 86400) * 1000000
  GROUP BY uid
)
SELECT country, users, usd_1000u,
       multiIf(users < 300, 'Z', usd_1000u >= 60, 'T1', usd_1000u >= 15, 'T2', 'T3') AS tier
FROM (
  SELECT ifNull(c.country, '') AS country, count() AS users, round(sum(ifNull(r.usd, 0)) / users * 1000, 2) AS usd_1000u
  FROM cohort AS c LEFT JOIN rev AS r ON c.uid = r.uid
  GROUP BY country
)
WHERE country != ''
ORDER BY users DESC
SETTINGS max_threads = 8, max_execution_time = 1800, join_use_nulls = 1;
