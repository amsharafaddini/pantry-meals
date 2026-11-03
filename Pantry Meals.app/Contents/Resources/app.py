import os
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from tkinter import ttk
from types import SimpleNamespace
from httpx import ConnectTimeout
from openai import APIConnectionError, APIError, APITimeoutError
from langchain_core.exceptions import OutputParserException

import psycopg
from dotenv import load_dotenv, set_key

import meals


def connect():
    return psycopg.connect(
        os.getenv("DATABASE_URL", "dbname=pantry_meals_public"),
        row_factory=meals.dict_row,
    )


def recipe_count():
    with connect() as db:
        return db.execute("SELECT count(*) AS total FROM recipes").fetchone()["total"]


def run(query, items):
    text = StringIO()
    with connect() as db, redirect_stdout(text):
        db.execute("CREATE TEMP TABLE pantry (ingredient text PRIMARY KEY) ON COMMIT DROP")
        if items:
            db.execute("INSERT INTO pantry SELECT unnest(%s::text[])", (items,))
        meals.run(db, SimpleNamespace(command="dinner", request=query, minutes=45, save=False))
    return text.getvalue().strip()


def main():
    settings = os.getenv("PANTRY_SETTINGS", meals.ROOT / ".env")
    load_dotenv(settings)
    window = tk.Tk()
    window.title("Pantry Meals")
    window.geometry("720x610")
    window.minsize(600, 470)
    page = ttk.Frame(window, padding=18)
    page.pack(fill="both", expand=True)
    pool = ThreadPoolExecutor(max_workers=1)
    ingredients = set()

    ttk.Label(page, text="Pantry Meals", font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
    library = ttk.Label(page)
    library.pack(anchor="w", pady=(0, 12))
    ttk.Label(page, text="Ingredients you have").pack(anchor="w")
    pantry = ttk.Label(page, wraplength=550)
    pantry.pack(anchor="w")
    food = ttk.Entry(page)
    food.pack(fill="x", pady=5)
    ttk.Label(page, text="Use commas for several items, like egg, tomato, oil").pack(anchor="w")

    edit = ttk.Frame(page)
    edit.pack(anchor="w", pady=(4, 12))

    ttk.Label(page, text="What would you like to cook?").pack(anchor="w")
    request = ttk.Entry(page)
    request.pack(fill="x", pady=5)
    ttk.Label(page, text="Try shakshuka or leave it blank for an idea. Meals take up to 45 minutes.").pack(anchor="w")

    actions = ttk.Frame(page)
    actions.pack(anchor="w", pady=(6, 10))
    result = ttk.Frame(page)
    result.pack(fill="both", expand=True)
    output = tk.Text(result, wrap="word", padx=10, pady=8, font="TkDefaultFont", state="disabled")
    scroll = ttk.Scrollbar(result, command=output.yview)
    output.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    output.pack(side="left", fill="both", expand=True)

    def show(message):
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", message)
        output.configure(state="disabled")

    def refresh():
        items = ", ".join(sorted(ingredients))
        pantry.configure(text=items or "Your pantry is empty.")

    def edit_pantry(command):
        if find_button.instate(["disabled"]):
            return
        items = [item.strip() for item in food.get().split(",") if item.strip()]
        if not items:
            show("Enter an ingredient first.")
            return
        items = {item.lower() for item in items}
        if command == "add":
            ingredients.update(items)
        else:
            ingredients.difference_update(items)
        food.delete(0, "end")
        refresh()

    def find():
        load_dotenv(settings, override=True)
        query = request.get().strip()
        find_button.state(["disabled"])
        show("Looking for recipes and waiting for the meal service...")
        task = pool.submit(run, query, sorted(ingredients))

        def check():
            if not task.done():
                window.after(100, check)
                return
            try:
                show(task.result())
            except APITimeoutError as error:
                if isinstance(error.__cause__, ConnectTimeout):
                    show("Could not connect to the meal service. Try another network "
                         "or check your VPN settings.")
                else:
                    show("The meal service connected but took too long to answer. "
                         "Try again in a moment.")
            except APIConnectionError:
                show("Could not connect to the meal service. Check your connection "
                     "and try again.")
            except (APIError, OutputParserException, ValueError, psycopg.Error) as error:
                show(f"Could not find a meal. {error}")
            finally:
                find_button.state(["!disabled"])

        window.after(100, check)

    ttk.Button(edit, text="Add", command=lambda: edit_pantry("add")).pack(side="left")
    ttk.Button(edit, text="Remove", command=lambda: edit_pantry("remove")).pack(side="left", padx=6)
    find_button = ttk.Button(actions, text="Find meal", command=find)
    find_button.pack(side="left")
    def settings_window():
        dialog = tk.Toplevel(window)
        dialog.title("Settings")
        box = ttk.Frame(dialog, padding=16)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="API key").pack(anchor="w")
        key = ttk.Entry(box, show="*", width=36)
        key.pack(pady=6)
        key.focus_set()

        def save_key():
            value = key.get().strip()
            if value:
                set_key(settings, "API_KEY", value)
                dialog.destroy()
                show("API key saved")

        ttk.Button(box, text="Save", command=save_key).pack(anchor="w")

    ttk.Button(actions, text="Settings", command=settings_window).pack(side="left", padx=6)
    request.bind("<Return>", lambda event: find_button.invoke())
    refresh()
    try:
        library.configure(text=f"{recipe_count()} recipes in the library")
        show("Add what you have, then click Find meal.")
    except psycopg.Error as error:
        show(str(error))
    food.focus_set()
    window.mainloop()
    pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
