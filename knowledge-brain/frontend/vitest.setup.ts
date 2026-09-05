import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView at all — any component that
// calls it (e.g. auto-scrolling a chat transcript) throws in tests
// without this. A no-op is enough; tests don't care about real scroll
// position.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
