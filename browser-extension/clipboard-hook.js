(() => {
  'use strict';
  const clipboard = globalThis.Clipboard;
  const proto = clipboard && clipboard.prototype;
  if (!proto || typeof proto.writeText !== 'function' || proto.__indiedlHooked) return;
  const original = proto.writeText;
  proto.writeText = function (text) {
    try {
      const value = String(text || '');
      if (/https?:\/\/(?:www\.)?tiktok\.com\/@[^/?#\s]+\/video\/\d+|https?:\/\/(?:vm|vt)\.tiktok\.com\/[\w-]+\/?|https?:\/\/www\.tiktok\.com\/t\/[\w-]+\/?/i.test(value)) {
        window.postMessage({ source: 'indiedl-clipboard', text: value }, location.origin);
      }
    } catch (_) {}
    return original.apply(this, arguments);
  };
  try { Object.defineProperty(proto, '__indiedlHooked', { value: true }); } catch (_) {}
})();
