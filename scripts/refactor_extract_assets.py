"""
Automated asset separation tool for PartShelf templates.
Extracts embedded CSS and JavaScript from all Jinja2 HTML templates
into external static/css and static/js files.
"""

from pathlib import Path
import re
import json

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

CSS_DIR.mkdir(parents=True, exist_ok=True)
JS_DIR.mkdir(parents=True, exist_ok=True)


def refactor_home():
    html_file = TEMPLATES_DIR / "home.html"
    content = html_file.read_text(encoding="utf-8")
    
    # Extract style
    m = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    if m:
        css_content = m.group(1).strip() + "\n"
        css_file = CSS_DIR / "home.css"
        css_file.write_text(css_content, encoding="utf-8")
        print(f"Extracted: {css_file} ({len(css_content)} bytes)")
        
        replacement = '<link href="/static/css/home.css" rel="stylesheet">'
        content = content[:m.start()] + replacement + content[m.end():]
        html_file.write_text(content, encoding="utf-8")
        print(f"Updated: {html_file}")


def refactor_search():
    html_file = TEMPLATES_DIR / "search.html"
    content = html_file.read_text(encoding="utf-8")
    
    # 1. Extract style
    m_style = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    if m_style:
        css_content = m_style.group(1).strip() + "\n"
        css_file = CSS_DIR / "search.css"
        css_file.write_text(css_content, encoding="utf-8")
        print(f"Extracted: {css_file} ({len(css_content)} bytes)")
        replacement_style = '<link href="/static/css/search.css" rel="stylesheet">'
        content = content[:m_style.start()] + replacement_style + content[m_style.end():]
    
    # 2. Extract script
    # Match the inline script at the bottom
    m_script = re.search(r"<script>(?![\s\S]*?<script>)(.*?)</script>", content, re.DOTALL)
    if m_script:
        js_code = m_script.group(1).strip()
        # Decouple initial_query
        js_code = js_code.replace(
            'let currentQuery = "{{ initial_query }}".trim();',
            "let currentQuery = (document.getElementById('centerSearchInput')?.value || '').trim();"
        )
        js_file = JS_DIR / "search.js"
        js_file.write_text(js_code + "\n", encoding="utf-8")
        print(f"Extracted: {js_file} ({len(js_code)} bytes)")
        
        replacement_script = '<script src="/static/js/search.js"></script>'
        content = content[:m_script.start()] + replacement_script + content[m_script.end():]
    
    html_file.write_text(content, encoding="utf-8")
    print(f"Updated: {html_file}")


def refactor_navbar():
    html_file = TEMPLATES_DIR / "partials" / "navbar.html"
    content = html_file.read_text(encoding="utf-8")
    
    m_script = re.search(r"<script>\s*\(\(\)\s*=>\s*\{(.*?)\}\)\(\);\s*</script>", content, re.DOTALL)
    if not m_script:
        m_script = re.search(r"<script>\s*\(function\(\)\s*\{(.*?)\}\)\(\);\s*</script>", content, re.DOTALL)
    
    if m_script:
        raw_body = m_script.group(1)
        
        # Replace Jinja translations with navI18n object references
        js_body = raw_body
        js_body = js_body.replace("{{ t('search.live_no_matches') }}", "${navI18n.live_no_matches || 'No matches found'}")
        js_body = js_body.replace("{{ t('search.card_inventory_title') }}", "${navI18n.card_inventory_title || 'Inventory'}")
        js_body = js_body.replace("{{ t('search.card_jlcparts_title') }}", "${navI18n.card_jlcparts_title || 'JLCParts'}")
        js_body = js_body.replace("{{ t('search.card_altium_title') }}", "${navI18n.card_altium_title || 'Altium'}")
        js_body = js_body.replace("{{ t('search.card_kicad_title') }}", "${navI18n.card_kicad_title || 'KiCad'}")
        js_body = js_body.replace("{{ t('app.nav_lib_fasteners') }}", "${navI18n.nav_lib_fasteners || 'Mechanical'}")
        js_body = js_body.replace("{{ t('search.live_view_all') }}", "${navI18n.live_view_all || 'View All Results'}")
        
        # Prepend navI18n loading
        nav_js_code = (
            "(() => {\n"
            "  const navI18n = JSON.parse(document.getElementById('navbar-translations')?.textContent || '{}');\n"
            + js_body
            + "\n})();\n"
        )
        
        js_file = JS_DIR / "navbar_search.js"
        js_file.write_text(nav_js_code, encoding="utf-8")
        print(f"Extracted: {js_file} ({len(nav_js_code)} bytes)")
        
        replacement = (
            '<script id="navbar-translations" type="application/json">\n'
            '      {\n'
            '        "live_no_matches": {{ t(\'search.live_no_matches\') | tojson }},\n'
            '        "card_inventory_title": {{ t(\'search.card_inventory_title\') | tojson }},\n'
            '        "card_jlcparts_title": {{ t(\'search.card_jlcparts_title\') | tojson }},\n'
            '        "card_altium_title": {{ t(\'search.card_altium_title\') | tojson }},\n'
            '        "card_kicad_title": {{ t(\'search.card_kicad_title\') | tojson }},\n'
            '        "nav_lib_fasteners": {{ t(\'app.nav_lib_fasteners\') | tojson }},\n'
            '        "live_view_all": {{ t(\'search.live_view_all\') | tojson }}\n'
            '      }\n'
            '    </script>\n'
            '    <script src="/static/js/navbar_search.js"></script>'
        )
        content = content[:m_script.start()] + replacement + content[m_script.end():]
        html_file.write_text(content, encoding="utf-8")
        print(f"Updated: {html_file}")


def refactor_standard_page(filename: str, js_filename: str):
    html_file = TEMPLATES_DIR / filename
    content = html_file.read_text(encoding="utf-8")
    
    # Find inline script that is not application/json or src=
    pattern = re.compile(r"<script>(?![\s\S]*?<script>)(.*?)</script>", re.DOTALL)
    m = pattern.search(content)
    if m:
        js_code = m.group(1).strip() + "\n"
        js_file = JS_DIR / js_filename
        js_file.write_text(js_code, encoding="utf-8")
        print(f"Extracted: {js_file} ({len(js_code)} bytes)")
        
        replacement = f'<script src="/static/js/{js_filename}"></script>'
        content = content[:m.start()] + replacement + content[m.end():]
        html_file.write_text(content, encoding="utf-8")
        print(f"Updated: {html_file}")


def refactor_detail_page(filename: str, js_filename: str, param_name: str, jinja_expr: str, js_var: str):
    html_file = TEMPLATES_DIR / filename
    content = html_file.read_text(encoding="utf-8")
    
    # 1. Add data attribute to #detailContainer
    data_attr = f'data-{param_name}="{jinja_expr}"'
    if 'id="detailContainer"' in content and data_attr not in content:
        content = content.replace('id="detailContainer"', f'id="detailContainer" {data_attr}')
    
    # 2. Extract script
    pattern = re.compile(r"<script>(?![\s\S]*?<script>)(.*?)</script>", re.DOTALL)
    m = pattern.search(content)
    if m:
        js_code = m.group(1).strip()
        
        # Replace the Jinja assignment line with reading from data attribute / URL fallback
        # e.g. const compId = {{ comp_id }};
        if param_name == "standard-code":
            js_replacement = (
                f"const {js_var} = document.getElementById('detailContainer')?.dataset?.{re.sub(r'-([a-z])', lambda m: m.group(1).upper(), param_name)}"
                f" || decodeURIComponent(window.location.pathname.split('/').filter(Boolean).pop());"
            )
        else:
            js_replacement = (
                f"const {js_var} = document.getElementById('detailContainer')?.dataset?.{re.sub(r'-([a-z])', lambda m: m.group(1).upper(), param_name)}"
                f" || window.location.pathname.split('/').filter(Boolean).pop();"
            )
        
        js_code = re.sub(
            rf"const\s+{js_var}\s*=\s*\{{.*?\}};",
            js_replacement,
            js_code
        )
        
        js_file = JS_DIR / js_filename
        js_file.write_text(js_code + "\n", encoding="utf-8")
        print(f"Extracted: {js_file} ({len(js_code)} bytes)")
        
        replacement = f'<script src="/static/js/{js_filename}"></script>'
        content = content[:m.start()] + replacement + content[m.end():]
        html_file.write_text(content, encoding="utf-8")
        print(f"Updated: {html_file}")


def main():
    print("Beginning automated asset separation...")
    
    # CSS
    refactor_home()
    refactor_search()
    
    # Navbar
    refactor_navbar()
    
    # Standard pages (without custom URL params in script)
    refactor_standard_page("projects.html", "projects.js")
    refactor_standard_page("project_details.html", "project_details.js")
    refactor_standard_page("procurement.html", "procurement.js")
    refactor_standard_page("libraries_altium.html", "libraries_altium.js")
    refactor_standard_page("libraries_jlcparts.html", "libraries_jlcparts.js")
    refactor_standard_page("libraries_kicad.html", "libraries_kicad.js")
    refactor_standard_page("libraries_fasteners.html", "libraries_fasteners.js")
    
    # Detail pages with URL / ID parameter
    refactor_detail_page("libraries_altium_details.html", "libraries_altium_details.js", "comp-id", "{{ comp_id }}", "compId")
    refactor_detail_page("libraries_jlcparts_details.html", "libraries_jlcparts_details.js", "lcsc", "{{ lcsc }}", "lcscNum")
    refactor_detail_page("libraries_kicad_details.html", "libraries_kicad_details.js", "sym-id", "{{ sym_id }}", "symId")
    refactor_detail_page("libraries_fasteners_details.html", "libraries_fasteners_details.js", "standard-code", "{{ standard_code }}", "standardCode")
    
    print("\nAsset separation complete! Verifying remaining inline styles and scripts...")
    
    # Verification
    files = sorted(list(TEMPLATES_DIR.rglob("*.html")))
    remaining_styles = 0
    remaining_scripts = 0
    for f in files:
        txt = f.read_text(encoding="utf-8")
        styles = re.findall(r"<style\b[^>]*>(.*?)</style>", txt, re.DOTALL)
        raw_scripts = [
            m for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", txt, re.DOTALL)
            if "application/json" not in m.group(1) and "src=" not in m.group(1) and m.group(2).strip()
        ]
        if styles:
            remaining_styles += len(styles)
            print(f"Warning: {f.name} still has {len(styles)} style tags!")
        if raw_scripts:
            remaining_scripts += len(raw_scripts)
            print(f"Warning: {f.name} still has {len(raw_scripts)} inline script tags!")
    
    if remaining_styles == 0 and remaining_scripts == 0:
        print("ALL HTML templates are 100% clean of inline style and script tags!")
    else:
        print(f"Remaining styles: {remaining_styles}, remaining scripts: {remaining_scripts}")


if __name__ == "__main__":
    main()
