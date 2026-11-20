// @ts-check
// Cash Flow page: draws its Sankey diagram with the ECharts helper the extension
// serves (see beancount_sg/ext/echarts.py).

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  async onExtensionPageLoad() {
    const helper = new URL("echarts.js", window.location.href).href;
    const { renderECharts } = await import(helper);
    await renderECharts();
  },
};
