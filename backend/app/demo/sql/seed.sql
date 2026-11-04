-- Synthetic bookstore showcase data. Fixed ids make risk demos repeatable.

INSERT INTO bookstore.users (id, email, display_name) OVERRIDING SYSTEM VALUE VALUES
    (1, 'mira@example.test', 'Mira Shah'),
    (2, 'owen@example.test', 'Owen Blake'),
    (3, 'priya@example.test', 'Priya Nair'),
    (4, 'luca@example.test', 'Luca Chen'),
    (5, 'asha@example.test', 'Asha Patel'),
    (6, 'noah@example.test', 'Noah Reed'),
    (7, 'imani@example.test', 'Imani Cole'),
    (8, 'elias@example.test', 'Elias Brooks'),
    (9, 'sofia@example.test', 'Sofia Kim'),
    (10, 'kai@example.test', 'Kai Morgan');

INSERT INTO bookstore.categories (id, parent_category_id, name, description)
OVERRIDING SYSTEM VALUE VALUES
    (1, NULL, 'Books', 'All bookstore titles.'),
    (2, 1, 'Fiction', 'Stories and novels.'),
    (3, 1, 'Nonfiction', 'Reference and practical titles.'),
    (4, 3, 'Technology', 'Software and engineering.'),
    (5, 3, 'History', 'Historical research and atlases.');

INSERT INTO bookstore.products (
    id, sku, title, unit_price_cents, stock_quantity, active, category_id
) OVERRIDING SYSTEM VALUE VALUES
    (1, 'SKU-NOVEL-001', 'The Left Margin', 1999, 12, true, 2),
    (2, 'SKU-GUIDE-002', 'Index Design', 4500, 3, true, 4),
    (3, 'SKU-RARE-003', 'Out of Print Atlas', 12000, 0, false, 5),
    (4, 'SKU-NOTE-004', 'Field Notes', 800, 40, true, 3),
    (5, 'SKU-DB-005', 'Relational Design', 3200, 18, true, 4),
    (6, 'SKU-FIC-006', 'A Map of Small Worlds', 2800, 25, true, 2),
    (7, 'SKU-HIS-007', 'Cities Through Time', 1800, 9, true, 5),
    (8, 'SKU-REF-008', 'Practical Cataloguing', 2500, 14, true, 3);

INSERT INTO bookstore.addresses (
    id, user_id, label, recipient_name, address_line, address_line_2,
    city, region, postal_code, country_code
) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 'home', 'Mira Shah', '10 Demo Lane', NULL, 'Test City', 'CA', '90001', 'US'),
    (2, 1, 'work', 'Mira Shah', '20 Sample Street', 'Suite 2', 'Test City', 'CA', '90002', 'US'),
    (3, 2, 'home', 'Owen Blake', '30 Example Road', NULL, 'Sampleton', 'NY', '10001', 'US'),
    (4, 3, 'home', 'Priya Nair', '40 Fiction Way', NULL, 'Sampleton', 'NY', '10002', 'US'),
    (5, 4, 'home', 'Luca Chen', '50 Demo Lane', NULL, 'Mocksville', 'TX', '73301', 'US'),
    (6, 5, 'home', 'Asha Patel', '60 Sample Street', NULL, 'Mocksville', 'TX', '73302', 'US'),
    (7, 6, 'home', 'Noah Reed', '70 Example Road', NULL, 'Test City', 'CA', '90003', 'US'),
    (8, 7, 'home', 'Imani Cole', '80 Fiction Way', NULL, 'Sampleton', 'NY', '10003', 'US'),
    (9, 8, 'home', 'Elias Brooks', '90 Demo Lane', NULL, 'Mocksville', 'TX', '73303', 'US'),
    (10, 9, 'home', 'Sofia Kim', '100 Sample Street', NULL, 'Test City', 'CA', '90004', 'US'),
    (11, 10, 'home', 'Kai Morgan', '110 Example Road', NULL, 'Sampleton', 'NY', '10004', 'US'),
    (12, 3, 'work', 'Priya Nair', '120 Fiction Way', 'Floor 3', 'Sampleton', 'NY', '10005', 'US');

INSERT INTO bookstore.orders (id, user_id, shipping_address_id, status, placed_at)
OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 2, 'pending', now() - interval '20 days'),
    (2, 2, 3, 'paid', now() - interval '18 days'),
    (3, 3, 4, 'paid', now() - interval '16 days'),
    (4, 4, 5, 'pending', now() - interval '14 days'),
    (5, 5, 6, 'paid', now() - interval '12 days'),
    (6, 6, 7, 'cancelled', now() - interval '10 days'),
    (7, 7, 8, 'paid', now() - interval '8 days'),
    (8, 8, 9, 'pending', now() - interval '6 days'),
    (9, 9, 10, 'paid', now() - interval '4 days'),
    (10, 10, 11, 'paid', now() - interval '3 days'),
    (11, 2, 3, 'paid', now() - interval '2 days'),
    (12, 3, 12, 'pending', now() - interval '1 day');

INSERT INTO bookstore.order_items (
    id, order_id, product_id, quantity, unit_price_cents
) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 1, 2, 1999),
    (2, 1, 4, 1, 800),
    (3, 2, 2, 1, 4500),
    (4, 3, 3, 1, 12000),
    (5, 3, 5, 1, 3200),
    (6, 4, 6, 2, 2800),
    (7, 5, 7, 1, 1800),
    (8, 5, 8, 1, 2500),
    (9, 6, 1, 1, 1999),
    (10, 7, 5, 3, 3200),
    (11, 7, 2, 1, 4500),
    (12, 8, 6, 1, 2800),
    (13, 9, 8, 2, 2500),
    (14, 9, 4, 4, 800),
    (15, 10, 7, 1, 1800),
    (16, 11, 3, 1, 12000),
    (17, 12, 5, 1, 3200);

INSERT INTO bookstore.payments (
    id, order_id, payment_method, status, amount_cents, currency, provider_reference
) OVERRIDING SYSTEM VALUE VALUES
    (1, 2, 'card', 'captured', 4500, 'USD', 'demo-pay-002'),
    (2, 3, 'wallet', 'captured', 15200, 'USD', 'demo-pay-003'),
    (3, 4, 'card', 'authorized', 5600, 'USD', 'demo-pay-004'),
    (4, 5, 'gift_card', 'captured', 4300, 'USD', 'demo-pay-005'),
    (5, 6, 'card', 'failed', 1999, 'USD', 'demo-pay-006'),
    (6, 7, 'card', 'captured', 14100, 'USD', 'demo-pay-007'),
    (7, 9, 'wallet', 'captured', 8200, 'USD', 'demo-pay-009'),
    (8, 10, 'card', 'captured', 1800, 'USD', 'demo-pay-010'),
    (9, 11, 'card', 'refunded', 12000, 'USD', 'demo-pay-011');

INSERT INTO bookstore.reviews (
    id, user_id, product_id, rating, headline, body
) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 1, 5, 'A thoughtful story', 'A synthetic sample review.'),
    (2, 2, 2, 4, 'Useful reference', 'Clear examples for the demo dataset.'),
    (3, 3, 3, 3, 'Interesting atlas', NULL),
    (4, 4, 5, 5, 'Strong data model', 'Helpful for discussing relationships.'),
    (5, 5, 6, 4, 'Enjoyable read', NULL),
    (6, 7, 7, 5, 'Well researched', 'Synthetic classroom review.'),
    (7, 8, 8, 3, 'Good overview', 'A representative sample record.'),
    (8, 9, 4, 4, 'Handy notebook', NULL);

INSERT INTO bookstore.inventory_movements (
    id, product_id, order_item_id, reason, quantity_delta
) OVERRIDING SYSTEM VALUE VALUES
    (1, 1, NULL, 'restock', 20),
    (2, 2, NULL, 'restock', 10),
    (3, 3, NULL, 'restock', 5),
    (4, 4, NULL, 'restock', 50),
    (5, 5, NULL, 'restock', 15),
    (6, 6, NULL, 'restock', 22),
    (7, 7, NULL, 'restock', 8),
    (8, 8, NULL, 'restock', 30),
    (9, 1, 1, 'sale', -2),
    (10, 4, 2, 'sale', -1),
    (11, 2, 3, 'sale', -1),
    (12, 3, 4, 'sale', -1),
    (13, 5, 5, 'sale', -1),
    (14, 6, 6, 'sale', -2),
    (15, 7, 7, 'sale', -1),
    (16, 8, 8, 'sale', -1),
    (17, 3, NULL, 'adjustment', -1),
    (18, 4, 14, 'return', 1);

SELECT setval(pg_get_serial_sequence('bookstore.users', 'id'), (SELECT MAX(id) FROM bookstore.users));
SELECT setval(pg_get_serial_sequence('bookstore.categories', 'id'), (SELECT MAX(id) FROM bookstore.categories));
SELECT setval(pg_get_serial_sequence('bookstore.products', 'id'), (SELECT MAX(id) FROM bookstore.products));
SELECT setval(pg_get_serial_sequence('bookstore.addresses', 'id'), (SELECT MAX(id) FROM bookstore.addresses));
SELECT setval(pg_get_serial_sequence('bookstore.orders', 'id'), (SELECT MAX(id) FROM bookstore.orders));
SELECT setval(pg_get_serial_sequence('bookstore.order_items', 'id'), (SELECT MAX(id) FROM bookstore.order_items));
SELECT setval(pg_get_serial_sequence('bookstore.payments', 'id'), (SELECT MAX(id) FROM bookstore.payments));
SELECT setval(pg_get_serial_sequence('bookstore.reviews', 'id'), (SELECT MAX(id) FROM bookstore.reviews));
SELECT setval(pg_get_serial_sequence('bookstore.inventory_movements', 'id'), (SELECT MAX(id) FROM bookstore.inventory_movements));
