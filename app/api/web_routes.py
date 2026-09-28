import json
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.i18n import i18n, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

templates = Jinja2Templates(directory="templates")

router = APIRouter()

favicon_path = 'favicon.ico'

def get_current_language(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    return lang

def render_template(request: Request, name: str, context: dict = None) -> HTMLResponse:
    if context is None:
        context = {}
    lang = get_current_language(request)
    context["lang"] = lang
    context["t"] = lambda key, **kwargs: i18n.get(key, lang, **kwargs)
    context["translations_json"] = json.dumps(i18n.get_all(lang), ensure_ascii=False)
    
    response = templates.TemplateResponse(request=request, name=name, context=context)
    if "lang" in request.query_params:
        response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response

@router.get("/set_language")
def set_language(request: Request, lang: str = DEFAULT_LANGUAGE, next: str = "/"):
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    if not next.startswith("/"):
        next = "/"
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response

@router.get("/", response_class=HTMLResponse)
def get_home_template(request: Request):
    return render_template(request=request, name="home.html")

@router.get("/inventory", response_class=HTMLResponse)
def get_inventory_template(request: Request):
    return render_template(request=request, name="inventory.html")

@router.get("/component_details", response_class=HTMLResponse)
def get_component_details_template(request: Request):
    return render_template(request=request, name="component_details.html")

@router.get("/projects", response_class=HTMLResponse)
def get_projects_template(request: Request):
    return render_template(request=request, name="projects.html")