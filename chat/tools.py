"""Tools the KAI agent can call — its hands.

Each tool is a plain Python function returning a STRING (tool results
go back to the model as text). TOOL_SCHEMAS describes the tools in the
OpenAI function-calling format so the model knows they exist and what
arguments they take. run_tool is the single dispatch point: the agent
loop never calls tool functions directly.

Safety: the calculator parses the expression into an AST and only
allows arithmetic nodes — no eval(), no names, no calls — so a model
(or a prompt injection) cannot turn it into code execution.
"""

import ast
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------- schemas

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluate an arithmetic expression exactly. Use for any "
                "maths instead of guessing: +, -, *, /, %, **, "
                "parentheses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "e.g. '45000 * 0.18' or '(1200/7)**2'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": (
                "Get the current date and time (server local time). Use "
                "whenever the user asks about today, dates, or deadlines."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weather",
            "description": (
                "Get the current weather and today's forecast for a city "
                "anywhere in the world (temperature, conditions, rain)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Delhi' or 'Mumbai'",
                    }
                },
                "required": ["city"],
            },
        },
    },
]

# ---------------------------------------------------------------- calculator

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        return left**right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("only arithmetic is allowed")


def calculator(expression):
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression} = {result}"
    except Exception as exc:
        return f"Calculator error: {exc}"


# ---------------------------------------------------------------- datetime

def current_datetime():
    now = datetime.now().astimezone()
    return now.strftime("Today is %A, %d %B %Y. Local time: %H:%M (%Z).")


# ---------------------------------------------------------------- weather

def _get_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "KAI/2.0 (personal assistant)"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "light drizzle",
    53: "drizzle",
    55: "drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "light showers",
    81: "showers",
    82: "violent showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def weather(city):
    """Open-Meteo: free, no API key. Geocode the city, then forecast."""
    try:
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode(
                {"name": city, "count": 1, "language": "en", "format": "json"}
            )
        )
        results = geo.get("results") or []
        if not results:
            return f"Weather error: could not find a city named '{city}'."
        place = results[0]
        forecast = _get_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": 1,
                }
            )
        )
        current = forecast["current"]
        daily = forecast["daily"]
        condition = _WEATHER_CODES.get(current["weather_code"], "unknown")
        rain = daily["precipitation_probability_max"][0]
        return (
            f"Weather in {place['name']}, {place.get('country', '')}: "
            f"{current['temperature_2m']}°C, {condition}, "
            f"humidity {current['relative_humidity_2m']}%, "
            f"wind {current['wind_speed_10m']} km/h. "
            f"Today: high {daily['temperature_2m_max'][0]}°C, "
            f"low {daily['temperature_2m_min'][0]}°C, "
            f"rain probability {rain}%."
        )
    except Exception as exc:
        return f"Weather error: {exc}"


# ---------------------------------------------------------------- dispatch

_TOOLS = {
    "calculator": calculator,
    "current_datetime": current_datetime,
    "weather": weather,
}


def run_tool(name, args):
    """Run one tool by name with a dict of arguments. Always returns a
    string — unknown tools and bad arguments become error text the
    model can react to, never an exception."""
    function = _TOOLS.get(name)
    if function is None:
        return f"Error: unknown tool '{name}'."
    try:
        return str(function(**(args or {})))
    except TypeError as exc:
        return f"Error: bad arguments for {name}: {exc}"
    except Exception as exc:  # a tool must never kill the agent loop
        return f"Error: {name} failed: {exc}"
