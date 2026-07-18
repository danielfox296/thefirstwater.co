/* Sessions overlay (WP5): re-checks the live feed between site rebuilds and
   updates remaining counts / sold-out state on session pages. The static
   page is fully correct without this file — it only upgrades. No deps. */
(function () {
  'use strict';
  var root = document.querySelector('[data-sessions-feed]');
  if (!root || !window.fetch) return;
  fetch(root.getAttribute('data-sessions-feed'), { mode: 'cors' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (feed) {
      if (!feed || !feed.sessions) return;
      feed.sessions.forEach(function (s) {
        var el = null;
        var cards = root.querySelectorAll('[data-session-id]');
        for (var i = 0; i < cards.length; i++) {
          if (cards[i].getAttribute('data-session-id') === String(s.id)) { el = cards[i]; break; }
        }
        if (!el) return;
        el.setAttribute('data-session-status', s.status);
        var buy = el.querySelector('[data-session-buy]');
        if (buy) buy.disabled = (s.status !== 'on_sale');
        var left = el.querySelector('[data-session-remaining]');
        if (left) {
          var show = s.status === 'on_sale' && typeof s.remaining === 'number';
          left.hidden = !show;
          if (left.previousElementSibling) left.previousElementSibling.hidden = !show;
          if (show) left.textContent = s.remaining + ' left';
        }
        var wait = el.querySelector('.session-waitlist');
        if (wait) wait.hidden = !(s.status === 'sold_out' && s.waitlist_open);
      });
    })
    .catch(function () { /* feed unreachable: static state stands */ });
})();
