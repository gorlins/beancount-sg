// @ts-check
// Draws a Fava extension page's ECharts charts (see beancount_sg/ext/echarts.py).
//
// Each chart is a `.echart` element with its ECharts option as JSON inside, and
// the URL to load ECharts from in its `data-echarts` attribute.

/**
 * Open a Fava page as a link would. Fava's router follows clicks on links in the
 * page, so this clicks a passing one next to the chart.
 * @param {Element} chart
 * @param {string} url
 */
function follow(chart, url) {
  const link = document.createElement("a");
  link.href = url;
  link.hidden = true;
  chart.after(link);
  link.click();
  link.remove();
}

/**
 * Draw the charts in `root`.
 * @param {ParentNode} [root]
 */
export async function renderECharts(root = document) {
  const charts = [...root.querySelectorAll("div.echart")];
  const src = charts[0]?.getAttribute("data-echarts");
  if (!src) {
    return;
  }
  const echarts = await import(src);
  const { color, fontFamily } = getComputedStyle(document.body);
  for (const element of charts) {
    if (!(element instanceof HTMLElement)) {
      continue;
    }
    const option = JSON.parse(element.querySelector("script")?.textContent ?? "{}");
    const chart = echarts.init(element, null, { renderer: "svg" });
    // Series labels have their own color; give them the page's, unless set.
    const series = (option.series ?? []).map((/** @type {{ label?: object }} */ each) => ({
      ...each,
      label: { color, fontFamily, ...each.label },
    }));
    chart.setOption({
      backgroundColor: "transparent",
      textStyle: { color, fontFamily },
      ...option,
      series,
    });
    chart.on("click", (/** @type {{ data?: { url?: string } }} */ params) => {
      const url = params.data?.url;
      if (url) {
        follow(element, url);
      }
    });
    new ResizeObserver(() => chart.resize()).observe(element);
  }
}
