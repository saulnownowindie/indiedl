(function () {
    'use strict';

    if (window.top !== window.self) return;

    const MAX_QUEUE = 30;

    const ICON = {
        download: 'M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z',
        video:    'M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z',
        audio:    'M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z',
        image:    'M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z',
        start:    'M9 4H5v16h4v-2H7V6h2V4zm2 8l7-5v10l-7-5z',
        end:      'M15 4h4v16h-4v-2h2V6h-2V4zm-2 8L6 7v10l7-5z',
        add:      'M14 10H3v2h11v-2zm0-4H3v2h11V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM3 16h7v-2H3v2z',
        list:     'M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z'
    };

    const MODE_DEF = {
        video: { label: 'Video',  icon: 'video' },
        audio: { label: 'Audio',  icon: 'audio' },
        image: { label: 'Imagen', icon: 'image' }
    };

    const PLATFORMS = {
        youtube:   { modes: ['video', 'audio'],           clip: true  },
        instagram: { modes: ['video', 'audio', 'image'],  clip: false },
        tiktok:    { modes: ['video', 'audio'],           clip: false },
        x:         { modes: ['video', 'audio', 'image'],  clip: false },
        pinterest: { modes: ['image', 'video'],           clip: false },
        other:     { modes: ['video', 'audio', 'image'],  clip: false }
    };

    function detectPlatform() {
        const h = location.hostname;
        if (h.includes('youtube.com')) return 'youtube';
        if (h.includes('instagram.com')) return 'instagram';
        if (h.includes('tiktok.com')) return 'tiktok';
        if (h.includes('x.com') || h.includes('twitter.com')) return 'x';
        if (h.includes('pinterest.')) return 'pinterest';
        return 'other';
    }

    function isShortForm() {
        const { hostname: h, pathname: p } = window.location;
        if (h.includes('tiktok.com')) return true;
        if (h.includes('instagram.com') && (p.includes('/reel/') || p.includes('/reels/'))) return true;
        if (h.includes('youtube.com') && p.startsWith('/shorts/')) return true;
        return false;
    }

    let platform     = detectPlatform();
    let currentModes = PLATFORMS[platform].modes.slice();
    let clipAllowed  = PLATFORMS[platform].clip;
    let currentMode  = currentModes[0];
    let autoImageModeUrl = null;

    let inT = null, outT = null, curUrl = null;

    let lastCopied = { url: null, ts: 0 };
    const COPIED_TTL_MS = 120000;

    function captureCopied(text) {
        try {
            if (!text) return;
            const s = String(text).trim();
            let m = s.match(/https?:\/\/(?:www\.)?tiktok\.com\/@[^/?#\s]+\/video\/\d+/i);
            if (!m) m = s.match(/https?:\/\/(?:vm|vt)\.tiktok\.com\/[\w-]+\/?/i);
            if (!m) m = s.match(/https?:\/\/(?:www\.)?tiktok\.com\/t\/[\w-]+\/?/i);
            if (m) lastCopied = { url: m[0].replace(/\/$/, ''), ts: Date.now() };
        } catch (_) {}
    }
    window.addEventListener('message', (event) => {
        if (event.source !== window || !event.data || event.data.source !== 'indiedl-clipboard') return;
        captureCopied(event.data.text);
    });
    function getRecentCopied() {
        return (lastCopied.url && Date.now() - lastCopied.ts < COPIED_TTL_MS) ? lastCopied.url : null;
    }

    if (platform === 'tiktok') {
        document.addEventListener('copy', () => {
            try {
                const sel = String(window.getSelection && window.getSelection());
                captureCopied(sel);
                const ae = document.activeElement;
                if (ae && typeof ae.value === 'string' && typeof ae.selectionStart === 'number') {
                    captureCopied(ae.value.slice(ae.selectionStart, ae.selectionEnd) || ae.value);
                }
            } catch (_) {}
        }, true);
    }

    let queueCache = [];
    let queueLoaded = false;
    const queueReady = chrome.storage.local.get('indiedl_queue').then((saved) => {
        queueCache = Array.isArray(saved.indiedl_queue) ? saved.indiedl_queue : [];
        queueLoaded = true;
    }).catch(() => { queueCache = []; queueLoaded = true; });
    const loadQueue = () => queueCache.slice();
    const saveQueue = (q) => {
        queueCache = Array.isArray(q) ? q.slice() : [];
        chrome.storage.local.set({ indiedl_queue: queueCache }).catch(() => {});
    };

    function el(tag, props = {}, ...kids) {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (k === 'className') n.className = v;
            else if (k === 'text') n.textContent = v;
            else n[k] = v;
        }
        kids.forEach(c => n.appendChild(c));
        return n;
    }
    function svgIcon(d) {
        const NS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', d);
        svg.appendChild(p);
        return svg;
    }
    const fmt = (sec) => {
        sec = Math.max(0, Math.floor(sec));
        const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
        const p = (x) => String(x).padStart(2, '0');
        return h ? `${h}:${p(m)}:${p(s)}` : `${m}:${p(s)}`;
    };

    const style = document.createElement('style');
    style.textContent = `
        #indiedl-bar {
            display: inline-flex; align-items: center; gap: 6px; margin-left: 8px; flex-wrap: wrap;
            font-family: 'Roboto', 'Segoe UI', Arial, sans-serif; vertical-align: middle;
            visibility: hidden; z-index: 10;
        }
        #indiedl-bar.ready { visibility: visible; }

        #indiedl-bar.floating {
            position: fixed; bottom: 80px; right: 24px; z-index: 2147483646; margin: 0;
            background: #151B21; border: 2px solid #FFF333; border-radius: 16px;
            padding: 8px; max-width: 420px; box-shadow: 0 8px 24px rgba(0,0,0,.6);
        }
        #indiedl-bar.hidden { display: none !important; }

        /* CAMBIO CLAVE: Posición inicial fuera de pantalla para evitar el parpadeo arriba a la izquierda */
        #indiedl-bar.tt-floating,
        #indiedl-bar.yt-shorts-floating,
        #indiedl-bar.ig-floating {
            position: fixed !important;
            right: auto !important;
            bottom: auto !important;
            left: 0 !important;
            top: 0 !important;
            z-index: 2147483647 !important;
            display: flex !important;
            flex-direction: column !important;
            flex-wrap: nowrap !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 8px !important;
            width: 42px !important;
            min-width: 42px !important;
            max-width: 42px !important;
            margin: 0 !important;
            padding: 8px !important;
            border: 1.5px solid #FFF333 !important;
            border-radius: 24px !important;
            background: rgba(21, 27, 33, .96) !important;
            box-shadow: 0 8px 24px rgba(0,0,0,.55) !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            /* La posición real viaja en transform (compone en GPU, no reflow). */
            transform: translate3d(-9999px, -9999px, 0) !important;
            will-change: transform;
            transition: opacity .12s ease-out !important;
        }
        #indiedl-bar.tt-floating.positioned,
        #indiedl-bar.yt-shorts-floating.positioned,
        #indiedl-bar.ig-floating.positioned {
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }
        #indiedl-bar.positioned.smooth {
            transition: opacity .12s ease-out,
                        transform .22s cubic-bezier(.2, .8, .2, 1) !important;
        }
        #indiedl-bar.tt-floating button,
        #indiedl-bar.yt-shorts-floating button,
        #indiedl-bar.ig-floating button {
            all: unset !important;
            box-sizing: border-box !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            flex: 0 0 36px !important;
            width: 36px !important;
            min-width: 36px !important;
            max-width: 36px !important;
            height: 36px !important;
            min-height: 36px !important;
            max-height: 36px !important;
            margin: 0 !important;
            padding: 0 !important;
            border: 1.5px solid #FFF333 !important;
            border-radius: 50% !important;
            background: #0D1116 !important;
            color: #FFF333 !important;
            cursor: pointer !important;
        }
        #indiedl-bar.tt-floating button span,
        #indiedl-bar.yt-shorts-floating button span,
        #indiedl-bar.ig-floating button span { display: none !important; }
        #indiedl-bar.tt-floating button svg,
        #indiedl-bar.yt-shorts-floating button svg,
        #indiedl-bar.ig-floating button svg {
            display: block !important;
            width: 18px !important;
            height: 18px !important;
            flex: 0 0 18px !important;
            fill: currentColor !important;
            pointer-events: none !important;
        }
        #indiedl-bar.tt-floating button.dl,
        #indiedl-bar.yt-shorts-floating button.dl,
        #indiedl-bar.ig-floating button.dl {
            background: #FFF333 !important;
            color: #0D1116 !important;
        }
        #indiedl-bar.tt-floating button:hover,
        #indiedl-bar.tt-floating button:focus-visible,
        #indiedl-bar.yt-shorts-floating button:hover,
        #indiedl-bar.yt-shorts-floating button:focus-visible,
        #indiedl-bar.ig-floating button:hover,
        #indiedl-bar.ig-floating button:focus-visible {
            background: #FFF333 !important;
            color: #0D1116 !important;
        }

        #indiedl-bar.no-clip-platform .clip-control {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }

        #indiedl-bar.ig-icons {
            flex-wrap: nowrap !important;
            align-items: center !important;
            gap: 6px !important;
            margin-left: 0 !important;
            padding: 0 !important;
            transform: none !important;
            vertical-align: middle !important;
        }
        #indiedl-bar.ig-inline {
            display: inline-flex !important;
            flex-direction: row !important;
            margin-left: 8px !important;
        }
        #indiedl-bar.ig-reel {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 8px !important;
            width: 36px !important;
            min-width: 36px !important;
            max-width: 36px !important;
            margin: 0 0 14px 0 !important;
            padding: 0 !important;
        }
        #indiedl-bar.ig-icons button {
            all: unset !important;
            box-sizing: border-box !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            flex: 0 0 36px !important;
            width: 36px !important;
            min-width: 36px !important;
            max-width: 36px !important;
            height: 36px !important;
            min-height: 36px !important;
            max-height: 36px !important;
            margin: 0 !important;
            padding: 0 !important;
            border: 1.5px solid #FFF333 !important;
            border-radius: 50% !important;
            background: #0D1116 !important;
            color: #FFF333 !important;
            box-shadow: 0 2px 6px rgba(0,0,0,.35) !important;
            cursor: pointer !important;
            transition: background .15s, color .15s, transform .1s !important;
        }
        #indiedl-bar.ig-icons button span { display: none !important; }
        #indiedl-bar.ig-icons button svg {
            display: block !important;
            width: 18px !important;
            height: 18px !important;
            flex: 0 0 18px !important;
            fill: currentColor !important;
            pointer-events: none !important;
        }
        #indiedl-bar.ig-icons button.dl {
            background: #FFF333 !important;
            color: #0D1116 !important;
        }
        #indiedl-bar.ig-icons button.set {
            background: rgba(255,243,51,.20) !important;
        }
        #indiedl-bar.ig-icons button:hover,
        #indiedl-bar.ig-icons button:focus-visible {
            background: #FFF333 !important;
            color: #0D1116 !important;
        }
        #indiedl-bar.ig-icons button:active { transform: scale(.94) !important; }
        #indiedl-bar.ig-icons button:focus-visible { outline: 2px solid #FFF333 !important; outline-offset: 2px !important; }

        #indiedl-bar button {
            display: inline-flex; align-items: center; gap: 6px;
            height: 36px; padding: 0 14px 0 10px; border-radius: 18px; cursor: pointer;
            border: 1.5px solid #FFF333; background: #0D1116; color: #FFF333;
            font-size: 13px; font-weight: 700; white-space: nowrap; line-height: 1;
            transition: background .15s, color .15s, transform .1s;
        }
        #indiedl-bar button svg { width: 20px; height: 20px; fill: currentColor; flex: none; }
        #indiedl-bar button:hover { background: #FFF333; color: #0D1116; }
        #indiedl-bar button:disabled { opacity: .55; cursor: wait; }
        #indiedl-bar button:active { transform: scale(.96); }
        #indiedl-bar button.dl { background: #FFF333; color: #0D1116; }
        #indiedl-bar button.dl:hover { background: #FFE600; border-color: #FFE600; }
        #indiedl-bar button.set { background: rgba(255,243,51,.20); }
        #indiedl-bar button.set:hover { background: #FFF333; }

        #indiedl-pop {
            position: fixed; z-index: 2147483647; width: 340px; max-height: 60vh; overflow: auto;
            background: #151B21; border: 2px solid #FFF333; border-radius: 12px; padding: 12px;
            font-family: 'Segoe UI', Arial, sans-serif; color: #F4F6F8; font-size: 13px;
            box-shadow: 0 10px 30px rgba(0,0,0,.8); display: none;
        }
        #indiedl-pop.show { display: block; }
        #indiedl-pop .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;
            color: #FFF333; font-weight: 800; text-transform: uppercase; }
        #indiedl-pop .head button { background: #0D1116; color: #FFF333; border: 1px solid #FFF333; border-radius: 6px;
            padding: 4px 10px; cursor: pointer; font-size: 12px; font-weight: 700; }
        #indiedl-pop .row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-top: 1px solid #2a323a; }
        #indiedl-pop .row .t { flex: 1; min-width: 0; }
        #indiedl-pop .row .t b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
        #indiedl-pop .row .t small { color: #AAB4BE; }
        #indiedl-pop .row .x { cursor: pointer; color: #AAB4BE; background: none; border: none; font-size: 16px; }
        #indiedl-pop .row .x:hover { color: #FF5B65; }
        #indiedl-pop .empty { color: #AAB4BE; padding: 10px 0; text-align: center; }

        #indiedl-toast {
            position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); z-index: 2147483647;
            background: #0D1116; color: #FFF333; border: 1px solid #FFF333; padding: 10px 16px; border-radius: 8px;
            font: 13px 'Segoe UI', Arial, sans-serif; opacity: 0; transition: opacity .25s; pointer-events: none;
            max-width: 90vw; text-align: center;
        }
        #indiedl-toast.show { opacity: 1; }
    `;

    function injectStyle() {
        if (style.isConnected) return;
        const root = document.head || document.documentElement;
        if (root) root.appendChild(style);
    }
    injectStyle();
    if (!style.isConnected) {
        document.addEventListener('DOMContentLoaded', injectStyle, { once: true });
    }

    function makeBtn(cls, onclick) {
        const b = el('button', { type: 'button', className: cls, onclick });
        const lbl = el('span');
        b.append(svgIcon(ICON.download), lbl);
        b._lbl = lbl;
        return b;
    }
    function setBtn(b, iconD, text, title) {
        b.replaceChild(svgIcon(iconD), b.firstChild);
        b._lbl.textContent = text;
        b.setAttribute('aria-label', text);
        if (title) b.title = title;
    }

    const bDl    = makeBtn('dl', () => download());
    const bMode  = makeBtn('',   () => cycleMode());
    const bIn    = makeBtn('clip-control',  () => markIn());
    const bOut   = makeBtn('clip-control', () => markOut());
    const bQ     = makeBtn('',   () => addToQueue());
    const bList  = makeBtn('',   (e) => { e.stopPropagation(); togglePop(); });

    bIn.addEventListener('contextmenu',  (e) => { e.preventDefault(); inT = null;  refresh(); });
    bOut.addEventListener('contextmenu', (e) => { e.preventDefault(); outT = null; refresh(); });

    const bar     = el('div', { id: 'indiedl-bar' }, bDl, bMode, bIn, bOut, bQ, bList);
    const pop     = el('div', { id: 'indiedl-pop' });
    const toastEl = el('div', { id: 'indiedl-toast' });

    function refresh() {
        if (!currentModes.includes(currentMode)) currentMode = currentModes[0];
        const mode = currentMode;
        const def  = MODE_DEF[mode];
        const n    = loadQueue().length;
        for (const actionButton of [bDl, bQ, bList]) actionButton.disabled = !queueLoaded;

        setBtn(bDl, ICON.download, n ? `Descargar +${n}` : 'Descargar', n ? `Descarga este video y los ${n} de la cola` : 'Descarga este contenido');

        const nextMode = currentModes[(currentModes.indexOf(mode) + 1) % currentModes.length];
        setBtn(bMode, ICON[def.icon], def.label, `Tipo de descarga: ${def.label}. Clic para pasar a ${MODE_DEF[nextMode].label}.`);

        const isShort = isShortForm();
        const isRegularYouTubeVideo = platform === 'youtube' && window.location.pathname === '/watch' && !isShort;
        const showClip = isRegularYouTubeVideo && clipAllowed && mode === 'video';

        bar.classList.toggle('no-clip-platform', !showClip);

        for (const clipButton of [bIn, bOut]) {
            const hideClipButton = !showClip;
            clipButton.hidden = hideClipButton;
            if (hideClipButton) {
                clipButton.style.setProperty('display', 'none', 'important');
            } else {
                clipButton.style.removeProperty('display');
                clipButton.style.display = 'inline-flex';
            }
            clipButton.setAttribute('aria-hidden', String(hideClipButton));
        }

        setBtn(bIn,  ICON.start, inT  != null ? `Inicio ${fmt(inT)}`  : 'Inicio', 'Marca el inicio del recorte');
        setBtn(bOut, ICON.end,   outT != null ? `Fin ${fmt(outT)}`    : 'Fin', 'Marca el final del recorte');
        bIn.classList.toggle('set',  inT  != null);
        bOut.classList.toggle('set', outT != null);

        setBtn(bQ,    ICON.add,  'A la cola', 'Guarda este contenido en la cola');
        setBtn(bList, ICON.list, `Cola (${n})`, 'Ver y editar la cola');
    }

    function cycleMode() {
        const i = currentModes.indexOf(currentMode);
        currentMode = currentModes[(i + 1) % currentModes.length];
        refresh();
    }

    let toastTimer = null;
    function toast(msg) {
        if (!document.body.contains(toastEl)) document.body.appendChild(toastEl);
        toastEl.textContent = msg;
        toastEl.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastEl.classList.remove('show'), 4500);
    }

    function getVideo() {
        return document.querySelector('video.html5-main-video')
            || Array.from(document.querySelectorAll('video')).find(v => !v.paused)
            || document.querySelector('video');
    }
    function getTitle() {
        const h1 = document.querySelector('ytd-watch-metadata h1');
        const t = (h1 && h1.textContent.trim()) || document.title;
        return t.replace(/^\(\d+\)\s*/, '').replace(/\s*[-|]\s*YouTube$/i, '').trim().slice(0, 120);
    }
    function getCleanUrl() {
        const href = window.location.href;
        const host = window.location.hostname.toLowerCase();

        const cleanMatch = (value, pattern) => {
            if (!value) return null;
            try {
                const u = new URL(value, location.origin);
                const m = u.href.match(pattern);
                return m ? m[1].replace(/\/$/, '') : null;
            } catch (_) { return null; }
        };

        if (host.endsWith('tiktok.com')) {
            const ttPattern = /(https?:\/\/(?:www\.)?tiktok\.com\/@[^/?#]+\/video\/\d+)/i;
            const direct = cleanMatch(href, ttPattern);
            if (direct) return direct;

            const isVisible = (node) => {
                if (!node || !node.getBoundingClientRect) return false;
                const r = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return r.width > 100 && r.height > 100 &&
                    r.bottom > 0 && r.top < innerHeight &&
                    r.right > 0 && r.left < innerWidth &&
                    style.display !== 'none' && style.visibility !== 'hidden';
            };
            const isOnScreen = (node) => {
                if (!node || !node.getBoundingClientRect) return false;
                const r = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
                    r.right > 0 && r.left < innerWidth &&
                    style.display !== 'none' && style.visibility !== 'hidden';
            };
            const areaOf = (node) => {
                const r = node.getBoundingClientRect();
                return Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) *
                    Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
            };
            const centerDistance = (node) => {
                const r = node.getBoundingClientRect();
                return Math.hypot(
                    (r.left + r.width / 2 - innerWidth / 2) / Math.max(innerWidth, 1),
                    (r.top + r.height / 2 - innerHeight / 2) / Math.max(innerHeight, 1)
                );
            };
            const normalizeTikTokUrl = (value) => cleanMatch(value, ttPattern);

            const urlFromPlayerId = (video) => {
                let id = null, box = null;
                for (let n = video, d = 0; n && d < 25; n = n.parentElement, d++) {
                    const m = (n.id || '').match(/xgwrapper-\d+-(\d{15,22})/);
                    if (m) { id = m[1]; box = n; break; }
                }
                if (!id) return null;
                let user = '_';
                for (let n = box, d = 0; n && d < 8; n = n.parentElement, d++) {
                    const a = n.querySelector && n.querySelector('[data-e2e="video-author-uniqueid"], a[href^="/@"]');
                    if (a) {
                        const m = ((a.textContent || '') + ' ' + (a.getAttribute('href') || '')).match(/@?([\w.-]{2,64})/);
                        if (m && m[1] !== 'video') { user = m[1].replace(/^@/, ''); break; }
                    }
                }
                return `https://www.tiktok.com/@${user}/video/${id}`;
            };

            const reactKeys = (node) => {
                if (!node) return [];
                try {
                    return Object.keys(node).filter(key =>
                        key.startsWith('__reactProps$') ||
                        key.startsWith('__reactFiber$') ||
                        key.startsWith('__reactContainer$')
                    );
                } catch (_) { return []; }
            };
            const extractItemsFromReact = (root) => {
                const candidates = [];
                const seen = new Set();
                const candidateSeen = new Set();
                const addCandidate = (obj) => {
                    if (!obj || typeof obj !== 'object' || candidateSeen.has(obj)) return;
                    candidateSeen.add(obj);
                    const id = String(
                        obj.id ?? obj.itemId ?? obj.item_id ?? obj.awemeId ??
                        obj.aweme_id ?? obj.videoId ?? obj.video_id ?? ''
                    );
                    const authorObj = obj.author || obj.authorInfo || obj.author_info ||
                        obj.user || obj.userInfo || obj.user_info || {};
                    const username = String(
                        authorObj.uniqueId ?? authorObj.unique_id ?? authorObj.unique_id_str ??
                        authorObj.username ?? obj.uniqueId ?? obj.unique_id ??
                        obj.authorName ?? obj.author_name ?? ''
                    ).replace(/^@/, '');
                    const videoObj = obj.video && typeof obj.video === 'object' ? obj.video : null;
                    const videoId = String(
                        videoObj?.id ?? videoObj?.videoId ?? videoObj?.video_id ?? id
                    );
                    if (/^\d{15,22}$/.test(videoId) && /^[\w.-]{2,64}$/.test(username)) {
                        candidates.push(`https://www.tiktok.com/@${username}/video/${videoId}`);
                    }
                };
                const walk = (value, depth) => {
                    if (!value || typeof value !== 'object' || depth > 7 || seen.has(value)) return;
                    seen.add(value);
                    if (Array.isArray(value)) {
                        for (const item of value.slice(0, 80)) walk(item, depth + 1);
                        return;
                    }
                    addCandidate(value);
                    for (const key of Object.keys(value).slice(0, 100)) {
                        if (key === 'stateNode' || key === 'memoizedProps' ||
                            key === 'pendingProps' || key === 'return' ||
                            key === 'child' || key === 'sibling' ||
                            key === 'children' || key === 'item' || key === 'itemInfo' ||
                            key === 'itemStruct' || key === 'video' || key === 'author' ||
                            key === 'authorInfo' || key === 'user') {
                            try { walk(value[key], depth + 1); } catch (_) {}
                        } else if (depth < 3 && value[key] && typeof value[key] === 'object') {
                            try { walk(value[key], depth + 1); } catch (_) {}
                        }
                    }
                };

                let node = root;
                for (let depth = 0; depth < 12 && node; depth++, node = node.parentElement) {
                    const videos = node.querySelectorAll ? node.querySelectorAll('video') : [];
                    if (videos.length > 1) continue;
                    for (const key of reactKeys(node)) {
                        try {
                            const attached = node[key];
                            if (key.startsWith('__reactProps$')) walk(attached, 0);
                            else if (key.startsWith('__reactFiber$')) {
                                let fiber = attached;
                                for (let n = 0; fiber && n < 8; n++, fiber = fiber.return) {
                                    walk(fiber.memoizedProps, 0);
                                    walk(fiber.pendingProps, 0);
                                    if (fiber.stateNode && fiber.stateNode !== node) {
                                        for (const propKey of reactKeys(fiber.stateNode)) {
                                            if (propKey.startsWith('__reactProps$')) {
                                                walk(fiber.stateNode[propKey], 0);
                                            }
                                        }
                                    }
                                }
                            }
                        } catch (_) {}
                    }
                    const unique = [...new Set(candidates)];
                    if (unique.length === 1) return unique[0];
                    if (unique.length > 1) return null;
                }
                return null;
            };

            const getPermalink = (root) => {
                if (!root) return [];
                const links = [];
                if (root.matches && root.matches('a[href]')) links.push(root);
                if (root.querySelectorAll) {
                    links.push(...root.querySelectorAll('a[href*="/video/"], a[href*="/@"]'));
                }
                return [...new Set(links)]
                    .filter(a => isOnScreen(a) || /copy link|copiar enlace/i.test(a.getAttribute('aria-label') || a.textContent || ''))
                    .map(a => normalizeTikTokUrl(a.href))
                    .filter(Boolean);
            };

            const videos = Array.from(document.querySelectorAll('video')).filter(isVisible);
            const rankedVideos = videos.map(video => ({
                video,
                score: (video.paused ? 0 : 1e9) + areaOf(video) - centerDistance(video) * 2e5
            })).sort((a, b) => b.score - a.score);

            for (const { video } of rankedVideos) {
                const playerUrl = urlFromPlayerId(video);
                if (playerUrl) return playerUrl;

                const reactUrl = extractItemsFromReact(video);
                if (reactUrl) return reactUrl;

                let node = video;
                for (let depth = 0; depth < 16 && node; depth++, node = node.parentElement) {
                    const videosInNode = node.querySelectorAll ? node.querySelectorAll('video') : [];
                    if (videosInNode.length > 1) continue;
                    const links = getPermalink(node);
                    const uniqueLinks = [...new Set(links)];
                    if (uniqueLinks.length === 1) return uniqueLinks[0];

                    const wrapper = node.closest && node.closest(
                        '[data-e2e*="video"], [data-e2e*="modal"], [role="dialog"], article, ' +
                        '[class*="DivVideo"], [class*="VideoDetail"], [class*="Modal"]'
                    );
                    if (wrapper && wrapper.querySelectorAll('video').length === 1) {
                        const wrapperLinks = [...new Set(getPermalink(wrapper))];
                        if (wrapperLinks.length === 1) return wrapperLinks[0];
                    }
                }
            }

            const copyControls = Array.from(document.querySelectorAll('button, [role="button"], a'))
                .filter(el => {
                    const label = [
                        el.getAttribute('aria-label'), el.getAttribute('title'),
                        el.innerText, el.textContent
                    ].filter(Boolean).join(' ');
                    return /copy link|copiar enlace|copy video link|copiar vínculo/i.test(label) &&
                        el.getBoundingClientRect().width > 0;
                });
            for (const control of copyControls) {
                let node = control;
                for (let depth = 0; depth < 7 && node; depth++, node = node.parentElement) {
                    const vids = node.querySelectorAll ? node.querySelectorAll('video') : [];
                    if (vids.length > 1) continue;
                    const links = [...new Set(getPermalink(node))];
                    if (links.length === 1) return links[0];
                }
            }

            const visiblePermalinks = [...new Set(
                Array.from(document.querySelectorAll('a[href*="/@"][href*="/video/"]'))
                    .filter(isOnScreen)
                    .map(a => normalizeTikTokUrl(a.href))
                    .filter(Boolean)
            )];
            if (visiblePermalinks.length === 1) return visiblePermalinks[0];

            const copied = getRecentCopied();
            if (copied) return copied;

            return null;
        }

        if (host.endsWith('instagram.com')) {
            const igPattern = /(https?:\/\/(?:www\.)?instagram\.com\/(?:p|reel|reels|tv)\/[^/?#]+)/i;
            const videos = Array.from(document.querySelectorAll('video'));
            const ranked = videos.map(video => {
                const r = video.getBoundingClientRect();
                const area = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) *
                    Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
                const dist = Math.hypot(
                    (r.left + r.width / 2 - innerWidth / 2) / Math.max(innerWidth, 1),
                    (r.top + r.height / 2 - innerHeight / 2) / Math.max(innerHeight, 1)
                );
                return { video, score: (video.paused ? 0 : 1e9) + area - dist * 2e5 };
            }).sort((a, b) => b.score - a.score);

            for (const { video } of ranked) {
                let node = video;
                for (let depth = 0; depth < 12 && node; depth++, node = node.parentElement) {
                    const links = [];
                    if (node.matches && node.matches('a[href]')) links.push(node);
                    if (node.querySelectorAll) links.push(...node.querySelectorAll('a[href*="/reel/"], a[href*="/reels/"], a[href*="/p/"], a[href*="/tv/"]'));
                    for (const link of links) {
                        const result = cleanMatch(link.href, igPattern);
                        if (result) return result;
                    }
                }
            }
            return cleanMatch(href, igPattern);
        }

        if (host.endsWith('youtube.com')) {
            if (href.includes('/watch')) {
                const id = new URL(href).searchParams.get('v');
                if (id) return `https://www.youtube.com/watch?v=${id}`;
            }
            const m = href.match(/https?:\/\/(?:www\.)?youtube\.com\/shorts\/([^/?#]+)/i);
            if (m) return `https://www.youtube.com/shorts/${m[1]}`;
        }
        if (host.endsWith('x.com') || host.endsWith('twitter.com')) {
            const m = href.match(/(https?:\/\/(?:www\.)?(?:x|twitter)\.com\/\w+\/status\/\d+)/i);
            if (m) return m[1];
        }
        return href.split('?')[0];
    }

    function markIn() {
        const v = getVideo();
        if (!v) return toast('No encontré el video.');
        const t = Math.floor(v.currentTime);
        if (outT != null && t >= outT) return toast('El inicio tiene que ser antes del fin.');
        inT = t; refresh();
    }
    function markOut() {
        const v = getVideo();
        if (!v) return toast('No encontré el video.');
        const t = Math.floor(v.currentTime);
        if (inT != null && t <= inT) return toast('El fin tiene que ser después del inicio.');
        outT = t; refresh();
    }

    function getClip() {
        if (!clipAllowed || isShortForm()) return null;
        if (currentMode !== 'video') return null;
        if (inT == null && outT == null) return null;
        const v = getVideo();
        const dur = v && isFinite(v.duration) ? Math.floor(v.duration) : null;
        const s = inT != null ? inT : 0;
        const e = outT != null ? outT : dur;
        return (e != null && e > s) ? { s, e } : null;
    }
    function resetClip() { inT = outT = null; refresh(); }

    function addToQueue() {
        const url = getCleanUrl();
        if (!url) return toast(platform === 'tiktok' ? 'No pude detectar el TikTok visible.' : platform === 'instagram' ? 'No pude detectar el Reel visible.' : 'No se pudo detectar el enlace.');
        const q = loadQueue();
        if (q.length >= MAX_QUEUE) return toast(`La cola está llena (${MAX_QUEUE}).`);
        const clip = getClip();
        if (q.some(i => i.url === url && i.s === (clip ? clip.s : undefined) && i.e === (clip ? clip.e : undefined))) {
            return toast('Ese contenido ya está en la cola.');
        }
        q.push({ url, title: getTitle(), s: clip ? clip.s : undefined, e: clip ? clip.e : undefined });
        saveQueue(q);
        toast(`Añadido a la cola (${q.length})` + (clip ? ` · ${fmt(clip.s)} → ${fmt(clip.e)}` : ''));
        resetClip();
        if (pop.classList.contains('show')) renderPop();
    }

    function launch(uri) {
        const a = document.createElement('a');
        a.href = uri;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => a.remove(), 1000);
        toast('Abriendo IndieDL...');
    }

    function download() {
        const url  = getCleanUrl();
        const q    = loadQueue();
        if (!url) return toast(platform === 'tiktok' ? 'No pude vincular este video de TikTok. Tocá «Copiar enlace» y reintentá.' : 'No pude detectar el enlace.');
        const mode = currentMode;
        const clip = getClip();

        if (!q.length) {
            let uri = `ytdl://${mode}/?u=${encodeURIComponent(url)}`;
            if (clip) uri += `&s=${clip.s}&e=${clip.e}`;
            launch(uri);
            resetClip();
            return;
        }

        const items = q.slice();
        if (url && !items.some(i => i.url === url)) {
            items.push({ url, title: getTitle(), s: clip ? clip.s : undefined, e: clip ? clip.e : undefined });
        }
        const uri = 'ytdl://batch/?' + items.slice(0, MAX_QUEUE).map(i =>
            `u=${encodeURIComponent(i.url)}&t=${encodeURIComponent(i.title || '')}`).join('&');
        launch(uri);
        saveQueue([]);
        resetClip();
        pop.classList.remove('show');
    }

    function renderPop() {
        const q = loadQueue();
        const clearBtn = el('button', { type: 'button', text: 'Vaciar', onclick: () => { saveQueue([]); renderPop(); refresh(); } });
        pop.replaceChildren(el('div', { className: 'head' }, el('span', { text: `Cola (${q.length})` }), clearBtn));
        if (!q.length) { pop.appendChild(el('div', { className: 'empty', text: 'La cola está vacía.' })); return; }
        q.forEach((it, idx) => {
            const range = it.s != null ? `✂ ${fmt(it.s)} → ${fmt(it.e)}` : 'completo';
            const x = el('button', { type: 'button', className: 'x', text: '✕', title: 'Quitar de la cola', onclick: () => {
                const cur = loadQueue(); cur.splice(idx, 1); saveQueue(cur); renderPop(); refresh();
            } });
            pop.appendChild(el('div', { className: 'row' },
                el('div', { className: 't' }, el('b', { text: it.title || it.url }), el('small', { text: range })), x));
        });
    }
    function togglePop() {
        if (pop.classList.contains('show')) { pop.classList.remove('show'); return; }
        renderPop();
        if (!document.body.contains(pop)) document.body.appendChild(pop);
        const r = bList.getBoundingClientRect();
        pop.style.top  = Math.min(r.bottom + 8, window.innerHeight - 120) + 'px';
        pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 360)) + 'px';
        pop.classList.add('show');
    }
    document.addEventListener('click', (e) => {
        if (!pop.contains(e.target) && !bar.contains(e.target)) pop.classList.remove('show');
    });

    function isVideoPage() {
        const { hostname: h, pathname: p } = window.location;
        if (h.includes('youtube.com'))   return p === '/watch' || p.startsWith('/shorts/');
        if (h.includes('instagram.com')) return /^\/(p|reel|reels|tv)\//.test(p);
        if (h.includes('tiktok.com')) {
            if (p.startsWith('/search') || p.startsWith('/tag') || p.startsWith('/explore')) {
                return Array.from(document.querySelectorAll('video')).some(v => {
                    const r = v.getBoundingClientRect();
                    return r.width > 350 && r.height > 350 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
                });
            }
            return true;
        }
        return true;
    }

    function isImageOnlyInstagramPost() {
        if (platform !== 'instagram' || !location.pathname.startsWith('/p/')) return false;
        const postPath = location.pathname.replace(/\/$/, '');
        const postLink = Array.from(document.querySelectorAll('article a[href]')).find((link) => {
            try { return new URL(link.href).pathname.replace(/\/$/, '') === postPath; }
            catch (_) { return false; }
        });
        const post = postLink?.closest('article') || document.querySelector('article');
        if (!post) return false;
        const visible = (node) => {
            const r = node.getBoundingClientRect();
            return r.width > 150 && r.height > 150 && r.bottom > 0 && r.top < innerHeight &&
                r.right > 0 && r.left < innerWidth;
        };
        const hasVideo = Array.from(post.querySelectorAll('video')).some(visible);
        const hasImage = Array.from(post.querySelectorAll('img')).some((img) =>
            img.naturalWidth > 150 && visible(img)
        );
        return hasImage && !hasVideo;
    }

    let positionFrame = 0;
    let positionObserver = null;
    let shortsFrozen = false;       // congela la barra mientras el Short se desplaza
    let shortsFreezeTimer = 0;
    let lastShortsLeft = null;      // última X buena de la barra en Shorts

    function isShortsPage() {
        return platform === 'youtube' && location.pathname.startsWith('/shorts/');
    }

    // El video del Short visible (para que la barra nunca quede encima de la imagen).
    function shortsVideoRect() {
        let best = null, bestArea = 0;
        document.querySelectorAll('ytd-reel-video-renderer video, #shorts-container video').forEach((v) => {
            const r = v.getBoundingClientRect();
            if (r.width < 100 || r.height < 100 || r.bottom <= 0 || r.top >= innerHeight) return;
            const area = (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) * r.width;
            if (area > bestArea) { bestArea = area; best = r; }
        });
        return best;
    }

    // TikTok en ventana/modal (búsqueda, mensajes, enlaces a un video o foto): el video/foto queda a la
    // izquierda y un panel de información a la derecha, con los botones de acción en una fila horizontal.
    function tiktokActionsHorizontal(likeNode, lr) {
        if (likeNode && /^browse-/.test(likeNode.getAttribute('data-e2e') || '')) return true;
        const comment = Array.from(document.querySelectorAll(
            '[data-e2e="comment-icon"], [data-e2e="browse-comment-icon"], [data-e2e="video-comment-icon"]'
        )).find((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight; });
        if (!comment) return false;
        const cr = comment.getBoundingClientRect();
        return Math.abs(cr.top - lr.top) < 24 && Math.abs(cr.left - lr.left) > 30;
    }
    // Rect del video/foto principal (el más grande a la vista) que queda a la izquierda de maxRight.
    function tiktokMediaRect(maxRight) {
        let best = null, bestArea = 0;
        document.querySelectorAll('video, img').forEach((n) => {
            if (n.closest('#indiedl-bar, #indiedl-pop')) return;
            const r = n.getBoundingClientRect();
            if (r.width < 200 || r.height < 200 || r.right <= 0 || r.left >= innerWidth || r.bottom <= 0 || r.top >= innerHeight) return;
            if (r.right > maxRight + 4) return;
            const area = (Math.min(r.right, innerWidth) - Math.max(r.left, 0)) * (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
            if (area > bestArea) { bestArea = area; best = r; }
        });
        return best;
    }

    // Mientras se hace scroll/cambia de Short la barra se queda quieta; al asentarse se acomoda suave.
    function freezeShorts(ms) {
        if (!isShortsPage()) return;
        shortsFrozen = true;
        clearTimeout(shortsFreezeTimer);
        shortsFreezeTimer = setTimeout(() => {
            shortsFrozen = false;
            scheduleShortBarPosition();
        }, ms || 450);
    }

    // LÓGICA DE POSICIÓN MEJORADA Y UNIFICADA
    function positionShortBar() {
        if (!bar.classList.contains('tt-floating') && !bar.classList.contains('yt-shorts-floating') && !bar.classList.contains('ig-floating')) return;

        const isShorts = isShortsPage();
        if (isShorts && shortsFrozen && bar.classList.contains('positioned')) return;

        const brd = bar.getBoundingClientRect();
        const w = brd.width || 42;
        const h = brd.height || 200;

        const placeAt = (left, top) => {
            if (isShorts) {
                // Nunca encima del video: a la derecha, si no a la izquierda, si no la última X buena.
                const vr = shortsVideoRect();
                if (vr && left < vr.right - 2 && left + w > vr.left + 2) {
                    if (vr.right + 10 + w <= innerWidth - 8) left = vr.right + 10;
                    else if (vr.left - 10 - w >= 8) left = vr.left - 10 - w;
                    else if (lastShortsLeft !== null) left = lastShortsLeft;
                }
            }
            left = Math.max(8, Math.min(innerWidth - w - 8, left));
            top = Math.max(8, Math.min(innerHeight - h - 8, top));
            if (isShorts) lastShortsLeft = left;
            const first = !bar.classList.contains('positioned');
            if (first) bar.classList.remove('smooth');   // la primera vez aparece directo, sin deslizarse desde fuera
            // Una sola propiedad animable: nada de left/top (cada frame forzaría
            // layout). La barra se mueve con transform y se compone en la GPU.
            bar.style.setProperty('left', '0px', 'important');
            bar.style.setProperty('top', '0px', 'important');
            bar.style.setProperty('right', 'auto', 'important');
            bar.style.setProperty('bottom', 'auto', 'important');
            bar.style.setProperty(
                'transform',
                `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`,
                'important');
            bar.classList.add('positioned');
            if (first) {
                void bar.offsetWidth;
                requestAnimationFrame(() => bar.classList.add('smooth'));
            }
        };

        let likeBtn = null;
        let tiktokLikeNode = null;
        let instagramScope = document;
        if (platform === 'instagram' && location.pathname.startsWith('/p/')) {
            const postPath = location.pathname.replace(/\/$/, '');
            const postLink = Array.from(document.querySelectorAll('article a[href]')).find((link) => {
                try { return new URL(link.href).pathname.replace(/\/$/, '') === postPath; }
                catch (_) { return false; }
            });
            instagramScope = postLink?.closest('article') || document.querySelector('article') || document;

            // Posts/carruseles: la barra queda FIJA a la izquierda del post, fuera de la imagen.
            // Se ancla al contenedor del post (que no cambia al pasar de foto), no a la foto activa.
            if (instagramScope !== document) {
                const ar = instagramScope.getBoundingClientRect();
                const visTop = Math.max(ar.top, 0);
                const visBottom = Math.min(ar.bottom, innerHeight);
                if (ar.width > 150 && visBottom - visTop > 60) {
                    let left = ar.left - w - 14;
                    if (left < 8 && ar.right + 14 + w <= innerWidth - 8) left = ar.right + 14; // sin lugar a la izquierda
                    const top = visTop + (visBottom - visTop - h) / 2;
                    placeAt(left, top);
                    return;
                }
            }
        }

        // 1. Buscar el botón de Like según la plataforma
        if (platform === 'instagram') {
            const likeCandidates = Array.from(instagramScope.querySelectorAll(
                'svg[aria-label="Like"], svg[aria-label="Me gusta"], svg[aria-label="Unlike"], svg[aria-label="Ya no me gusta"]'
            ));
            const likeIcon = likeCandidates.find(node => {
                const r = node.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight;
            });
            if (likeIcon) likeBtn = likeIcon.closest('button, div[role="button"]') || likeIcon;

        } else if (platform === 'youtube') {
            const activeReel = document.querySelector('ytd-reel-video-renderer[is-active]') ||
                document.querySelector('ytd-reel-video-renderer') || document;
            const youtubeLikes = Array.from(activeReel.querySelectorAll(
                '#like-button, ytd-reel-player-overlay-renderer [aria-label*="Me gusta"], ' +
                'ytd-reel-player-overlay-renderer [aria-label*="Like"], ' +
                'ytd-reel-player-overlay-renderer button[aria-label*="like" i], ' +
                'ytd-reel-player-overlay-renderer [role="button"][aria-label*="like" i]'
            ));
            likeBtn = youtubeLikes.find(node => {
                const r = node.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
                    r.right > innerWidth * 0.55;
            }) || Array.from(document.querySelectorAll(
                '#like-button, [aria-label*="Me gusta"], [aria-label*="Like"]'
            )).find(node => {
                const r = node.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
                    r.right > innerWidth * 0.55;
            });
            if (likeBtn && likeBtn.tagName !== 'BUTTON') {
                likeBtn = likeBtn.querySelector('button') || likeBtn;
            }

        } else if (platform === 'tiktok') {
            const likeCandidates = Array.from(document.querySelectorAll(
                '[data-e2e="like-icon"], [data-e2e="browse-like-icon"], [data-e2e="video-like-icon"]'
            ));
            const likeIcon = likeCandidates.find(node => {
                const r = node.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
                    r.right > innerWidth * 0.55;
            });
            if (likeIcon) { tiktokLikeNode = likeIcon; likeBtn = likeIcon.closest('button, div[role="button"]') || likeIcon; }
        }

        // 2. Posicionar respecto al Like
        if (likeBtn) {
            const lr = likeBtn.getBoundingClientRect();
            if (lr.width > 0 && lr.height > 0) {
                let left, top;
                if (platform === 'instagram') {
                    left = lr.left - w - 10;
                    top = lr.top + (lr.height - h) / 2;
                } else if (platform === 'youtube' && location.pathname.startsWith('/shorts/')) {
                    // Shorts: colocar IndieDL encima del control de Like.
                    left = lr.left + (lr.width - w) / 2;
                    top = lr.top - h - 8;
                } else if (platform === 'tiktok' && tiktokActionsHorizontal(tiktokLikeNode, lr)) {
                    // Ventana de TikTok (búsqueda/mensajes): barra fija a la izquierda del video/foto, afuera de la imagen,
                    // centrada en vertical. No se pega al panel de la derecha (ahí tapaba el texto).
                    const media = tiktokMediaRect(lr.left);
                    left = media ? media.left - w - 14 : 12;
                    if (media && left < 8 && lr.left - media.right >= w + 40) left = media.right + 14; // sin lugar a la izquierda
                    top = innerHeight / 2 - h / 2;
                } else if (platform === 'tiktok') {
                    // TikTok: colocar IndieDL encima del avatar/foto superior de la columna social.
                    const profileNodes = Array.from(document.querySelectorAll(
                        '[data-e2e*="video-follow"], [data-e2e*="avatar"], [aria-label*="perfil" i]'
                    ));
                    const profileTarget = profileNodes.map(node => {
                        const control = node.closest('button, [role="button"]') || node;
                        return { rect: control.getBoundingClientRect() };
                    }).filter(({ rect }) => rect.width >= 24 && rect.width <= 100 &&
                        rect.height >= 24 && rect.height <= 100 && rect.bottom > 0 && rect.top < innerHeight &&
                        rect.right > innerWidth * 0.55 && Math.abs(rect.left - lr.left) < 150 && rect.top < lr.top
                    ).sort((a, b) => a.rect.top - b.rect.top)[0];
                    const anchor = profileTarget?.rect || lr;
                    left = anchor.left + (anchor.width - w) / 2;
                    top = anchor.top - h - 8;
                } else {
                    left = lr.left + (lr.width - w) / 2;
                    top = lr.top - h - 8;
                }
                placeAt(left, top);
                return;
            }
        }

        // 3. Fallback: Si no se encuentra el Like, usar el video
        const activeShort = platform === 'youtube'
            ? (document.querySelector('ytd-reel-video-renderer[is-active]') || document.querySelector('ytd-reel-video-renderer'))
            : null;
        let video = activeShort?.querySelector('video') || document.querySelector('video');
        if (video) {
            const vr = video.getBoundingClientRect();
            if (vr.width > 100 && vr.height > 100) {
                let left = vr.right - w - 10;
                let top = vr.top + (vr.height - h) / 2;
                if (platform === 'youtube' && location.pathname.startsWith('/shorts/')) {
                    const actionsTop = vr.top + vr.height * 0.50;
                    left = innerWidth - vr.right >= w + 8 ? vr.right + 5 : vr.right - w - 5;
                    top = actionsTop - h - 8;
                } else if (platform === 'tiktok') {
                    left = vr.right - w - 5;
                    top = vr.top + vr.height * 0.50 - h - 8;
                }
                placeAt(left, top);
                return;
            }
        }

        // TikTok sin Like ni video detectables (p. ej. publicación de fotos): izquierda de la imagen principal.
        if (platform === 'tiktok') {
            const media = tiktokMediaRect(innerWidth * 0.75);
            placeAt(media ? media.left - w - 14 : 12, innerHeight / 2 - h / 2);
            return;
        }

        // El DOM de Shorts tarda a veces en exponer video/Like al cargar o cambiar de Short.
        // Mostrar la barra dentro de la zona del reproductor mientras aparece el objetivo real.
        if (platform === 'youtube' && location.pathname.startsWith('/shorts/')) {
            const renderer = activeShort?.getBoundingClientRect();
            if (renderer && renderer.width > 100 && renderer.height > 100) {
                const actionsTop = renderer.top + renderer.height * 0.50;
                const left = innerWidth - renderer.right >= w + 8 ? renderer.right + 5 : renderer.right - w - 5;
                placeAt(left, actionsTop - h - 8);
            } else {
                placeAt(innerWidth * 0.72, innerHeight * 0.50 - h - 8);
            }
        }
    }

    function scheduleShortBarPosition() {
        if (positionFrame) return;
        positionFrame = requestAnimationFrame(() => {
            positionFrame = 0;
            positionShortBar();
        });
    }

    window.addEventListener('resize', scheduleShortBarPosition, { passive: true });
    window.addEventListener('scroll', scheduleShortBarPosition, { passive: true, capture: true });
    document.addEventListener('visibilitychange', scheduleShortBarPosition);

    let mountFrame = 0;
    function scheduleMount() {
        if (mountFrame) return;
        mountFrame = requestAnimationFrame(() => {
            mountFrame = 0;
            mount();
        });
    }

    if (typeof MutationObserver !== 'undefined') {
        const pageObserver = new MutationObserver((records) => {
            const pageChanged = records.some(record => {
                const target = record.target;
                if (target === bar || (target.nodeType === 1 && bar.contains(target))) return false;
                const changedNodes = [...record.addedNodes, ...record.removedNodes];
                return changedNodes.some(node =>
                    node !== bar && !(node.nodeType === 1 && (node.id === 'indiedl-bar' || node.id === 'indiedl-pop' || node.id === 'indiedl-toast'))
                );
            });
            if (!pageChanged) return;

            if (platform === 'instagram' || platform === 'tiktok') {
                scheduleMount();
            }
            if (platform === 'instagram' || platform === 'tiktok' || (platform === 'youtube' && location.pathname.startsWith('/shorts/'))) {
                scheduleShortBarPosition();
            }
        });
        const observeRoot = document.documentElement;
        if (observeRoot) pageObserver.observe(observeRoot, { childList: true, subtree: true });
    }

    // YouTube conserva copias ocultas de la página anterior (al volver atrás). querySelector devolvía
    // a veces esa copia invisible y la barra quedaba "montada" pero sin verse. Se elige la visible.
    function isUsableHost(n) {
        if (!n || !n.isConnected || n.closest('[hidden]')) return false;
        if (n.getClientRects().length > 0) return true;
        return !!(n.parentElement && n.parentElement.getClientRects().length > 0);
    }
    function pickVisibleHost(selectors) {
        for (const sel of selectors) {
            for (const n of document.querySelectorAll(sel)) {
                if (isUsableHost(n)) return n;
            }
        }
        return null;
    }
    function barIsShown() {
        return bar.isConnected && !bar.closest('[hidden]') && bar.getClientRects().length > 0;
    }
    // Reintenta montar varias veces: tras navegar, YouTube dibuja los botones con retraso.
    let remountTimers = [];
    function remountSoon() {
        remountTimers.forEach(clearTimeout);
        remountTimers = [0, 250, 700, 1500, 3000, 6000].map((ms) => setTimeout(() => {
            if (!barIsShown()) curUrl = null;
            mount();
        }, ms));
    }

    function resetBarTransform() {
        // Al volver al modo incrustado la barra tiene que fluir con el layout:
        // si quedara el transform flotante, aparecería corrida.
        for (const prop of ['transform', 'left', 'top', 'right', 'bottom']) {
            bar.style.removeProperty(prop);
        }
    }

    function mount() {
        if (document.hidden || !document.body) return;

        const currentUrl = window.location.href;
        const videoPage = isVideoPage();
        bar.classList.toggle('hidden', !videoPage);

        if (!videoPage) {
            bar.classList.remove(
                'ready', 'positioned', 'floating', 'ig-floating', 'ig-icons', 'ig-reel',
                'ig-inline', 'tt-floating', 'yt-shorts-floating'
            );
            resetBarTransform();
            bar.classList.add('hidden');
            curUrl = currentUrl;
            return;
        }

        // En publicaciones fotográficas de Instagram, abrir IndieDL directamente en Imagen.
        // La app nativa se encarga de mostrar el selector para elegir una, varias o todas.
        if (platform === 'instagram' && location.pathname.startsWith('/p/') &&
            autoImageModeUrl !== currentUrl && isImageOnlyInstagramPost()) {
            currentMode = 'image';
            autoImageModeUrl = currentUrl;
            refresh();
        }

        const needsVisibleHost = platform === 'youtube' && location.pathname === '/watch';
        if (curUrl === currentUrl && bar.classList.contains('ready') && bar.parentElement && bar.parentElement.isConnected &&
            (!needsVisibleHost || barIsShown())) {
            return;
        }

        let host = null;
        let isIG = false;
        let igIsReel = false;

        if (platform === 'youtube' && location.pathname.startsWith('/shorts/')) {
            if (bar.parentElement !== document.body) document.body.appendChild(bar);
            bar.classList.remove('hidden');
            bar.classList.remove('floating', 'ig-reel', 'ig-inline', 'ig-icons', 'tt-floating', 'ig-floating');
            bar.classList.add('yt-shorts-floating', 'ready');
            curUrl = currentUrl;
            refresh();
            scheduleShortBarPosition();
            return;
        } else if (platform === 'youtube' && location.pathname === '/watch') {
            host = pickVisibleHost([
                'ytd-watch-metadata #top-level-buttons-computed',
                'ytd-watch-metadata #actions',
                '#actions #top-level-buttons-computed',
                '#actions',
                '#menu-container'
            ]);

        } else if (platform === 'instagram') {
            igIsReel = location.pathname.includes('/reel/') || location.pathname.includes('/reels/');
            if (igIsReel || location.pathname.includes('/p/')) {
                if (bar.parentElement !== document.body) document.body.appendChild(bar);
                bar.classList.remove('hidden');
                bar.classList.remove('floating', 'tt-floating', 'yt-shorts-floating', 'ig-reel', 'ig-inline');
                bar.classList.add('ig-floating', 'ig-icons', 'ready');
                curUrl = currentUrl;
                refresh();
                scheduleShortBarPosition();
                return;
            }
        }

        if (host) {
            if (bar.parentElement !== host) {
                if (isIG && igIsReel) {
                    host.insertBefore(bar, host.firstChild);
                } else {
                    host.appendChild(bar);
                }
            }

            bar.classList.remove('floating');
            resetBarTransform();
            bar.classList.add('ready');

            if (isIG) {
                bar.classList.add('ig-icons');
                if (igIsReel) {
                    bar.classList.add('ig-reel');
                    bar.classList.remove('ig-inline');
                } else {
                    bar.classList.add('ig-inline');
                    bar.classList.remove('ig-reel');
                }
            } else {
                bar.classList.remove('ig-reel', 'ig-inline', 'ig-icons', 'tt-floating', 'yt-shorts-floating', 'ig-floating');
            }

            curUrl = currentUrl;
            refresh();
        } else {
            if (platform === 'instagram' || (platform === 'youtube' && location.pathname === '/watch')) {
                bar.classList.remove('ready');
            } else {
                if (bar.parentElement !== document.body) document.body.appendChild(bar);
                bar.classList.remove('ig-reel', 'ig-inline', 'ig-icons');
                if (platform === 'tiktok') {
                    bar.classList.remove('hidden');
                    bar.classList.remove('floating', 'yt-shorts-floating');
                    bar.classList.add('tt-floating');
                } else {
                    bar.classList.remove('tt-floating', 'yt-shorts-floating');
                    bar.classList.add('floating');
                    resetBarTransform();
                }
                bar.classList.add('ready');
                curUrl = currentUrl;
                refresh();
                if (platform === 'tiktok') scheduleShortBarPosition();
            }
        }
    }

    queueReady.then(() => refresh());
    setInterval(mount, 700);
    window.addEventListener('resize', scheduleShortBarPosition, { passive: true });
    window.addEventListener('scroll', scheduleShortBarPosition, { passive: true, capture: true });
    window.addEventListener('scroll', () => {
        if (platform === 'instagram') {
            scheduleMount();
            scheduleShortBarPosition();
        }
    }, { passive: true, capture: true });

    window.addEventListener('yt-navigate-start', () => { bar.classList.remove('ready'); curUrl = null; freezeShorts(600); });
    window.addEventListener('yt-navigate-finish', () => { curUrl = null; mount(); remountSoon(); freezeShorts(450); });
    window.addEventListener('yt-page-data-updated', () => { curUrl = null; mount(); remountSoon(); });
    // Volver atrás / restaurar la pestaña desde la caché del navegador.
    window.addEventListener('pageshow', () => { curUrl = null; remountSoon(); scheduleShortBarPosition(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { curUrl = null; remountSoon(); } });

    // Shorts: la barra se queda quieta mientras haces scroll y se acomoda suave al asentarse el video.
    window.addEventListener('wheel', () => freezeShorts(450), { passive: true, capture: true });
    window.addEventListener('touchmove', () => freezeShorts(450), { passive: true, capture: true });
    window.addEventListener('keydown', (e) => {
        if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown'].includes(e.key)) freezeShorts(450);
    }, true);
    document.addEventListener('click', (e) => {
        if (e.target && e.target.closest && e.target.closest('#navigation-button-up, #navigation-button-down')) freezeShorts(650);
    }, true);

    const pushState = history.pushState;
    history.pushState = function() {
        pushState.apply(history, arguments);
        curUrl = null;
        freezeShorts(450);
        setTimeout(() => { mount(); scheduleShortBarPosition(); }, 100);
        remountSoon();
    };
    const replaceState = history.replaceState;
    history.replaceState = function() {
        replaceState.apply(history, arguments);
        curUrl = null;
        setTimeout(() => { mount(); scheduleShortBarPosition(); }, 100);
    };
    window.addEventListener('popstate', () => { curUrl = null; freezeShorts(450); setTimeout(() => { mount(); scheduleShortBarPosition(); }, 100); remountSoon(); });

    mount();
})();






