"""
Home Meal Planner App - Simple At-Home Meal Plan Generator
- Inputs: TDEE (or compute from BMR stats) + activity level, days (1-7), meals/day, dietary prefs
- Output: Daily plan at 25% deficit, grocery list, and downloadable PDF (with per-meal steps)
- Embeddable UI (single-file Flask app using render_template_string)
"""
from __future__ import annotations
import os, sys, math, random, io, re, argparse, datetime, unittest, json, tempfile
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from flask import Flask, request, render_template_string, send_file, make_response

# Optional PDF deps
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Detect availability of the native multiprocessing extension so we can choose safe run settings
try:
    import _multiprocessing  # type: ignore
    MULTIPROC_AVAILABLE = True
except Exception:
    MULTIPROC_AVAILABLE = False

APP_NAME = "Home Meal Planner"
ALLOWED_EMBED_DOMAIN = None  # e.g., "https://your-ghl-site.com" to lock down with CSP

app = Flask(__name__)

# -----------------------------
# Activity multipliers
# -----------------------------
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "very": 1.725,
    "athlete": 1.9,
}

# -----------------------------
# Meal database (expanded + micro "macro lever" snacks)
# Each item: name, meal_type, K (kcal), P/C/F (g), tags, ingredients, instructions (list[str])
# -----------------------------
MEALS: List[Dict[str, Any]] = [
    # ===== BREAKFASTS =====
    {"name":"Greek Yogurt Parfait","meal_type":"breakfast","K":320,"P":28,"C":38,"F":6,
     "tags":["breakfast","quick","high_protein"],
     "ingredients":["2 cups 0% Greek yogurt","1/2 cup berries","1/4 cup granola","1 tbsp honey"],
     "instructions":["Add half the yogurt to a bowl.","Layer berries and granola.","Top with remaining yogurt and drizzle honey."]},
    {"name":"Veggie Egg Scramble + Toast","meal_type":"breakfast","K":360,"P":24,"C":32,"F":14,
     "tags":["breakfast","quick"],
     "ingredients":["3 eggs","1 cup peppers/onion","1 tsp olive oil","1 slice whole-grain bread"],
     "instructions":["Heat oil in a nonstick pan.","Sauté veggies 2–3 min.","Scramble in eggs until set.","Toast bread and serve."]},
    {"name":"Protein Oats","meal_type":"breakfast","K":400,"P":30,"C":50,"F":9,
     "tags":["breakfast","high_protein","quick"],
     "ingredients":["1/2 cup oats","1 scoop whey","1 cup almond milk","1 banana"],
     "instructions":["Microwave oats with milk 2 min.","Stir in protein powder.","Slice banana on top."]},
    {"name":"Tofu Scramble Wrap","meal_type":"breakfast","K":380,"P":24,"C":44,"F":12,
     "tags":["breakfast","vegan","dairy_free","high_protein","quick"],
     "ingredients":["6 oz firm tofu","1 small whole-grain tortilla","1/2 cup spinach","1/4 cup salsa"],
     "instructions":["Crumble tofu into hot pan.","Cook 4–5 min, add spinach.","Fill tortilla and add salsa."]},
    {"name":"Egg-White Veggie Omelet","meal_type":"breakfast","K":260,"P":28,"C":16,"F":8,
     "tags":["breakfast","low_carb","quick","high_protein"],
     "ingredients":["6 egg whites","1 cup mushrooms/spinach","nonstick spray"],
     "instructions":["Spray pan and cook veggies 2–3 min.","Add egg whites and fold when set."]},
    {"name":"Breakfast Burrito (HP)","meal_type":"breakfast","K":650,"P":42,"C":62,"F":22,
     "tags":["breakfast","high_protein"],
     "ingredients":["1 large tortilla","3 eggs","3 oz turkey sausage","1/4 cup cheese","salsa"],
     "instructions":["Cook sausage.","Scramble eggs.","Fill tortilla with eggs, sausage, cheese and salsa; roll."]},
    {"name":"Green Smoothie Bowl","meal_type":"breakfast","K":300,"P":20,"C":42,"F":7,
     "tags":["breakfast","vegetarian","quick"],
     "ingredients":["1 scoop vanilla protein","1 cup spinach","1/2 banana","1/2 cup frozen mango","1 cup almond milk","2 tbsp granola"],
     "instructions":["Blend protein, fruit, spinach and milk.","Pour into bowl; sprinkle granola."]},
    {"name":"Big Protein Smoothie","meal_type":"breakfast","K":600,"P":45,"C":70,"F":14,
     "tags":["breakfast","high_protein","quick"],
     "ingredients":["2 scoops whey","1 banana","2 tbsp peanut butter","1.5 cups milk"],
     "instructions":["Blend all ingredients 45–60 sec until smooth."]},
    {"name":"Overnight Oats (lite)","meal_type":"breakfast","K":280,"P":16,"C":44,"F":6,
     "tags":["breakfast","vegetarian","budget"],
     "ingredients":["1/3 cup oats","1/2 cup milk","1/2 cup yogurt","cinnamon"],
     "instructions":["Mix all in jar.","Refrigerate overnight.","Stir and eat cold."]},

    # ===== LUNCHES =====
    {"name":"Chicken Burrito Bowl","meal_type":"lunch","K":520,"P":45,"C":58,"F":12,
     "tags":["lunch","high_protein","quick"],
     "ingredients":["6 oz chicken","3/4 cup brown rice","1/2 cup black beans","pico","lettuce"],
     "instructions":["Warm rice and beans.","Top with sliced cooked chicken, pico and lettuce."]},
    {"name":"Turkey Avocado Sandwich","meal_type":"lunch","K":480,"P":36,"C":46,"F":16,
      "tags":["lunch","quick"],
      "ingredients":["2 slices whole-grain bread","5 oz turkey","1/4 avocado","lettuce","tomato","mustard"],
      "instructions":["Toast bread.","Layer turkey, avocado, veg and mustard; slice."]},
    {"name":"Chickpea Salad Bowl","meal_type":"lunch","K":450,"P":20,"C":55,"F":14,
     "tags":["lunch","vegetarian","high_protein","budget"],
     "ingredients":["1 cup chickpeas","mixed greens","cucumber","tomato","light vinaigrette"],
     "instructions":["Rinse chickpeas.","Toss all ingredients with dressing."]},
    {"name":"Tuna Rice Bowl","meal_type":"lunch","K":520,"P":42,"C":60,"F":12,
     "tags":["lunch","high_protein","quick","budget"],
     "ingredients":["1 can tuna","3/4 cup rice","1/2 cup corn","light mayo","sriracha"],
     "instructions":["Mix tuna with a little mayo.","Serve over warm rice with corn and sriracha."]},
    {"name":"Grilled Chicken Salad (LC)","meal_type":"lunch","K":350,"P":38,"C":18,"F":12,
     "tags":["lunch","low_carb","high_protein"],
     "ingredients":["5 oz grilled chicken","big salad mix","cherry tomatoes","cucumber","light vinaigrette"],
     "instructions":["Slice chicken.","Toss everything with vinaigrette."]},
    {"name":"Soba Noodle Bowl","meal_type":"lunch","K":640,"P":30,"C":85,"F":18,
     "tags":["lunch","vegetarian"],
     "ingredients":["2 oz dry soba","edamame","shredded carrots","sesame dressing"],
     "instructions":["Cook soba per package.","Rinse and toss with toppings and dressing."]},
    {"name":"Turkey & Rice Meal Prep","meal_type":"lunch","K":700,"P":45,"C":80,"F":18,
     "tags":["lunch","high_protein","budget"],
     "ingredients":["6 oz lean ground turkey","1 cup cooked rice","1/2 cup peas","BBQ sauce"],
     "instructions":["Brown turkey.","Serve over rice with peas and drizzle of BBQ."]},
    {"name":"Lentil Soup + Toast","meal_type":"lunch","K":430,"P":24,"C":62,"F":10,
     "tags":["lunch","vegetarian","budget"],
     "ingredients":["1.5 cups lentil soup","1 slice whole-grain bread"],
     "instructions":["Heat soup.","Toast bread and serve on side."]},
    {"name":"High-Cal Chicken Pesto Pasta","meal_type":"lunch","K":820,"P":48,"C":88,"F":26,
     "tags":["lunch","high_protein"],
     "ingredients":["3 oz dry pasta","6 oz chicken","2 tbsp pesto","spinach"],
     "instructions":["Boil pasta.","Sauté chicken.","Toss all with pesto and spinach."]},

    # ===== DINNERS =====
    {"name":"Salmon, Quinoa, Broccoli","meal_type":"dinner","K":560,"P":42,"C":50,"F":18,
     "tags":["dinner","high_protein"],
     "ingredients":["6 oz salmon","3/4 cup quinoa","1.5 cups broccoli","lemon","olive oil"],
     "instructions":["Bake salmon 10–12 min at 400°F (200°C).","Microwave or steam broccoli.","Serve with cooked quinoa and lemon."]},
    {"name":"Turkey Chili (1 bowl)","meal_type":"dinner","K":540,"P":40,"C":48,"F":18,
     "tags":["dinner","high_protein","budget"],
     "ingredients":["8 oz lean turkey","kidney beans","tomato sauce","onion","spices"],
     "instructions":["Brown turkey with onion.","Add sauce, beans and spices; simmer 10–15 min."]},
    {"name":"Tofu Stir-Fry + Rice","meal_type":"dinner","K":520,"P":28,"C":62,"F":16,
     "tags":["dinner","vegan","dairy_free","high_protein","quick"],
     "ingredients":["6 oz tofu","mixed veg","1 tbsp soy sauce","3/4 cup rice"],
     "instructions":["Stir-fry tofu and veg 6–8 min.","Add soy sauce; serve over rice."]},
    {"name":"Chicken Pasta Primavera","meal_type":"dinner","K":560,"P":44,"C":62,"F":12,
     "tags":["dinner","high_protein"],
     "ingredients":["6 oz chicken","2 cups mixed veg","2 oz dry pasta","marinara"],
     "instructions":["Boil pasta.","Sauté chicken and veg.","Combine with marinara."]},
    {"name":"Shrimp Alfredo (lighter)","meal_type":"dinner","K":680,"P":42,"C":72,"F":20,
     "tags":["dinner"],
     "ingredients":["7 oz shrimp","2 oz dry fettuccine","light alfredo sauce"],
     "instructions":["Boil pasta.","Sauté shrimp 3–4 min.","Toss with warmed sauce."]},
    {"name":"Steak, Potatoes & Asparagus","meal_type":"dinner","K":750,"P":50,"C":70,"F":25,
     "tags":["dinner","high_protein","gluten_free"],
     "ingredients":["7 oz sirloin","8 oz potatoes","1 cup asparagus","1 tsp olive oil"],
     "instructions":["Roast potatoes 20–25 min at 425°F (220°C).","Sear steak 3–4 min/side; rest.","Sauté asparagus 3–4 min."]},
    {"name":"Vegan Chickpea Curry","meal_type":"dinner","K":680,"P":24,"C":90,"F":22,
     "tags":["dinner","vegan","dairy_free","budget"],
     "ingredients":["1 cup chickpeas","1 cup light coconut milk","curry paste","1 cup rice"],
     "instructions":["Simmer coconut milk with curry paste.","Add chickpeas 8–10 min.","Serve over rice."]},
    {"name":"Zoodle Turkey Bolognese (LC)","meal_type":"dinner","K":340,"P":32,"C":18,"F":12,
     "tags":["dinner","low_carb","high_protein"],
     "ingredients":["6 oz lean turkey","zucchini noodles","marinara"],
     "instructions":["Brown turkey.","Heat marinara and toss with zoodles 2–3 min."]},
    {"name":"Stuffed Sweet Potato (HP)","meal_type":"dinner","K":620,"P":34,"C":78,"F":18,
     "tags":["dinner","high_protein","vegetarian"],
     "ingredients":["1 large sweet potato","1 cup black beans","Greek yogurt","green onions"],
     "instructions":["Microwave potato 6–8 min until soft.","Split and top with warm beans, yogurt and onions."]},

    # ===== SNACKS =====
    {"name":"Apple + Peanut Butter","meal_type":"snack","K":240,"P":7,"C":28,"F":12,
     "tags":["snack","budget","quick"],
     "ingredients":["1 apple","1.5 tbsp peanut butter"],
     "instructions":["Slice apple and dip in peanut butter."]},
    {"name":"Cottage Cheese + Pineapple","meal_type":"snack","K":220,"P":24,"C":22,"F":5,
     "tags":["snack","high_protein","quick"],
     "ingredients":["1 cup low-fat cottage cheese","1/2 cup pineapple"],
     "instructions":["Spoon cottage cheese into a bowl and top with pineapple."]},
    {"name":"Protein Shake","meal_type":"snack","K":180,"P":24,"C":6,"F":5,
     "tags":["snack","high_protein","quick"],
     "ingredients":["1 scoop whey","water or milk"],
     "instructions":["Shake or blend until smooth."]},
    {"name":"Hummus + Carrots","meal_type":"snack","K":200,"P":6,"C":22,"F":10,
     "tags":["snack","vegan","dairy_free","budget","quick"],
     "ingredients":["1/4 cup hummus","1 cup carrots"],
     "instructions":["Dip carrots in hummus and enjoy."]},
    {"name":"Rice Cake + Turkey","meal_type":"snack","K":180,"P":14,"C":18,"F":4,
     "tags":["snack","high_protein","low_carb","quick"],
     "ingredients":["1 rice cake","3 oz sliced turkey","mustard"],
     "instructions":["Spread mustard and layer turkey on rice cake."]},
    {"name":"Trail Mix (controlled)","meal_type":"snack","K":300,"P":10,"C":28,"F":16,
     "tags":["snack","vegetarian","budget"],
     "ingredients":["1/4 cup mixed nuts","2 tbsp raisins"],
     "instructions":["Portion into a small bowl and eat mindfully."]},
    {"name":"Greek Yogurt + PB + Cocoa","meal_type":"snack","K":280,"P":24,"C":18,"F":10,
     "tags":["snack","high_protein"],
     "ingredients":["1 cup Greek yogurt","1 tbsp peanut butter","1 tsp cocoa powder"],
     "instructions":["Mix PB and cocoa into yogurt until smooth."]},
    {"name":"Avocado Toast (lite)","meal_type":"snack","K":260,"P":7,"C":28,"F":12,
     "tags":["snack","vegetarian"],
     "ingredients":["1 slice whole-grain bread","1/4 avocado","lemon","salt"],
     "instructions":["Toast bread.","Mash avocado with lemon and salt; spread."]},

    # --- micro “macro levers” for final adjustments ---
    {"name":"Banana","meal_type":"snack","K":105,"P":1,"C":27,"F":0,
     "tags":["snack","quick","carb_boost"],
     "ingredients":["1 medium banana"],"instructions":["Peel and eat."]},
    {"name":"Plain Rice Cup","meal_type":"snack","K":200,"P":4,"C":45,"F":0,
     "tags":["snack","quick","carb_boost","gluten_free"],
     "ingredients":["1 cup cooked white rice"],"instructions":["Microwave-safe cup; heat if desired."]},
    {"name":"Chicken Breast Bites","meal_type":"snack","K":120,"P":26,"C":0,"F":2,
     "tags":["snack","high_protein","protein_boost","gluten_free","quick"],
     "ingredients":["4 oz cooked chicken breast, cubed"],"instructions":["Keep pre-cooked in fridge; eat chilled or warm."]},
        # --- High-Protein Power Pack (for 40% P macro support) ---
    {"name":"Chicken Breast + Greens (LC)","meal_type":"lunch","K":380,"P":52,"C":18,"F":10,
     "tags":["lunch","high_protein","low_carb","quick","gluten_free"],
     "ingredients":["7 oz chicken breast","2 cups mixed greens","1/2 cup cherry tomatoes","2 tbsp light vinaigrette"],
     "instructions":["Grill or pan-sear chicken 4–6 min/side.","Toss greens and tomatoes with vinaigrette.","Slice chicken and serve on top."]},
    {"name":"Turkey Egg-White Scramble","meal_type":"breakfast","K":320,"P":46,"C":18,"F":6,
     "tags":["breakfast","high_protein","low_carb","quick"],
     "ingredients":["5 egg whites","2 oz lean turkey","1/2 cup peppers/onion","nonstick spray"],
     "instructions":["Spray pan and sauté veg 2–3 min.","Add turkey, then egg whites; scramble until set."]},
    {"name":"Shrimp & Veggie Stir-Fry (LC)","meal_type":"dinner","K":410,"P":48,"C":24,"F":10,
     "tags":["dinner","high_protein","low_carb","quick","gluten_free","dairy_free"],
     "ingredients":["7 oz shrimp","2 cups mixed veg","1 tbsp soy sauce or coco aminos","1 tsp sesame oil"],
     "instructions":["Stir-fry veg 3–4 min.","Add shrimp 2–3 min until pink.","Finish with soy sauce and sesame oil."]},
    {"name":"Skyr Cup + Berries","meal_type":"snack","K":170,"P":24,"C":16,"F":1,
     "tags":["snack","high_protein","quick"],
     "ingredients":["1 cup plain skyr (or 0% Greek yogurt)","1/3 cup berries"],
     "instructions":["Spoon skyr into a cup.","Top with berries."]},
    {"name":"Cottage Cheese Bowl (Lean)","meal_type":"snack","K":190,"P":28,"C":10,"F":4,
     "tags":["snack","high_protein","quick"],
     "ingredients":["1 cup low-fat cottage cheese","cucumber slices","pepper"],
     "instructions":["Add cottage cheese to a bowl.","Top with cucumber and pepper."]},
    {"name":"High-Protein Chicken Wrap","meal_type":"lunch","K":430,"P":48,"C":36,"F":10,
     "tags":["lunch","high_protein","quick"],
     "ingredients":["1 high-protein tortilla","5 oz cooked chicken breast","lettuce","tomato","mustard"],
     "instructions":["Layer chicken and veg in tortilla.","Add mustard and wrap."]},
    {"name":"Lean Beef & Veg Plate","meal_type":"dinner","K":500,"P":50,"C":34,"F":16,
     "tags":["dinner","high_protein","gluten_free"],
     "ingredients":["6 oz 93% lean ground beef","2 cups zucchini/peppers","salt","pepper"],
     "instructions":["Brown beef 5–7 min.","Sauté veg 4–5 min.","Season and plate together."]}

]

MEAL_TYPES = ["breakfast","lunch","dinner","snack"]

# ---- Macro levers (tiny "adjustment" snacks) ----
MACRO_LEVERS = {
    "P": {"name":"Adj: Whey in Water","meal_type":"snack","K":110,"P":24,"C":3,"F":1,
          "tags":["adjustment","high_protein","quick"],
          "ingredients":["1 scoop whey","water"],
          "instructions":["Shake with water and drink."]},
    "C": {"name":"Adj: Rice Cakes (2)","meal_type":"snack","K":140,"P":2,"C":32,"F":0,
          "tags":["adjustment","quick","low_fat"],
          "ingredients":["2 plain rice cakes"],
          "instructions":["Eat as a quick carb add-on."]},
    "F": {"name":"Adj: Olive Oil (1 tbsp)","meal_type":"snack","K":120,"P":0,"C":0,"F":14,
          "tags":["adjustment","quick","fat_boost","gluten_free","dairy_free","vegan"],
          "ingredients":["1 tbsp extra-virgin olive oil"],
          "instructions":["Drizzle over salad or veggies."]},
}


def macro_rebalance_day(picks, kcal_target, macro_targets, max_adjustments=4):
    """
    Append small 'lever' items and/or drop a conflicting snack so the day
    lands near 40/30/30 ± ~3% while staying ~ within ±3% calories.
    """
    p_t, c_t, f_t = macro_targets
    lower = int(kcal_target * 0.97)
    upper = int(kcal_target * 1.03)

    picks = picks[:]  # work on a copy
    for _ in range(max_adjustments):
        k, p, c, f = _totals(picks)
        dp, dc, df = p_t - p, c_t - c, f_t - f

        # close enough? (grams tolerance scales with target)
        if (abs(dp) <= max(8, p_t * 0.05) and
            abs(dc) <= max(10, c_t * 0.06) and
            abs(df) <= max(5, f_t * 0.06) and
            lower <= k <= upper):
            break

        # fix the biggest miss (by kcal effect)
        errs = [("P", abs(dp*4)), ("C", abs(dc*4)), ("F", abs(df*9))]
        errs.sort(key=lambda x: x[1], reverse=True)
        key = errs[0][0]

        # add a lever toward the worst macro
        lever = dict(MACRO_LEVERS[key])  # copy
        lever["tags"] = lever.get("tags", []) + ["adjustment"]
        picks.append(lever)

        # if kcal now too high, try dropping a conflicting snack
        k, p, c, f = _totals(picks)
        if k > upper:
            over_key = "C" if c > c_t else ("F" if f > f_t else "K")
            snack_ix, best_score = None, -1
            for i, m in enumerate(picks):
                if m["meal_type"] != "snack" or "adjustment" in m.get("tags", []):
                    continue
                score = m["C"] if over_key == "C" else (m["F"]*9 if over_key == "F" else m["K"])
                if score > best_score:
                    best_score, snack_ix = score, i
            if snack_ix is not None:
                picks.pop(snack_ix)
            else:
                # nothing to drop? back out the lever we just added
                picks.pop()

    return picks


# -----------------------------
# Utility functions
# -----------------------------

def mifflin_st_jeor(sex: str, age: int, height_cm: float, weight_kg: float) -> float:
    if sex.lower() == "male":
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

def compute_tdee(bmr: float, activity: str) -> float:
    factor = ACTIVITY_FACTORS.get(activity, 1.2)
    return bmr * factor

def grams_from_kcal(target_kcal: float, p_ratio=0.40, c_ratio=0.30, f_ratio=0.30) -> Tuple[int,int,int]:
    """40/30/30 by default."""
    p_g = round((target_kcal * p_ratio) / 4)
    c_g = round((target_kcal * c_ratio) / 4)
    f_g = round((target_kcal * f_ratio) / 9)
    return p_g, c_g, f_g

def filter_meals(prefs: Dict[str,Any]) -> List[Dict[str,Any]]:
    selected = []
    excludes = set([x.strip().lower() for x in prefs.get("excludes","" ).split(',') if x.strip()])
    for m in MEALS:
        t = set(m.get("tags",[]))
        if prefs.get("vegetarian") and not ("vegetarian" in t or "vegan" in t):
            continue
        if prefs.get("vegan") and "vegan" not in t:
            continue
        if prefs.get("dairy_free") and "dairy_free" not in t and "vegan" not in t:
            continue
        # naive GF handling; extend tags in DB as needed
        if excludes:
            text = (m["name"] + " " + " ".join(m.get("ingredients",[]))).lower()
            if any(x in text for x in excludes):
                continue
        selected.append(m)
    return selected

def _totals(picks: List[Dict[str,Any]]) -> Tuple[int,int,int,int]:
    k = sum(m["K"] for m in picks)
    p = sum(m["P"] for m in picks)
    c = sum(m["C"] for m in picks)
    f = sum(m["F"] for m in picks)
    return k,p,c,f

def _score_plan(picks, kcal_target, p_target, c_target, f_target):
    """Lower is better. Strongly favors protein hitting target; penalizes carb overages.
       Also adds a small penalty when the average protein density (P per kcal) is low."""
    k = sum(m["K"] for m in picks)
    p = sum(m["P"] for m in picks)
    c = sum(m["C"] for m in picks)
    f = sum(m["F"] for m in picks)

    # Relative errors/penalties
    kcal_err = abs(k - kcal_target) / max(1, kcal_target)

    # Protein: under-shoot is heavily punished; overshoot lightly punished (we prefer slightly high protein)
    p_under = max(0.0, (p_target - p) / max(1.0, p_target))
    p_over  = max(0.0, (p - p_target) / max(1.0, p_target)) * 0.25

    # Carbs: we mostly care about not going too high
    c_over  = max(0.0, (c - c_target) / max(1.0, c_target))
    c_under = max(0.0, (c_target - c) / max(1.0, c_target)) * 0.40  # small penalty (low-carb days are OK)

    # Fat: symmetric but lighter weight than protein/carbs
    f_err   = abs(f - f_target) / max(1.0, f_target) * 0.60

    # Protein density bonus: encourage meals with more P per kcal
    avg_pd = (sum(m["P"] / max(1, m["K"]) for m in picks) / len(picks)) if picks else 0.0
    density_bonus = max(0.0, 0.10 - avg_pd)  # if avg < 0.10 P/kcal, nudge upward

    return (
        kcal_err * 30
        + p_under * 120
        + p_over  * 15
        + c_over  * 80
        + c_under * 25
        + f_err
        + density_bonus * 40
    )


def pick_day_plan(target_kcal: int, meals_db: List[Dict[str,Any]], meals_per_day: int,
                  macro_targets: Optional[Tuple[int,int,int]] = None) -> Tuple[List[Dict[str,Any]], int]:
    """Macro-aware selection: starts with high-protein picks per meal type, then refines with swaps.
       Aims for kcal ±5% AND grams near the 40/30/30 daily targets."""
    if not meals_db:
        return [], 0

    p_t, c_t, f_t = macro_targets if macro_targets else (0, 0, 0)

    # Helper: protein density
    def pd(m: Dict[str,Any]) -> float:
        return m["P"] / max(1.0, m["K"])

    # Buckets by type sorted by protein density
    MEAL_TYPES_LOCAL = ["breakfast", "lunch", "dinner", "snack"]
    by_type: Dict[str,List[Dict[str,Any]]] = {mt: [] for mt in MEAL_TYPES_LOCAL}
    for m in meals_db:
        by_type.setdefault(m["meal_type"], []).append(m)

    sorted_global = sorted(meals_db, key=pd, reverse=True)
    sorted_by_type = {mt: sorted(bucket, key=pd, reverse=True) for mt, bucket in by_type.items()}

    # Build the sequence we want to fill
    if meals_per_day >= 3:
        seq = ["breakfast", "lunch", "dinner"] + ["snack"] * (meals_per_day - 3)
    elif meals_per_day == 2:
        seq = ["lunch", "dinner"]
    else:
        seq = ["dinner"]

    # Seed with high-protein options per slot
    picks: List[Dict[str,Any]] = []
    total_k = 0
    for mt in seq:
        bucket = sorted_by_type.get(mt) or sorted_global
        cutoff = max(3, len(bucket) // 2) if len(bucket) > 3 else len(bucket)  # prefer top half by PD
        candidate_pool = bucket[:cutoff] if cutoff else bucket
        choice = random.choice(candidate_pool) if candidate_pool else random.choice(sorted_global)
        picks.append(choice)
        total_k += choice["K"]

    # Hill-climb with swaps to improve score
    attempts = 350
    best_score = _score_plan(picks, target_kcal, p_t, c_t, f_t)
    lower = int(target_kcal * 0.95)
    upper = int(target_kcal * 1.05)

    while attempts > 0:
        attempts -= 1
        idx = random.randrange(len(picks))
        mt = picks[idx]["meal_type"]
        bucket = sorted_by_type.get(mt) or sorted_global
        top_span = max(5, len(bucket) // 2) if len(bucket) > 5 else len(bucket)
        candidate = random.choice(bucket[:top_span]) if top_span else random.choice(sorted_global)

        trial = picks[:]
        trial[idx] = candidate
        new_score = _score_plan(trial, target_kcal, p_t, c_t, f_t)
        if new_score < best_score:
            picks = trial
            best_score = new_score
            total_k = sum(m["K"] for m in picks)

            # early exit if we’re within kcal and each macro is close
            kcal_ok = lower <= total_k <= upper
            p_ok = abs(sum(m["P"] for m in picks) - p_t) <= max(6, 0.06 * p_t)
            c_ok = abs(sum(m["C"] for m in picks) - c_t) <= max(8, 0.08 * c_t)
            f_ok = abs(sum(m["F"] for m in picks) - f_t) <= max(6, 0.06 * f_t)
            if kcal_ok and p_ok and c_ok and f_ok:
                break

    # Last-mile: if protein still low, replace the weakest (often snack) with a much denser pick
    current_P = sum(m["P"] for m in picks)
    if current_P < p_t - max(8, 0.06 * p_t):
        indices = list(range(len(picks)))
        snack_idxs = [i for i in indices if picks[i]["meal_type"] == "snack"]
        pool_idxs = snack_idxs if snack_idxs else indices
        victim_idx = min(pool_idxs, key=lambda i: pd(picks[i]))
        victim_type = picks[victim_idx]["meal_type"]
        candidate_bucket = sorted_by_type.get(victim_type) or sorted_global
        # grab a meaningfully denser item than the victim (or fall back to top)
        hp_candidate = next(
            (m for m in candidate_bucket if pd(m) >= pd(picks[victim_idx]) * 1.25),
            candidate_bucket[0]
        )
        picks[victim_idx] = hp_candidate
        total_k = sum(m["K"] for m in picks)

    return picks, total_k

def aggregate_grocery_list(plan: List[List[Dict[str,Any]]]) -> Dict[str,int]:
    counts: Dict[str,int] = {}
    for day in plan:
        for meal in day:
            for item in meal.get("ingredients", []):
                counts[item] = counts.get(item, 0) + 1
    return counts

# -----------------------------
# HTML
# -----------------------------
HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{{ app_name }}</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Helvetica,Arial,sans-serif;background:#0b1220;color:#e8eefc;margin:0}
    .wrap{max-width:1100px;margin:0 auto;padding:24px}
    .card{background:#101b33;border:1px solid #1f2b4a;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.35);padding:24px}
    .grid{display:grid;gap:16px}
    @media(min-width:900px){.grid-2{grid-template-columns:1fr 1fr}}
    label{font-weight:600}
    input,select,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid #243559;background:#0f192d;color:#e8eefc}
    .btn{display:inline-block;background:#6aa2ff;color:#081126;border:none;border-radius:12px;padding:12px 16px;font-weight:700;cursor:pointer}
    .btn.secondary{background:#1f2b4a;color:#cfe0ff;border:1px solid #2b3d67}
    .pill{display:inline-block;padding:6px 10px;border-radius:999px;background:#1e335c;border:1px solid #2b3d67;font-size:12px;margin-right:6px}
    .muted{color:#9db2d9}
    .kpi{font-size:14px}
    .meal{background:#0f192d;border:1px solid #1f2b4a;border-radius:12px;padding:12px;margin:8px 0}
    .flex{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
    .right{float:right}
    .center{text-align:center}
  </style>
  {% if csp %}<meta http-equiv="Content-Security-Policy" content="frame-ancestors {{ csp }} 'self';">{% endif %}
</head>
<body>
<div class="wrap">
  <h1 style="margin:0 0 10px 0">🏠 {{ app_name }}</h1>
  <p class="muted">Simple at-home meal plan generator. Enter TDEE directly, or provide stats to calculate it. The plan targets a <b>25% deficit</b> for weight loss and builds a grocery list.</p>

  <div class="grid grid-2">
    <form class="card" method="post" action="{{ url_for('generate') }}">
      <h2 style="margin-top:0">Inputs</h2>
      <div class="grid grid-2">
        <div>
          <label>TDEE (kcal)</label>
          <input name="tdee" type="number" step="1" placeholder="e.g., 2400">
        </div>
        <div>
          <label>Days</label>
          <select name="days">
            {% for d in range(1,8) %}<option value="{{d}}">{{d}}</option>{% endfor %}
          </select>
        </div>
        <div>
          <label>Meals per day</label>
          <select name="meals_per_day">
            {% for m in [2,3,4,5] %}<option value="{{m}}" {% if m==3 %}selected{% endif %}>{{m}}</option>{% endfor %}
          </select>
        </div>
      </div>

      <h3>Or compute from stats</h3>
      <div class="grid grid-2">
        <div>
          <label>Sex</label>
          <select name="sex">
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
        </div>
        <div>
          <label>Age</label>
          <input name="age" type="number" step="1" placeholder="27">
        </div>
        <div>
          <label>Height</label>
          <div class="flex">
            <input name="height_ft" type="number" step="1" placeholder="ft" style="max-width:90px"> 
            <input name="height_in" type="number" step="1" placeholder="in" style="max-width:90px">
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">We’ll convert feet+inches to centimeters automatically.</div>
        </div>
        <div>
          <label>Weight</label>
          <input name="weight_lb" type="number" step="0.1" placeholder="lb">
          <div class="muted" style="font-size:12px;margin-top:4px">We’ll convert pounds to kilograms automatically.</div>
        </div>
        <div>
          <label>Activity</label>
          <select name="activity">
            {% for k,v in activities.items() %}<option value="{{k}}">{{k.title()}}</option>{% endfor %}
          </select>
        </div>
      </div>
      <div class="muted" style="font-size:12px;margin-top:-8px">Prefer metric? You can still use the old fields: height_cm / weight_kg.</div>

      <h3>Preferences</h3>
      <div class="grid grid-2">
        <label><input type="checkbox" name="vegetarian"> Vegetarian</label>
        <label><input type="checkbox" name="vegan"> Vegan</label>
        <label><input type="checkbox" name="dairy_free"> Dairy-free</label>
        <label><input type="checkbox" name="gluten_free"> Gluten-free</label>
      </div>
      <label>Exclusions (comma-separated keywords, e.g., tuna, peanut)</label>
      <input name="excludes" placeholder=""> 

      <div style="margin-top:16px" class="flex">
        <button class="btn" type="submit">Generate Plan</button>
        <a class="btn secondary" href="{{ url_for('index') }}">Reset</a>
      </div>
      <p class="muted" style="margin-top:12px">Tip: Leave TDEE blank and fill stats (ft/in + lb or metric) to auto-calculate using Mifflin-St Jeor, then we apply your activity factor.</p>
    </form>

    <div class="card">
      <h2 style="margin-top:0">What you get</h2>
      <ul>
        <li>Daily plan hitting ~75% of TDEE (±5%)</li>
        <li><b>Macro targets: 40% protein / 30% carbs / 30% fat</b> with macro-aware selection</li>
        <li>Quick, simple meals chosen from a growing database</li>
        <li>Per-meal step-by-step instructions</li>
        <li>Aggregated grocery list / buying guide</li>
        <li>One-click PDF export</li>
      </ul>
    </div>
  </div>

  {% if result %}
  <div class="card" style="margin-top:16px">
    <h2 style="margin-top:0">Your Plan
      <a class="btn right" href="{{ url_for('pdf', token=result.token) }}">Download PDF</a>
    </h2>
    <div class="flex kpi">
      <div class="pill">TDEE: {{ result.tdee }} kcal</div>
      <div class="pill">Target: {{ result.target_kcal }} kcal/day</div>
      <div class="pill">Meals/day: {{ result.meals_per_day }}</div>
      <div class="pill">Days: {{ result.days }}</div>
      <div class="pill">Macros/day: {{ result.p_g }}P / {{ result.c_g }}C / {{ result.f_g }}F (g)</div>
    </div>

    {% for day in result.plan %}
      <h3 style="margin-bottom:8px">Day {{ loop.index }} <span class="muted">(~{{ result.day_totals[loop.index0] }} kcal)</span></h3>
      <div>
        {% for meal in day %}
          <div class="meal">
            <b>{{ meal.name }}</b>
            <div class="muted">{{ meal.meal_type.title() }} • {{ meal.K }} kcal • {{ meal.P }}P / {{ meal.C }}C / {{ meal.F }}F</div>
            {% if meal.instructions %}
            <details style="margin-top:6px">
              <summary class="muted">Steps</summary>
              <ol style="margin:6px 0 0 20px">
                {% for step in meal.instructions %}
                  <li>{{ step }}</li>
                {% endfor %}
              </ol>
            </details>
            {% endif %}
          </div>
        {% endfor %}
      </div>
    {% endfor %}

    <h3>Grocery List</h3>
    <div class="grid grid-2">
      {% for item, qty in result.grocery.items() %}
        <div>• {{ item }} <span class="muted">x{{ qty }}</span></div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <p class="center muted" style="margin-top:20px">© {{ year }} {{ app_name }}. For education only, not medical advice.</p>
</div>
</body>
</html>
"""

# -----------------------------
# Routes
# -----------------------------
@app.after_request
def add_csp(resp):
    if ALLOWED_EMBED_DOMAIN:
        resp.headers['Content-Security-Policy'] = f"frame-ancestors {ALLOWED_EMBED_DOMAIN} 'self'"
    return resp

@app.get('/')
def index():
    return render_template_string(HTML, app_name=APP_NAME, activities=ACTIVITY_FACTORS, result=None, csp=ALLOWED_EMBED_DOMAIN, year=datetime.datetime.now().year)

@dataclass
class Result:
    token: str
    tdee: int
    target_kcal: int
    days: int
    meals_per_day: int
    p_g: int
    c_g: int
    f_g: int
    plan: List[List[Dict[str,Any]]]
    day_totals: List[int]
    grocery: Dict[str,int]

@app.post('/generate')
def generate():
    form = request.form
    # Pull TDEE or compute
    tdee_raw = form.get('tdee', '').strip()
    activity = form.get('activity', 'sedentary')
    if tdee_raw:
        try:
            tdee = int(float(tdee_raw))
        except Exception:
            tdee = 0
    else:
        sex = form.get('sex','male')

        def _to_float(val, default=None):
            try:
                return float(val)
            except Exception:
                return default

        try:
            age = int(form.get('age','30'))
        except Exception:
            age = 30

        # Height (imperial first)
        ft_raw = form.get('height_ft', '').strip()
        in_raw = form.get('height_in', '').strip()
        lb_raw = form.get('weight_lb', '').strip()
        height_cm = None
        weight_kg = None
        ft = _to_float(ft_raw, None)
        inches = _to_float(in_raw, None)
        if ft is not None or inches is not None:
            ft = ft or 0.0
            inches = inches or 0.0
            height_cm = (ft * 12.0 + inches) * 2.54

        # Weight
        lb = _to_float(lb_raw, None)
        if lb is not None:
            weight_kg = lb * 0.45359237

        # Fallback to metric fields if needed
        if height_cm is None:
            height_cm = _to_float(form.get('height_cm','175'), 175.0)
        if weight_kg is None:
            weight_kg = _to_float(form.get('weight_kg','80'), 80.0)

        bmr = mifflin_st_jeor(sex, age, float(height_cm), float(weight_kg))
        tdee = int(round(compute_tdee(bmr, activity)))

    days = max(1, min(7, int(form.get('days','3'))))
    meals_per_day = max(2, min(5, int(form.get('meals_per_day','3'))))

    prefs = {
        "vegetarian": bool(form.get('vegetarian')),
        "vegan": bool(form.get('vegan')),
        "dairy_free": bool(form.get('dairy_free')),
        "gluten_free": bool(form.get('gluten_free')),
        "excludes": form.get('excludes','')
    }

    # 25% deficit
    target_kcal = int(round(tdee * 0.75))

    # 40/30/30 macro targets
    p_g, c_g, f_g = grams_from_kcal(target_kcal)

    # Filter meals for prefs
    pool = filter_meals(prefs) or MEALS[:]

    # Build plan (correctly indented!)
    plan: List[List[Dict[str,Any]]] = []
    day_totals: List[int] = []
    for _ in range(days):
        picks, total = pick_day_plan(target_kcal, pool, meals_per_day, macro_targets=(p_g, c_g, f_g))
        # Tighten to 40/30/30 with tiny adjustment items
        picks = macro_rebalance_day(picks, target_kcal, (p_g, c_g, f_g))
        plan.append(picks)
        day_totals.append(sum(m["K"] for m in picks))  # or use `total` if you prefer pre-adjustment

    grocery = aggregate_grocery_list(plan)

    token = str(random.randint(10**9, 10**10-1))
    _RESULTS[token] = {
        "tdee": tdee,
        "target_kcal": target_kcal,
        "days": days,
        "meals_per_day": meals_per_day,
        "p_g": p_g,
        "c_g": c_g,
        "f_g": f_g,
        "plan": plan,
        "day_totals": day_totals,
        "grocery": grocery,
        "prefs": prefs,
    }

    result = Result(token, tdee, target_kcal, days, meals_per_day, p_g, c_g, f_g, plan, day_totals, grocery)
    return render_template_string(HTML, app_name=APP_NAME, activities=ACTIVITY_FACTORS, result=result, csp=ALLOWED_EMBED_DOMAIN, year=datetime.datetime.now().year)


_RESULTS: Dict[str,Dict[str,Any]] = {}

@app.get('/pdf/<token>')
def pdf(token: str):
    data = _RESULTS.get(token)
    if not data:
        return make_response("Session expired. Please regenerate.", 410)
    if not REPORTLAB_AVAILABLE:
        return make_response("PDF engine not installed. Run: pip install reportlab", 501)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title=f"{APP_NAME} Plan")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Small', fontSize=9, leading=11))
    story: List[Any] = []

    story.append(Paragraph(f"<b>{APP_NAME}</b>", styles['Title']))
    story.append(Paragraph(f"Target: {data['target_kcal']} kcal/day • Days: {data['days']} • Meals/day: {data['meals_per_day']}", styles['Normal']))
    story.append(Paragraph(f"Macros/day: {data['p_g']}P / {data['c_g']}C / {data['f_g']}F (g)", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))

    for i, day in enumerate(data['plan'], start=1):
        story.append(Paragraph(f"<b>Day {i}</b> (~{data['day_totals'][i-1]} kcal)", styles['Heading2']))
        table_data = [["Meal","kcal","P","C","F"]]
        for m in day:
            table_data.append([m['name'], str(m['K']), str(m['P']), str(m['C']), str(m['F'])])
        t = Table(table_data, hAlign='LEFT', colWidths=[3.7*inch, 0.8*inch, 0.6*inch, 0.6*inch, 0.6*inch])
        t.setStyle(TableStyle([
            ('GRID',(0,0),(-1,-1),0.4,colors.grey),
            ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ]))
        story.append(t)
        for m in day:
            steps = m.get('instructions')
            if steps:
                story.append(Paragraph(f"<b>Steps – {m['name']}</b>", styles['Normal']))
                story.append(Paragraph("<br/>".join([f"{idx+1}. {s}" for idx, s in enumerate(steps)]), styles['Small']))
        story.append(Spacer(1, 0.2*inch))

    story.append(PageBreak())
    story.append(Paragraph("<b>Grocery List</b>", styles['Heading2']))
    glines = [f"• {item}  x{qty}" for item, qty in data['grocery'].items()]
    story.append(Paragraph("<br/>".join(glines), styles['Small']))

    doc.build(story)
    buf.seek(0)
    filename = f"meal_plan_{token}.pdf"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype='application/pdf')

# -----------------------------
# OFFLINE helpers
# -----------------------------
def build_plan_from_params(tdee: Optional[int], days: int, meals_per_day: int, activity: str, stats: Optional[Dict[str,Any]], prefs: Dict[str,Any]) -> Dict[str,Any]:
    if not tdee:
        if stats is None:
            stats = {"sex":"male","age":30,"height_cm":175.0,"weight_kg":80.0}
        height_cm = stats.get('height_cm')
        weight_kg = stats.get('weight_kg')
        if height_cm is None and (stats.get('height_ft') is not None or stats.get('height_in') is not None):
            ft = float(stats.get('height_ft') or 0)
            inch = float(stats.get('height_in') or 0)
            height_cm = (ft*12 + inch) * 2.54
        if weight_kg is None and stats.get('weight_lb') is not None:
            weight_kg = float(stats.get('weight_lb')) * 0.45359237
        if height_cm is None: height_cm = 175.0
        if weight_kg is None: weight_kg = 80.0
        bmr = mifflin_st_jeor(stats.get('sex','male'), int(stats.get('age',30)), float(height_cm), float(weight_kg))
        tdee = int(round(compute_tdee(bmr, activity)))
    target_kcal = int(round(tdee * 0.75))
    p_g, c_g, f_g = grams_from_kcal(target_kcal)

    pool = filter_meals(prefs) or MEALS[:]

    plan: List[List[Dict[str,Any]]] = []
    totals: List[int] = []
    for _ in range(days):
        picks, total = pick_day_plan(target_kcal, pool, meals_per_day, macro_targets=(p_g, c_g, f_g))
        plan.append(picks)
        totals.append(total)

    grocery = aggregate_grocery_list(plan)
    return {
        "tdee": tdee,
        "target_kcal": target_kcal,
        "days": days,
        "meals_per_day": meals_per_day,
        "p_g": p_g,
        "c_g": c_g,
        "f_g": f_g,
        "plan": plan,
        "day_totals": totals,
        "grocery": grocery,
    }

def offline_emit(plan: Dict[str,Any], out_pdf: Optional[str], out_html: Optional[str], out_json: Optional[str]) -> None:
    if out_json:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2)
        print(f"Wrote JSON: {out_json}")
    if out_pdf and REPORTLAB_AVAILABLE:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, title=f"{APP_NAME} Plan")
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Small', fontSize=9, leading=11))
        story: List[Any] = []
        story.append(Paragraph(f"<b>{APP_NAME}</b>", styles['Title']))
        story.append(Paragraph(f"Target: {plan['target_kcal']} kcal/day • Days: {plan['days']} • Meals/day: {plan['meals_per_day']}", styles['Normal']))
        story.append(Paragraph(f"Macros/day: {plan['p_g']}P / {plan['c_g']}C / {plan['f_g']}F (g)", styles['Normal']))
        story.append(Spacer(1, 0.2*inch))
        for i, day in enumerate(plan['plan'], start=1):
            story.append(Paragraph(f"<b>Day {i}</b> (~{plan['day_totals'][i-1]} kcal)", styles['Heading2']))
            table_data = [["Meal","kcal","P","C","F"]]
            for m in day:
                table_data.append([m['name'], str(m['K']), str(m['P']), str(m['C']), str(m['F'])])
            t = Table(table_data, hAlign='LEFT', colWidths=[3.7*inch, 0.8*inch, 0.6*inch, 0.6*inch, 0.6*inch])
            t.setStyle(TableStyle([
                ('GRID',(0,0),(-1,-1),0.4,colors.grey),
                ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
            ]))
            story.append(t)
            for m in day:
                steps = m.get('instructions') or []
                if steps:
                    story.append(Paragraph(f"<b>Steps – {m['name']}</b>", styles['Normal']))
                    story.append(Paragraph("<br/>".join([f"{idx+1}. {s}" for idx, s in enumerate(steps)]), styles['Small']))
            story.append(Spacer(1, 0.2*inch))
        story.append(PageBreak())
        story.append(Paragraph("<b>Grocery List</b>", styles['Heading2']))
        glines = [f"• {item}  x{qty}" for item, qty in plan['grocery'].items()]
        story.append(Paragraph("<br/>".join(glines), styles['Small']))
        doc.build(story)
        with open(out_pdf, 'wb') as f:
            f.write(buf.getvalue())
        print(f"Wrote PDF: {out_pdf}")
    elif out_html:
        def esc(x: str) -> str:
            return (x.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'))
        html = ["<html><head><meta charset='utf-8'><title>Plan</title></head><body>"]
        html.append(f"<h1>{esc(APP_NAME)}</h1>")
        html.append(f"<p>Target: {plan['target_kcal']} kcal/day. Days: {plan['days']}. Meals/day: {plan['meals_per_day']}.")
        for i, day in enumerate(plan['plan'], start=1):
            html.append(f"<h2>Day {i} (~{plan['day_totals'][i-1]} kcal)</h2>")
            html.append("<ul>")
            for m in day:
                steps = m.get('instructions') or []
                html.append(
                    "<li>" + f"{esc(m['name'])} - {m['K']} kcal - {m['P']}P/{m['C']}C/{m['F']}F" +
                    ("<details><summary>Steps</summary><ol>" + "".join([f"<li>{esc(s)}</li>" for s in steps]) + "</ol></details>" if steps else "") +
                    "</li>"
                )
            html.append("</ul>")
        html.append("<h2>Grocery List</h2><ul>")
        for item, qty in plan['grocery'].items():
            html.append(f"<li>{esc(item)} x{qty}</li>")
        html.append("</ul></body></html>")
        with open(out_html, 'w', encoding='utf-8') as f:
            f.write("\n".join(html))
        print(f"Wrote HTML: {out_html}")

# -----------------------------
# Tests (only run if RUN_TESTS=1)
# -----------------------------
class AppTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_index_ok(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        # index page renders (we don't assert specific content that requires a generated plan)
        self.assertIn(b'Generate Plan', r.data)

if __name__ == '__main__':
    if os.environ.get('RUN_TESTS') == '1':
        unittest.main()
    else:
        parser = argparse.ArgumentParser(description='Home Meal Planner App')
        parser.add_argument('--offline', action='store_true', help='Generate outputs without starting a server')
        parser.add_argument('--tdee', type=int, default=None)
        parser.add_argument('--days', type=int, default=3)
        parser.add_argument('--meals', type=int, default=3)
        parser.add_argument('--activity', type=str, default='sedentary', choices=list(ACTIVITY_FACTORS.keys()))
        parser.add_argument('--sex', type=str, default='male', choices=['male','female'])
        parser.add_argument('--age', type=int, default=30)
        parser.add_argument('--height_ft', type=float, default=None)
        parser.add_argument('--height_in', type=float, default=None)
        parser.add_argument('--weight_lb', type=float, default=None)
        parser.add_argument('--height_cm', type=float, default=None)
        parser.add_argument('--weight_kg', type=float, default=None)
        parser.add_argument('--out_pdf', type=str, default=None)
        parser.add_argument('--out_html', type=str, default='meal_plan_demo.html')
        parser.add_argument('--out_json', type=str, default=None)
        args = parser.parse_args()

        if args.offline:
            stats = {
                'sex': args.sex,
                'age': args.age,
                'height_ft': args.height_ft,
                'height_in': args.height_in,
                'weight_lb': args.weight_lb,
                'height_cm': args.height_cm,
                'weight_kg': args.weight_kg,
            }
            prefs = {'vegetarian': False, 'vegan': False, 'dairy_free': False, 'gluten_free': False, 'excludes': ''}
            plan = build_plan_from_params(args.tdee, max(1, min(7, args.days)), max(2, min(5, args.meals)), args.activity, stats, prefs)
            offline_emit(plan, args.out_pdf, args.out_html, args.out_json)
            print('[info]: Offline demo generated.')
        else:
            port = int(os.environ.get('PORT', '5000'))
            debug = bool(os.environ.get('DEV_DEBUG'))
            app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False, threaded=True)
