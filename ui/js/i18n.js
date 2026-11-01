/* Every UI string comes from locales/<lang>.json; English is the default. */
(function () {
  const HS = (window.HS = window.HS || {});
  const strings = {};

  function stored() {
    try {
      return localStorage.getItem("hs.lang");
    } catch (e) {
      return null;
    }
  }

  HS.lang = stored() === "el" ? "el" : "en";

  HS.loadStrings = async function () {
    for (const lang of ["en", "el"]) {
      const r = await fetch("/ui/locales/" + lang + ".json");
      strings[lang] = await r.json();
    }
  };

  HS.t = function (key, vars) {
    let s = (strings[HS.lang] && strings[HS.lang][key]) || (strings.en && strings.en[key]) || key;
    if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  };

  HS.setLang = function (lang) {
    HS.lang = lang;
    try {
      localStorage.setItem("hs.lang", lang);
    } catch (e) {}
    document.documentElement.lang = lang;
    HS.translateStatic();
  };

  HS.translateStatic = function () {
    document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = HS.t(el.dataset.i18n)));
    document.querySelectorAll("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === HS.lang));
  };
})();
