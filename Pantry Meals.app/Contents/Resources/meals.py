import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from openai import APIError
from langchain_core.exceptions import OutputParserException

from agent import find_meal

ROOT = Path(__file__).resolve().parent


def load_recipes(db):
    db.execute((ROOT / "schema.sql").read_text())
    recipes = json.loads((ROOT / "recipes.json").read_text())
    sample_ids = [
        "egg-fried-rice", "tomato-omelet", "lentil-soup", "garlic-pasta",
        "chickpea-salad", "banana-oats", "potato-hash", "cheese-toast",
        "tuna-wrap", "apple-yogurt",
    ]
    db.execute("DELETE FROM recipes WHERE id = ANY(%s)", (sample_ids,))
    with db.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO recipes VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
               ingredients = EXCLUDED.ingredients, minutes = EXCLUDED.minutes,
               directions = EXCLUDED.directions""",
            recipes,
        )


def find_recipes(db, query, minutes):
    return db.execute(
        """WITH keywords AS (
               SELECT string_agg(quote_literal(word), ' | ')::tsquery AS query
               FROM unnest(tsvector_to_array(to_tsvector('english', %s))) AS word
           ), matches AS (
               SELECT r.*, ARRAY(
                   SELECT ingredient FROM unnest(r.ingredients) AS item(ingredient)
                   WHERE NOT EXISTS (
                       SELECT 1 FROM pantry p WHERE p.ingredient = item.ingredient
                   )
               ) AS missing,
               ts_rank(to_tsvector('english', name || ' ' ||
                   array_to_string(ingredients, ' ') || ' ' || directions),
                   keywords.query) AS relevance,
               to_tsvector('english', name) @@ keywords.query AS title_match
               FROM recipes r CROSS JOIN keywords
               WHERE minutes <= %s
           )
           SELECT id, name, ingredients, minutes, directions, missing
           FROM matches
           ORDER BY coalesce(title_match, false) DESC, (coalesce(relevance, 0) > 0) DESC,
                    cardinality(missing), relevance DESC, minutes, id
           LIMIT 4""",
        (query, minutes),
    ).fetchall()


def run(db, args):
    if args.command == "init":
        load_recipes(db)
        count = db.execute("SELECT count(*) AS total FROM recipes").fetchone()["total"]
        print(f"Recipe library ready. {count} recipes.")
    elif args.command in ("add", "remove"):
        ingredients = sorted({item.strip().lower() for item in args.ingredients} - {""})
        with db.cursor() as cursor:
            if args.command == "add":
                cursor.executemany(
                    "INSERT INTO pantry VALUES (%s) ON CONFLICT DO NOTHING",
                    [(item,) for item in ingredients],
                )
            else:
                cursor.execute("DELETE FROM pantry WHERE ingredient = ANY(%s)", (ingredients,))
        print("Pantry updated.")
    elif args.command in ("pantry", "shopping"):
        table = "pantry" if args.command == "pantry" else "shopping_list"
        rows = db.execute(f"SELECT ingredient FROM {table} ORDER BY ingredient").fetchall()
        print("\n".join(row["ingredient"] for row in rows) or "List is empty.")
    elif args.command == "clear-shopping":
        db.execute("DELETE FROM shopping_list")
        print("Shopping list cleared.")
    elif args.command == "dinner":
        recipe = find_meal(args.request, lambda query: find_recipes(db, query, args.minutes))
        if recipe is None:
            print("No matching recipe in the library.")
            return
        missing = recipe["missing"]
        print(f'{recipe["name"]} · {recipe["minutes"]} min')
        print(f'Source: UniTools World Recipes / {recipe["id"].removeprefix("unitools-")}')
        print("Ingredients: " + ", ".join(recipe["ingredients"]))
        print("To buy: " + (", ".join(missing) or "nothing"))
        print(recipe["directions"])
        if args.save and missing:
            with db.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO shopping_list VALUES (%s) ON CONFLICT DO NOTHING",
                    [(item,) for item in missing],
                )
            print("Missing ingredients saved to your shopping list.")


def main():
    load_dotenv(os.getenv("PANTRY_SETTINGS", ROOT / ".env"))
    parser = argparse.ArgumentParser(description="Pantry Meals: find a meal with the food you have.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "pantry", "shopping", "clear-shopping"):
        commands.add_parser(name)
    for name in ("add", "remove"):
        commands.add_parser(name).add_argument("ingredients", nargs="+")
    dinner = commands.add_parser("dinner")
    dinner.add_argument("request", nargs="?", default="")
    dinner.add_argument("--minutes", type=int, default=30)
    dinner.add_argument("--save", action="store_true")
    args = parser.parse_args()
    if args.command == "dinner" and args.minutes < 1:
        parser.error("--minutes must be at least 1")
    try:
        with psycopg.connect(
            os.getenv("DATABASE_URL", "dbname=pantry_meals_public"), row_factory=dict_row
        ) as db:
            run(db, args)
    except (APIError, OutputParserException, ValueError) as error:
        parser.exit(1, f"Could not find a meal: {error}\n")
    except psycopg.Error as error:
        parser.exit(1, f"Database error: {error}\n")


if __name__ == "__main__":
    main()
