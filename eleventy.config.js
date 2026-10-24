const fs = require("fs");
const path = require("path");
const { EleventyHtmlBasePlugin } = require("@11ty/eleventy");

module.exports = function (eleventyConfig) {
  // Prefixes absolute links when served from a sub-path (github.io/baysideweb/).
  eleventyConfig.addPlugin(EleventyHtmlBasePlugin);
  eleventyConfig.addPassthroughCopy({ "src/css": "css" });
  eleventyConfig.addPassthroughCopy({ "src/js": "js" });
  eleventyConfig.addPassthroughCopy({ "src/img": "img" });
  eleventyConfig.addPassthroughCopy({ "src/favicon.svg": "favicon.svg" });

  // Catalogue sorted by title; inCategory filters by category key.
  eleventyConfig.addFilter("inCategory", (items, key) =>
    items.filter((p) => p.data.category === key)
  );
  eleventyConfig.addFilter("unique", (arr) => [...new Set(arr)].sort());
  eleventyConfig.addFilter("pluck", (items, key) =>
    items.map((p) => p.data[key]).filter(Boolean)
  );
  // Small version of a scraped photo (name-t.webp) when one exists, otherwise the photo itself.
  eleventyConfig.addFilter("thumb", (img) => {
    if (!img) return img;
    const t = img.replace(/\.webp$/, "-t.webp");
    return t !== img && fs.existsSync(path.join("src", t)) ? t : img;
  });
  // The next n products in the same list after this page (wrapping round), for "you might also like".
  eleventyConfig.addFilter("related", (items, url, n) => {
    const i = items.findIndex((p) => p.url === url);
    const out = [];
    for (let k = 1; k < items.length && out.length < n; k++) out.push(items[(i + k + items.length) % items.length]);
    return out;
  });
  eleventyConfig.addFilter("byTitles", (items, titles) =>
    (titles || []).map((t) => items.find((p) => p.data.title === t)).filter(Boolean)
  );
  eleventyConfig.addFilter("year", () => new Date().getFullYear());

  eleventyConfig.addCollection("catalogue", (api) =>
    api
      .getFilteredByTag("product")
      .sort((a, b) =>
        a.data.title.localeCompare(b.data.title)
      )
  );

  return {
    pathPrefix: process.env.PATH_PREFIX || "/",
    dir: { input: "src", output: "_site", includes: "_includes", data: "_data" },
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
};
