
import io, random, datetime
from dataclasses import dataclass
from typing import Any, Dict, List
from flask import Blueprint, current_app, render_template, request, send_file, make_response
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from ..services.macros import mifflin_st_jeor, compute_tdee, grams_from_kcal, ACTIVITY_FACTORS
from ..services.meals_loader import load_meals
from ..services.planner import filter_meals, pick_day_plan, aggregate_grocery

bp = Blueprint("web", __name__, template_folder="../templates", static_folder="../static")
_DATA_CACHE: Dict[str, Dict[str,Any]] = {}

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

@bp.get("/")
def index():
    return render_template("index.html",
        app_name=current_app.config.get("APP_NAME","Home Meal Planner"),
        activities=ACTIVITY_FACTORS, result=None, year=datetime.datetime.now().year)

@bp.post("/generate")
def generate():
    form = request.form
    tdee = int(float(form.get("tdee","2300")))
    days = 2
    meals_per_day = 3
    target_kcal = int(round(tdee*0.75))
    p_g,c_g,f_g = grams_from_kcal(target_kcal)
    meals = load_meals(current_app.root_path)
    pool = filter_meals(meals, {})
    plan=[]; totals=[]
    for _ in range(days):
        picks,total = pick_day_plan(target_kcal, pool, meals_per_day, (p_g,c_g,f_g))
        plan.append(picks); totals.append(total)
    grocery = aggregate_grocery(plan)
    token = str(random.randint(10**9, 10**10-1))
    _DATA_CACHE[token] = dict(tdee=tdee,target_kcal=target_kcal,days=days,meals_per_day=meals_per_day,p_g=p_g,c_g=c_g,f_g=f_g,plan=plan,day_totals=totals,grocery=grocery)
    return render_template("index.html",
        app_name=current_app.config.get("APP_NAME","Home Meal Planner"),
        activities=ACTIVITY_FACTORS,
        result=Result(token,tdee,target_kcal,days,meals_per_day,p_g,c_g,f_g,plan,totals,grocery),
        year=datetime.datetime.now().year)

@bp.get("/pdf/<token>")
def pdf(token:str):
    data = _DATA_CACHE.get(token)
    if not data: return make_response("Session expired. Please regenerate.", 410)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Small', fontSize=9, leading=11))
    story=[Paragraph("Meal Plan", styles["Title"])]
    doc.build(story)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"meal_plan_{token}.pdf", mimetype="application/pdf")
