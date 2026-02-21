import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import json
import requests
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_me
from datetime import date

# --- APP CONFIG ---
st.set_page_config(page_title="The Dinner Decider", page_icon="🍲", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
conn = st.connection("gsheets", type=GSheetsConnection)

def fetch_data():
    return conn.read(ttl="1m")

def save_data(df):
    conn.update(data=df)
    st.cache_data.clear()

# --- HELPERS: SCRAPING ---
def get_original_recipe_url(short_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
    try:
        res = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
        full_pin_url = res.url
        soup = BeautifulSoup(res.text, 'html.parser')
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.text)
                if isinstance(data, dict) and 'url' in data:
                    if "pinterest.com" not in data['url']:
                        return data['url']
            except: continue
        meta_link = soup.find("meta", property="og:see_also")
        if meta_link: return meta_link["content"]
        return full_pin_url
    except Exception:
        return short_url

def generic_fallback_scraper(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.text)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'Recipe' in item.get('@type', []):
                            data = item
                            break
                    if isinstance(data, list): data = data[0]
                if isinstance(data, dict) and '@graph' in data:
                    recipes = [item for item in data['@graph'] if 'Recipe' in item.get('@type', [])]
                    if recipes: data = recipes[0]
                if isinstance(data, dict) and 'Recipe' in data.get('@type', []):
                    title = data.get('name')
                    ing_list = data.get('recipeIngredient', [])
                    if isinstance(ing_list, str): ing_list = [ing_list]
                    return title, ing_list
            except: continue
    except Exception: return None, None
    return None, None

# --- HELPERS: RATINGS & HISTORY ---
def get_rating(df, meal_name):
    row = df[df["Meal"] == meal_name]
    if row.empty: return 0, 0
    rating = row.iloc[0].get("Rating", 0)
    count = row.iloc[0].get("RatingCount", 0)
    return float(rating) if pd.notna(rating) else 0, int(count) if pd.notna(count) else 0

def add_rating(df, meal_name, new_rating):
    idx = df[df["Meal"] == meal_name].index
    if idx.empty: return df
    avg, count = get_rating(df, meal_name)
    new_avg = ((avg * count) + new_rating) / (count + 1)
    df.at[idx[0], "Rating"] = round(new_avg, 2)
    df.at[idx[0], "RatingCount"] = count + 1
    return df

def mark_made_today(df, meal_name):
    idx = df[df["Meal"] == meal_name].index
    if idx.empty: return df
    made_count = df.at[idx[0], "MadeCount"] if "MadeCount" in df.columns else 0
    made_count = int(made_count) if pd.notna(made_count) else 0
    df.at[idx[0], "MadeCount"] = made_count + 1
    df.at[idx[0], "LastMade"] = str(date.today())
    return df

def days_since_last_made(df, meal_name):
    row = df[df["Meal"] == meal_name]
    if row.empty: return None
    last = row.iloc[0].get("LastMade")
    if pd.isna(last) or last == "" or last is None: return None
    try:
        return (date.today() - date.fromisoformat(str(last))).days
    except: return None

def stars(rating):
    full = int(round(rating))
    return "⭐" * full + "☆" * (5 - full) if rating > 0 else "No ratings yet"

def ensure_columns(df):
    for col in ["Rating", "RatingCount", "MadeCount", "LastMade"]:
        if col not in df.columns:
            df[col] = None
    return df

def build_shopping_list(df, meal_names):
    """Returns a deduplicated, sorted list of ingredients for the given meals."""
    all_ingredients = []
    for meal_name in meal_names:
        row = df[df["Meal"] == meal_name]
        if row.empty: continue
        ings = str(row.iloc[0].get("Ingredients", ""))
        items = [i.strip() for i in ings.split('\n') if i.strip()]
        all_ingredients.extend(items)
    seen = set()
    deduped = []
    for item in all_ingredients:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return sorted(deduped)

# --- LOAD DATA ---
st.title("🍲 The Dinner Decider")
df = fetch_data()
df = ensure_columns(df)

# ============================================================
# SIDEBAR: Add New Recipe
# ============================================================
with st.sidebar:
    st.header("Add a New Favorite")
    url_input = st.text_input("Paste Recipe or Pinterest URL")
    if st.button("Auto-Fill from URL"):
        with st.spinner("Fetching..."):
            target_url = get_original_recipe_url(url_input) if "pin.it" in url_input or "pinterest.com" in url_input else url_input
            try:
                scraper = scrape_me(target_url)
                st.session_state.form_meal_name = scraper.title()
                st.session_state.form_ingredients = "\n".join(scraper.ingredients())
            except:
                title, ing = generic_fallback_scraper(target_url)
                if title:
                    st.session_state.form_meal_name = title
                    st.session_state.form_ingredients = "\n".join(ing) if ing else ""
                else:
                    st.error("Could not extract details automatically.")

    name = st.text_input("Meal Name", key="form_meal_name")
    cat = st.selectbox("Category", ["Quick & Easy", "Date Night", "Healthy", "Takeout Shortcut"], key="form_category")
    ing = st.text_area("Ingredients (one per line)", key="form_ingredients")

    if st.button("Save to Community Pool", type="primary"):
        if name:
            if name.strip().lower() in df["Meal"].str.strip().str.lower().tolist():
                st.warning(f"'{name}' is already in the cookbook!")
            else:
                new_row = pd.DataFrame([{
                    "Meal": name, "Category": cat, "Ingredients": ing,
                    "Rating": None, "RatingCount": None, "MadeCount": None, "LastMade": None
                }])
                updated_df = pd.concat([df, new_row], ignore_index=True)
                save_data(updated_df)
                st.success(f"Added {name}!")
                st.rerun()
        else:
            st.error("Please enter a meal name.")

    st.divider()
    with st.expander("🔒 Admin Settings"):
        pw = st.text_input("Admin Password", type="password")
        if pw == st.secrets.get("ADMIN_PASSWORD", "admin123"):
            if st.button("Wipe All Recipes (Careful!)"):
                empty_df = pd.DataFrame(columns=["Meal", "Category", "Ingredients", "Rating", "RatingCount", "MadeCount", "LastMade"])
                save_data(empty_df)
                st.rerun()

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(["🎲 The Decider", "🛒 Shopping List", "📅 Weekly Planner", "📖 Shared Cookbook"])

# ============================================================
# TAB 1: THE DECIDER
# ============================================================
with tab1:
    st.header("What's for dinner?")

    with st.expander("⚙️ Filters", expanded=False):
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            all_cats = ["All"] + sorted(df["Category"].dropna().unique().tolist()) if not df.empty else ["All"]
            selected_cat = st.selectbox("Filter by category", all_cats)
        with filter_col2:
            fridge_ingredients = st.text_input("Ingredients I have (comma-separated)", placeholder="chicken, garlic, pasta")
        avoid_recent = st.checkbox("Skip meals made in the last 7 days", value=True)

    # Apply filters
    filtered_df = df.copy()
    if selected_cat != "All":
        filtered_df = filtered_df[filtered_df["Category"] == selected_cat]
    if fridge_ingredients.strip():
        have = [i.strip().lower() for i in fridge_ingredients.split(",") if i.strip()]
        filtered_df = filtered_df[filtered_df.apply(
            lambda row: any(h in str(row.get("Ingredients", "")).lower() for h in have), axis=1
        )]
    if avoid_recent:
        filtered_df = filtered_df[filtered_df.apply(
            lambda row: (days_since_last_made(df, row["Meal"]) or 999) > 7, axis=1
        )]

    # Exclude last spun meal to prevent back-to-back repeats
    last_spun = st.session_state.get("last_spun_meal")
    spin_pool = filtered_df[filtered_df["Meal"] != last_spun] if last_spun and len(filtered_df) > 1 else filtered_df

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🎲 Spin the Wheel", use_container_width=True, type="primary"):
            if not spin_pool.empty:
                choice = spin_pool.sample().iloc[0]
                st.session_state.current_choice = choice
                st.session_state.last_spun_meal = choice["Meal"]
                st.balloons()
            elif not filtered_df.empty:
                choice = filtered_df.sample().iloc[0]
                st.session_state.current_choice = choice
                st.session_state.last_spun_meal = choice["Meal"]
                st.info("All matching meals were made recently — picked one anyway!")
                st.balloons()
            else:
                st.warning("No meals match your current filters!")

    with col2:
        if not filtered_df.empty:
            meal_options = ["— Pick a meal —"] + filtered_df["Meal"].tolist()
            selected_meal = st.selectbox("Or choose manually", meal_options, label_visibility="collapsed")
            if selected_meal != "— Pick a meal —":
                st.session_state.current_choice = df[df["Meal"] == selected_meal].iloc[0]

    # Result display
    if 'current_choice' in st.session_state:
        choice = st.session_state.current_choice
        st.divider()
        st.markdown(f"## 🍽️ Tonight: **{choice['Meal']}**")
        st.caption(f"Category: {choice['Category']}")

        avg, count = get_rating(df, choice['Meal'])
        days_ago = days_since_last_made(df, choice['Meal'])
        made_count = int(choice.get('MadeCount', 0)) if pd.notna(choice.get('MadeCount')) else 0

        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            st.markdown(f"**Rating:** {stars(avg)} ({count} ratings)")
        with meta_col2:
            st.markdown(f"**Last made:** {f'{days_ago} day(s) ago' if days_ago is not None else 'Never'}")
        with meta_col3:
            st.markdown(f"**Times made:** {made_count}")

        if pd.notna(choice['Ingredients']) and str(choice['Ingredients']).strip():
            st.subheader("Ingredients")
            items = [i.strip() for i in str(choice['Ingredients']).split('\n') if i.strip()]
            check_col1, check_col2 = st.columns(2)
            for i, item in enumerate(items):
                with (check_col1 if i % 2 == 0 else check_col2):
                    st.checkbox(item, key=f"chk_{item}_{i}")

        st.divider()
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            st.markdown("**Rate this meal:**")
            rating_val = st.select_slider("Rating", options=[1, 2, 3, 4, 5], value=3,
                                          label_visibility="collapsed", key="rating_slider")
            if st.button("Submit Rating ⭐"):
                df = fetch_data()
                df = ensure_columns(df)
                df = add_rating(df, choice['Meal'], rating_val)
                save_data(df)
                st.success("Rating saved!")
                st.rerun()
        with action_col2:
            st.markdown("**Made this tonight?**")
            if st.button("✅ Mark as Made Today"):
                df = fetch_data()
                df = ensure_columns(df)
                df = mark_made_today(df, choice['Meal'])
                save_data(df)
                st.success("Logged!")
                st.rerun()

# ============================================================
# TAB 2: SHOPPING LIST BUILDER
# ============================================================
with tab2:
    st.header("🛒 Shopping List Builder")
    if df.empty:
        st.write("No meals saved yet.")
    else:
        st.markdown("Select meals to build a combined, deduplicated grocery list:")
        selected_meals = st.multiselect("Choose meals", df["Meal"].tolist())

        if selected_meals:
            deduped = build_shopping_list(df, selected_meals)

            st.subheader(f"{len(selected_meals)} meal(s) · {len(deduped)} unique ingredients")

            list_col1, list_col2 = st.columns(2)
            for i, item in enumerate(deduped):
                with (list_col1 if i % 2 == 0 else list_col2):
                    st.checkbox(item, key=f"shop_{item}_{i}")

            st.divider()
            plain_list = "\n".join(f"• {item}" for item in deduped)
            st.text_area("📋 Copy to clipboard", value=plain_list, height=200)

# ============================================================
# TAB 3: WEEKLY MEAL PLANNER
# ============================================================
with tab3:
    st.header("📅 Weekly Meal Planner")
    if df.empty:
        st.write("No meals saved yet.")
    else:
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        meal_options_plan = ["— Day off —"] + df["Meal"].tolist()

        if st.button("🎲 Auto-fill the week"):
            pool = df["Meal"].tolist()
            sample = (pool * 7)[:7] if len(pool) < 7 else df["Meal"].sample(7).tolist()
            for day, meal in zip(days, sample):
                st.session_state[f"plan_{day}"] = meal

        st.markdown("Assign a meal to each day, then get your shopping list below.")
        plan = {}
        col_left, col_right = st.columns(2)
        for i, day in enumerate(days):
            current_val = st.session_state.get(f"plan_{day}", "— Day off —")
            idx = meal_options_plan.index(current_val) if current_val in meal_options_plan else 0
            with (col_left if i % 2 == 0 else col_right):
                plan[day] = st.selectbox(day, meal_options_plan, index=idx, key=f"plan_{day}")

        planned_meals = [m for m in plan.values() if m != "— Day off —"]
        if planned_meals:
            st.divider()
            st.subheader("🛒 Weekly Shopping List")
            deduped = build_shopping_list(df, planned_meals)
            st.caption(f"{len(planned_meals)} meals planned · {len(deduped)} unique ingredients")

            wk_col1, wk_col2 = st.columns(2)
            for i, item in enumerate(deduped):
                with (wk_col1 if i % 2 == 0 else wk_col2):
                    st.checkbox(item, key=f"week_{item}_{i}")

            st.divider()
            plain_list = "\n".join(f"• {item}" for item in deduped)
            st.text_area("📋 Copy to clipboard", value=plain_list, height=250)

# ============================================================
# TAB 4: SHARED COOKBOOK
# ============================================================
with tab4:
    st.header("📖 Shared Cookbook")
    if not df.empty:
        display_df = df[["Meal", "Category", "Rating", "RatingCount", "MadeCount", "LastMade"]].copy()
        display_df["Rating"] = display_df.apply(
            lambda r: f"{stars(float(r['Rating']) if pd.notna(r['Rating']) else 0)} "
                      f"({int(r['RatingCount']) if pd.notna(r['RatingCount']) else 0})",
            axis=1
        )
        display_df["MadeCount"] = display_df["MadeCount"].fillna(0).astype(int)
        display_df["LastMade"] = display_df["LastMade"].fillna("Never")
        display_df = display_df.drop(columns=["RatingCount"])
        display_df.rename(columns={"MadeCount": "Times Made", "LastMade": "Last Made"}, inplace=True)

        sort_col1, sort_col2 = st.columns([2, 1])
        with sort_col1:
            sort_by = st.selectbox("Sort by", ["Meal", "Category", "Times Made", "Last Made"])
        with sort_col2:
            asc = st.checkbox("Ascending", value=True)

        display_df = display_df.sort_values(sort_by, ascending=asc)
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.write("No meals saved yet.")
