-- 为已有转单号且完全没有报价版本的未归档旧订单补录 0 元兼容报价。
-- 该报价仅用于通过旧订单导出校验，不覆盖任何已有报价。

SELECT COUNT(*) AS eligible_orders_before
FROM orders o
WHERE o.archive = 0
  AND EXISTS (
      SELECT 1
      FROM cargos c
      WHERE c.target_order_uid = o.uid
        AND c.archive = 0
        AND c.transfer_id IS NOT NULL
        AND LENGTH(TRIM(c.transfer_id)) > 0
  )
  AND NOT EXISTS (
      SELECT 1
      FROM order_quote_versions q
      WHERE q.order_uid = o.uid
  );

START TRANSACTION;

INSERT INTO order_quote_versions (
    order_uid,
    version_no,
    transportation_mode_id,
    transportation_name,
    channel_cost,
    min_price,
    unit_price,
    surcharge,
    weight_snapshot,
    receivable_amount,
    quoted_price,
    status,
    is_final,
    quote_remark,
    review_remark,
    quoter_id,
    quoter_name,
    reviewer_id,
    reviewer_name,
    create_date,
    review_date,
    effective_date
)
SELECT
    o.uid,
    1,
    tm.id,
    COALESCE(o.transportation, ''),
    COALESCE(tm.cost, 0),
    COALESCE(tm.min_price, 0),
    0,
    0,
    ROUND(COALESCE(cargo_weight.total_weight, 0), 3),
    0,
    0,
    'adopted',
    1,
    '历史订单导出兼容：系统补录0元报价',
    NULL,
    o.salesman_id,
    u.name,
    NULL,
    NULL,
    COALESCE(NULLIF(o.create_date, ''), NULLIF(o.order_date, ''), DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s')),
    NULL,
    COALESCE(NULLIF(o.create_date, ''), NULLIF(o.order_date, ''), DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s'))
FROM orders o
LEFT JOIN users u
    ON u.id = o.salesman_id
LEFT JOIN transportation_modes tm
    ON tm.name = o.transportation
LEFT JOIN (
    SELECT
        c.target_order_uid AS order_uid,
        SUM(COALESCE(c.weight, 0)) AS total_weight
    FROM cargos c
    WHERE c.archive = 0
    GROUP BY c.target_order_uid
) cargo_weight
    ON cargo_weight.order_uid = o.uid
WHERE o.archive = 0
  AND EXISTS (
      SELECT 1
      FROM cargos transfer_cargo
      WHERE transfer_cargo.target_order_uid = o.uid
        AND transfer_cargo.archive = 0
        AND transfer_cargo.transfer_id IS NOT NULL
        AND LENGTH(TRIM(transfer_cargo.transfer_id)) > 0
  )
  AND NOT EXISTS (
      SELECT 1
      FROM order_quote_versions existing_quote
      WHERE existing_quote.order_uid = o.uid
  );

SELECT ROW_COUNT() AS inserted_zero_quotes;

SELECT COUNT(*) AS eligible_orders_remaining
FROM orders o
WHERE o.archive = 0
  AND EXISTS (
      SELECT 1
      FROM cargos c
      WHERE c.target_order_uid = o.uid
        AND c.archive = 0
        AND c.transfer_id IS NOT NULL
        AND LENGTH(TRIM(c.transfer_id)) > 0
  )
  AND NOT EXISTS (
      SELECT 1
      FROM order_quote_versions q
      WHERE q.order_uid = o.uid
  );

COMMIT;
