CREATE TABLE IF NOT EXISTS citas (
    id SERIAL PRIMARY KEY,
    paciente TEXT NOT NULL,
    motivo TEXT NOT NULL,
    fecha TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO citas (paciente, motivo) VALUES
    ('paciente-001', 'control general'),
    ('paciente-002', 'chequeo de presion'),
    ('paciente-003', 'consulta de seguimiento');
