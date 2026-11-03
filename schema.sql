CREATE TABLE IF NOT EXISTS pantry (
    ingredient text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS recipes (
    id text PRIMARY KEY,
    name text NOT NULL,
    ingredients text[] NOT NULL,
    minutes integer NOT NULL CHECK (minutes > 0),
    directions text NOT NULL
);

CREATE TABLE IF NOT EXISTS shopping_list (
    ingredient text PRIMARY KEY
);
