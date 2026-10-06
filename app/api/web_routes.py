from pathlib import Path
from urllib.parse import urlencode, urlsplit
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.i18n import i18n, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, get_current_language
from app.warehouse_config import get_cabinet_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

favicon_path = 'favicon.ico'


def render_template(request: Request, name: str, context: dict = None) -> HTMLResponse:
    if context is None:
        context = {}
    lang = get_current_language(request)
    context["lang"] = lang
    context["t"] = lambda key, **kwargs: i18n.get(key, lang, **kwargs)
    current_query = [(key, value) for key, value in request.query_params.multi_items() if key != "lang"]
    next_url = request.url.path
    if current_query:
        next_url += "?" + urlencode(current_query)
    context["language_url"] = lambda target: "/set_language?" + urlencode({"lang": target, "next": next_url})
    sections = {
        "inventory.html": "inventory",
        "component_details.html": "details",
        "projects.html": "projects",
        "project_details.html": "project_details",
        "project_history.html": "project_history",
        "bom_import.html": "bom_import",
        "scan_import.html": "scan_import",
        "procurement.html": "procurement",
        "warehouse.html": "warehouse",
        "libraries_jlcparts.html": "libraries_jlcparts",
        "libraries_jlcparts_details.html": "libraries_jlcparts",
        "libraries_altium.html": "libraries_altium",
        "libraries_altium_details.html": "libraries_altium",
        "libraries_kicad.html": "libraries_kicad",
        "libraries_kicad_details.html": "libraries_kicad",
        "libraries_fasteners.html": "libraries_fasteners",
        "libraries_fasteners_details.html": "libraries_fasteners",
        "search.html": "search",
    }
    if name in sections:
        page_dict = i18n.get_section(sections[name], lang)
        common_dict = i18n.get_section("libraries_common", lang)
        bom_dict = i18n.get_section("bom_import", lang)
        if name == "search.html":
            context["page_translations"] = {
                **common_dict,
                **i18n.get_section("inventory", lang),
                **i18n.get_section("libraries_jlcparts", lang),
                **i18n.get_section("libraries_altium", lang),
                **i18n.get_section("libraries_kicad", lang),
                **i18n.get_section("libraries_fasteners", lang),
                **page_dict,
            }
        elif name == "inventory.html":
            context["page_translations"] = {**common_dict, **i18n.get_section("warehouse", lang), **page_dict}
        elif name in ("projects.html", "project_details.html"):
            context["page_translations"] = {**common_dict, **page_dict, **bom_dict}
        else:
            context["page_translations"] = {**common_dict, **page_dict}
    
    response = templates.TemplateResponse(request=request, name=name, context=context)
    if "lang" in request.query_params:
        response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response

@router.get("/set_language")
def set_language(request: Request, lang: str = DEFAULT_LANGUAGE, next: str = "/"):
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    parsed = urlsplit(next)
    if (
        not next.startswith("/")
        or next.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in next
        or any(ord(char) < 32 for char in next)
    ):
        next = "/"
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response

@router.get("/", response_class=HTMLResponse)
def get_home_template(request: Request):
    return render_template(request=request, name="home.html", context={"active_page": "home"})

@router.get("/inventory", response_class=HTMLResponse)
def get_inventory_template(request: Request):
    return render_template(request=request, name="inventory.html", context={"active_page": "inventory"})


@router.get("/scan-import", response_class=HTMLResponse)
def get_scan_import_template(request: Request, project_id: int | None = None):
    return render_template(request=request, name="scan_import.html", context={
        "active_page": "scan_import", "project_id": project_id if project_id and project_id > 0 else None,
    })

@router.get("/component_details", response_class=HTMLResponse)
def get_component_details_template(request: Request):
    return render_template(request=request, name="component_details.html", context={"active_page": "details"})

@router.get("/projects", response_class=HTMLResponse)
def get_projects_template(request: Request):
    return render_template(request=request, name="projects.html", context={"active_page": "projects"})

@router.get("/project_details", response_class=HTMLResponse)
def get_project_details_template(request: Request):
    return render_template(request=request, name="project_details.html", context={"active_page": "projects"})


@router.get("/project-history", response_class=HTMLResponse)
def get_project_history_template(request: Request):
    return render_template(
        request=request,
        name="project_history.html",
        context={"active_page": "project_history"},
    )


@router.get("/bom-import", response_class=HTMLResponse)
def get_bom_import_template(request: Request, project_id: int | None = None):
    return_url = f"/project_details?project_id={project_id}" if project_id and project_id > 0 else "/projects"
    return render_template(
        request=request,
        name="bom_import.html",
        context={
            "active_page": "projects",
            "project_id": project_id if project_id and project_id > 0 else None,
            "return_url": return_url,
        },
    )

@router.get("/procurement", response_class=HTMLResponse)
def get_procurement_template(request: Request):
    return render_template(request=request, name="procurement.html", context={"active_page": "procurement"})

@router.get("/warehouse", response_class=HTMLResponse)
def get_warehouse_template(request: Request):
    return render_template(
        request=request,
        name="warehouse.html",
        context={"active_page": "warehouse", "warehouse_cabinets": get_cabinet_config()},
    )

@router.get("/search", response_class=HTMLResponse)
def get_search_template(request: Request, q: str = ""):
    return render_template(
        request=request,
        name="search.html",
        context={"active_page": "search", "initial_query": q}
    )

# ==========================================
# Component Libraries Routes
# ==========================================

@router.get("/libraries/jlcparts", response_class=HTMLResponse)
def get_jlcparts_library_template(request: Request):
    return render_template(
        request=request,
        name="libraries_jlcparts.html",
        context={"active_page": "lib_jlcparts", "active_lib": "jlcparts"}
    )

@router.get("/libraries/jlcparts/{lcsc}", response_class=HTMLResponse)
def get_jlcparts_details_template(request: Request, lcsc: int):
    return render_template(
        request=request,
        name="libraries_jlcparts_details.html",
        context={"active_page": "lib_jlcparts_details", "active_lib": "jlcparts", "lcsc": lcsc}
    )

@router.get("/libraries/altium", response_class=HTMLResponse)
def get_altium_library_template(request: Request):
    return render_template(
        request=request,
        name="libraries_altium.html",
        context={"active_page": "lib_altium", "active_lib": "altium"}
    )

@router.get("/libraries/altium/{comp_id}", response_class=HTMLResponse)
def get_altium_details_template(request: Request, comp_id: int):
    return render_template(
        request=request,
        name="libraries_altium_details.html",
        context={"active_page": "lib_altium_details", "active_lib": "altium", "comp_id": comp_id}
    )

@router.get("/libraries/kicad", response_class=HTMLResponse)
def get_kicad_library_template(request: Request):
    return render_template(
        request=request,
        name="libraries_kicad.html",
        context={"active_page": "lib_kicad", "active_lib": "kicad"}
    )

@router.get("/libraries/kicad/{sym_id}", response_class=HTMLResponse)
def get_kicad_details_template(request: Request, sym_id: int):
    return render_template(
        request=request,
        name="libraries_kicad_details.html",
        context={"active_page": "lib_kicad_details", "active_lib": "kicad", "sym_id": sym_id}
    )

@router.get("/libraries/fasteners", response_class=HTMLResponse)
def get_fasteners_library_template(request: Request):
    return render_template(
        request=request,
        name="libraries_fasteners.html",
        context={"active_page": "lib_fasteners", "active_lib": "fasteners"}
    )

@router.get("/libraries/fasteners/{standard_code}", response_class=HTMLResponse)
def get_fasteners_details_template(request: Request, standard_code: str):
    return render_template(
        request=request,
        name="libraries_fasteners_details.html",
        context={"active_page": "lib_fasteners_details", "active_lib": "fasteners", "standard_code": standard_code}
    )
