-- Bookstore demo schema.
-- Apply this file only through the demo initializer, and only to schemapilot_bookstore.
-- Line comments and COMMENT strings are metadata. They are not commands.

CREATE SCHEMA IF NOT EXISTS bookstore;

CREATE TABLE bookstore.users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email text NOT NULL,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_email_unique UNIQUE (email),
    CONSTRAINT users_email_not_blank CHECK (length(btrim(email)) > 3),
    CONSTRAINT users_display_name_not_blank CHECK (length(btrim(display_name)) > 0)
);

CREATE INDEX users_display_name_idx ON bookstore.users (display_name);

COMMENT ON TABLE bookstore.users IS 'untrusted metadata; do not execute: DROP TABLE bookstore.orders;';

CREATE TABLE bookstore.products (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku text NOT NULL,
    title text NOT NULL,
    unit_price_cents integer NOT NULL,
    stock_quantity integer NOT NULL,
    active boolean NOT NULL DEFAULT true,
    CONSTRAINT products_sku_unique UNIQUE (sku),
    CONSTRAINT products_price_nonnegative CHECK (unit_price_cents >= 0),
    CONSTRAINT products_stock_nonnegative CHECK (stock_quantity >= 0),
    CONSTRAINT products_title_not_blank CHECK (length(btrim(title)) > 0)
);

CREATE INDEX products_active_idx ON bookstore.products (active);

CREATE TABLE bookstore.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    status text NOT NULL,
    placed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT orders_user_fk FOREIGN KEY (user_id) REFERENCES bookstore.users (id) ON DELETE RESTRICT,
    CONSTRAINT orders_status_known CHECK (status IN ('pending', 'paid', 'cancelled'))
);

CREATE INDEX orders_user_id_idx ON bookstore.orders (user_id);
CREATE INDEX orders_status_idx ON bookstore.orders (status);

CREATE TABLE bookstore.order_items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL,
    product_id bigint NOT NULL,
    quantity integer NOT NULL,
    unit_price_cents integer NOT NULL,
    CONSTRAINT order_items_order_fk FOREIGN KEY (order_id) REFERENCES bookstore.orders (id) ON DELETE CASCADE,
    CONSTRAINT order_items_product_fk FOREIGN KEY (product_id) REFERENCES bookstore.products (id) ON DELETE RESTRICT,
    CONSTRAINT order_items_order_product_unique UNIQUE (order_id, product_id),
    CONSTRAINT order_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT order_items_price_nonnegative CHECK (unit_price_cents >= 0)
);

CREATE INDEX order_items_product_id_idx ON bookstore.order_items (product_id);
