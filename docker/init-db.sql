-- ============================================================
-- AegisRAG — Inicialización de PostgreSQL
-- Se ejecuta automáticamente en el primer arranque del contenedor.
-- ============================================================

-- Extensión para generación de UUIDs (claves primarias)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Extensión para búsqueda de texto completo avanzada
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
