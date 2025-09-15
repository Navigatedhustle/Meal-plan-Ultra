
from typing import Tuple
ACTIVITY_FACTORS = {"sedentary":1.2,"light":1.375,"moderate":1.55,"very":1.725,"athlete":1.9}
def mifflin_st_jeor(sex:str, age:int, height_cm:float, weight_kg:float)->float:
    return 10*weight_kg + 6.25*height_cm - 5*age + (5 if sex.lower()=="male" else -161)
def compute_tdee(bmr:float, activity:str)->float: return bmr*ACTIVITY_FACTORS.get(activity,1.2)
def grams_from_kcal(target_kcal:float,p_ratio=0.40,c_ratio=0.30,f_ratio=0.30)->Tuple[int,int,int]:
    return round(target_kcal*p_ratio/4), round(target_kcal*c_ratio/4), round(target_kcal*f_ratio/9)
