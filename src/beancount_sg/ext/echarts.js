// @ts-check
// Draws a Fava extension page's ECharts charts (see beancount_sg/ext/echarts.py).
//
// Each chart is a `.echart` element with its option, all but the data, as JSON
// inside; where to load ECharts from in `data-library`; and, in `data-source`,
// an endpoint whose JSON is the option's data part, merged in once fetched.

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
 * The chart's option, in the page's text color and font unless it sets its own.
 * @param {HTMLElement} element
 */
function baseOption(element) {
  const option = JSON.parse(element.querySelector("script")?.textContent ?? "{}");
  const { color, fontFamily } = getComputedStyle(document.body);
  // Series labels have their own default color.
  const series = (option.series ?? []).map((/** @type {{ label?: object }} */ each) => ({
    ...each,
    label: { color, fontFamily, ...each.label },
  }));
  return { backgroundColor: "transparent", textStyle: { color, fontFamily }, ...option, series };
}

/**
 * Draw the charts in `root`.
 * @param {ParentNode} [root]
 */
export async function renderECharts(root = document) {
  const elements = [...root.querySelectorAll("div.echart")].filter(
    (element) => element instanceof HTMLElement,
  );
  const library = elements[0]?.dataset.library;
  if (!library) {
    return;
  }
  const echarts = await import(library);
  await Promise.all(
    elements.map(async (element) => {
      const chart = echarts.init(element, null, { renderer: "svg" });
      chart.setOption(baseOption(element));
      chart.on("click", (/** @type {{ data?: { url?: string } }} */ params) => {
        const url = params.data?.url;
        if (url) {
          follow(element, url);
        }
      });
      new ResizeObserver(() => chart.resize()).observe(element);
      const { source } = element.dataset;
      if (source) {
        chart.showLoading();
        const response = await fetch(source);
        chart.hideLoading();
        if (response.ok) {
          chart.setOption(await response.json());
        } else {
          element.textContent = `Couldn't load the chart's data (${response.status}).`;
        }
      }
    }),
  );
}
