
import random
from typing import List, Dict, Any, Tuple, Optional
MEAL_TYPES = ["breakfast","lunch","dinner","snack"]
def filter_meals(meals: List[Dict[str,Any]], prefs: Dict[str,Any]) -> List[Dict[str,Any]]:
    selected = []
    excludes = set([x.strip().lower() for x in (prefs.get("excludes") or "").split(',') if x.strip()])
    for m in meals:
        tags = set(m.get("tags",[]))
        if prefs.get("vegetarian") and not (("vegetarian" in tags) or ("vegan" in tags)): continue
        if prefs.get("vegan") and "vegan" not in tags: continue
        if prefs.get("dairy_free") and "dairy_free" not in tags and "vegan" not in tags: continue
        text = (m.get("name","") + " " + " ".join(m.get("ingredients",[]))).lower()
        if any(x in text for x in excludes): continue
        selected.append(m)
    return selected or meals
def _score(picks,kcal_target,p_t,c_t,f_t):
    k=sum(m["K"] for m in picks); p=sum(m["P"] for m in picks); c=sum(m["C"] for m in picks); f=sum(m["F"] for m in picks)
    return abs(k-kcal_target)*1.0 + abs(p-p_t)*2.0 + abs(c-c_t)*1.5 + abs(f-f_t)*1.5
def pick_day_plan(target_kcal:int, meals_db:List[Dict[str,Any]], meals_per_day:int, macro_targets:Optional[Tuple[int,int,int]]=None)->Tuple[List[Dict[str,Any]],int]:
    by_type = {t:[m for m in meals_db if m["meal_type"]==t] for t in MEAL_TYPES}
    seq = ["dinner"] if meals_per_day==1 else (["lunch","dinner"] if meals_per_day==2 else (["breakfast","lunch","dinner"] if meals_per_day==3 else ["breakfast","lunch","dinner","snack"]))
    random.shuffle(seq)
    picks=[random.choice(by_type.get(mt) or meals_db) for mt in seq]
    attempts=150; low,up=int(target_kcal*0.95), int(target_kcal*1.05)
    p_t,c_t,f_t = macro_targets or (0,0,0)
    best=_score(picks,target_kcal,p_t,c_t,f_t) if macro_targets else abs(sum(m["K"] for m in picks)-target_kcal)
    while attempts>0:
        attempts-=1
        i=random.randrange(0,len(picks)); mt=picks[i]["meal_type"]; cand=random.choice(by_type.get(mt) or meals_db)
        new=picks[:]; new[i]=cand
        if macro_targets:
            sc=_score(new,target_kcal,p_t,c_t,f_t)
            if sc<best: picks=new; best=sc
        else:
            if abs(sum(m["K"] for m in new)-target_kcal) < abs(sum(m["K"] for m in picks)-target_kcal): picks=new
        if low<=sum(m["K"] for m in picks)<=up and (not macro_targets or best<20): break
    return picks, sum(m["K"] for m in picks)
def aggregate_grocery(plan: List[List[Dict[str,Any]]])->Dict[str,int]:
    out={}
    for day in plan:
        for meal in day:
            for it in meal.get("ingredients",[]): out[it]=out.get(it,0)+1
    return out
