"""ECharts in Fava extension reports: options in the template, data from an endpoint.

Fava's own charts are bar, line and hierarchy charts. `ECharts
<https://echarts.apache.org>`_ adds others, e.g. Sankey diagrams. A report
using it:

1. Also subclasses `ECharts`, which serves the browser helper, ``echarts.js``,
   as one of the extension's endpoints::

       class MyReport(ECharts, FavaExtensionBase): ...

2. Serves each chart's data from an endpoint of its own, as the part of an
   ECharts option that holds data, e.g. ``{"dataset": {"source": [...]}}``::

       @extension_endpoint
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

ECharts is loaded from `ECHARTS_URL`, the latest 6.x release on a CDN, unless
the ledger sets another URL for all its reports, e.g. to pin a version, with a
``beancount-sg-option`` like Fava's ``fava-option``::

    2020-01-01 custom "beancount-sg-option" "echarts-url" "https://cdn.jsdelivr.net/npm/echarts@6.1.0/dist/echarts.esm.min.mjs"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from beancount.core.data import Custom
from fava.application import url_for
from fava.ext import extension_endpoint
from flask import Response, send_file

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@6/dist/echarts.esm.min.mjs"
HELPER = Path(__file__).with_name("echarts.js")
# The custom directive type, and its option, that set where ECharts loads from.
OPTION = "beancount-sg-option"
URL_OPTION = "echarts-url"


class ECharts:
    """A mixin for a Fava extension that draws ECharts charts."""

    # From `FavaExtensionBase`.
    ledger: Any
    name: str

    @extension_endpoint("echarts.js")
    def echarts_helper(self) -> Response:
        """The browser helper that draws the page's charts."""
        return send_file(HELPER, mimetype="text/javascript")

    @property
    def echarts_url(self) -> str:
        """Where to load ECharts from: the ledger's ``echarts-url`` option (the last), or
        `ECHARTS_URL`."""
        urls = [
            entry.values[1].value
            for entry in self.ledger.all_entries_by_type.Custom
            if isinstance(entry, Custom)
            and entry.type == OPTION
            and len(entry.values) == 2
            and entry.values[0].value == URL_OPTION
        ]
        return urls[-1] if urls else ECHARTS_URL

    def endpoint_url(self, endpoint: str) -> str:
        """The URL of one of the extension's endpoints, with the page's filters."""
        # The extension's report URL, which Fava's url_for gives the filters, plus
        # the endpoint: url_for can't name it, as it has its own ``endpoint``.
        report = urlsplit(url_for("extension_report", extension_name=self.name))
        return urlunsplit(report._replace(path=report.path + endpoint))
