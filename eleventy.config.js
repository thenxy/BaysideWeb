const { EleventyHtmlBasePlugin } = require("@11ty/eleventy");

module.exports = function (eleventyConfig) {
  // Prefixes absolute links when served from a sub-path (github.io/baysideweb/).
  eleventyConfig.addPlugin(EleventyHtmlBasePlugin);
  eleventyConfig.addPassthroughCopy({ "src/css": "css" });
  eleventyConfig.addPassthroughCopy({ "src/js": "js" });
  eleventyConfig.addPassthroughCopy({ "src/img": "img" });
  eleventyConfig.addPassthroughCopy({ "src/favicon.svg": "favicon.svg" });

  // Catalogue sorted by range then title; inCategory filters by category key.
  eleventyConfig.addFilter("inCategory", (items, key) =>
    items.filter((p) => p.data.category === key)
  );
  eleventyConfig.addFilter("unique", (arr) => [...new Set(arr)].sort());
  eleventyConfig.addFilter("pluck", (items, key) =>
    items.map((p) => p.data[key]).filter(Boolean)
  );
  eleventyConfig.addFilter("year", () => new Date().getFullYear());

  eleventyConfig.addCollection("catalogue", (api) =>
    api
      .getFilteredByTag("product")
      .sort((a, b) =>
        ((a.data.range || "") + a.data.title).localeCompare((b.data.range || "") + b.data.title)
      )
  );

  return {
    pathPrefix: process.env.PATH_PREFIX || "/",
    dir: { input: "src", output: "_site", includes: "_includes", data: "_data" },
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
};
