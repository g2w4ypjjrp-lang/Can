// Tema seçimi (Sistem / Açık / Koyu). Sunucu ve tarayıcı ortak: sabitler istemci bileşeninden
// ayrı tutulur (sunucu bileşeni "use client" modülündeki düz değeri doğrudan okuyamaz).

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "ati-tema";

/** Sayfa boyanmadan önce çalışan betik (root layout, nonce'lu): kayıtlı seçimi uygular. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})();`;
