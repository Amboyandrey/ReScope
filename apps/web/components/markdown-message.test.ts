import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "./markdown-message";

const render = (content: string) => renderToStaticMarkup(createElement(MarkdownMessage, { content }));

describe("MarkdownMessage", () => {
  it("renders emphasis and GFM tables instead of showing the raw syntax", () => {
    const html = render("**AlloyX** is listed.\n\n| Technology | Description |\n|---|---|\n| **HydroShield** | Optical protection |");
    expect(html).toContain("<strong");
    expect(html).toContain("<table");
    expect(html).toContain("<th");
    expect(html).not.toContain("**");
    expect(html).not.toContain("|---|");
  });

  it("turns a literal <br> inside a table cell into a real line break", () => {
    const html = render("| A | B |\n|---|---|\n| one<br>two | x |");
    expect(html).toMatch(/one<br\/?>\s*two/);
  });

  it("escapes any other HTML a model emits rather than rendering it", () => {
    const html = render('<script>alert(1)</script> <img src="https://example.com/x.png">');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
  });

  it("shows markdown images as links so remote images are never fetched", () => {
    const html = render("![logo](https://example.com/logo.png)");
    expect(html).not.toContain("<img");
    expect(html).toContain('href="https://example.com/logo.png"');
  });

  it("opens links in a new tab without a referrer", () => {
    const html = render("[site](https://example.com)");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
