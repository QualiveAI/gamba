-- Только новый одноразовый CI PostgreSQL, не локальный/production кластер.
-- Пароли публичные тестовые; эта роль не используется вне service container.
CREATE ROLE caseplatform_test
    LOGIN PASSWORD 'ci-test-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE caseplatform_test OWNER caseplatform_test TEMPLATE template0;
REVOKE CONNECT ON DATABASE postgres, template1, caseplatform_test FROM PUBLIC;
GRANT CONNECT ON DATABASE caseplatform_test TO caseplatform_test;
\connect caseplatform_test
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO caseplatform_test;
