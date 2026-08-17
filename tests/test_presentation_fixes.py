import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
JS_FILE = ROOT / "app" / "static" / "js" / "presentation-fixes.js"
FOOTER = ROOT / "app" / "templates" / "partials" / "footer.html"
GLOBAL_CSS = ROOT / "app" / "static" / "css" / "presentation-fixes.css"
IMS_CSS = ROOT / "app" / "static" / "css" / "ims-dark-fixes.css"


def test_presentation_assets_are_loaded_globally():
    footer = FOOTER.read_text(encoding="utf-8")
    assert "css/presentation-fixes.css" in footer
    assert "css/ims-dark-fixes.css" in footer
    assert "js/presentation-fixes.js" in footer


def test_dark_mode_layers_cover_global_and_ims_surfaces():
    global_css = GLOBAL_CSS.read_text(encoding="utf-8")
    ims_css = IMS_CSS.read_text(encoding="utf-8")
    assert '[data-theme="dark"] body.authenticated .form-control' in global_css
    assert '[style*="color:#1c3558"]' in global_css
    assert '[data-theme="dark"] body.authenticated .ims-upload-card' in ims_css
    assert '[data-theme="dark"] body.authenticated .ims-dropzone' in ims_css
    assert "#production-results .alert" in ims_css


def test_realization_display_rounding_rule_and_scientific_zero():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available in this environment")

    harness = f"""
    global.Node = {{ TEXT_NODE: 3, ELEMENT_NODE: 1, DOCUMENT_FRAGMENT_NODE: 11 }};
    global.NodeFilter = {{ SHOW_TEXT: 4 }};
    global.MutationObserver = function() {{ this.observe = function() {{}}; }};
    global.document = {{
      readyState: 'complete',
      body: {{ nodeType: 1 }},
      createTreeWalker: function() {{ return {{ nextNode: function() {{ return null; }} }}; }}
    }};
    global.window = global;
    require({json.dumps(str(JS_FILE))});
    const values = [90.54, 95.50, 12.51, 12.50, 12.49, 79.6696913311, 0e4];
    console.log(JSON.stringify(values.map(global.roundRealizationForDisplay)));
    """
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout.strip()) == [91, 95, 13, 12, 12, 80, 0]
