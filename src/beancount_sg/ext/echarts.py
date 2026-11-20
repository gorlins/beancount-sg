"""ECharts in Fava extension reports: charts built in Python, drawn in the browser.

Fava's own charts are bar, line and hierarchy charts. `ECharts
<https://echarts.apache.org>`_ adds others, e.g. Sankey diagrams. A report uses
it in three steps:

1. Its extension class also subclasses `ECharts`, which serves the browser
   helper, ``echarts.js``, as one of the extension's endpoints::

       class MyReport(ECharts, FavaExtensionBase): ...

2. Its template places a chart, from an ECharts option built in Python::

       {{ extension.echart(option, height="300px") }}

3. Its JS module draws the page's charts when the page loads::

       export default {
         async onExtensionPageLoad() {
           const helper = new URL("echarts.js", window.location.href).href;
           const { renderECharts } = await import(helper);
           await renderECharts();
         },
       };

The helper loads ECharts from `ECHARTS_URL`, a CDN, and draws each chart in the
page's text color and font, on a transparent background. Clicking a node or
data item with a ``url`` opens that Fava page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fava.ext import extension_endpoint
from flask import Response, send_file
from jinja2.utils import htmlsafe_json_dumps
from markupsafe import Markup, escape

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.esm.min.mjs"
HELPER = Path(__file__).with_name("echarts.js")


class ECharts:
    """A mixin for a Fava extension that draws ECharts charts."""

    @extension_endpoint("echarts.js")
    def echarts_helper(self) -> Response:
        """The browser helper that draws the page's charts."""
        return send_file(HELPER, mimetype="text/javascript")

    @staticmethod
    def echart(option: dict[str, Any], height: str = "300px") -> Markup:
        """A chart's placeholder, which the helper draws from ``option``."""
        return Markup(
            '<div class="echart" data-echarts="{src}" style="height: {height}">'
            '<script type="application/json">{option}</script></div>'
        ).format(src=ECHARTS_URL, height=escape(height), option=htmlsafe_json_dumps(option))
