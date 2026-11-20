// @ts-check
// Cash Flow page: draws the Sankey diagram of where cash came from and went.
//
// Every flow goes into or out of cash, so the diagram is a hub: the nodes that
// brought money into cash on the left, cash in the middle, and where it went on
// the right. Each link's color fades from its source's to its target's. Fava
// serves an extension a single module, so this lays the hub out itself rather
// than bundling a general Sankey library.

const WIDTH = 960;
const NODE = 14; // node width
const GAP = 8; // between nodes in a column
const SLOT = 20; // the least height a node's label needs
const LABEL = 250; // room for the labels at each side
const SVG = "http://www.w3.org/2000/svg";

/** Colors by kind of node: the same in light and dark themes. */
const COLORS = {
  income: "#2e9d5b",
  spending: "#d9534f",
  investments: "#3a7bd5",
  debt: "#e08a2b",
  cash: "#8a8f98",
};

/**
 * @typedef {object} Node
 * @property {string} name
 * @property {number} value
 * @property {string} amount
 * @property {boolean} inflow
 * @property {keyof typeof COLORS} kind
 * @property {string} title
 * @property {string | null} url
 */

/**
 * @param {string} tag
 * @param {Record<string, string | number>} attributes
 * @param {Element} [parent]
 */
function element(tag, attributes, parent) {
  const found = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) {
    found.setAttribute(key, String(value));
  }
  parent?.append(found);
  return found;
}

/**
 * A column's nodes, top to bottom: each with its height, and the top of its slot.
 * @param {Node[]} nodes
 * @param {number} scale
 */
function stack(nodes, scale) {
  let y = 0;
  return nodes.map((node) => {
    const height = Math.max(node.value * scale, 1);
    const slot = Math.max(height, SLOT);
    const placed = { node, height, top: y + (slot - height) / 2, middle: y + slot / 2 };
    y += slot + GAP;
    return placed;
  });
}

/**
 * Open a page as a link would. Fava's router follows clicks on HTML links, not
 * SVG ones, so this clicks a passing HTML link next to the diagram.
 * @param {Element} svg
 * @param {string} url
 */
function follow(svg, url) {
  const link = document.createElement("a");
  link.href = url;
  link.hidden = true;
  svg.after(link);
  link.click();
  link.remove();
}

/**
 * Draw a node: its bar, and its name and amount beside it, linked to its page.
 * @param {SVGElement} svg
 * @param {{node: Node, height: number, top: number, middle: number}} placed
 * @param {number} x
 * @param {"start" | "end"} anchor
 */
function drawNode(svg, placed, x, anchor) {
  const { node } = placed;
  const group = element("g", node.url ? { class: "cash-flow-link" } : {}, svg);
  const { url } = node;
  if (url) {
    group.addEventListener("click", () => follow(svg, url));
  }
  element("title", {}, group).textContent = node.title;
  element(
    "rect",
    { x, y: placed.top, width: NODE, height: placed.height, fill: COLORS[node.kind] },
    group,
  );
  const label = element(
    "text",
    {
      x: anchor === "end" ? x - 6 : x + NODE + 6,
      y: placed.middle,
      "dominant-baseline": "middle",
      "text-anchor": anchor,
    },
    group,
  );
  label.textContent = `${node.name} ${node.amount}`;
}

/** @param {HTMLElement} container @param {Node[]} nodes */
function draw(container, nodes) {
  const inflows = nodes.filter((node) => node.inflow).sort((a, b) => b.value - a.value);
  const outflows = nodes.filter((node) => !node.inflow).sort((a, b) => b.value - a.value);
  const total = inflows.reduce((sum, node) => sum + node.value, 0);
  if (!total) {
    container.textContent = "No flows in this period.";
    return;
  }
  const rows = Math.max(inflows.length, outflows.length);
  const scale = (Math.max(320, rows * 30) - GAP * (rows - 1)) / total;
  const left = stack(inflows, scale);
  const right = stack(outflows, scale);
  const columns = [left, right].map((column) => {
    const last = column.at(-1);
    return last ? last.middle + Math.max(last.height, SLOT) / 2 : 0;
  });
  const inner = Math.max(...columns, total * scale);
  // Room above for cash's label, and below.
  const height = inner + 36;
  // Center each column, and cash, vertically.
  const shift = (/** @type {number} */ size) => 24 + (inner - size) / 2;
  const [leftShift, rightShift] = columns.map(shift);
  for (const placed of left) {
    placed.top += leftShift;
    placed.middle += leftShift;
  }
  for (const placed of right) {
    placed.top += rightShift;
    placed.middle += rightShift;
  }
  const cashTop = shift(total * scale);

  const svg = /** @type {SVGElement} */ (
    element("svg", { viewBox: `0 0 ${WIDTH} ${height}`, role: "img" })
  );
  svg.setAttribute("aria-label", "Where cash came from and went");
  const defs = element("defs", {}, svg);
  const xLeft = LABEL;
  const xCash = WIDTH / 2 - NODE / 2;
  const xRight = WIDTH - LABEL - NODE;

  /**
   * A link from one column's node to cash, or from cash to a node: a band whose
   * ends are the node's bar and its share of cash's bar.
   * @param {{node: Node, height: number, top: number}} placed
   * @param {number} cashY the top of the band at cash
   * @param {boolean} into whether it flows into cash
   * @param {number} index
   */
  const link = (placed, cashY, into, index) => {
    const [x0, y0, x1, y1] = into
      ? [xLeft + NODE, placed.top, xCash, cashY]
      : [xCash + NODE, cashY, xRight, placed.top];
    const middle = (x0 + x1) / 2;
    const band = placed.height;
    const id = `cash-flow-link-${index}`;
    const gradient = element(
      "linearGradient",
      { id, gradientUnits: "userSpaceOnUse", x1: x0, x2: x1, y1: 0, y2: 0 },
      defs,
    );
    const [from, to] = into
      ? [COLORS[placed.node.kind], COLORS.cash]
      : [COLORS.cash, COLORS[placed.node.kind]];
    element("stop", { offset: 0, "stop-color": from }, gradient);
    element("stop", { offset: 1, "stop-color": to }, gradient);
    const path = element(
      "path",
      {
        d:
          `M${x0},${y0} C${middle},${y0} ${middle},${y1} ${x1},${y1} ` +
          `L${x1},${y1 + band} C${middle},${y1 + band} ${middle},${y0 + band} ${x0},${y0 + band} Z`,
        fill: `url(#${id})`,
        "fill-opacity": 0.45,
      },
      svg,
    );
    element("title", {}, path).textContent = placed.node.title;
  };

  let cashY = cashTop;
  left.forEach((placed, index) => {
    link(placed, cashY, true, index);
    cashY += placed.height;
  });
  cashY = cashTop;
  right.forEach((placed, index) => {
    link(placed, cashY, false, left.length + index);
    cashY += placed.height;
  });

  const cash = element("g", {}, svg);
  element("title", {}, cash).textContent = "Cash";
  element(
    "rect",
    { x: xCash, y: cashTop, width: NODE, height: total * scale, fill: COLORS.cash },
    cash,
  );
  const label = element(
    "text",
    { x: WIDTH / 2, y: cashTop - 8, "text-anchor": "middle" },
    cash,
  );
  label.textContent = "Cash";
  for (const placed of left) {
    drawNode(svg, placed, xLeft, "end");
  }
  for (const placed of right) {
    drawNode(svg, placed, xRight, "start");
  }
  container.replaceChildren(svg);
}

/** @type {import("fava/extension-api").ExtensionModule} */
export default {
  onExtensionPageLoad() {
    const container = document.getElementById("cash-flow-sankey");
    const data = document.getElementById("cash-flow-sankey-data");
    if (container && data) {
      draw(container, JSON.parse(data.textContent ?? "[]"));
    }
  },
};
