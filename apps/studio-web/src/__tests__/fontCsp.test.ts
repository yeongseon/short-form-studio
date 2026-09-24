import { expect, it } from "vitest";
import html from "../../index.html?raw";
import nginx from "../../nginx.conf.template?raw";

it("loads no font stylesheets forbidden by the production content security policy", () => {
  // Given the shipped HTML and nginx policy.
  // When the production CSP allows only local styles and fonts.
  expect(nginx).toMatch(/style-src 'self'/);
  expect(nginx).toMatch(/font-src 'self'/);
  // Then HTML must not request third-party font stylesheets or preconnect hosts.
  expect(html).not.toMatch(/<link[^>]+href="https?:\/\//);
});
