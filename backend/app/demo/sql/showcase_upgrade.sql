-- One-time additive upgrade from the original 4-table, 3-user bookstore demo.
-- The CLI validates database identity and the exact baseline before execution.

CREATE TABLE bookstore.categories (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_category_id bigint,
    name text NOT NULL,
    description text,
    CONSTRAINT categories_name_unique UNIQUE (name),
    CONSTRAINT categories_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT categories_parent_fk FOREIGN KEY (parent_category_id)
        REFERENCES bookstore.categories (id) ON DELETE RESTRICT
);
CREATE INDEX categories_parent_category_id_idx ON bookstore.categories (parent_category_id);
INSERT INTO bookstore.categories (id, parent_category_id, name, description)
OVERRIDING SYSTEM VALUE VALUES
    (1, NULL, 'Books', 'All bookstore titles.'),
    (2, 1, 'Fiction', 'Stories and novels.'),
    (3, 1, 'Nonfiction', 'Reference and practical titles.'),
    (4, 3, 'Technology', 'Software and engineering.'),
    (5, 3, 'History', 'Historical research and atlases.');

ALTER TABLE bookstore.products ADD COLUMN category_id bigint;
UPDATE bookstore.products SET category_id = CASE sku
    WHEN 'SKU-NOVEL-001' THEN 2 WHEN 'SKU-GUIDE-002' THEN 4
    WHEN 'SKU-RARE-003' THEN 5 WHEN 'SKU-NOTE-004' THEN 3 END;
ALTER TABLE bookstore.products ALTER COLUMN category_id SET NOT NULL;
ALTER TABLE bookstore.products ADD CONSTRAINT products_category_fk
    FOREIGN KEY (category_id) REFERENCES bookstore.categories (id) ON DELETE RESTRICT;
CREATE INDEX products_category_id_idx ON bookstore.products (category_id);

INSERT INTO bookstore.users (id, email, display_name) OVERRIDING SYSTEM VALUE VALUES
    (4, 'luca@example.test', 'Luca Chen'),
    (5, 'asha@example.test', 'Asha Patel'),
    (6, 'noah@example.test', 'Noah Reed'),
    (7, 'imani@example.test', 'Imani Cole'),
    (8, 'elias@example.test', 'Elias Brooks'),
    (9, 'sofia@example.test', 'Sofia Kim'),
    (10, 'kai@example.test', 'Kai Morgan');

INSERT INTO bookstore.products (id, sku, title, unit_price_cents, stock_quantity, active, category_id)
OVERRIDING SYSTEM VALUE VALUES
    (5, 'SKU-DB-005', 'Relational Design', 3200, 18, true, 4),
    (6, 'SKU-FIC-006', 'A Map of Small Worlds', 2800, 25, true, 2),
    (7, 'SKU-HIS-007', 'Cities Through Time', 1800, 9, true, 5),
    (8, 'SKU-REF-008', 'Practical Cataloguing', 2500, 14, true, 3);

CREATE TABLE bookstore.addresses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    label text NOT NULL,
    recipient_name text NOT NULL,
    address_line text NOT NULL,
    address_line_2 text,
    city text NOT NULL,
    region text NOT NULL,
    postal_code text NOT NULL,
    country_code char(2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT addresses_user_label_unique UNIQUE (user_id, label),
    CONSTRAINT addresses_user_fk FOREIGN KEY (user_id)
        REFERENCES bookstore.users (id) ON DELETE RESTRICT,
    CONSTRAINT addresses_country_code_format CHECK (country_code ~ '^[A-Z]{2}$')
);
CREATE INDEX addresses_user_id_idx ON bookstore.addresses (user_id);
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

ALTER TABLE bookstore.orders ADD COLUMN shipping_address_id bigint;
UPDATE bookstore.orders SET shipping_address_id = CASE id WHEN 1 THEN 2 WHEN 2 THEN 3 END;
ALTER TABLE bookstore.orders ADD CONSTRAINT orders_shipping_address_fk
    FOREIGN KEY (shipping_address_id) REFERENCES bookstore.addresses (id) ON DELETE SET NULL;
CREATE INDEX orders_shipping_address_id_idx ON bookstore.orders (shipping_address_id);
INSERT INTO bookstore.orders (id, user_id, shipping_address_id, status, placed_at)
OVERRIDING SYSTEM VALUE VALUES
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

INSERT INTO bookstore.order_items (id, order_id, product_id, quantity, unit_price_cents)
OVERRIDING SYSTEM VALUE VALUES
    (4, 3, 3, 1, 12000), (5, 3, 5, 1, 3200), (6, 4, 6, 2, 2800),
    (7, 5, 7, 1, 1800), (8, 5, 8, 1, 2500), (9, 6, 1, 1, 1999),
    (10, 7, 5, 3, 3200), (11, 7, 2, 1, 4500), (12, 8, 6, 1, 2800),
    (13, 9, 8, 2, 2500), (14, 9, 4, 4, 800), (15, 10, 7, 1, 1800),
    (16, 11, 3, 1, 12000), (17, 12, 5, 1, 3200);

CREATE TABLE bookstore.payments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL,
    payment_method text NOT NULL,
    status text NOT NULL,
    amount_cents integer NOT NULL,
    currency char(3) NOT NULL DEFAULT 'USD',
    provider_reference text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT payments_reference_unique UNIQUE (provider_reference),
    CONSTRAINT payments_order_fk FOREIGN KEY (order_id)
        REFERENCES bookstore.orders (id) ON DELETE RESTRICT,
    CONSTRAINT payments_method_known CHECK (payment_method IN ('card', 'wallet', 'gift_card')),
    CONSTRAINT payments_status_known CHECK (status IN ('authorized', 'captured', 'failed', 'refunded')),
    CONSTRAINT payments_amount_positive CHECK (amount_cents > 0),
    CONSTRAINT payments_currency_format CHECK (currency ~ '^[A-Z]{3}$')
);
CREATE INDEX payments_order_id_idx ON bookstore.payments (order_id);
INSERT INTO bookstore.payments (id, order_id, payment_method, status, amount_cents, currency, provider_reference)
OVERRIDING SYSTEM VALUE VALUES
    (1, 2, 'card', 'captured', 4500, 'USD', 'demo-pay-002'),
    (2, 3, 'wallet', 'captured', 15200, 'USD', 'demo-pay-003'),
    (3, 4, 'card', 'authorized', 5600, 'USD', 'demo-pay-004'),
    (4, 5, 'gift_card', 'captured', 4300, 'USD', 'demo-pay-005'),
    (5, 6, 'card', 'failed', 1999, 'USD', 'demo-pay-006'),
    (6, 7, 'card', 'captured', 14100, 'USD', 'demo-pay-007'),
    (7, 9, 'wallet', 'captured', 8200, 'USD', 'demo-pay-009'),
    (8, 10, 'card', 'captured', 1800, 'USD', 'demo-pay-010'),
    (9, 11, 'card', 'refunded', 12000, 'USD', 'demo-pay-011');

CREATE TABLE bookstore.reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    product_id bigint NOT NULL,
    rating smallint NOT NULL,
    headline text NOT NULL,
    body text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reviews_user_product_unique UNIQUE (user_id, product_id),
    CONSTRAINT reviews_user_fk FOREIGN KEY (user_id)
        REFERENCES bookstore.users (id) ON DELETE RESTRICT,
    CONSTRAINT reviews_product_fk FOREIGN KEY (product_id)
        REFERENCES bookstore.products (id) ON DELETE RESTRICT,
    CONSTRAINT reviews_rating_range CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT reviews_headline_not_blank CHECK (length(btrim(headline)) > 0)
);
CREATE INDEX reviews_product_id_idx ON bookstore.reviews (product_id);
INSERT INTO bookstore.reviews (id, user_id, product_id, rating, headline, body)
OVERRIDING SYSTEM VALUE VALUES
    (1, 1, 1, 5, 'A thoughtful story', 'A synthetic sample review.'),
    (2, 2, 2, 4, 'Useful reference', 'Clear examples for the demo dataset.'),
    (3, 3, 3, 3, 'Interesting atlas', NULL),
    (4, 4, 5, 5, 'Strong data model', 'Helpful for discussing relationships.'),
    (5, 5, 6, 4, 'Enjoyable read', NULL),
    (6, 7, 7, 5, 'Well researched', 'Synthetic classroom review.'),
    (7, 8, 8, 3, 'Good overview', 'A representative sample record.'),
    (8, 9, 4, 4, 'Handy notebook', NULL);

CREATE TABLE bookstore.inventory_movements (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id bigint NOT NULL,
    order_item_id bigint,
    reason text NOT NULL,
    quantity_delta integer NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT inventory_movements_product_fk FOREIGN KEY (product_id)
        REFERENCES bookstore.products (id) ON DELETE RESTRICT,
    CONSTRAINT inventory_movements_order_item_fk FOREIGN KEY (order_item_id)
        REFERENCES bookstore.order_items (id) ON DELETE SET NULL,
    CONSTRAINT inventory_movements_reason_known CHECK (reason IN ('restock', 'sale', 'return', 'adjustment')),
    CONSTRAINT inventory_movements_nonzero CHECK (quantity_delta <> 0)
);
CREATE INDEX inventory_movements_product_id_idx ON bookstore.inventory_movements (product_id);
CREATE INDEX inventory_movements_order_item_id_idx ON bookstore.inventory_movements (order_item_id);
INSERT INTO bookstore.inventory_movements (id, product_id, order_item_id, reason, quantity_delta)
OVERRIDING SYSTEM VALUE VALUES
    (1, 1, NULL, 'restock', 20), (2, 2, NULL, 'restock', 10),
    (3, 3, NULL, 'restock', 5), (4, 4, NULL, 'restock', 50),
    (5, 5, NULL, 'restock', 15), (6, 6, NULL, 'restock', 22),
    (7, 7, NULL, 'restock', 8), (8, 8, NULL, 'restock', 30),
    (9, 1, 1, 'sale', -2), (10, 4, 2, 'sale', -1),
    (11, 2, 3, 'sale', -1), (12, 3, 4, 'sale', -1),
    (13, 5, 5, 'sale', -1), (14, 6, 6, 'sale', -2),
    (15, 7, 7, 'sale', -1), (16, 8, 8, 'sale', -1),
    (17, 3, NULL, 'adjustment', -1), (18, 4, 14, 'return', 1);

SELECT setval(pg_get_serial_sequence('bookstore.users', 'id'), (SELECT MAX(id) FROM bookstore.users));
SELECT setval(pg_get_serial_sequence('bookstore.categories', 'id'), (SELECT MAX(id) FROM bookstore.categories));
SELECT setval(pg_get_serial_sequence('bookstore.products', 'id'), (SELECT MAX(id) FROM bookstore.products));
SELECT setval(pg_get_serial_sequence('bookstore.addresses', 'id'), (SELECT MAX(id) FROM bookstore.addresses));
SELECT setval(pg_get_serial_sequence('bookstore.orders', 'id'), (SELECT MAX(id) FROM bookstore.orders));
SELECT setval(pg_get_serial_sequence('bookstore.order_items', 'id'), (SELECT MAX(id) FROM bookstore.order_items));
SELECT setval(pg_get_serial_sequence('bookstore.payments', 'id'), (SELECT MAX(id) FROM bookstore.payments));
SELECT setval(pg_get_serial_sequence('bookstore.reviews', 'id'), (SELECT MAX(id) FROM bookstore.reviews));
SELECT setval(pg_get_serial_sequence('bookstore.inventory_movements', 'id'), (SELECT MAX(id) FROM bookstore.inventory_movements));
