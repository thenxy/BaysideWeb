module.exports = function (eleventyConfig) {
  eleventyConfig.addPassthroughCopy({ "src/css": "css" });
  eleventyConfig.addPassthroughCopy({ "src/js": "js" });
  eleventyConfig.addPassthroughCopy({ "src/img": "img" });
  eleventyConfig.addPassthroughCopy({ "src/favicon.svg": "favicon.svg" });

  // Products sorted by brand then title, optionally filtered by category key.
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
        (a.data.brand + a.data.title).localeCompare(b.data.brand + b.data.title)
      )
  );

  return {
    dir: { input: "src", output: "_site", includes: "_includes", data: "_data" },
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
};
