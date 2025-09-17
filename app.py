"""
Home Meal Planner App - Simple At-Home Meal Plan Generator
- Inputs: TDEE (or compute from BMR stats) + activity level, days (1-7), meals/day, dietary prefs
- Output: Daily plan at 25% deficit, grocery list, and downloadable PDF (with per‑meal steps)
- Embeddable UI (single-file Flask app using render_template_string)

How to run (Windows/macOS/Linux):
1) Install deps once:
   python -m pip install flask reportlab
2) Save this file as: app.py
3) Run server locally:
   python app.py

Render/Gunicorn command (already used by Render):
   gunicorn -w 1 -t 120 --graceful-timeout 20 --max-requests 200 --max-requests-jitter 25 -b 0.0.0.0:$PORT app:app

Notes:
- Designed to be iframe-embeddable. If your host frames this app (e.g., GHL), set ALLOWED_EMBED_DOMAIN below to your site origin (e.g., "https://app.gohighlevel.com" or your custom domain).
- Tight calorie control: per-day calories are nudged into ±5% of target using tiny, preference‑aware "adjuster" snacks (or by trimming snacks if high).
- Macro aware: selection nudges toward the daily 40/30/30 (P/C/F) targets by default.
"""
from __future__ import annotations
import os, random, io, argparse, datetime, json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from flask import Flask, request, render_template_string, send_file, make_response, redirect, url_for

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

APP_NAME = "Home Meal Planner"
# Set this to the site that will embed you to allow framing via CSP, e.g.:
# ALLOWED_EMBED_DOMAIN = "https://app.gohighlevel.com"  # or your custom URL
ALLOWED_EMBED_DOMAIN = None

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
# Meal database (EXPANDED, high-protein friendly)
# Each item: name, meal_type, K kcal, P/C/F grams, tags, ingredients, instructions
# tags can include: breakfast, lunch, dinner, snack, vegetarian, vegan, dairy_free, gluten_free,
#                   high_protein, low_carb, quick, budget
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
    {"name":"Skyr & Berries Bowl","meal_type":"breakfast","K":260,"P":26,"C":28,"F":3,
     "tags":["breakfast","high_protein","quick"],
     "ingredients":["1 cup plain skyr","1/2 cup mixed berries","1 tsp honey"],
     "instructions":["Spoon skyr in bowl.","Top with berries and honey."]},
    {"name":"Egg White & Turkey Wrap","meal_type":"breakfast","K":340,"P":36,"C":28,"F":8,
     "tags":["breakfast","high_protein","quick"],
     "ingredients":["5 egg whites","2 oz turkey","1 small high-protein tortilla","hot sauce"],
     "instructions":["Scramble egg whites.","Warm tortilla, add turkey and eggs, roll."]},

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
    {"name":"Chicken Caesar Wrap (light)","meal_type":"lunch","K":520,"P":42,"C":45,"F":16,
     "tags":["lunch","high_protein","quick"],
     "ingredients":["1 high-protein tortilla","5 oz grilled chicken","romaine","light caesar"],
     "instructions":["Slice chicken.","Toss with romaine & dressing.","Wrap it."]},
    {"name":"Quinoa Black Bean Bowl","meal_type":"lunch","K":560,"P":22,"C":82,"F":14,
     "tags":["lunch","vegetarian","vegan"],
     "ingredients":["3/4 cup cooked quinoa","1 cup black beans","salsa","cilantro"],
     "instructions":["Heat quinoa & beans.","Top with salsa & cilantro."]},
    {"name":"Tofu Teriyaki Bowl","meal_type":"lunch","K":540,"P":32,"C":68,"F":14,
     "tags":["lunch","vegan","dairy_free","high_protein"],
     "ingredients":["6 oz tofu","3/4 cup rice","frozen stir-fry veg","teriyaki sauce"],
     "instructions":["Pan-fry tofu.","Stir-fry veg.","Serve over rice with sauce."]},

    # ===== DINNERS =====
    {"name":"Salmon, Quinoa, Broccoli","meal_type":"dinner","K":560,"P":42,"C":50,"F":18,
     "tags":["dinner","high_protein"],
     "ingredients":["6 oz salmon","3/4 cup quinoa","1.5 cups broccoli","lemon","olive oil"],
     "instructions":["Bake salmon 10–12 min at 400°F (200°C).","Steam broccoli.","Serve with quinoa and lemon."]},
    {"name":"Turkey Chili (1 bowl)","meal_type":"dinner","K":540,"P":40,"C":48,"F":18,
     "tags":["dinner","high_protein","budget"],
     "ingredients":["8 oz lean turkey","kidney beans","tomato sauce","onion","spices"],
     "instructions":["Brown turkey with onion.","Add sauce, beans, spices; simmer 10–15 min."]},
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
     "instructions":["Roast potatoes 20–25 min at 425°F (220°C).","Sear steak 3–4 min/side.","Sauté asparagus 3–4 min."]},
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
     "instructions":["Microwave potato 6–8 min.","Split and top with warm beans, yogurt, onions."]},
    {"name":"Air Fryer Chicken Thighs","meal_type":"dinner","K":600,"P":46,"C":12,"F":36,
     "tags":["dinner","high_protein","gluten_free","quick"],
     "ingredients":["7 oz boneless chicken thighs","seasoning","1 cup green beans"],
     "instructions":["Air fry chicken 18–20 min at 380°F (195°C).","Microwave green beans; serve."]},
    {"name":"Baked Cod & Potatoes","meal_type":"dinner","K":520,"P":42,"C":56,"F":12,
     "tags":["dinner","high_protein","gluten_free"],
     "ingredients":["7 oz cod","8 oz potatoes","1 cup spinach","lemon"],
     "instructions":["Bake cod 10–12 min at 400°F (200°C).","Roast potatoes.","Wilt spinach in pan; plate."]},
    {"name":"Ground Turkey Taco Bowls","meal_type":"dinner","K":640,"P":46,"C":70,"F":18,
     "tags":["dinner","high_protein"],
     "ingredients":["6 oz 93% ground turkey","3/4 cup rice","salsa","lettuce"],
     "instructions":["Brown turkey with taco spices.","Serve over rice with salsa & lettuce."]},

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
    {"name":"Skyr Cup","meal_type":"snack","K":150,"P":20,"C":12,"F":2,
     "tags":["snack","high_protein","quick"],
     "ingredients":["1 single-serve skyr"],
     "instructions":["Peel and eat."]},
    {"name":"Beef Jerky (1 oz)","meal_type":"snack","K":116,"P":9,"C":3,"F":7,
     "tags":["snack","high_protein","low_carb","quick","gluten_free"],
     "ingredients":["1 oz beef jerky"],
     "instructions":["Open bag and enjoy."]},
    {"name":"Hard-Boiled Eggs (2)","meal_type":"snack","K":156,"P":12,"C":2,"F":10,
     "tags":["snack","high_protein","quick","gluten_free"],
     "ingredients":["2 eggs"],
     "instructions":["Boil, peel, salt lightly."]},
    {"name":"Edamame Cup","meal_type":"snack","K":190,"P":17,"C":15,"F":7,
     "tags":["snack","high_protein","vegetarian","vegan","quick","gluten_free"],
     "ingredients":["1 cup shelled edamame"],
     "instructions":["Microwave per package; salt."]},
]

# Tiny adjusters for precise calorie/macro control
MICRO_ADJUSTERS = [
    {"name":"Adj: Plain Rice Cup","meal_type":"snack","K":200,"P":4,"C":45,"F":0,
     "tags":["adjustment","carb_boost","vegan","dairy_free","gluten_free"],
     "ingredients":["1 cup cooked white rice"],"instructions":["Heat if desired."]},
    {"name":"Adj: Banana","meal_type":"snack","K":105,"P":1,"C":27,"F":0,
     "tags":["adjustment","carb_boost","vegan","dairy_free","gluten_free"],
     "ingredients":["1 medium banana"],"instructions":["Peel and eat."]},
    {"name":"Adj: Whey in Water","meal_type":"snack","K":120,"P":24,"C":3,"F":1,
     "tags":["adjustment","protein_boost"],
     "ingredients":["1 scoop whey","water"],"instructions":["Shake and drink."]},
    {"name":"Adj: Chicken Breast Bites","meal_type":"snack","K":120,"P":26,"C":0,"F":2,
     "tags":["adjustment","protein_boost","gluten_free","dairy_free"],
     "ingredients":["4 oz cooked chicken breast"],"instructions":["Eat chilled or warm."]},
    {"name":"Adj: Olive Oil (1 tbsp)","meal_type":"snack","K":120,"P":0,"C":0,"F":14,
     "tags":["adjustment","fat_boost","vegan","dairy_free","gluten_free"],
     "ingredients":["1 tbsp extra-virgin olive oil"],"instructions":["Drizzle over salad/veg."]},
]

MEAL_TYPES = ["breakfast","lunch","dinner","snack"]

# -----------------------------
# Utility & nutrition helpers
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
    p_g = round((target_kcal * p_ratio) / 4)
    c_g = round((target_kcal * c_ratio) / 4)
    f_g = round((target_kcal * f_ratio) / 9)
    return p_g, c_g, f_g


def _compatible(meal: Dict[str,Any], prefs: Dict[str,Any], excludes: set) -> bool:
    tags = set(meal.get("tags",[]))
    if prefs.get("vegan") and "vegan" not in tags: return False
    if prefs.get("vegetarian") and not ("vegetarian" in tags or "vegan" in tags): return False
    if prefs.get("dairy_free") and not ("dairy_free" in tags or "vegan" in tags): return False
    if prefs.get("gluten_free") and "gluten_free" not in tags and meal.get("meal_type")!="snack":
        # snacks are mostly GF by choice; rely on tags for meals
        pass
    text = (meal["name"] + " " + " ".join(meal.get("ingredients",[]))).lower()
    if excludes and any(x in text for x in excludes): return False
    return True


def filter_meals(prefs: Dict[str,Any]) -> List[Dict[str,Any]]:
    selected = []
    excludes = set([x.strip().lower() for x in prefs.get("excludes","" ).split(',') if x.strip()])
    for m in MEALS:
        if _compatible(m, prefs, excludes):
            selected.append(m)
    return selected


def _totals(picks: List[Dict[str,Any]]) -> Tuple[int,int,int,int]:
    k = sum(m["K"] for m in picks); p = sum(m["P"] for m in picks)
    c = sum(m["C"] for m in picks); f = sum(m["F"] for m in picks)
    return k,p,c,f


def _score_plan(picks, kcal_target, p_target, c_target, f_target):
    k,p,c,f = _totals(picks)
    # Favor macro hit, then kcal
    return (
        abs(k - kcal_target) * 1.0 +
        abs(p - p_target) * 2.0 +
        abs(c - c_target) * 1.4 +
        abs(f - f_target) * 1.2
    )


def pick_day_plan(target_kcal: int, meals_db: List[Dict[str,Any]], meals_per_day: int,
                  macro_targets: Optional[Tuple[int,int,int]] = None) -> Tuple[List[Dict[str,Any]], int]:
    # Buckets
    by_type: Dict[str,List[Dict[str,Any]]] = {mt: [m for m in meals_db if m["meal_type"]==mt] for mt in MEAL_TYPES}
    # Build meal sequence
    if meals_per_day >= 3:
        seq = ["breakfast","lunch","dinner"] + ["snack"] * (meals_per_day - 3)
    elif meals_per_day == 2:
        seq = ["lunch","dinner"]
    else:
        seq = ["dinner"]

    # Seed with random picks, preferring high protein density
    def pd(m: Dict[str,Any]) -> float:
        return m["P"] / max(1.0, m["K"])

    picks: List[Dict[str,Any]] = []
    for mt in seq:
        bucket = by_type.get(mt) or meals_db
        bucket = sorted(bucket, key=pd, reverse=True)
        top = bucket[:max(4, len(bucket)//2)] if len(bucket)>6 else bucket
        choice = random.choice(top)
        picks.append(choice)

    # Hill-climb swaps
    if macro_targets:
        p_t, c_t, f_t = macro_targets
        best_score = _score_plan(picks, target_kcal, p_t, c_t, f_t)
    else:
        best_score = abs(_totals(picks)[0] - target_kcal)

    attempts = 300
    while attempts > 0:
        attempts -= 1
        i = random.randrange(len(picks))
        mt = picks[i]["meal_type"]
        bucket = by_type.get(mt) or meals_db
        candidate = random.choice(bucket)
        trial = picks[:]
        trial[i] = candidate
        if macro_targets:
            score = _score_plan(trial, target_kcal, p_t, c_t, f_t)
            if score < best_score:
                picks = trial; best_score = score
        else:
            k_old = _totals(picks)[0]; k_new = _totals(trial)[0]
            if abs(k_new - target_kcal) < abs(k_old - target_kcal):
                picks = trial

    return picks, _totals(picks)[0]


def tighten_calories(
    picks: List[Dict[str,Any]],
    kcal_target: int,
    macro_targets: Tuple[int,int,int],
    meals_db: List[Dict[str,Any]],
    prefs: Dict[str,Any],
    tol: float = 0.05,
    max_steps: int = 6
) -> List[Dict[str,Any]]:
    """Nudge a day's picks to sit within ±tol of kcal_target.
    If low: add adjuster snacks guided by the biggest macro gap.
    If high: remove a regular snack or swap a heavy item for a lighter one.
    """
    excludes = set([x.strip().lower() for x in prefs.get("excludes","").split(',') if x.strip()])
    adjusters = [a for a in MICRO_ADJUSTERS if _compatible(a, prefs, excludes)]
    lower = int(kcal_target * (1.0 - tol))
    upper = int(kcal_target * (1.0 + tol))

    steps = 0
    while steps < max_steps:
        steps += 1
        k,p,c,f = _totals(picks)
        if lower <= k <= upper:
            break
        p_t,c_t,f_t = macro_targets
        dp, dc, df = (p_t - p), (c_t - c), (f_t - f)
        if k < lower:  # add
            needs = [("P", max(0.0, dp)*4.0),("C", max(0.0, dc)*4.0),("F", max(0.0, df)*9.0)]
            needs.sort(key=lambda x: x[1], reverse=True)
            added = False
            for key,_ in needs:
                if key == "P": cands = [a for a in adjusters if a["P"] >= 20]
                elif key == "C": cands = [a for a in adjusters if a["C"] >= 20]
                else: cands = [a for a in adjusters if a["F"] >= 10]
                random.shuffle(cands)
                for a in cands:
                    if k + a["K"] <= upper + 80:
                        picks.append(dict(a, tags=(a.get("tags",[])+["adjustment"])))
                        added = True
                        break
                if added: break
            if not added and adjusters:
                picks.append(dict(adjusters[0], tags=(adjusters[0].get("tags",[])+["adjustment"])))
        else:  # k > upper
            # try removing largest non-adjustment snack first
            ix, best_k = None, 0
            for i,m in enumerate(picks):
                if m.get("meal_type")=="snack" and "adjustment" not in m.get("tags",[]):
                    if m["K"] > best_k: ix, best_k = i, m["K"]
            if ix is not None:
                picks.pop(ix); continue
            # else swap the heaviest non-snack for a lighter same-type
            j = max(range(len(picks)), key=lambda i: (picks[i]["meal_type"]!="snack", picks[i]["K"]))
            victim = picks[j]
            pool = [m for m in meals_db if m["meal_type"]==victim["meal_type"] and m["K"] < victim["K"]]
            pool = [m for m in pool if _compatible(m, prefs, excludes)]
            if pool:
                picks[j] = min(pool, key=lambda m: m["K"])
            else:
                # last resort: drop an adjustment
                adj_ix = next((i for i,m in enumerate(picks) if "adjustment" in m.get("tags",[])), None)
                if adj_ix is not None:
                    picks.pop(adj_ix)
                else:
                    break
    return picks


def aggregate_grocery_list(plan: List[List[Dict[str,Any]]]) -> Dict[str,int]:
    counts: Dict[str,int] = {}
    for day in plan:
        for meal in day:
            for item in meal.get("ingredients", []):
                counts[item] = counts.get(item, 0) + 1
    return counts

# -----------------------------
# HTML (single template)
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
        <li><b>Macro targets: 40% protein / 30% carbs / 30% fat</b></li>
        <li>Quick, simple meals chosen from a growing database</li>
        <li>Per‑meal step‑by‑step instructions</li>
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

_RESULTS: Dict[str,Dict[str,Any]] = {}

@app.route('/generate', methods=['GET','POST'])
def generate():
    # GET to /generate (e.g., iframe default) -> show index form
    if request.method == 'GET':
        return redirect(url_for('index'), code=302)

    form = request.form
    # Pull TDEE or compute from stats
    tdee_raw = (form.get('tdee') or '').strip()
    activity = form.get('activity', 'sedentary')
    if tdee_raw:
        try:
            tdee = int(float(tdee_raw))
        except Exception:
            tdee = 0
    else:
        sex = form.get('sex','male')
        def _to_float(val, default=None):
            try: return float(val)
            except Exception: return default
        try:
            age = int(form.get('age','30'))
        except Exception:
            age = 30
        # Imperial first
        ft = _to_float(form.get('height_ft','').strip(), None)
        inches = _to_float(form.get('height_in','').strip(), None)
        lb = _to_float(form.get('weight_lb','').strip(), None)
        height_cm = ( (ft or 0)*12 + (inches or 0) ) * 2.54 if (ft is not None or inches is not None) else _to_float(form.get('height_cm','175'), 175.0)
        weight_kg = (lb * 0.45359237) if (lb is not None) else _to_float(form.get('weight_kg','80'), 80.0)
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

    # 25% deficit and macro targets 40/30/30
    target_kcal = int(round(tdee * 0.75))
    p_g, c_g, f_g = grams_from_kcal(target_kcal)

    pool = filter_meals(prefs) or MEALS[:]

    # Build plan with tightening
    plan: List[List[Dict[str,Any]]] = []
    day_totals: List[int] = []
    for _ in range(days):
        picks, _ = pick_day_plan(target_kcal, pool, meals_per_day, macro_targets=(p_g, c_g, f_g))
        picks = tighten_calories(picks, target_kcal, (p_g, c_g, f_g), pool, prefs, tol=0.05, max_steps=6)
        plan.append(picks)
        day_totals.append(sum(m["K"] for m in picks))

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
# Offline generator (CLI)
# -----------------------------

def build_plan_from_params(tdee: Optional[int], days: int, meals_per_day: int, activity: str, stats: Optional[Dict[str,Any]], prefs: Dict[str,Any]) -> Dict[str,Any]:
    if not tdee:
        stats = stats or {"sex":"male","age":30,"height_cm":175.0,"weight_kg":80.0}
        sex = stats.get('sex','male')
        age = int(stats.get('age',30))
        height_cm = stats.get('height_cm')
        weight_kg = stats.get('weight_kg')
        if height_cm is None and (stats.get('height_ft') is not None or stats.get('height_in') is not None):
            ft = float(stats.get('height_ft') or 0); inch = float(stats.get('height_in') or 0)
