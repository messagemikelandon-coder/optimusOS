CREATE TABLE IF NOT EXISTS deployment_migrations (
    id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO deployment_migrations (id)
VALUES ('001_optimus_os_foundation')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS demo_service_requests (
    id bigserial PRIMARY KEY,
    customer_name text NOT NULL,
    vehicle_year integer NOT NULL,
    vehicle_make text NOT NULL,
    vehicle_model text NOT NULL,
    job_description text NOT NULL,
    postal_code text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
