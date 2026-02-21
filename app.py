import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import json
import requests
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_me

# --- APP CONFIG ---
st.set_page_config(page_title="The Dinner Decider", page_icon="🍲")

# --- GOOGLE SHEETS CONNECTION ---
conn = st.connection("gsheets", type=GSheetsConnection)

def fetch_data():
    return conn.read(ttl="1m")

# --- HELPERS: SCRAPING (Your Original Working Logic) ---
def get_original_recipe_url(short_url):
    """Follows a Pinterest short link to find the actual recipe blog URL."""
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
                
        # Fallback to metadata for Pinterest
        meta_link = soup.find("meta", property="og:see_also")
        if meta_link: return meta_link["content"]
            
        return full_pin_url
    except Exception:
        return short_url

def generic_fallback_scraper(url):
    """Deep-dives into JSON-LD to find ingredients when recipe_scrapers fails."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        json_scripts = soup.find_all('script', type='application/ld+json')
        
        for script in json_scripts:
            try:
                data = json.loads(script.text)
                # Handle list-style JSON-LD
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'Recipe' in item.get('@type', []):
                            data = item
                            break
                    if isinstance(data, list): data = data[0]

                # Handle @graph-style JSON-LD
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

# --- UI SETUP ---
st.title("🍲 The Dinner Decider")

df = fetch_data()

with st.sidebar:
    st.header("Add a New Favorite")
    
    url_input = st.text_input("Paste Recipe or Pinterest URL")
    if st.button("Auto-Fill from URL"):
        with st.spinner("Fetching..."):
            # Use the Unmasker
            target_url = get_original_recipe_url(url_input) if "pin.it" in url_input or "pinterest.com" in url_input else url_input
            
            try:
                scraper = scrape_me(target_url)
                st.session_state.form_meal_name = scraper.title()
                # Use Newline Join
                st.session_state.form_ingredients = "\n".join(scraper.ingredients())
            except:
                title, ing = generic_fallback_scraper(target_url)
                if title:
                    st.session_state.form_meal_name = title
                    # Use Newline Join
                    st.session_state.form_ingredients = "\n".join(ing) if ing else ""
                else:
                    st.error("Could not extract details automatically.")

    name = st.text_input("Meal Name", key="form_meal_name")
    cat = st.selectbox("Category", ["Quick & Easy", "Date Night", "Healthy", "Takeout Shortcut"], key="form_category")
    ing = st.text_area("Ingredients (one per line)", key="form_ingredients")
    
    if st.button("Save to Community Pool", type="primary"):
        if name:
            new_row = pd.DataFrame([{"Meal": name, "Category": cat, "Ingredients": ing}])
            updated_df = pd.concat([df, new_row], ignore_index=True)
            conn.update(data=updated_df)
            st.cache_data.clear() # Fixes the "not showing up" bug
            st.success(f"Added {name}!")
            st.rerun()
        else:
            st.error("Please enter a meal name.")

    st.divider()
    
    with st.expander("🔒 Admin Settings"):
        pw = st.text_input("Admin Password", type="password")
        if pw == st.secrets.get("ADMIN_PASSWORD", "admin123"):
            if st.button("Wipe All Recipes (Careful!)"):
                empty_df = pd.DataFrame(columns=["Meal", "Category", "Ingredients"])
                conn.update(data=empty_df)
                st.cache_data.clear() # Fixes the cache bug
                st.rerun()

# --- MAIN TABS ---
tab1, tab2 = st.tabs(["🎲 The Decider", "📖 Shared Cookbook"])

with tab1:
    st.header("What's for dinner?")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🎲 Spin the Wheel", use_container_width=True, type="primary"):
            if not df.empty:
                choice = df.sample().iloc[0]
                st.session_state.current_choice = choice
                st.balloons()
            else:
                st.warning("The cookbook is empty!")

    with col2:
        if not df.empty:
            meal_options = ["— Pick a meal —"] + df["Meal"].tolist()
            selected_meal = st.selectbox("Or choose manually", meal_options, label_visibility="collapsed")
            if selected_meal != "— Pick a meal —":
                st.session_state.current_choice = df[df["Meal"] == selected_meal].iloc[0]

    if 'current_choice' in st.session_state:
        choice = st.session_state.current_choice
        st.markdown(f"## You are having: **{choice['Meal']}**")
        st.caption(f"Category: {choice['Category']}")
        if pd.notna(choice['Ingredients']):
            items = [i.strip() for i in str(choice['Ingredients']).split('\n')]
            for item in items:
                if item: st.checkbox(item, key=f"chk_{item}")

with tab2:
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.write("No meals saved yet.")
