// @ts-check
// Batch Edit page: Search loads the preview table from the extension's `preview`
// endpoint, and Apply posts to its `apply` endpoint, then reloads the preview. The
// page itself never reloads, so its URL keeps only Fava's own parameters.

/**
 * The search fields, plus the page's URL parameters (Fava's filters: time, account...).
 * @param {HTMLFormElement} form
 * @returns {Record<string, string>}
 */
function requestParams(form) {
  const params = Object.fromEntries(new URLSearchParams(window.location.search));
  for (const [name, value] of new FormData(form)) {
    params[name] = String(value);
  }
  return params;
}

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  onExtensionPageLoad(ctx) {
    const form = document.getElementById("batch-edit-form");
    const preview = document.getElementById("batch-edit-preview");
    if (!(form instanceof HTMLFormElement) || !preview) {
      return;
    }

    const loadPreview = async () => {
      const html = await ctx.api.request("preview", "GET", requestParams(form), undefined, "string");
      preview.innerHTML = /** @type {string} */ (html);
    };

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void loadPreview();
    });
    form.addEventListener("reset", () => {
      preview.innerHTML = "";
    });

    // The Apply button is part of the loaded preview, so listen on its container.
    preview.addEventListener("click", async (event) => {
      const button = event.target;
      if (!(button instanceof HTMLButtonElement) || button.id !== "batch-edit-apply") {
        return;
      }
      if (!confirm(`Edit ${button.dataset.count} transactions in your ledger files?`)) {
        return;
      }
      button.disabled = true;
      const result = /** @type {{changed: number, errors: string[]}} */ (
        await ctx.api.request("apply", "POST", requestParams(form))
      );
      const errors = result.errors.length ? `\n\nErrors:\n${result.errors.join("\n")}` : "";
      alert(`Edited ${result.changed} transactions.${errors}`);
      await loadPreview();
    });
  },
};
