INSERT INTO demo_service_requests (
    customer_name,
    vehicle_year,
    vehicle_make,
    vehicle_model,
    job_description,
    postal_code
)
SELECT *
FROM (
    VALUES
        ('Demo Customer A', 2018, 'Honda', 'CR-V', 'Replace front brake pads and rotors', '66442'),
        ('Demo Customer B', 2020, 'Toyota', 'Camry', 'Diagnose no-start condition', '95677')
) AS demo(customer_name, vehicle_year, vehicle_make, vehicle_model, job_description, postal_code)
WHERE NOT EXISTS (
    SELECT 1
    FROM demo_service_requests existing
    WHERE existing.customer_name = demo.customer_name
      AND existing.job_description = demo.job_description
);
