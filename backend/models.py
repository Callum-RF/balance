"""
Database models for the Balance app.
"""
from datetime import date as date_type, datetime
from typing import Optional

from sqlmodel import SQLModel, Field


# ---------------------------------------------------------------------------
# Categories (hierarchical: e.g. Food -> Groceries, Entertainment -> Books)
# ---------------------------------------------------------------------------
class CategoryBase(SQLModel):
    name: str
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id")


class Category(CategoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class CategoryCreate(CategoryBase):
    pass


class CategoryRead(CategoryBase):
    id: int


# ---------------------------------------------------------------------------
# Expense transactions
# ---------------------------------------------------------------------------
class TransactionBase(SQLModel):
    date: date_type
    amount: float
    merchant: Optional[str] = None
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    payment_method: Optional[str] = None
    notes: Optional[str] = None
    receipt_image_path: Optional[str] = None
    tag: Optional[str] = None  # free-text context tag, e.g. "alone", "with friends"
    is_subscription_payment: bool = False


class Transaction(TransactionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TransactionCreate(TransactionBase):
    pass


class TransactionRead(TransactionBase):
    id: int
    created_at: datetime


class TransactionUpdate(SQLModel):
    date: Optional[date_type] = None
    amount: Optional[float] = None
    merchant: Optional[str] = None
    category_id: Optional[int] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None
    receipt_image_path: Optional[str] = None
    tag: Optional[str] = None


# ---------------------------------------------------------------------------
# Income (parallel to Transaction, but money coming in rather than out)
# ---------------------------------------------------------------------------
INCOME_SOURCES = ["Salary", "Freelance", "Gift", "Refund", "Investment", "Interest", "Other"]


class IncomeBase(SQLModel):
    date: date_type
    amount: float
    source: str = "Other"  # one of INCOME_SOURCES
    payer: Optional[str] = None  # e.g. employer, client, platform
    tag: Optional[str] = None
    notes: Optional[str] = None


class Income(IncomeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class IncomeCreate(IncomeBase):
    pass


class IncomeRead(IncomeBase):
    id: int
    created_at: datetime


class IncomeUpdate(SQLModel):
    date: Optional[date_type] = None
    amount: Optional[float] = None
    source: Optional[str] = None
    payer: Optional[str] = None
    tag: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Food log entries
# ---------------------------------------------------------------------------
class FoodLogBase(SQLModel):
    date: date_type
    meal_type: Optional[str] = None
    food_name: str
    barcode: Optional[str] = None
    quantity_g: float = 100.0
    tag: Optional[str] = None  # e.g. "alone", "with friends"
    eaten_out: bool = False  # meal bought out (restaurant/takeaway) vs cooked at home

    # "good" macro/micro nutrients
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sugar_g: Optional[float] = None
    sodium_mg: Optional[float] = None

    # "bad version" / limit nutrients
    saturated_fat_g: Optional[float] = None
    trans_fat_g: Optional[float] = None
    added_sugar_g: Optional[float] = None
    alcohol_g: Optional[float] = None
    caffeine_mg: Optional[float] = None


class FoodLog(FoodLogBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FoodLogCreate(FoodLogBase):
    pass


class FoodLogRead(FoodLogBase):
    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Barcode -> nutrition cache (per 100g)
# ---------------------------------------------------------------------------
class FoodItemCache(SQLModel, table=True):
    barcode: str = Field(primary_key=True)
    name: Optional[str] = None

    calories_per_100g: Optional[float] = None
    protein_per_100g: Optional[float] = None
    carbs_per_100g: Optional[float] = None
    fat_per_100g: Optional[float] = None
    fiber_per_100g: Optional[float] = None
    sugar_per_100g: Optional[float] = None
    sodium_per_100g: Optional[float] = None
    saturated_fat_per_100g: Optional[float] = None
    trans_fat_per_100g: Optional[float] = None
    caffeine_per_100g: Optional[float] = None

    source: str = "openfoodfacts"
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Water intake log
# ---------------------------------------------------------------------------
class WaterLogBase(SQLModel):
    date: date_type
    amount_ml: float


class WaterLog(WaterLogBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WaterLogCreate(WaterLogBase):
    pass


class WaterLogRead(WaterLogBase):
    id: int


# ---------------------------------------------------------------------------
# User profile (single-row table: this is a single-user app)
# ---------------------------------------------------------------------------
class UserProfileBase(SQLModel):
    date_of_birth: Optional[date_type] = None
    height_cm: Optional[float] = None
    sex: Optional[str] = None  # "male" / "female" / "other" -- used only for BMR estimate
    activity_level: Optional[str] = "moderate"  # sedentary/light/moderate/active/very_active


class UserProfile(UserProfileBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class UserProfileUpdate(SQLModel):
    date_of_birth: Optional[date_type] = None
    height_cm: Optional[float] = None
    sex: Optional[str] = None
    activity_level: Optional[str] = None


class WeightLogBase(SQLModel):
    date: date_type
    weight_kg: float


class WeightLog(WeightLogBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class WeightLogCreate(WeightLogBase):
    pass


# ---------------------------------------------------------------------------
# Nutrient goals (single-row table)
# ---------------------------------------------------------------------------
class NutrientGoalsBase(SQLModel):
    calories: Optional[float] = 2000
    protein_g: Optional[float] = 100
    carbs_g: Optional[float] = 250
    fat_g: Optional[float] = 70
    fiber_g: Optional[float] = 30
    water_ml: Optional[float] = 2500

    # "bad version" daily limits
    sugar_limit_g: Optional[float] = 30       # added sugar limit
    saturated_fat_limit_g: Optional[float] = 20
    trans_fat_limit_g: Optional[float] = 0
    sodium_limit_mg: Optional[float] = 2300
    alcohol_limit_g: Optional[float] = 14
    caffeine_limit_mg: Optional[float] = 400


class NutrientGoals(NutrientGoalsBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class NutrientGoalsUpdate(SQLModel):
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    water_ml: Optional[float] = None
    sugar_limit_g: Optional[float] = None
    saturated_fat_limit_g: Optional[float] = None
    trans_fat_limit_g: Optional[float] = None
    sodium_limit_mg: Optional[float] = None
    alcohol_limit_g: Optional[float] = None
    caffeine_limit_mg: Optional[float] = None


# ---------------------------------------------------------------------------
# App settings (single-row table): display currency and optional PIN lock.
# The PIN is stored as a salted SHA-256 hash, never in plain text.
# ---------------------------------------------------------------------------
class AppSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    currency: str = "£"
    theme: str = "midnight"
    pin_hash: Optional[str] = None
    pin_salt: Optional[str] = None
    # Optional off-machine backup target (e.g. an external drive or a
    # cloud-synced folder). When set, each automated backup also copies the
    # snapshot + receipts here, so a disk failure can't take out both copies.
    backup_mirror_path: Optional[str] = None
    # Feature-module on/off overrides as a JSON object {module_key: bool}.
    # None / missing key = use the module's registry default (see MODULES in
    # the frontend). Lets the app ship a lean default while a power user keeps
    # everything switched on, without schema churn per module.
    modules_json: Optional[str] = None


# ---------------------------------------------------------------------------
# Budget targets (per category, or overall if category_id is None)
# ---------------------------------------------------------------------------
class BudgetTargetBase(SQLModel):
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    monthly_amount: float


class BudgetTarget(BudgetTargetBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class BudgetTargetCreate(BudgetTargetBase):
    pass


class BudgetTargetRead(BudgetTargetBase):
    id: int


# ---------------------------------------------------------------------------
# Pantry / food inventory
# ---------------------------------------------------------------------------
class PantryItemBase(SQLModel):
    name: str
    location: str = "pantry"  # fridge / freezer / pantry
    macro_group: Optional[str] = None  # protein / carbs / fat / produce / dairy / other
    quantity: float = 1
    unit: str = "unit"  # unit / g / kg / ml / l
    barcode: Optional[str] = None
    purchase_date: Optional[date_type] = None
    expiration_date: Optional[date_type] = None
    price: Optional[float] = None

    # nutrition for the WHOLE item/quantity as purchased (not per 100g),
    # used for pantry "runway" estimates
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None

    status: str = "active"  # active / consumed / thrown_away / expired


class PantryItem(PantryItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None  # when marked consumed/thrown_away/expired


class PantryItemCreate(PantryItemBase):
    pass


class PantryItemRead(PantryItemBase):
    id: int
    created_at: datetime
    resolved_at: Optional[datetime] = None


class PantryItemUpdate(SQLModel):
    name: Optional[str] = None
    location: Optional[str] = None
    macro_group: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expiration_date: Optional[date_type] = None
    price: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Subscriptions (recurring payments)
# ---------------------------------------------------------------------------
class SubscriptionBase(SQLModel):
    name: str
    amount: float
    billing_cycle: str = "monthly"  # monthly / yearly
    next_payment_date: Optional[date_type] = None
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    active: bool = True
    total_payments: Optional[int] = None  # None = ongoing indefinitely; set = fixed-term installment plan
    payments_made: int = 0


class Subscription(SubscriptionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionRead(SubscriptionBase):
    id: int
    created_at: datetime


class SubscriptionUpdate(SQLModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    billing_cycle: Optional[str] = None
    next_payment_date: Optional[date_type] = None
    category_id: Optional[int] = None
    active: Optional[bool] = None
    total_payments: Optional[int] = None
    payments_made: Optional[int] = None


# ---------------------------------------------------------------------------
# Price history (per named grocery item, for inflation/price-delta tracking)
# ---------------------------------------------------------------------------
class PriceObservationBase(SQLModel):
    item_name: str
    barcode: Optional[str] = None
    price: float
    date: date_type
    store: Optional[str] = None


class PriceObservation(PriceObservationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class PriceObservationCreate(PriceObservationBase):
    pass


class PriceObservationRead(PriceObservationBase):
    id: int


class PriceObservationUpdate(SQLModel):
    item_name: Optional[str] = None
    price: Optional[float] = None
    date: Optional[date_type] = None
    store: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheduled / recurring transactions: a template that produces a real
# Transaction (or Income) on a cadence -- auto-posted, or surfaced for the user
# to confirm first. Closes the loop on subscriptions/recurring detection, which
# spot recurrence but still made you log each actual charge by hand.
# ---------------------------------------------------------------------------
class ScheduledTransactionBase(SQLModel):
    kind: str = "expense"              # "expense" | "income"
    amount: float
    description: Optional[str] = None  # merchant (expense) or payer (income)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")  # expense
    source: Optional[str] = None       # income source (one of INCOME_SOURCES)
    tag: Optional[str] = None
    notes: Optional[str] = None
    cadence: str = "monthly"           # "weekly" | "monthly" | "yearly"
    next_date: date_type
    auto_post: bool = True             # True = auto-create; False = ask to confirm
    active: bool = True


class ScheduledTransaction(ScheduledTransactionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_posted: Optional[date_type] = None


class ScheduledTransactionCreate(ScheduledTransactionBase):
    pass


# ---------------------------------------------------------------------------
# Recipes / composed meals: a saved set of ingredients (with nutrition) that
# can be logged to the food diary in one tap, scaled by how many servings you
# ate. Ingredient nutrient fields are absolute totals for that ingredient's
# quantity, matching how FoodLog stores an entry.
# ---------------------------------------------------------------------------
class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    servings: float = 1
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecipeItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id")
    food_name: str
    quantity_g: float = 100.0
    barcode: Optional[str] = None

    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sugar_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    saturated_fat_g: Optional[float] = None
    trans_fat_g: Optional[float] = None
    added_sugar_g: Optional[float] = None
    alcohol_g: Optional[float] = None
    caffeine_mg: Optional[float] = None


# ---------------------------------------------------------------------------
# Shopping list: the bridge between Pantry, Finance and Recipes. Items can be
# added by hand or suggested from low/expiring pantry stock and things you buy
# repeatedly; once bought, they flow into the Pantry (and optionally record a
# grocery spend).
# ---------------------------------------------------------------------------
class ShoppingListItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    quantity_note: Optional[str] = None   # free text, e.g. "2", "500g", "a dozen"
    note: Optional[str] = None
    location: str = "pantry"              # where it goes when bought: fridge/freezer/pantry
    done: bool = False
    source: str = "manual"                # manual / pantry / recurring
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Savings goals / sinking funds: a named target you contribute towards, with
# progress and (optionally) a target date to pace against.
# ---------------------------------------------------------------------------
class SavingsGoal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    target_amount: float
    saved_amount: float = 0
    target_date: Optional[date_type] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Accounts & net worth: track balances across accounts (assets and
# liabilities) and snapshot total net worth over time to see a trend.
# ---------------------------------------------------------------------------
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    type: str = "current"   # current / savings / cash / investment / credit / loan
    balance: float = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NetWorthSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type
    net_worth: float
    assets: float
    liabilities: float
