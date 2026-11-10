# scripts/gen_docs.py
"""
A script to dynamically generate documentation files for MkDocs.
This is run automatically by the mkdocs-gen-files plugin.
"""

import mkdocs_gen_files

REPO = "https://github.com/aegis-stack/aegis-steward/blob/main/"
BRAND_MARK = "app/components/web_frontend/static/brand-mark.png"

# The root README.md is the docs site's index page: one source for the
# landing page on GitHub and on the site. Its paths are written from the
# repo root, so they are rewritten for a page served from docs/, and the
# brand mark (outside docs/) is carried in as a generated file.
with open("README.md") as readme:
    page = (
        readme.read()
        .replace(BRAND_MARK, "images/brand-mark.png")
        .replace('src="docs/images/', 'src="images/')
        .replace("](LICENSE)", f"]({REPO}LICENSE)")
    )
with mkdocs_gen_files.open("index.md", "w") as index:
    index.write(page)
with (
    open(BRAND_MARK, "rb") as src,
    mkdocs_gen_files.open("images/brand-mark.png", "wb") as dst,
):
    dst.write(src.read())
