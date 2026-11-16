// @ts-check
// Credit Card Rewards page. Fava's charts link every node to an account page, so
// a category's node (named `<card>:<category>`) would open a page for an account
// that doesn't exist. The page lists each category node's account name and the
// URL it should open instead (the card's page, filtered to the category); this
// points a clicked node's link there before Fava's router, which handles link
// clicks on the document, follows it.

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  onExtensionPageLoad() {
    const charts = document.querySelector('svelte-component[type="charts"]');
    const data = document.getElementById("rewards-category-links");
    if (!charts || !data) {
      return;
    }
    /** @type {Record<string, string>} */
    const links = JSON.parse(data.textContent ?? "{}");

    charts.addEventListener(
      "click",
      (event) => {
        const link = event.target instanceof Element ? event.target.closest("a") : null;
        const href = link?.getAttribute("href");
        if (!link || !href) {
          return;
        }
        const path = decodeURIComponent(new URL(href, window.location.href).pathname);
        const account = /\/account\/(.+?)\/?$/.exec(path)?.[1];
        const url = account ? links[account] : undefined;
        if (url) {
          link.setAttribute("href", url);
        }
      },
      // Capture, to run before the click reaches the document.
      true,
    );
  },
};
