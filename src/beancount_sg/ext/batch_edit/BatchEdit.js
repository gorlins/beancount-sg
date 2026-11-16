// @ts-check
// The Apply button posts the current search to the extension's `apply` endpoint,
// which edits the source files, then reloads the page to show the result.

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  onExtensionPageLoad(ctx) {
    const button = document.getElementById("batch-edit-apply");
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    button.addEventListener("click", async () => {
      if (!confirm(`Edit ${button.dataset.count} transactions in your ledger files?`)) {
        return;
      }
      button.disabled = true;
      // The page's query parameters hold both the search and Fava's filters.
      const params = Object.fromEntries(new URLSearchParams(window.location.search));
      const result = /** @type {{changed: number, errors: string[]}} */ (
        await ctx.api.request("apply", "POST", params)
      );
      const errors = result.errors.length ? `\n\nErrors:\n${result.errors.join("\n")}` : "";
      alert(`Edited ${result.changed} transactions.${errors}`);
      window.location.reload();
    });
  },
};
