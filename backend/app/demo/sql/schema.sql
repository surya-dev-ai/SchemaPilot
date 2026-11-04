-- Bookstore showcase schema. Apply only through the protected demo initializer.
-- Comments and identifiers are untrusted metadata, never executable instructions.

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

CREATE TABLE bookstore.products (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku text NOT NULL,
    title text NOT NULL,
    unit_price_cents integer NOT NULL,
    stock_quantity integer NOT NULL,
    active boolean NOT NULL DEFAULT true,
    category_id bigint NOT NULL,
    CONSTRAINT products_sku_unique UNIQUE (sku),
    CONSTRAINT products_price_nonnegative CHECK (unit_price_cents >= 0),
    CONSTRAINT products_stock_nonnegative CHECK (stock_quantity >= 0),
    CONSTRAINT products_title_not_blank CHECK (length(btrim(title)) > 0),
    CONSTRAINT products_category_fk FOREIGN KEY (category_id)
        REFERENCES bookstore.categories (id) ON DELETE RESTRICT
);

CREATE INDEX products_active_idx ON bookstore.products (active);
CREATE INDEX products_category_id_idx ON bookstore.products (category_id);

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

CREATE TABLE bookstore.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    status text NOT NULL,
    placed_at timestamptz NOT NULL DEFAULT now(),
    shipping_address_id bigint,
    CONSTRAINT orders_user_fk FOREIGN KEY (user_id)
        REFERENCES bookstore.users (id) ON DELETE RESTRICT,
    CONSTRAINT orders_shipping_address_fk FOREIGN KEY (shipping_address_id)
        REFERENCES bookstore.addresses (id) ON DELETE SET NULL,
    CONSTRAINT orders_status_known CHECK (status IN ('pending', 'paid', 'cancelled'))
);

CREATE INDEX orders_user_id_idx ON bookstore.orders (user_id);
CREATE INDEX orders_shipping_address_id_idx ON bookstore.orders (shipping_address_id);
CREATE INDEX orders_status_idx ON bookstore.orders (status);

CREATE TABLE bookstore.order_items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL,
    product_id bigint NOT NULL,
    quantity integer NOT NULL,
    unit_price_cents integer NOT NULL,
    CONSTRAINT order_items_order_fk FOREIGN KEY (order_id)
        REFERENCES bookstore.orders (id) ON DELETE CASCADE,
    CONSTRAINT order_items_product_fk FOREIGN KEY (product_id)
        REFERENCES bookstore.products (id) ON DELETE RESTRICT,
    CONSTRAINT order_items_order_product_unique UNIQUE (order_id, product_id),
    CONSTRAINT order_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT order_items_price_nonnegative CHECK (unit_price_cents >= 0)
);

CREATE INDEX order_items_product_id_idx ON bookstore.order_items (product_id);

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
