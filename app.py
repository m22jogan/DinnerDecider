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
# This looks for a "connections.gsheets" section in your Streamlit Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

def fetch_data():
    return conn.read(ttl="1m") # Cache for 1 minute for mobile speed

# --- HELPERS: SCRAPING ---
def get_original_recipe_url(short_url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.text)
                if isinstance(data, dict) and 'url' in data:
                    if "pinterest.com" not in data['url']: return data['url']
            except: continue
        return res.url
    except: return short_url

def generic_fallback_scraper(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.text)
                if isinstance(data, list): data = data[0]
                if isinstance(data, dict) and '@graph' in data:
                    recipes = [item for item in data['@graph'] if 'Recipe' in item.get('@type', [])]
                    if recipes: data = recipes[0]
                if isinstance(data, dict) and 'Recipe' in data.get('@type', []):
                    return data.get('name'), data.get('recipeIngredient', [])
            except: continue
    except: return None, None
    return None, None

# --- UI SETUP ---
st.title("🍲 The Dinner Decider")

# Fetch current data
df = fetch_data()

with st.sidebar:
    st.header("Add a New Favorite")
    
    # URL Import
    url_input = st.text_input("Paste Recipe or Pinterest URL")
    if st.button("Auto-Fill from URL"):
        with st.spinner("Fetching..."):
            target_url = get_original_recipe_url(url_input) if "pin.it" in url_input else url_input
            try:
                scraper = scrape_me(target_url)
                st.session_state.form_meal_name = scraper.title()
                st.session_state.form_ingredients = ", ".join(scraper.ingredients())
            except:
                title, ing = generic_fallback_scraper(target_url)
                if title:
                    st.session_state.form_meal_name = title
                    st.session_state.form_ingredients = ", ".join(ing)
                else:
                    st.error("Could not extract details automatically.")

    # Manual Entry
    name = st.text_input("Meal Name", key="form_meal_name")
    cat = st.selectbox("Category", ["Quick & Easy", "Date Night", "Healthy", "Takeout Shortcut"], key="form_category")
    ing = st.text_area("Ingredients (comma separated)", key="form_ingredients")
    
    if st.button("Save to Community Pool", type="primary"):
        if name:
            new_row = pd.DataFrame([{"Meal": name, "Category": cat, "Ingredients": ing}])
            updated_df = pd.concat([df, new_row], ignore_index=True)
            conn.update(data=updated_df)
            st.success(f"Added {name}!")
            st.rerun()
        else:
            st.error("Please enter a meal name.")

    st.divider()
    
    # ADMIN SECTION (The "Secret" Delete)
    with st.expander("🔒 Admin Settings"):
        pw = st.text_input("Admin Password", type="password")
        if pw == st.secrets.get("ADMIN_PASSWORD", "admin123"): # Set this in Streamlit secrets
            if st.button("Wipe All Recipes (Careful!)"):
                empty_df = pd.DataFrame(columns=["Meal", "Category", "Ingredients"])
                conn.update(data=empty_df)
                st.rerun()

# --- MAIN TABS ---
tab1, tab2 = st.tabs(["🎲 The Decider", "📖 Shared Cookbook"])

with tab1:
    st.header("What's for dinner?")
    if st.button("Spin the Wheel", use_container_width=True, type="primary"):
        if not df.empty:
            choice = df.sample().iloc[0]
            st.session_state.current_choice = choice
            st.balloons()
        else:
            st.warning("The cookbook is empty!")

    if 'current_choice' in st.session_state:
        choice = st.session_state.current_choice
        st.markdown(f"## You are having: **{choice['Meal']}**")
        st.caption(f"Category: {choice['Category']}")
        if pd.notna(choice['Ingredients']):
            items = [i.strip() for i in str(choice['Ingredients']).split(',')]
            for item in items:
                if item: st.checkbox(item, key=f"chk_{item}")

with tab2:
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.write("No meals saved yet. Use the sidebar to add one!")
