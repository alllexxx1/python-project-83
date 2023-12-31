DROP TABLE IF EXISTS url_checks;
DROP TABLE IF EXISTS urls;

CREATE TABLE urls (
  id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name varchar(255),
  created_at DATE DEFAULT CURRENT_DATE
);

CREATE TABLE url_checks (
  id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  url_id bigint REFERENCES urls (id),
  status_code SMALLINT,
  h1 text,
  title text,
  description text,
  created_at DATE DEFAULT CURRENT_DATE
);
