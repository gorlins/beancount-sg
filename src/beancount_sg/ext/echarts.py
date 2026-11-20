"""ECharts in Fava extension reports: options in the template, data from an endpoint.

Fava's own charts are bar, line and hierarchy charts. `ECharts
<https://echarts.apache.org>`_ adds others, e.g. Sankey diagrams. A report
using it:

1. Also subclasses `ECharts`, which serves the browser helper, ``echarts.js``,
   as one of the extension's endpoints::

       class MyReport(ECharts, FavaExtensionBase): ...

2. Serves each chart's data from an endpoint of its own, as the part of an
   ECharts option that holds data, e.g. ``{"dataset": {"source": [...]}}``::

       @extension_endpoint("totals")
       def totals(self) -> dict[str, object]: ...

3. Places the chart in its template: an element with class ``echart``, the
   chart's option (all but its data) as JSON inside, where to load ECharts from,
   and its data endpoint's URL, with the page's filters::

       <div class="echart" style="height: 300px"
            data-library="{{ extension.echarts_url }}"
            data-source="{{ extension.endpoint_url('totals') }}">
         <script type="application/json">{"series": [{"type": "bar"}]}</script>
       </div>

4. Draws the page's charts from its JS module when the page loads::

       export default {
         async onExtensionPageLoad() {
           const helper = new URL("echarts.js", window.location.href).href;
           const { renderECharts } = await import(helper);
           await renderECharts();
         },
       };

The helper loads ECharts, draws each chart from its option in the page's text
color and font, on a transparent background, then fetches its data and merges
it in (ECharts' dynamic data loading). Clicking a node or data item with a
``url`` opens that Fava page.

ECharts is loaded from `ECHARTS_URL`, the latest 5.x release on a CDN, unless
the extension's config sets ``echarts_url``, e.g. to pin a version::

    2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow" "{
      'echarts_url': 'https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.esm.min.mjs'}"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fava.application import url_for
from fava.ext import extension_endpoint
from flask import Response, send_file

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.esm.min.mjs"
HELPER = Path(__file__).with_name("echarts.js")


class ECharts:
    """A mixin for a Fava extension that draws ECharts charts."""

    # From `FavaExtensionBase`.
    config: Any
    name: str

    @extension_endpoint("echarts.js")
    def echarts_helper(self) -> Response:
        """The browser helper that draws the page's charts."""
        return send_file(HELPER, mimetype="text/javascript")

    @property
    def echarts_url(self) -> str:
        """Where to load ECharts from: the extension's ``echarts_url`` config, or `ECHARTS_URL`."""
        config = self.config if isinstance(self.config, dict) else {}
        return config.get("echarts_url", ECHARTS_URL)

    def endpoint_url(self, endpoint: str) -> str:
        """The URL of one of the extension's endpoints, with the page's filters."""
        # The extension's report URL, which Fava's url_for gives the filters, plus
        # the endpoint: url_for can't name it, as it has its own ``endpoint``.
        report = urlsplit(url_for("extension_report", extension_name=self.name))
        return urlunsplit(report._replace(path=report.path + endpoint))
