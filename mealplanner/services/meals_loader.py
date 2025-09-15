
import json, os
from typing import List, Dict, Any
def load_meals(root: str) -> List[Dict[str, Any]]:
    path = os.path.join(root, "mealplanner", "assets", "meals.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
