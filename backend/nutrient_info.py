"""
Static educational reference content about nutrients -- shown in the UI
next to goal progress bars. General educational information only, not
medical advice; figures are common public-health reference ranges
(NHS/EFSA/WHO-style ballpark figures) rather than personalized guidance.
"""

NUTRIENT_INFO = {
    "calories": {
        "label": "Calories",
        "kind": "target",
        "unit": "kcal",
        "summary": "Your body's energy budget. Consistently eating more than you burn leads to weight "
                   "gain over time; consistently eating less leads to weight loss.",
        "too_little": "Prolonged under-eating can cause fatigue, muscle loss, poor concentration, and "
                       "a slowed metabolism.",
        "too_much": "Sustained surplus intake is the main driver of gradual weight gain over months and years.",
    },
    "protein_g": {
        "label": "Protein",
        "kind": "target",
        "unit": "g",
        "summary": "Builds and repairs muscle, skin, and enzymes. Also the most satiating macronutrient, "
                   "helping manage appetite.",
        "too_little": "Can lead to muscle loss, slower recovery from exercise, hair/skin/nail issues, "
                       "and weaker immune function over time.",
        "too_much": "Generally well tolerated; very high long-term intake alongside low water intake may "
                     "stress the kidneys in people with existing kidney conditions.",
    },
    "carbs_g": {
        "label": "Carbohydrates",
        "kind": "target",
        "unit": "g",
        "summary": "Your body and brain's preferred quick-access fuel source, especially for exercise.",
        "too_little": "Can cause fatigue, irritability, poor exercise performance, and difficulty concentrating.",
        "too_much": "Excess intake beyond energy needs is stored as fat, and diets very high in refined "
                     "carbs are linked to blood sugar spikes and crashes.",
    },
    "fat_g": {
        "label": "Fat",
        "kind": "target",
        "unit": "g",
        "summary": "Needed for hormone production, absorbing vitamins A/D/E/K, and long-term energy storage.",
        "too_little": "Very low fat intake can disrupt hormone production and impair absorption of "
                       "fat-soluble vitamins.",
        "too_much": "Excess total fat intake contributes to a calorie surplus; the type of fat matters more "
                     "than the total (see saturated/trans fat below).",
    },
    "fiber_g": {
        "label": "Fiber",
        "kind": "target",
        "unit": "g",
        "summary": "Supports digestion, gut health, and helps you feel full; linked to lower heart disease risk.",
        "too_little": "Associated with constipation, poorer blood sugar control, and higher long-term risk "
                       "of heart disease.",
        "too_much": "Very high intake without enough water can cause bloating or digestive discomfort.",
    },
    "water_ml": {
        "label": "Water",
        "kind": "target",
        "unit": "ml",
        "summary": "Needed for nearly every bodily process -- temperature regulation, joint lubrication, "
                    "digestion, and nutrient transport.",
        "too_little": "Mild dehydration alone can cause headaches, fatigue, and reduced concentration.",
        "too_much": "Extremely large intake in a short period can (rarely) dilute blood sodium levels.",
    },
    # ---- "bad version" / limit nutrients ----
    "sugar_limit_g": {
        "label": "Added sugar",
        "kind": "limit",
        "unit": "g",
        "summary": "Sugar added during processing or preparation (not naturally occurring, e.g. in fruit).",
        "short_term": "Causes rapid blood sugar spikes followed by crashes -- linked to energy dips and cravings.",
        "long_term": "High long-term intake is associated with weight gain, type 2 diabetes risk, and "
                      "dental decay.",
    },
    "saturated_fat_limit_g": {
        "label": "Saturated fat",
        "kind": "limit",
        "unit": "g",
        "summary": "Found in fatty meat, butter, and many processed foods.",
        "short_term": "No significant short-term effect for most people in moderate amounts.",
        "long_term": "High long-term intake is linked to raised LDL cholesterol and increased cardiovascular risk.",
    },
    "trans_fat_limit_g": {
        "label": "Trans fat",
        "kind": "limit",
        "unit": "g",
        "summary": "Mostly artificial, found in some fried and processed foods (partially hydrogenated oils).",
        "short_term": "No noticeable short-term effect in small amounts.",
        "long_term": "Considered to have no safe long-term intake level -- consistently linked to heart "
                      "disease risk even in small quantities.",
    },
    "sodium_limit_mg": {
        "label": "Sodium",
        "kind": "limit",
        "unit": "mg",
        "summary": "Needed in small amounts for fluid balance and nerve function; easy to over-consume via "
                    "processed and restaurant food.",
        "short_term": "Can cause temporary bloating and increased thirst.",
        "long_term": "Long-term excess is strongly linked to high blood pressure and cardiovascular risk.",
    },
    "alcohol_limit_g": {
        "label": "Alcohol",
        "kind": "limit",
        "unit": "g",
        "summary": "A source of empty calories (7 kcal/g) that also affects sleep quality and judgement.",
        "short_term": "Impairs coordination and decision-making; disrupts sleep quality even in moderate amounts.",
        "long_term": "Regular high intake is linked to liver disease, several cancers, and dependency risk.",
    },
    "caffeine_limit_mg": {
        "label": "Caffeine",
        "kind": "limit",
        "unit": "mg",
        "summary": "A stimulant found in coffee, tea, energy drinks, and chocolate. Moderate intake can "
                    "improve alertness and focus.",
        "short_term": "Can improve alertness and performance in moderate doses; excess can cause jitteriness, "
                       "anxiety, and disrupted sleep -- especially if consumed later in the day.",
        "long_term": "Regular high intake can lead to tolerance, dependency, and chronically poor sleep quality.",
    },
}

# Foods/substances commonly tracked alongside caffeine for similar reasons
# (stimulant or habit-forming effect worth being mindful of).
CAFFEINE_LIKE_SUBSTANCES = [
    {
        "name": "Nicotine",
        "note": "Stimulant, highly habit-forming; commonly consumed via cigarettes/vapes rather than food.",
    },
    {
        "name": "Taurine",
        "note": "Common in energy drinks alongside caffeine; generally considered safe in typical doses, "
                "less well studied long-term at high intake.",
    },
    {
        "name": "Theobromine",
        "note": "Found in chocolate/cacao; milder stimulant effect than caffeine, similar family of compounds.",
    },
]


def get_nutrient_info(key: str):
    return NUTRIENT_INFO.get(key)
