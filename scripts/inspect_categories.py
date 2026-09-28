import sqlite3
import json

# JLCParts
conn_jlc = sqlite3.connect('data/libraries/jlcparts.db')
cur_jlc = conn_jlc.cursor()
cur_jlc.execute("SELECT DISTINCT category FROM jlc_components WHERE category != '' ORDER BY category")
jlc_cats = [r[0] for r in cur_jlc.fetchall()]

cur_jlc.execute("SELECT DISTINCT category, subcategory FROM jlc_components WHERE category != '' AND subcategory != '' ORDER BY category, subcategory")
jlc_cat_pairs = cur_jlc.fetchall()

# Altium
conn_alt = sqlite3.connect('data/libraries/altium_library.db')
cur_alt = conn_alt.cursor()
cur_alt.execute("SELECT DISTINCT category FROM altium_components WHERE category != '' ORDER BY category")
alt_cats = [r[0] for r in cur_alt.fetchall()]

print(f"Total JLCParts primary categories: {len(jlc_cats)}")
print(f"Total JLCParts subcategories: {len(jlc_cat_pairs)}")
print(f"Total Altium categories: {len(alt_cats)}")

print("\n--- Altium categories ---")
for c in alt_cats:
    print(c)

print("\n--- JLCParts primary categories ---")
for c in jlc_cats:
    print(c)

jlc_hierarchy = {}
for cat, sub in jlc_cat_pairs:
    if cat not in jlc_hierarchy:
        jlc_hierarchy[cat] = []
    jlc_hierarchy[cat].append(sub)

with open('scratch_categories.json', 'w', encoding='utf-8') as f:
    json.dump({
        "altium_categories": alt_cats,
        "jlcparts_categories": jlc_cats,
        "jlcparts_hierarchy": jlc_hierarchy
    }, f, indent=2, ensure_ascii=False)

print("\nSaved hierarchy to scratch_categories.json")
