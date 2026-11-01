/* Calls into the Python core over the local server, plus the progress poll. */
(function () {
  const HS = (window.HS = window.HS || {});
  HS.token = new URLSearchParams(location.search).get("t") || "";

  HS.call = async function (name, args = {}) {
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-HS-Token": HS.token },
      body: JSON.stringify(args),
    });
    if (!r.ok) throw new Error(r.status + " " + r.statusText);
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    return j.data;
  };

  const listeners = [];
  HS.on = (fn) => listeners.push(fn);

  let busy = false;
  async function poll() {
    if (busy) return;
    busy = true;
    try {
      const r = await HS.call("poll");
      HS.job = r.job;
      for (const ev of r.events) listeners.forEach((fn) => fn(ev));
    } catch (e) {
      /* the server stops with the window */
    } finally {
      busy = false;
    }
  }
  setInterval(poll, 400);
})();
