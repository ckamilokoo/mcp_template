CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    position VARCHAR(100) NOT NULL,
    department VARCHAR(50) NOT NULL,
    salary DECIMAL(10,2) NOT NULL,
    hire_date DATE NOT NULL DEFAULT CURRENT_DATE
);

INSERT INTO employees (name, position, department, salary) VALUES
('Ana García', 'Desarrolladora Senior', 'IT', 75000),
('Carlos López', 'Analista de Datos', 'Analytics', 65000),
('María Rodríguez', 'Diseñadora UX', 'Diseño', 60000);