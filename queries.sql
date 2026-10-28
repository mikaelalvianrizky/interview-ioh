-- Q1. Top 10 recharge amounts by total revenue, per channel.
-- The data has only 10 distinct amounts, so every channel lists all of them. The ranking still
-- says something: revenue order differs from both face value and transaction count.
WITH by_amount AS (
    SELECT channel, amount, COUNT(*) AS transactions, SUM(amount) AS revenue
    FROM recharges
    GROUP BY channel, amount
)
SELECT channel, revenue_rank, amount, transactions, revenue
FROM (
    SELECT *, RANK() OVER (PARTITION BY channel ORDER BY revenue DESC) AS revenue_rank
    FROM by_amount
)
WHERE revenue_rank <= 10
ORDER BY channel, revenue_rank;

-- Q2. Monthly active rechargers and average revenue per user, by segment.
-- arppu divides revenue by subscribers who recharged that month, arpu by every subscriber in the
-- segment. They can rank segments differently. partial_month flags months the data only partly covers.
WITH monthly AS (
    SELECT strftime('%Y-%m', r.date) AS month, s.segment,
           COUNT(DISTINCT r.subscriber_id) AS active_rechargers,
           SUM(r.amount) AS revenue
    FROM recharges r
    JOIN subscribers s USING (subscriber_id)
    GROUP BY month, s.segment
),
segment_size AS (
    SELECT segment, COUNT(*) AS subscribers FROM subscribers GROUP BY segment
),
bounds AS (
    SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM recharges
)
SELECT m.month, m.segment, m.active_rechargers, m.revenue,
       ROUND(1.0 * m.revenue / m.active_rechargers) AS arppu,
       ROUND(1.0 * m.revenue / z.subscribers) AS arpu,
       (m.month || '-01' < b.min_date
        OR DATE(m.month || '-01', '+1 month', '-1 day') > b.max_date) AS partial_month
FROM monthly m
JOIN segment_size z USING (segment)
CROSS JOIN bounds b
ORDER BY m.month, m.segment;

-- Q3. Subscribers who recharged in the last 30 days but not in the 30 days before that.
-- today = 2026-09-24. Windows are (today-30, today] = 2026-08-26..2026-09-24 and
-- (today-60, today-30] = 2026-07-27..2026-08-25. The data has no rows dated today itself.
WITH params AS (SELECT DATE('2026-09-24') AS today),
per_sub AS (
    SELECT r.subscriber_id,
           SUM(r.date > DATE(p.today, '-30 days')) AS recent,
           SUM(r.date <= DATE(p.today, '-30 days')) AS previous
    FROM recharges r
    CROSS JOIN params p
    WHERE r.date > DATE(p.today, '-60 days') AND r.date <= p.today
    GROUP BY r.subscriber_id
)
SELECT ps.subscriber_id, s.segment, ps.recent AS recharges_last_30d
FROM per_sub ps
JOIN subscribers s USING (subscriber_id)
WHERE ps.recent > 0 AND ps.previous = 0
ORDER BY ps.subscriber_id;

-- Q4. Days since last recharge and average gap between recharges, per subscriber.
-- The mean of consecutive gaps telescopes to (last - first) / (n - 1), so no window function is needed.
-- avg_gap_days is NULL below 2 recharges. LEFT JOIN keeps the subscribers who never recharged.
WITH params AS (SELECT DATE('2026-09-24') AS today)
SELECT s.subscriber_id, s.segment,
       COUNT(r.date) AS recharge_count,
       MAX(r.date) AS last_recharge,
       CAST(julianday(p.today) - julianday(MAX(r.date)) AS INTEGER) AS days_since_last_recharge,
       ROUND((julianday(MAX(r.date)) - julianday(MIN(r.date))) / NULLIF(COUNT(r.date) - 1, 0), 1)
           AS avg_gap_days
FROM subscribers s
LEFT JOIN recharges r USING (subscriber_id)
CROSS JOIN params p
GROUP BY s.subscriber_id
ORDER BY s.subscriber_id;
