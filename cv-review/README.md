# Free CV & LinkedIn Review funnel

Page: `cv-review/index.html` (live at `/cv-review/` on GitHub Pages).

Flow: upload CV -> instant free scan (sample findings) -> choose £85 CV+LinkedIn update or £380 Full Placement Support -> name/email/mobile/CV submitted to hr@resumecraftinghub.com -> payment link -> expert updates within 24-48 h and emails the CV back.

## Setup (one-time)
1. Email delivery uses FormSubmit (free, no server). Open the page, submit one test registration, then click the **activation link** FormSubmit emails to hr@resumecraftinghub.com. After that every registration arrives with the CV attached.
2. Create two payment links (Stripe Payment Link / PayPal / Razorpay): £85 and £380. Paste them into `PAY_LINKS` in the `CONFIG` block at the top of the script. Until then the page asks the candidate to email you for the link.
3. Scan results are sample/indicative text, not a real analysis. Do not claim otherwise in marketing.

## Sharing
Link: `https://niroshini-creator.github.io/rch-sponsor-register/cv-review/`
Add `?src=linkedin`, `?src=whatsapp`, `?src=email` to track where candidates come from (visible in your analytics).
See `share-messages.md` for copy-paste posts.
