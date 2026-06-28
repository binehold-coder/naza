# Lighthouse Release Checklist

- Run Lighthouse for desktop and mobile on:
  - /index.html
  - /contact.html
  - /ua/index.html
  - /ua/contact.html
- Performance target: 85+
- Accessibility target: 95+
- Best Practices target: 95+
- SEO target: 95+

## Manual checks

- No broken internal links (FR and UA).
- Contact map loads and is visible on all 4 pages.
- Language switch links FR <-> UA work on equivalent pages.
- Social sharing preview shows title, description, and logo image.
- 404 page opens at /404.html and has working links.

## Optional next optimizations

- Convert large JPG images in assets/img and img to WebP/AVIF variants.
- Add width/height attributes for key images to reduce CLS.
- Preconnect to fonts.googleapis.com and fonts.gstatic.com.