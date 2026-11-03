import json
import os
from typing import TypedDict

from httpx import Timeout
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph


class MealState(TypedDict, total=False):
    request: str
    query: str
    tries: int
    recipes: list[dict]
    choice: dict
    meal: dict | None


def find_meal(request, search):
    key = os.getenv("API_KEY")
    if not key:
        raise ValueError("Add your API key in Settings first.")

    model = ChatOpenAI(
        api_key=key,
        base_url=os.getenv("API_URL", "https://api.gapgpt.app/v1"),
        model=os.getenv("API_MODEL", "gpt-4o-mini"),
        temperature=0,
        max_tokens=180,
        max_retries=0,
        timeout=Timeout(35, connect=7),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Help choose a meal. Use only the recipes provided. Respect the user's "
         "request and prefer meals that need fewer groceries. If the choices are poor "
         "and another search is allowed, return JSON with a search field containing "
         "short English keywords. Otherwise return JSON with a recipe field containing "
         "an exact recipe ID or null if none fits."),
        ("human", "Request: {request}\nAnother search allowed: {retry}\nRecipes: {recipes}"),
    ])
    choose = prompt | model | JsonOutputParser()

    def get_recipes(state):
        return {"recipes": search(state["query"]), "tries": state["tries"] + 1}

    def ask(state):
        options = [
            {name: value for name, value in recipe.items() if name != "directions"}
            for recipe in state["recipes"]
        ]
        choice = choose.invoke({
            "request": state["request"],
            "retry": state["tries"] < 2,
            "recipes": json.dumps(options, ensure_ascii=False),
        })
        if not isinstance(choice, dict):
            raise ValueError("the meal service returned an invalid choice.")
        query = choice.get("search")
        if state["tries"] < 2 and isinstance(query, str) and query.strip():
            return {"choice": choice, "query": query.strip()[:120]}
        if "recipe" not in choice:
            raise ValueError("the meal service did not pick a recipe.")
        return {"choice": {"recipe": choice["recipe"]}}

    def next_step(state):
        return "search" if "search" in state["choice"] else "finish"

    def finish(state):
        recipe_id = state["choice"]["recipe"]
        if recipe_id is None:
            return {"meal": None}
        for recipe in state["recipes"]:
            if recipe["id"] == recipe_id:
                return {"meal": recipe}
        raise ValueError("the meal service picked a recipe outside the search results.")

    graph = StateGraph(MealState)
    graph.add_node("search", get_recipes)
    graph.add_node("choose", ask)
    graph.add_node("finish", finish)
    graph.add_edge(START, "search")
    graph.add_edge("search", "choose")
    graph.add_conditional_edges("choose", next_step, ["search", "finish"])
    graph.add_edge("finish", END)
    return graph.compile().invoke({"request": request, "query": request, "tries": 0})["meal"]
