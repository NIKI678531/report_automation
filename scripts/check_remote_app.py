"""Exercise built federation assets in Chromium without starting any HTTP server.

Run npm run build, npm run build:host-contract --workspace @commentary/web,
then python scripts/check_remote_app.py. All browser requests are intercepted;
the backend fixtures never connect to a database or write application data.
"""
from copy import deepcopy
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "/remote/fund-cmt-auto"
API = BASE + "/api/v1"
HOST = "https://host.contract.test"
ASSETS = ROOT / "frontend/dist"
HOST_ASSETS = ROOT / "var/remote-contract/host"


def report_fixture():
    return {
        "id": "contract-report", "product_code": "3033", "product_name": "CSOP Hang Seng TECH Index ETF",
        "constituent_index_code": "HSTECH", "benchmark_instrument_code": "HSTECHN",
        "benchmark_code": "HSTECH", "report_date": "2026-08-31", "language_mode": "EN",
        "status": "EDITING", "lane": "PRODUCTION", "revision": 1, "version": 1,
        "active_snapshot_id": None, "created_at": "2026-08-31T00:00:00Z",
        "translation_enabled": False, "quality_results": [], "artifacts": [],
        "latest_document": {"version": 1, "checksum": "contract", "content": {
            "month_name": "August", "product_ticker": "3033.HK", "language_mode": "EN",
            "sections": {
                "month_in_review": {"title": "August in Review", "summary": "Contract review", "drivers": [], "monitor": [], "outlook": ""},
                "historical_performance": {"rows": []}, "company_news": [], "constituents": [],
                "analytics": {"top10": [], "top": [], "bottom": [], "portfolio": []},
                "footnotes": {"historical": "", "constituents": "", "analytics": ""},
            },
        }},
    }


def check_browser(browser, remote_origin="", host_origin=HOST):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    state = {"report": report_fixture(), "fail_save": False, "saves": []}
    requests, errors, unexpected = [], [], []

    def serve(route):
        url = urlparse(route.request.url)
        path = url.path
        requests.append(route.request.url)
        headers = {"Access-Control-Allow-Origin": "*"}
        if path.startswith(API):
            resource = path[len(API):]
            if resource == "/reports":
                data = [state["report"]]
            elif resource == "/products":
                data = [{"product_code": "3033", "name_en": "CSOP Hang Seng TECH Index ETF"}]
            elif resource == "/reports/contract-report":
                data = state["report"]
            elif resource == "/reports/contract-report/automatic-data/refresh":
                data = {"changed": False}
            elif resource == "/reports/contract-report/document" and route.request.method == "PATCH":
                if state["fail_save"]:
                    route.fulfill(status=409, json={"message": "Contract save rejected"})
                    return
                payload = route.request.post_data_json
                state["saves"].append(deepcopy(payload))
                state["report"]["latest_document"]["content"] = payload["content"]
                state["report"]["latest_document"]["version"] += 1
                data = {"version": state["report"]["latest_document"]["version"]}
            elif resource == "/reports/contract-report/preview":
                route.fulfill(content_type="text/html", body="<h1>Contract report preview</h1>")
                return
            else:
                unexpected.append(f"{route.request.method} {path}")
                route.fulfill(status=404, json={"message": "Unexpected contract API request"})
                return
            route.fulfill(json=data, headers=headers)
            return
        if path.startswith(BASE + "/"):
            relative = path[len(BASE) + 1:] or "index.html"
            file = ASSETS / relative
        elif path.startswith("/host-assets/"):
            file = HOST_ASSETS / path.removeprefix("/host-assets/")
        elif path in {"/fund-cmt-auto", "/host-home"}:
            route.fulfill(content_type="text/html", body='''<!doctype html><html lang="fr"><head>
<style>body { margin: 13px; background: rgb(239, 240, 241); }
button { color: rgb(90, 12, 34); border-radius: 0; }
#host-control { font: 17px serif; }</style></head><body><div id="root"></div>
<script src="/host-assets/main.js"></script></body></html>''')
            return
        else:
            unexpected.append(path)
            route.fulfill(status=404, body="Not found")
            return
        if not file.resolve().is_relative_to(ROOT) or not file.is_file():
            unexpected.append(path)
            route.fulfill(status=404, body="Missing asset")
            return
        content_type = "text/javascript" if file.suffix == ".js" else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        route.fulfill(body=file.read_bytes(), content_type=content_type, headers=headers)

    context.route("**/*", serve)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    target = host_origin + "/fund-cmt-auto" + (f"?remoteOrigin={remote_origin}" if remote_origin else "")
    page.goto(target)
    surface = page.locator("[data-fund-cmt-auto]")
    expect(surface.get_by_role("heading", name="Report center", exact=True)).to_be_visible()
    if not remote_origin:
        output = ROOT / "output/playwright/fund-cmt-remote.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
    assert page.url == target
    assert page.evaluate("document.documentElement.lang") == "fr"
    assert page.locator("#host-control").evaluate("el => getComputedStyle(el).color") == "rgb(90, 12, 34)"
    assert page.locator("body").evaluate("el => getComputedStyle(el).margin") == "13px"
    assert surface.locator(".fund-cmt-surface").evaluate("el => getComputedStyle(el).color") == "rgb(30, 41, 59)"
    assert surface.get_by_role("heading", name="Report center", exact=True).evaluate("el => getComputedStyle(el).fontFamily").startswith("Inter")
    assert page.evaluate("window.contractShareScope.react['18.3.1'].loaded") == 1
    assert page.evaluate("window.contractShareScope.react['18.3.1'].from") == "contractHost"
    assert list(page.evaluate("Object.keys(window.contractShareScope['react-router-dom'])")) == ["6.30.0"]

    try:
        surface.locator("button.report-record").click(timeout=8000)
    except Exception:
        print(json.dumps({"requests": requests, "errors": errors, "unexpected": unexpected,
                          "surface": surface.locator(".fund-cmt-surface").inner_text()}, ensure_ascii=True))
        raise
    expect(surface.locator(".tiptap").first).to_be_visible()
    surface.locator(".tiptap").first.fill("Edited inside shadow DOM")
    # Selection/formatting is a sensitive integration point for shadow DOM editors.
    surface.locator(".tiptap").first.press("ControlOrMeta+a")
    surface.get_by_title("Bold", exact=True).first.click()
    expect(surface.locator(".tiptap strong").first).to_have_text("Edited inside shadow DOM")
    surface.get_by_role("button", name=re.compile("Footnotes & Disclosures")).click()
    expect(surface.get_by_label("Historical footnote")).to_be_visible()
    assert state["saves"], "Switching modules must save rich-text edits"
    surface.get_by_label("Historical footnote").fill("Disclosure saved through remote proxy")
    state["fail_save"] = True
    surface.get_by_role("button", name="Report center", exact=True).click()
    expect(surface.get_by_role("alert")).to_contain_text("Contract save rejected")
    expect(surface.get_by_label("Historical footnote")).to_have_value("Disclosure saved through remote proxy")
    assert page.url == target
    state["fail_save"] = False
    surface.get_by_role("button", name="Report center", exact=True).click()
    expect(surface.get_by_role("heading", name="Report center", exact=True)).to_be_visible()
    assert state["report"]["latest_document"]["content"]["sections"]["footnotes"]["historical"] == "Disclosure saved through remote proxy"
    assert page.url == target

    surface.locator("button.report-record").click()
    with page.expect_popup() as popup_info:
        surface.get_by_role("button", name="Preview", exact=True).click()
    preview = popup_info.value
    expect(preview.get_by_role("heading", name="Contract report preview")).to_be_visible()
    assert urlparse(preview.url).path == API + "/reports/contract-report/preview"
    preview.close()
    page.get_by_role("link", name="Host home", exact=True).click()
    expect(page.get_by_role("heading", name="Host home", exact=True)).to_be_visible()
    assert page.locator("[data-fund-cmt-fonts]").count() == 0
    assert page.locator("[data-fund-cmt-auto]").count() == 0
    assert page.evaluate("document.documentElement.lang") == "fr"
    page.get_by_role("link", name="Fund commentary", exact=True).click()
    expect(surface.get_by_role("heading", name="Report center", exact=True)).to_be_visible()
    assert page.locator("[data-fund-cmt-fonts]").count() == 1
    page.go_back()
    expect(page.get_by_role("heading", name="Host home", exact=True)).to_be_visible()
    assert not errors, errors
    assert not unexpected, unexpected
    assert all(not urlparse(url).path.startswith("/api/") for url in requests)
    if remote_origin:
        chunks = [url for url in requests if "/remote/fund-cmt-auto/assets/" in url]
        assert chunks and all(url.startswith(remote_origin) for url in chunks), chunks
    context.close()
    return {"remote_origin": remote_origin or "same origin", "requests": len(requests), "saves": len(state["saves"])}


def check_standalone(browser):
    # Reuse an isolated request context to validate the HTML bootstrap publicPath.
    context = browser.new_context()
    failures = []
    def serve(route):
        path = urlparse(route.request.url).path
        if path.startswith(API):
            route.fulfill(json=[])
            return
        file = ASSETS / (path.removeprefix(BASE + "/") or "index.html")
        if not file.resolve().is_relative_to(ASSETS) or not file.is_file():
            failures.append(path)
            route.fulfill(status=404)
            return
        route.fulfill(body=file.read_bytes(), content_type="text/javascript" if file.suffix == ".js" else mimetypes.guess_type(file.name)[0] or "application/octet-stream")
    context.route("**/*", serve)
    page = context.new_page()
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.goto(HOST + BASE + "/")
    expect(page.get_by_role("heading", name="Report center", exact=True)).to_be_visible()
    assert not failures, failures
    context.close()


if __name__ == "__main__":
    assert (ASSETS / "remoteEntry.js").is_file(), "Build the remote first"
    assert (HOST_ASSETS / "main.js").is_file(), "Build the host contract fixture first"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        results = [check_browser(browser), check_browser(browser, "http://localhost:3030", "http://localhost:3000")]
        check_standalone(browser)
        browser.close()
    print(json.dumps({"status": "passed", "host_contract": results, "standalone": "passed"}, indent=2))
