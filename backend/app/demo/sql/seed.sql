-- Bookstore demo seed. Fixed ids make migration and constraint tests repeatable.

INSERT INTO bookstore.users (id, email, display_name) OVERRIDING SYSTEM VALUE VALUES
    (1, 'mira@example.test', 'Mira Shah'),
    (2, 'owen@example.test', 'Owen Blake'),
    (3, 'priya@example.test', 'Priya Nair');

INSERT INTO bookstore.products (
    id, sku, title, unit_price_cents, stock_quantity, active
) OVERRIDING SYSTEM VALUE VALUES
    (1, 'SKU-NOVEL-001', 'The Left Margin', 1999, 12, true),
    (2, 'SKU-GUIDE-002', 'Index Design', 4500, 3, true),
    (3, 'SKU-RARE-003', 'Out of Print Atlas', 12000, 0, false),
    (4, 'SKU-NOTE-004', 'Field Notes', 800, 40, true);

INSERT INTO bookstore.orders (id, user_id, status) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 'pending'),
    (2, 2, 'paid');

INSERT INTO bookstore.order_items (
    id, order_id, product_id, quantity, unit_price_cents
) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 1, 2, 1999),
    (2, 1, 4, 1, 800),
    (3, 2, 2, 1, 4500);

SELECT setval(pg_get_serial_sequence('bookstore.users', 'id'), (SELECT MAX(id) FROM bookstore.users));
SELECT setval(pg_get_serial_sequence('bookstore.products', 'id'), (SELECT MAX(id) FROM bookstore.products));
SELECT setval(pg_get_serial_sequence('bookstore.orders', 'id'), (SELECT MAX(id) FROM bookstore.orders));
SELECT setval(pg_get_serial_sequence('bookstore.order_items', 'id'), (SELECT MAX(id) FROM bookstore.order_items));
