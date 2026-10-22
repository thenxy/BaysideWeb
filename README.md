# Bayside Flooring Studio

Static site built with [Eleventy](https://www.11ty.dev). Quote only, no checkout.

- `npm install && npm start` runs it locally, `npm run build` outputs `_site/`.
- Products are markdown files in `src/products/` (one per product). Categories are in `src/_data/categories.json`.
- Business details (phone, email, areas) are in `src/_data/site.json`. Anything marked `TODO` must be replaced.
- Quote form posts to [Web3Forms](https://web3forms.com): create a free access key for the email that should receive quotes and put it in `site.json` as `web3formsKey`.
- Easy editing: sign in at [app.pagescms.org](https://app.pagescms.org) with GitHub, pick this repo, and edit products and business details in the browser. Config is `.pages.yml`.
- Hosting: connect the repo to Cloudflare Pages or Netlify. Build command `npm run build`, output directory `_site`.
