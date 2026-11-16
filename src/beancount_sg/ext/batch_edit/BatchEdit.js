// @ts-check
// Batch Edit page. Search loads the preview table from the extension's `preview`
// endpoint and records the search in the page's URL (so reloads and navigation
// keep it); a URL with a search runs it when the page loads. Apply posts to the
// `apply` endpoint and shows the transactions it edited, as they are now.

const FIELDS = ["payee_regex", "narration_regex", "new_payee", "new_category"];

/**
 * The page's URL parameters with the search fields replaced by the form's values:
 * Fava's own filters (time, account...) plus the non-empty search fields.
 * @param {HTMLFormElement} form
 * @returns {URLSearchParams}
 */
function searchParams(form) {
  const params = new URLSearchParams(window.location.search);
  const data = new FormData(form);
  for (const field of FIELDS) {
    const value = String(data.get(field) ?? "");
    if (value) {
      params.set(field, value);
    } else {
      params.delete(field);
    }
  }
  return params;
}

/**
 * Record the search in the page's URL without reloading or adding a history entry.
 * @param {URLSearchParams} params
 */
function setUrlParams(params) {
  const query = params.toString();
  history.replaceState(history.state, "", window.location.pathname + (query ? `?${query}` : ""));
}

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  onExtensionPageLoad(ctx) {
    const form = document.getElementById("batch-edit-form");
    const results = document.getElementById("batch-edit-preview");
    if (!(form instanceof HTMLFormElement) || !results) {
      return;
    }

    /** @param {string} endpoint @param {"GET" | "POST"} method */
    const load = async (endpoint, method) => {
      const params = Object.fromEntries(searchParams(form));
      const html = await ctx.api.request(endpoint, method, params, undefined, "string");
      results.innerHTML = /** @type {string} */ (html);
    };

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      setUrlParams(searchParams(form));
      void load("preview", "GET");
    });
    form.addEventListener("reset", () => {
      results.innerHTML = "";
      const params = new URLSearchParams(window.location.search);
      FIELDS.forEach((field) => params.delete(field));
      setUrlParams(params);
    });

    // The Apply button is part of the loaded preview, so listen on its container.
    results.addEventListener("click", async (event) => {
      const button = event.target;
      if (!(button instanceof HTMLButtonElement) || button.id !== "batch-edit-apply") {
        return;
      }
      if (!confirm(`Edit ${button.dataset.count} transactions in your ledger files?`)) {
        return;
      }
      button.disabled = true;
      await load("apply", "POST");
    });

    // Restore a search recorded in the URL, e.g. after a reload.
    const params = new URLSearchParams(window.location.search);
    for (const field of FIELDS) {
      const input = form.elements.namedItem(field);
      if (input instanceof HTMLInputElement) {
        input.value = params.get(field) ?? "";
      }
    }
    if (params.get("payee_regex") || params.get("narration_regex")) {
      void load("preview", "GET");
    }
  },
};
