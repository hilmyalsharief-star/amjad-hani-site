/* Amjad Hani site — behaviour only. All content is rendered at build time (build.py). */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DEFAULT = window.__DEFAULT_LANG || 'en';
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };

  /* ------------------------------------------------------------ language + header */
  const langBtn = $('#lang'), menuBtn = $('#menu'), nav = $('#nav'), topbar = $('.topbar');
  let current = DEFAULT;

  function closeMenu() {
    if (!nav) return;
    nav.classList.remove('open');
    menuBtn.setAttribute('aria-expanded', 'false');
    menuBtn.setAttribute('aria-label', current === 'ar' ? 'فتح القائمة' : 'Open menu');
    menuBtn.textContent = '☰';
  }

  function setLang(next, persist) {
    current = next;
    document.documentElement.lang = next;
    document.documentElement.dir = next === 'ar' ? 'rtl' : 'ltr';
    $$('[data-en][data-ar]').forEach(el => {
      const v = el.dataset[next];
      if (v === undefined) return;
      if (el.tagName === 'OPTION') el.textContent = v; else el.innerHTML = v;
    });
    if (langBtn) {
      langBtn.textContent = next === 'en' ? 'AR' : 'EN';
      langBtn.setAttribute('aria-label', next === 'en' ? 'Switch to Arabic' : 'التبديل إلى الإنجليزية');
    }
    closeMenu();
    if (persist) store.set('lang', next);
    const msg = $('.form-msg:not([hidden])');
    if (msg && msg.dataset.key) msg.textContent = form_text(msg.dataset.form, msg.dataset.key);
  }

  const saved = store.get('lang');
  const initial = (saved === 'en' || saved === 'ar') ? saved : (DEFAULT);
  if (initial !== DEFAULT) setLang(initial, false);

  if (langBtn) langBtn.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); setLang(current === 'en' ? 'ar' : 'en', true); });
  if (menuBtn) {
    menuBtn.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      const opened = nav.classList.toggle('open');
      menuBtn.setAttribute('aria-expanded', String(opened));
      menuBtn.textContent = opened ? '×' : '☰';
      menuBtn.setAttribute('aria-label', opened ? (current === 'ar' ? 'إغلاق القائمة' : 'Close menu') : (current === 'ar' ? 'فتح القائمة' : 'Open menu'));
    });
    $$('a', nav).forEach(a => a.addEventListener('click', closeMenu));
    document.addEventListener('click', e => { if (topbar && !topbar.contains(e.target)) closeMenu(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
  }
  const updateHeader = () => {
    if (!topbar) return;
    const s = window.scrollY > 8;
    topbar.classList.toggle('is-scrolled', s);
    topbar.style.boxShadow = s ? '0 8px 28px rgba(0,0,0,.08)' : 'none';
  };
  window.addEventListener('scroll', updateHeader, { passive: true }); updateHeader();

  /* ------------------------------------------------------------ generic slider */
  function slider(root, o) {
    const slides = $$(o.slide, root);
    const dots = $$('.s-dot', root);
    if (!slides.length) return null;
    let i = Math.max(0, slides.findIndex(s => s.classList.contains('is-active')));
    let timer = 0, paused = false, visible = true;
    function schedule() {
      clearTimeout(timer);
      if (reduced || slides.length < 2 || paused || !visible || document.hidden) return;
      if (o.holdOnVideo && o.holdOnVideo(slides[i])) return;
      timer = setTimeout(() => go(i + 1), (o.interval || 5) * 1000);
    }
    function go(n) {
      i = (n + slides.length) % slides.length;
      slides.forEach((s, k) => s.classList.toggle('is-active', k === i));
      dots.forEach((d, k) => d.classList.toggle('is-active', k === i));
      if (o.onChange) o.onChange(slides, i);
      schedule();
    }
    $$('.s-prev', root).forEach(b => b.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); go(i - 1); }));
    $$('.s-next', root).forEach(b => b.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); go(i + 1); }));
    dots.forEach(d => d.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); go(+d.dataset.i); }));
    // swipe
    let sx = 0, sy = 0;
    root.addEventListener('touchstart', e => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
    root.addEventListener('touchend', e => {
      const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
      if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.4) go(i + (dx < 0 ? 1 : -1) * (document.documentElement.dir === 'rtl' ? -1 : 1));
    }, { passive: true });
    if (o.pauseOnHover) { root.addEventListener('mouseenter', () => { paused = true; clearTimeout(timer); }); root.addEventListener('mouseleave', () => { paused = false; schedule(); }); }
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(es => { visible = es[0].isIntersecting; if (o.onVisible) o.onVisible(visible, slides, i); visible ? schedule() : clearTimeout(timer); }, { threshold: .15 }).observe(root);
    }
    document.addEventListener('visibilitychange', () => { document.hidden ? clearTimeout(timer) : schedule(); });
    if (o.onChange) o.onChange(slides, i);
    schedule();
    return { go, next: () => go(i + 1), schedule };
  }

  /* hero */
  const hero = $('.hero');
  if (hero) {
    const interval = parseFloat(hero.dataset.interval) || 6;
    const isVid = s => !!$('video.hero-video', s);
    const ctl = slider(hero, {
      slide: '.hero-slide', interval,
      holdOnVideo: s => isVid(s) && !(window.__heroVideoFailed),
      onChange(slides, i) {
        slides.forEach((s, k) => {
          const v = $('video.hero-video', s);
          if (v) {
            if (k === i && !reduced) {
              v.currentTime = 0;
              const p = v.play();
              if (p && p.catch) p.catch(() => { window.__heroVideoFailed = true; ctl && ctl.schedule(); });
            } else v.pause();
          }
          const f = $('iframe.hero-embed', s);
          if (f && k === i && !f.src && f.dataset.src) f.src = f.dataset.src;
        });
      },
    });
    $$('video.hero-video', hero).forEach(v => v.addEventListener('ended', () => ctl && ctl.next()));
  }

  /* project cards */
  $$('[data-slider]').forEach(root => {
    slider(root, {
      slide: '.pslide', interval: parseFloat(root.dataset.interval) || 4, pauseOnHover: true,
      onChange(slides, i) { slides.forEach((s, k) => { const v = $('video', s); if (v) (k === i ? v.play().catch(() => {}) : v.pause()); }); },
    });
  });

  /* ------------------------------------------------------------ projects filter */
  const grid = $('.project-grid');
  if (grid) {
    const cards = $$('.project-card', grid), tabs = $('.proj-tabs'), tabBtns = tabs ? $$('button', tabs) : [];
    const restagger = () => { let n = 0; cards.forEach(c => { if (getComputedStyle(c).display !== 'none') { c.classList.toggle('alt', n % 2 === 1); n++; } }); };
    restagger();
    function apply(cat, scroll) {
      $$('.cat-card').forEach(b => b.classList.toggle('is-active', b.dataset.cat === cat));
      tabBtns.forEach(b => b.classList.toggle('is-active', b.dataset.cat === cat));
      if (tabs) tabs.hidden = false;
      grid.dataset.view = cat;
      cards.forEach(c => c.classList.toggle('is-hidden', !(cat === 'all' || (c.dataset.cats || '').split(' ').includes(cat))));
      restagger();
      try { history.replaceState(null, '', '#projects/' + cat); } catch (e) { /* ignore */ }
      if (scroll) (tabs || grid).scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
    }
    $$('[data-cat]').forEach(b => b.addEventListener('click', () => apply(b.dataset.cat, true)));
    const m = location.hash.match(/^#projects\/(.+)$/);
    if (m) apply(decodeURIComponent(m[1]), false);
  }

  /* ------------------------------------------------------------ team dialogs */
  $$('.team-card').forEach(b => b.addEventListener('click', () => { const d = document.getElementById(b.dataset.member); if (d && d.showModal) d.showModal(); }));
  $$('dialog.modal').forEach(d => {
    d.addEventListener('click', e => { if (e.target === d || e.target.closest('[data-close]')) d.close(); });
  });

  /* ------------------------------------------------------------ lightbox */
  const lb = $('#lightbox');
  if (lb) {
    const stage = $('.lb-stage', lb), cap = $('.lb-cap', lb);
    let list = [], k = 0, opener = null;
    const show = () => { const it = list[k]; stage.innerHTML = ''; const img = new Image(); img.src = it.src; img.alt = it.cap || ''; stage.appendChild(img); cap.textContent = it.cap || ''; $('.lb-prev', lb).hidden = $('.lb-next', lb).hidden = list.length < 2; };
    const close = () => { lb.hidden = true; stage.innerHTML = ''; document.body.style.overflow = ''; if (opener) opener.focus(); };
    document.addEventListener('click', e => {
      const b = e.target.closest('.lb-item');
      if (b) {
        const same = $$('.lb-item[data-group="' + b.dataset.group + '"]');
        list = same.map(x => ({ src: x.dataset.lb, cap: x.dataset.cap })); k = same.indexOf(b); opener = b;
        lb.hidden = false; document.body.style.overflow = 'hidden'; show(); $('.lb-close', lb).focus();
        return;
      }
      if (e.target.closest('.lb-close') || e.target === lb || e.target === stage) close();
      else if (e.target.closest('.lb-prev')) { k = (k - 1 + list.length) % list.length; show(); }
      else if (e.target.closest('.lb-next')) { k = (k + 1) % list.length; show(); }
    });
    document.addEventListener('keydown', e => {
      if (lb.hidden) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowLeft') { k = (k - 1 + list.length) % list.length; show(); }
      if (e.key === 'ArrowRight') { k = (k + 1) % list.length; show(); }
    });
  }

  /* ------------------------------------------------------------ before / after */
  $$('[data-ba]').forEach(ba => { const r = $('.ba-range', ba); r.addEventListener('input', () => ba.style.setProperty('--pos', r.value + '%')); });

  /* ------------------------------------------------------------ counters */
  const counters = $$('[data-count]');
  if (counters.length) {
    const run = el => {
      const to = parseFloat(el.dataset.count) || 0;
      if (reduced) { el.textContent = to; return; }
      const t0 = performance.now(), dur = 1400;
      const step = t => { const p = Math.min(1, (t - t0) / dur); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    };
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { run(e.target); io.unobserve(e.target); } }), { threshold: .4 });
      counters.forEach(c => { c.textContent = '0'; io.observe(c); });
    }
  }

  /* ------------------------------------------------------------ video embeds (load on click) */
  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-embed]');
    if (!b) return;
    const f = document.createElement('iframe');
    f.className = 'embed-frame' + (b.classList.contains('fill') ? ' fill' : '');
    f.src = b.dataset.embed; f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen'; f.allowFullscreen = true; f.title = 'Video';
    b.replaceWith(f);
  });

  /* ------------------------------------------------------------ request form */
  const MSG = {
    nokey: { en: 'The form is not connected yet. Please contact us directly.', ar: 'النموذج غير مفعّل بعد. يرجى التواصل معنا مباشرة.' },
  };
  function form_text(form, key) {
    const f = document.getElementById(form); if (!f) return '';
    if (key === 'nokey') return MSG.nokey[current];
    return f.dataset[key + '-' + current];
  }
  const form = $('#start');
  if (form) {
    const msg = $('.form-msg', form), btn = $('button[type=submit]', form);
    const say = (type, key) => { msg.hidden = false; msg.className = 'form-msg ' + (type === 'ok' ? 'ok' : 'err'); msg.dataset.key = key; msg.dataset.form = form.id; msg.textContent = form_text(form.id, key); };
    form.addEventListener('submit', e => {
      e.preventDefault();
      let bad = false;
      $$('.field', form).forEach(f => {
        const c = $('input,textarea,select', f); let ok = true;
        if (c.required && !c.value.trim()) ok = false;
        if (c.type === 'email' && c.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.value)) ok = false;
        if (c.name === 'phone' && c.value && c.value.replace(/\D/g, '').length < 7) ok = false;
        f.classList.toggle('invalid', !ok); if (!ok) bad = true;
      });
      const consent = $('[name=consent]', form);
      if (consent && !consent.checked) bad = true;
      if (bad) return say('err', 'inv');
      if ($('[name=botcheck]', form).checked) return say('ok', 'ok');
      const key = form.dataset.key;
      if (!key) return say('err', 'nokey');
      const data = Object.fromEntries(new FormData(form).entries());
      delete data.botcheck; delete data.consent;
      data.access_key = key; data.subject = form.dataset.subject; data.from_name = 'Website'; data.message = data.description;
      btn.disabled = true;
      fetch('https://api.web3forms.com/submit', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(data) })
        .then(r => r.json()).then(j => { if (j.success) { form.reset(); say('ok', 'ok'); } else say('err', 'err'); })
        .catch(() => say('err', 'err')).finally(() => { btn.disabled = false; });
    });
  }

  /* ------------------------------------------------------------ images that fail to load */
  document.addEventListener('error', e => { if (e.target && e.target.tagName === 'IMG') e.target.classList.add('broken'); }, true);
})();
