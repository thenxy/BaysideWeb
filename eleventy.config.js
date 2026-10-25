const fs = require("fs");
const path = require("path");
const { EleventyHtmlBasePlugin } = require("@11ty/eleventy");

module.exports = function (eleventyConfig) {
  // Prefixes absolute links when served from a sub-path (github.io/baysideweb/).
  eleventyConfig.addPlugin(EleventyHtmlBasePlugin);
  // Changes on every build so browsers fetch fresh CSS/JS after an update instead of using a cached copy.
  eleventyConfig.addGlobalData("buildId", () => Date.now().toString(36));
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
  // Home page sample board: [{product, colour}] -> link, small photo and labels, skipping anything not found.
  eleventyConfig.addFilter("swatchCards", (items, specs) =>
    (specs || []).map((s) => {
      const p = items.find((x) => x.data.title === s.product);
      if (!p) return null;
      const c = (p.data.colours || []).find((k) => k.image && k.name.toLowerCase().startsWith(String(s.colour).toLowerCase()))
        || (p.data.colours || []).find((k) => k.image);
      const img = (c && c.image) || p.data.image;
      if (!img) return null;
      const t = img.replace(/\.webp$/, "-t.webp");
      return {
        url: p.url,
        title: p.data.title,
        colour: c ? c.name : "",
        image: fs.existsSync(path.join("src", t)) ? t : img,
      };
    }).filter(Boolean)
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
