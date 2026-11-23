<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maru Quick — Supply Portal</title>
<link rel="icon" type="image/png" href="favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800;900&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }
img { display:block; max-width:100%; }
a { text-decoration:none; color:inherit; }

:root {
    --yellow:     #F5C518;
    --yellow-dk:  #D4A900;
    --yellow-pale:#FFFBEA;
    --dark:       #0E0E0E;
    --dark2:      #1A1A1A;
    --mid:        #6B7280;
    --light:      #F8F7F4;
    --white:      #FFFFFF;
    --blue:       #1A6BFF;
    --border:     #E5E7EB;
    --fh:         'Sora', sans-serif;
    --fb:         'DM Sans', sans-serif;
    --max:        1280px;
    --px:         clamp(20px, 5vw, 72px);
    --radius:     14px;
    --radius-lg:  24px;
}

body {
    font-family: var(--fb);
    background: var(--white);
    color: var(--dark);
    line-height: 1.6;
    overflow-x: hidden;
}

/* ── HEADER ─────────────────────────────────────────── */
header {
    position: sticky;
    top: 0;
    z-index: 200;
    background: var(--white);
    border-bottom: 1px solid var(--border);
    box-shadow: 0 1px 12px rgba(0,0,0,.05);
}
.header-inner {
    max-width: var(--max);
    margin: 0 auto;
    padding: 0 var(--px);
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 70px;
    gap: 24px;
}
.logo {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
}
.logo img { height: 44px; width: auto; }
.logo-fallback {
    font-family: var(--fh);
    font-size: 1.3rem;
    font-weight: 800;
    color: var(--dark);
}
.logo-fallback span { color: var(--yellow-dk); }

nav {
    display: flex;
    align-items: center;
    gap: 28px;
}
nav a {
    font-size: .88rem;
    font-weight: 500;
    color: var(--mid);
    transition: color .2s;
    white-space: nowrap;
}
nav a:hover { color: var(--dark); }
nav a.active { color: var(--dark); font-weight: 600; }

.nav-pill {
    background: var(--yellow);
    color: var(--dark) !important;
    padding: 7px 18px;
    border-radius: 50px;
    font-weight: 700 !important;
    font-size: .83rem !important;
    transition: background .2s, transform .2s !important;
}
.nav-pill:hover { background: var(--yellow-dk) !important; transform: translateY(-1px); }

.btn-login-nav {
    background: var(--blue);
    color: var(--white) !important;
    padding: 9px 22px;
    border-radius: 50px;
    font-weight: 600 !important;
    font-size: .85rem !important;
    transition: opacity .2s !important;
}
.btn-login-nav:hover { opacity: .85 !important; }

.nav-toggle {
    display: none;
    flex-direction: column;
    gap: 5px;
    cursor: pointer;
    background: none;
    border: none;
    padding: 4px;
}
.nav-toggle span {
    width: 24px; height: 2px;
    background: var(--dark);
    border-radius: 2px;
    transition: all .3s;
}

/* ── HERO ────────────────────────────────────────────── */
.hero {
    background: var(--yellow);
    padding: clamp(64px, 8vw, 100px) var(--px);
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: '';
    position: absolute;
    top: -80px; right: -80px;
    width: 500px; height: 500px;
    background: rgba(255,255,255,0.12);
    border-radius: 50%;
    pointer-events: none;
}
.hero::after {
    content: '';
    position: absolute;
    bottom: -120px; left: 40%;
    width: 400px; height: 400px;
    background: rgba(0,0,0,0.04);
    border-radius: 50%;
    pointer-events: none;
}
.hero-inner {
    max-width: var(--max);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 48px;
    align-items: center;
    position: relative;
    z-index: 1;
}
.hero-tag {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: rgba(0,0,0,0.08);
    color: var(--dark);
    padding: 6px 14px;
    border-radius: 50px;
    font-size: .78rem;
    font-weight: 700;
    letter-spacing: .04em;
    text-transform: uppercase;
    margin-bottom: 20px;
}
.hero-tag svg { width: 14px; height: 14px; }
.hero h1 {
    font-family: var(--fh);
    font-size: clamp(2rem, 4.5vw, 3.4rem);
    font-weight: 900;
    line-height: 1.1;
    letter-spacing: -.03em;
    color: var(--dark);
    margin-bottom: 20px;
}
.hero p {
    font-size: clamp(.95rem, 1.4vw, 1.1rem);
    color: rgba(14,14,14,0.7);
    max-width: 480px;
    margin-bottom: 36px;
    line-height: 1.7;
}
.hero-btns {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
}
.btn-primary {
    background: var(--dark);
    color: var(--white);
    padding: 14px 32px;
    border-radius: 50px;
    font-family: var(--fb);
    font-weight: 700;
    font-size: .95rem;
    border: none;
    cursor: pointer;
    transition: background .2s, transform .2s;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
}
.btn-primary:hover { background: #222; transform: translateY(-2px); }
.btn-secondary {
    background: transparent;
    color: var(--dark);
    padding: 14px 32px;
    border-radius: 50px;
    font-family: var(--fb);
    font-weight: 600;
    font-size: .95rem;
    border: 2px solid rgba(14,14,14,0.3);
    cursor: pointer;
    transition: border-color .2s, transform .2s;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
}
.btn-secondary:hover { border-color: var(--dark); transform: translateY(-2px); }

/* Hero right — trust cards */
.hero-right {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}
.trust-card {
    background: var(--white);
    border-radius: var(--radius);
    padding: 22px 20px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    transition: transform .2s;
}
.trust-card:hover { transform: translateY(-3px); }
.trust-card svg {
    width: 32px; height: 32px;
    margin-bottom: 12px;
    color: var(--yellow-dk);
}
.trust-card h3 {
    font-family: var(--fh);
    font-size: .9rem;
    font-weight: 700;
    margin-bottom: 4px;
    color: var(--dark);
}
.trust-card p {
    font-size: .78rem;
    color: var(--mid);
    line-height: 1.5;
    margin: 0;
}
.trust-card.featured {
    background: var(--dark);
    grid-column: span 2;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 18px 22px;
}
.trust-card.featured svg { color: var(--yellow); margin: 0; flex-shrink: 0; }
.trust-card.featured h3 { color: var(--white); margin: 0; }
.trust-card.featured p { color: #9CA3AF; margin: 0; }

/* ── STATS STRIP ─────────────────────────────────────── */
.stats-strip {
    background: var(--dark);
    padding: 36px var(--px);
}
.stats-inner {
    max-width: var(--max);
    margin: 0 auto;
    display: flex;
    justify-content: space-around;
    gap: 24px;
    flex-wrap: wrap;
}
.stat-item { text-align: center; }
.stat-item .num {
    font-family: var(--fh);
    font-size: clamp(1.8rem, 3vw, 2.6rem);
    font-weight: 900;
    color: var(--yellow);
    display: block;
    line-height: 1;
    margin-bottom: 6px;
}
.stat-item .label {
    font-size: .82rem;
    color: #9CA3AF;
    font-weight: 500;
}

/* ── WHY PARTNER ─────────────────────────────────────── */
.section {
    padding: clamp(64px, 8vw, 96px) var(--px);
}
.section-inner { max-width: var(--max); margin: 0 auto; }
.section-label {
    display: inline-block;
    background: var(--yellow-pale);
    color: var(--yellow-dk);
    padding: 5px 14px;
    border-radius: 50px;
    font-size: .75rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    margin-bottom: 16px;
}
.section-title {
    font-family: var(--fh);
    font-size: clamp(1.7rem, 3vw, 2.6rem);
    font-weight: 800;
    letter-spacing: -.03em;
    color: var(--dark);
    margin-bottom: 14px;
    max-width: 600px;
}
.section-sub {
    font-size: 1rem;
    color: var(--mid);
    max-width: 540px;
    line-height: 1.7;
    margin-bottom: 56px;
}

.why-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
}
.why-card {
    background: var(--light);
    border-radius: var(--radius-lg);
    padding: 32px 28px;
    position: relative;
    overflow: hidden;
    transition: transform .2s, box-shadow .2s;
    border: 1px solid var(--border);
}
.why-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 16px 48px rgba(0,0,0,0.08);
}
.why-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--yellow);
    opacity: 0;
    transition: opacity .2s;
}
.why-card:hover::before { opacity: 1; }
.why-icon {
    width: 48px; height: 48px;
    background: var(--yellow);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 20px;
}
.why-icon svg { width: 22px; height: 22px; color: var(--dark); }
.why-card h3 {
    font-family: var(--fh);
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--dark);
}
.why-card p {
    font-size: .88rem;
    color: var(--mid);
    line-height: 1.6;
}

/* ── HOW IT WORKS ────────────────────────────────────── */
.how-section {
    background: var(--dark);
    padding: clamp(64px, 8vw, 96px) var(--px);
}
.how-inner { max-width: var(--max); margin: 0 auto; }
.how-section .section-label {
    background: rgba(245,197,24,0.15);
    color: var(--yellow);
}
.how-section .section-title { color: var(--white); }
.how-section .section-sub { color: #9CA3AF; }

.steps-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2px;
    position: relative;
}
.steps-grid::before {
    content: '';
    position: absolute;
    top: 28px;
    left: 10%;
    right: 10%;
    height: 1px;
    background: rgba(255,255,255,0.1);
}
.step {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: var(--radius);
    padding: 28px 22px;
    text-align: center;
    position: relative;
    z-index: 1;
    transition: background .2s;
}
.step:hover { background: rgba(255,255,255,0.07); }
.step-num {
    width: 48px; height: 48px;
    background: var(--yellow);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--fh);
    font-weight: 800;
    font-size: 1.1rem;
    color: var(--dark);
    margin: 0 auto 18px;
}
.step h3 {
    font-family: var(--fh);
    font-size: .95rem;
    font-weight: 700;
    color: var(--white);
    margin-bottom: 8px;
}
.step p { font-size: .82rem; color: #9CA3AF; line-height: 1.6; }

/* ── CATEGORIES ──────────────────────────────────────── */
.categories-section {
    background: var(--light);
    padding: clamp(64px, 8vw, 96px) var(--px);
}
.cat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 48px;
}
.cat-card {
    background: var(--white);
    border-radius: var(--radius-lg);
    padding: 28px 20px;
    text-align: center;
    border: 1.5px solid var(--border);
    cursor: pointer;
    transition: all .2s;
    position: relative;
    overflow: hidden;
}
.cat-card:hover {
    border-color: var(--yellow);
    transform: translateY(-3px);
    box-shadow: 0 12px 36px rgba(245,197,24,0.15);
}
.cat-icon {
    width: 52px; height: 52px;
    background: var(--yellow-pale);
    border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    margin: 0 auto 16px;
    transition: background .2s;
}
.cat-icon svg { width: 24px; height: 24px; color: var(--yellow-dk); stroke: var(--yellow-dk); }
.cat-card:hover .cat-icon { background: var(--yellow); }
.cat-card:hover .cat-icon svg { color: var(--dark); stroke: var(--dark); }
.cat-card h3 {
    font-family: var(--fh);
    font-size: .9rem;
    font-weight: 700;
    color: var(--dark);
    margin-bottom: 4px;
}
.cat-card p { font-size: .75rem; color: var(--mid); }
.cat-card .cat-arrow {
    position: absolute;
    bottom: 12px; right: 16px;
    width: 28px; height: 28px;
    background: var(--yellow);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity .2s, transform .2s;
    transform: translateX(-4px);
}
.cat-card:hover .cat-arrow { opacity: 1; transform: translateX(0); }
.cat-arrow svg { width: 14px; height: 14px; }

/* ── CTA ─────────────────────────────────────────────── */
.cta-section {
    background: var(--yellow);
    padding: clamp(64px, 8vw, 96px) var(--px);
    text-align: center;
    position: relative;
    overflow: hidden;
}
.cta-section::before {
    content: '';
    position: absolute;
    top: -100px; left: -100px;
    width: 400px; height: 400px;
    background: rgba(255,255,255,0.15);
    border-radius: 50%;
}
.cta-section::after {
    content: '';
    position: absolute;
    bottom: -80px; right: -80px;
    width: 350px; height: 350px;
    background: rgba(0,0,0,0.04);
    border-radius: 50%;
}
.cta-inner {
    max-width: 640px;
    margin: 0 auto;
    position: relative;
    z-index: 1;
}
.cta-section h2 {
    font-family: var(--fh);
    font-size: clamp(1.8rem, 3.5vw, 2.8rem);
    font-weight: 900;
    letter-spacing: -.03em;
    color: var(--dark);
    margin-bottom: 16px;
}
.cta-section p {
    font-size: 1rem;
    color: rgba(14,14,14,0.65);
    margin-bottom: 36px;
    line-height: 1.7;
}
.cta-btns {
    display: flex;
    gap: 14px;
    justify-content: center;
    flex-wrap: wrap;
}

/* ── FOOTER ──────────────────────────────────────────── */
footer {
    background: var(--dark);
    padding: 56px var(--px) 32px;
}
.footer-inner {
    max-width: var(--max);
    margin: 0 auto;
}
.footer-top {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 48px;
    margin-bottom: 48px;
    padding-bottom: 48px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
.footer-brand .logo-fallback { font-size: 1.5rem; color: var(--white); margin-bottom: 14px; }
.footer-brand .logo-fallback span { color: var(--yellow); }
.footer-brand p { font-size: .85rem; color: #6B7280; line-height: 1.7; max-width: 280px; }
.footer-col h4 {
    font-family: var(--fh);
    font-size: .8rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: #9CA3AF;
    margin-bottom: 16px;
}
.footer-col a {
    display: block;
    font-size: .85rem;
    color: #6B7280;
    margin-bottom: 10px;
    transition: color .2s;
}
.footer-col a:hover { color: var(--white); }
.footer-bottom {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}
.footer-bottom p { font-size: .8rem; color: #4B5563; }

/* ── RESPONSIVE ──────────────────────────────────────── */
@media (max-width: 1024px) {
    .why-grid { grid-template-columns: repeat(2, 1fr); }
    .steps-grid { grid-template-columns: repeat(2, 1fr); }
    .steps-grid::before { display: none; }
    .cat-grid { grid-template-columns: repeat(2, 1fr); }
    .footer-top { grid-template-columns: 1fr 1fr; gap: 32px; }
}
@media (max-width: 768px) {
    .nav-toggle { display: flex; }
    nav.desktop-nav {
        display: none;
        position: absolute;
        top: 70px; left: 0; right: 0;
        background: var(--white);
        flex-direction: column;
        padding: 20px var(--px);
        gap: 16px;
        border-bottom: 1px solid var(--border);
        box-shadow: 0 8px 24px rgba(0,0,0,.08);
        z-index: 100;
    }
    nav.desktop-nav.open { display: flex; }
    .hero-inner { grid-template-columns: 1fr; }
    .hero-right { display: none; }
    .why-grid { grid-template-columns: 1fr; }
    .steps-grid { grid-template-columns: 1fr; }
    .cat-grid { grid-template-columns: repeat(2, 1fr); }
    .footer-top { grid-template-columns: 1fr; gap: 28px; }
    .footer-bottom { flex-direction: column; text-align: center; }
}
@media (max-width: 480px) {
    .cat-grid { grid-template-columns: 1fr 1fr; }
    .stats-inner { flex-direction: column; align-items: center; gap: 28px; }
}

/* ── ANIMATIONS ──────────────────────────────────────── */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(24px); }
    to   { opacity: 1; transform: translateY(0); }
}
.hero-text { animation: fadeUp .6s ease both; }
.hero-right { animation: fadeUp .6s .15s ease both; }
.trust-card { animation: fadeUp .5s ease both; }
.trust-card:nth-child(1) { animation-delay: .1s; }
.trust-card:nth-child(2) { animation-delay: .2s; }
.trust-card:nth-child(3) { animation-delay: .3s; }
</style>
</head>
<body>

<!-- HEADER -->
<header>
    <div class="header-inner">
        <a href="index.php" class="logo">
            <img src="assets/images/logo.webp" alt="Maru Quick"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
            <span class="logo-fallback" style="display:none;">Maru<span>Quick</span></span>
        </a>
        <button class="nav-toggle" aria-label="Toggle menu"
            onclick="document.querySelector('.desktop-nav').classList.toggle('open')">
            <span></span><span></span><span></span>
        </button>
        <nav class="desktop-nav">
            <a href="supply_portal.php" class="nav-pill active">Supply Portal</a>
            <a href="offers.php">Offers</a>
            <a href="contact.php">Contact</a>
            <a href="about.php">About Us</a>
            <a href="login.php" class="btn-login-nav">Login</a>
        </nav>
    </div>
</header>

<!-- HERO -->
<section class="hero">
    <div class="hero-inner">
        <div class="hero-text">
            <div class="hero-tag">
                <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                </svg>
                Wholesale FMCG Supply Portal
            </div>
            <h1>Wholesale FMCG Products For Your Business</h1>
            <p>Get the best prices on all your orders. Trusted by MSMEs across Botswana to keep shelves stocked and businesses running.</p>
            <div class="hero-btns">
                <a href="supply_signup.php" class="btn-primary">
                    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
                    Sign Up Now
                </a>
                <a href="supply_login.php" class="btn-secondary">
                    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
                    Login to Portal
                </a>
            </div>
        </div>

        <div class="hero-right">
            <div class="trust-card">
                <img src="assets/images/10525469.png" alt="Fast Delivery" style="width:52px;height:52px;object-fit:contain;margin-bottom:12px;">
                <h3>Fast Delivery</h3>
                <p>Reliable same-week delivery across Gaborone and major towns</p>
            </div>
            <div class="trust-card">
                <img src="assets/images/unnamed.png" alt="Quality Assured" style="width:52px;height:52px;object-fit:contain;margin-bottom:12px;">
                <h3>Quality Assured</h3>
                <p>100% authentic products from verified suppliers and distributors</p>
            </div>
            <div class="trust-card">
                <img src="assets/images/5579187.png" alt="Best Prices" style="width:52px;height:52px;object-fit:contain;margin-bottom:12px;">
                <h3>Best Prices</h3>
                <p>Competitive wholesale rates that protect your profit margins</p>
            </div>
            <div class="trust-card">
                <img src="assets/images/4961693.png" alt="24/7 Support" style="width:52px;height:52px;object-fit:contain;margin-bottom:12px;">
                <h3>24/7 Support</h3>
                <p>Dedicated account managers available whenever you need help</p>
            </div>
            <div class="trust-card featured">
                <svg width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                </svg>
                <div>
                    <h3>100+ MSMEs Already Onboard</h3>
                    <p>Join businesses across Botswana ordering smarter with Maru Quick</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- STATS STRIP -->
<div class="stats-strip">
    <div class="stats-inner">
        <div class="stat-item">
            <span class="num">BWP0</span>
            <span class="label">ikwadise mahala</span>
        </div>
        <div class="stat-item">
            <span class="num">Fast Delivery</span>
            <span class="label">Re a Deliver'a</span>
        </div>
    </div>
</div>

<!-- WHY PARTNER -->
<section class="section">
    <div class="section-inner">
        <span class="section-label">Why Choose Us</span>
        <h2 class="section-title">Advertise with the Maru Quick Supply Portal</h2>
        <p class="section-sub">We built the Supply Portal specifically for Botswana's MSMEs — no minimum orders, no complicated procurement, just reliable stock at honest prices.</p>

        <div class="why-grid">
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
                </div>
                <h3>Increased Sales Volume</h3>
                <p>Benefit from our platform traffic and reach active consumers who are already looking to buy from local businesses like yours.</p>
            </div>
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                </div>
                <h3>Increased Brand Awareness</h3>
                <p>Allow the public to be acquainted with your product across the Maru Quick network of thousands of active users.</p>
            </div>
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                </div>
                <h3>Optimise Ad Spend</h3>
                <p>Advertise where it matters — to business owners and consumers who are actively making purchasing decisions right now.</p>
            </div>
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
                </div>
                <h3>Reliable Fulfilment</h3>
                <p>Your orders are tracked from placement to delivery. No chasing suppliers, no uncertainty — just stock arriving when it should.</p>
            </div>
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                </div>
                <h3>No Hidden Costs</h3>
                <p>What you see is what you pay. Transparent pricing with no setup fees, no subscription costs, and no surprise charges on delivery.</p>
            </div>
            <div class="why-card">
                <div class="why-icon">
                    <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <h3>Verified Suppliers Only</h3>
                <p>Every supplier on the portal is vetted and verified. Your business only ever receives legitimate, quality-checked products.</p>
            </div>
        </div>
    </div>
</section>

<!-- HOW IT WORKS -->
<section class="how-section">
    <div class="how-inner">
        <span class="section-label">Getting Started</span>
        <h2 class="section-title">How the Supply Portal works</h2>
        <p class="section-sub">Four simple steps from sign-up to your first delivery. No paperwork, no waiting rooms.</p>

        <div class="steps-grid">
            <div class="step">
                <div class="step-num">1</div>
                <h3>Create Your Account</h3>
                <p>Sign up in under 2 minutes. Your business account gives you access to the full supplier catalogue immediately.</p>
            </div>
            <div class="step">
                <div class="step-num">2</div>
                <h3>Browse & Select</h3>
                <p>Browse thousands of wholesale FMCG products by category. Filter by price, brand, or minimum order quantity.</p>
            </div>
            <div class="step">
                <div class="step-num">3</div>
                <h3>Place Your Order</h3>
                <p>Add to cart, confirm your delivery address, and pay securely. Bulk order discounts apply automatically at checkout.</p>
            </div>
            <div class="step">
                <div class="step-num">4</div>
                <h3>Receive & Restock</h3>
                <p>Your order is delivered within 48 hours. Track in real time from your dashboard and reorder with one click.</p>
            </div>
        </div>
    </div>
</section>

<!-- CATEGORIES -->
<section class="categories-section">
    <div class="section-inner">
        <span class="section-label">Product Categories</span>
        <h2 class="section-title">Shop by category</h2>
        <p class="section-sub">From snacks and beverages to cleaning supplies and personal care — everything your business needs in one place.</p>

        <div class="cat-grid">
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg></div>
                <h3>Snacks</h3>
                <p>Crisps, biscuits, sweets & more</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M8 2h8l1 10H7L8 2z"/><path d="M7 12c0 5 2 8 5 8s5-3 5-8"/><line x1="9" y1="7" x2="15" y2="7"/></svg></div>
                <h3>Beverages</h3>
                <p>Cold drinks, juices, water & energy</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M12 22V12"/><path d="M12 12C12 7 8 4 5 6s-1 7 3 8"/><path d="M12 12c0-5 4-8 7-6s1 7-3 8"/><path d="M12 12c-3-3-3-7 0-8s3 5 0 8"/></svg></div>
                <h3>Vegetables</h3>
                <p>Fresh produce for food businesses</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M9 2h6l1 3H8L9 2z"/><rect x="6" y="5" width="12" height="16" rx="2"/><path d="M10 11c0-1 .9-2 2-2s2 1 2 2"/><circle cx="12" cy="14" r="1"/></svg></div>
                <h3>Personal Care</h3>
                <p>Soaps, lotions, hygiene products</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M3 21l9-9"/><path d="M12.22 6.22L16 2.5a1 1 0 0 1 1.41 0l4.09 4.09a1 1 0 0 1 0 1.41L17.78 11.8a2 2 0 0 1-2.83 0l-2.73-2.75a2 2 0 0 1 0-2.83z"/></svg></div>
                <h3>Cleaning Supplies</h3>
                <p>Detergents, mops, cloths & more</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M3 11l19-9-9 19-2-8-8-2z"/></svg></div>
                <h3>Dry Goods</h3>
                <p>Flour, rice, sugar, cooking essentials</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M8 2h8l2 5H6L8 2z"/><path d="M6 7v13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7"/><path d="M10 12h4"/></svg></div>
                <h3>Dairy & Chilled</h3>
                <p>Milk, yoghurt, cheese & cold items</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
            <div class="cat-card">
                <div class="cat-icon"><svg fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg></div>
                <h3>All Products</h3>
                <p>Browse the full wholesale catalogue</p>
                <div class="cat-arrow">
                    <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- CTA -->
<section class="cta-section">
    <div class="cta-inner">
        <h2>Ready to stock smarter?</h2>
        <p>Join over 100 Botswana businesses already ordering wholesale through Maru Quick. Sign up free and place your first order today.</p>
        <div class="cta-btns">
            <a href="signup.php" class="btn-primary">
                Get Started Free
            </a>
            <a href="contact.php" class="btn-secondary">
                Talk to Us First
            </a>
        </div>
    </div>
</section>

<!-- FOOTER -->
<style>
/* --- MaruQuick app casing: phone-only fixed bottom tab bar --- */
body { padding-bottom:76px; }
.m-bottomnav {
  display:flex;
  position:fixed; left:0; right:0; bottom:0; z-index:500;
  background: var(--dark, #0E0E0E);
  align-items:stretch; justify-content:space-around;
  padding: 9px 4px calc(9px + env(safe-area-inset-bottom));
  box-shadow: 0 -4px 20px rgba(0,0,0,.18);
}
.m-bottomnav .m-nav-item {
  display:flex; flex-direction:column; align-items:center; justify-content:space-between; gap:4px;
  color:#9CA3AF; font-family: var(--fb, 'DM Sans', sans-serif);
  font-size:.62rem; font-weight:600; flex:1; padding:2px; text-align:center; text-decoration:none;
}
.m-bottomnav .m-nav-label { display:block; width:100%; text-align:center; line-height:1.12; }
.m-bottomnav .m-nav-item.active { color: var(--yellow, #F5C518); }
.m-bottomnav .m-nav-icon { display:flex; align-items:center; justify-content:center; }
.m-bottomnav .m-nav-icon svg { width:20px; height:20px; }
.m-bottomnav .m-nav-scan .m-nav-icon-wrap {
  width:44px; height:44px; border-radius:50%; background: var(--yellow, #F5C518);
  display:flex; align-items:center; justify-content:center; color: var(--dark, #0E0E0E);
  margin-top:-20px; box-shadow:0 4px 14px rgba(245,197,24,.4);
}
.m-bottomnav .m-nav-scan.active .m-nav-icon-wrap { background: var(--yellow-dk, #D4A900); }
</style>

<!-- ===== MOBILE BOTTOM NAV (phone only) — mirrors portal.php ===== -->
<nav class="m-bottomnav" id="mBottomNav" aria-label="Primary">
  <a class="m-nav-item" href="portal.php" data-nav="home">
    <span class="m-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></span><span class="m-nav-label">Home</span>
  </a>
  <a class="m-nav-item" href="financial_services.php" data-nav="money">
    <span class="m-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><path d="M6 15h4"/></svg></span><span class="m-nav-label">Financial Services</span>
  </a>
  <a class="m-nav-item m-nav-scan" href="portal.php" data-nav="scan">
    <span class="m-nav-icon-wrap"><svg viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><g transform="scale(0.02) translate(0,1200) scale(0.1,-0.1)"><path d="M3822 8888 l3 -1843 3645 0 3645 0 3 1843 2 1842 -3650 0 -3650 0 2 -1842z m6019 1511 c86 -26 159 -124 159 -216 1 -170 87 -345 220 -448 101 -77 147 -93 365 -124 106 -16 180 -77 205 -172 7 -25 10 -228 8 -571 -3 -498 -4 -535 -22 -568 -49 -92 -111 -128 -241 -140 -149 -15 -263 -63 -355 -151 -107 -104 -165 -230 -177 -384 -3 -44 -12 -95 -20 -113 -21 -51 -80 -109 -131 -129 -45 -17 -153 -18 -2382 -18 -2229 0 -2337 1 -2382 18 -51 20 -110 77 -131 129 -8 18 -17 69 -21 113 -17 213 -126 382 -306 475 -63 32 -126 49 -223 59 -133 13 -194 49 -243 141 -18 33 -19 70 -22 568 -2 343 1 546 8 571 15 55 49 102 102 137 38 26 61 33 120 38 167 16 262 50 361 131 120 98 190 239 204 410 9 119 52 191 137 231 l51 24 2339 0 c1724 0 2349 -3 2377 -11z M5387 9933 c-3 -5 -17 -43 -31 -86 -96 -287 -322 -524 -601 -630 -55 -22 -110 -43 -121 -47 -22 -8 -22 -13 -23 -247 0 -131 3 -255 7 -277 7 -38 8 -39 87 -66 315 -107 577 -376 661 -679 l17 -61 484 0 c265 0 483 3 483 6 0 3 -29 42 -65 87 -168 209 -285 477 -324 744 -16 102 -14 326 4 441 41 272 159 535 332 739 29 34 53 67 53 73 0 12 -956 15 -963 3z M7314 9926 c-345 -56 -629 -264 -782 -571 -82 -165 -107 -279 -106 -475 1 -134 5 -168 28 -254 100 -371 379 -651 752 -753 88 -24 116 -27 259 -27 131 0 176 4 246 21 188 48 356 141 490 273 133 132 205 247 263 421 192 575 -151 1197 -742 1345 -122 30 -294 39 -408 20z M8590 9929 c0 -6 22 -36 49 -67 168 -195 291 -469 337 -747 24 -147 15 -412 -19 -555 -59 -249 -166 -464 -326 -655 l-50 -60 477 -3 c262 -1 482 0 489 2 6 3 19 31 28 63 59 203 227 429 407 549 78 52 217 119 283 135 25 6 48 16 52 22 4 7 7 379 3 533 0 17 -13 25 -67 43 -318 104 -566 349 -673 666 l-27 80 -481 3 c-343 1 -482 -1 -482 -9z M890 5912 c-7 -3 -10 -479 -10 -1403 l0 -1399 575 0 575 0 0 1400 0 1400 -23 0 c-12 0 -266 1 -565 3 -298 1 -547 1 -552 -1z M2502 4508 l3 -1203 535 -5 c476 -4 538 -7 565 -22 25 -14 490 -399 1101 -913 72 -60 205 -171 295 -246 90 -75 223 -185 294 -245 294 -248 393 -330 447 -369 78 -58 218 -129 326 -165 173 -58 210 -60 1062 -60 853 0 889 2 1062 60 198 66 308 140 583 391 99 90 271 246 382 347 205 187 235 220 275 307 19 42 23 67 23 155 0 98 -2 109 -33 173 -82 168 -258 261 -438 230 -127 -22 -155 -43 -444 -328 -278 -275 -329 -315 -470 -370 -148 -58 -173 -60 -805 -60 -678 0 -698 2 -885 94 -87 43 -152 93 -392 305 -214 189 -225 198 -493 431 -307 266 -326 285 -353 343 -53 117 -4 249 116 309 34 17 83 18 702 23 589 5 671 7 715 22 204 69 357 241 401 448 50 236 -70 498 -283 617 -124 69 -97 66 -753 73 -661 8 -693 10 -885 77 -201 70 -306 139 -563 366 -104 93 -216 187 -248 209 -141 95 -344 174 -508 197 -49 7 -313 11 -707 11 l-629 0 2 -1202z"/></g></svg></span><span class="m-nav-label">Get Paid</span>
  </a>
  <a class="m-nav-item active" href="supply_portal.php" data-nav="supply">
    <span class="m-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8 12 3 3 8l9 5 9-5Z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/></svg></span><span class="m-nav-label">Supply Portal</span>
  </a>
  <a class="m-nav-item" href="account.php" data-nav="account">
    <span class="m-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></span><span class="m-nav-label">Account</span>
  </a>
</nav>
<script>
(function () {
  "use strict";
  var navItems = document.querySelectorAll('#mBottomNav .m-nav-item');
  navItems.forEach(function (item) {
    item.addEventListener('click', function () {
      navItems.forEach(function (i) { i.classList.remove('active'); });
      item.classList.add('active');
    });
  });
})();
</script>

<footer>
    <div class="footer-inner">
        <div class="footer-top">
            <div class="footer-brand">
                <div class="logo-fallback">Maru<span>Quick</span></div>
                <p>Botswana's MSME supply and POS platform. Built to help small businesses grow, stock smarter, and sell faster.</p>
            </div>
            <div class="footer-col">
                <h4>Portal</h4>
                <a href="supply_portal.php">Supply Portal</a>
                <a href="signup.php">Register Business</a>
                <a href="login.php">Login</a>
            </div>
            <div class="footer-col">
                <h4>Company</h4>
                <a href="about.php">About Us</a>
                <a href="contact.php">Contact</a>
                <a href="offers.php">Offers</a>
            </div>
            <div class="footer-col">
                <h4>Support</h4>
                <a href="mailto:maruquickbotswana@gmail.com">maruquickbotswana@gmail.com</a>
                <a href="contact.php">Help Centre</a>
            </div>
        </div>
        <div class="footer-bottom">
            <p>&copy; 2026 Maru Quick. All rights reserved.</p>
        </div>
    </div>
</footer>
</body>
</html>
