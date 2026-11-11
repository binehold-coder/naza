NAZA COUTURE — FIRST JINJA2 PROTOTYPE (HOME PAGE ONLY)

This prototype is deliberately isolated. It generates only the French and Ukrainian homepages into ./preview-site and copies existing css/, js/, assets/. It does NOT overwrite existing HTML files, push to GitHub, deploy to Vercel, or touch production.

1) In your local repository, create a backup/commit before adding files.
2) Copy the folders/files from this archive into the repository root:
   build.py, requirements.txt, templates/, content/
3) The required site.json and site.schema.json are already included in this archive.
4) In Terminal, from the repository root run:
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   python build.py
5) Open preview-site/index.html and preview-site/ua/index.html in a browser.

Expected result:
- preview-site/index.html (French homepage)
- preview-site/ua/index.html (Ukrainian homepage)
- preview-site/css/, preview-site/js/, preview-site/assets/ copied from the existing source.

Important:
- Original index.html and ua/index.html remain untouched.
- The build folder is a test output, not a production release.
- This is the first migration slice, not the completed site generator.
- Sunday remains omitted because null in site.json means unknown, not confirmed closed.
