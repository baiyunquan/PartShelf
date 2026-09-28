from urllib.parse import urlencode, urlsplit
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
    current_query = [(key, value) for key, value in request.query_params.multi_items() if key != "lang"]
    next_url = request.url.path
    if current_query:
        next_url += "?" + urlencode(current_query)
    context["language_url"] = lambda target: "/set_language?" + urlencode({"lang": target, "next": next_url})
    sections = {"inventory.html": "inventory", "component_details.html": "details"}
    if name in sections:
        context["page_translations"] = i18n.get_section(sections[name], lang)
    
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
