(function () {
  function init() {
    var form = document.getElementById('prefs-form');
    if (!form) return;
    form.querySelectorAll('.pref-row').forEach(function (row) {
      var key = row.dataset.key;
      var input = row.querySelector('input, select');
      var status = row.querySelector('.pref-status');
      if (!input) return;
      input.addEventListener('change', function () {
        var value = input.type === 'checkbox' ? input.checked : input.value;
        status.textContent = 'saving…';
        fetch('/api/settings/pref', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Dictate-WebUI': '1' },
          body: JSON.stringify({ key: key, value: value })
        }).then(function (r) {
          if (!r.ok) { return r.text().then(function (t) { throw new Error(t); }); }
          return r.json();
        }).then(function () {
          status.textContent = '✓ saved';
          setTimeout(function () { status.textContent = ''; }, 1500);
        }).catch(function (err) {
          status.textContent = '✗ ' + err.message;
        });
      });
    });
  }
  function initLaunchAtLogin() {
    var input = document.getElementById('launch-at-login');
    if (!input) return;
    var status = document.querySelector('#launch-at-login-row .pref-status');
    input.addEventListener('change', function () {
      var enabled = input.checked;
      input.disabled = true;
      if (status) status.textContent = 'saving…';
      fetch('/api/settings/launch-at-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Dictate-WebUI': '1' },
        body: JSON.stringify({ enabled: enabled })
      }).then(function (r) {
        if (!r.ok) { return r.text().then(function (t) { throw new Error(t); }); }
        return r.json();
      }).then(function (data) {
        input.checked = !!data.enabled;
        if (status) {
          status.textContent = '✓ saved';
          setTimeout(function () { status.textContent = ''; }, 1500);
        }
      }).catch(function (err) {
        input.checked = !enabled;
        if (status) status.textContent = '✗ ' + err.message;
      }).finally(function () {
        input.disabled = false;
      });
    });
  }
  function renderPermissions(data) {
    var list = document.querySelector('[data-perm-list]');
    var banner = document.querySelector('[data-perm-banner]');
    if (!list || !data || !data.permissions) return;

    data.permissions.forEach(function (perm) {
      var row = list.querySelector('[data-perm-key="' + perm.key + '"]');
      if (!row) return;
      var pill = row.querySelector('[data-perm-pill]');
      if (pill) {
        pill.textContent = perm.granted ? 'Granted' : 'Not granted';
        pill.classList.toggle('is-granted', !!perm.granted);
        pill.classList.toggle('is-denied', !perm.granted);
        pill.setAttribute('aria-label', perm.label + (perm.granted ? ' granted' : ' not granted'));
      }
      var impact = row.querySelector('.perm-impact');
      if (perm.granted && impact) impact.remove();
      var btn = row.querySelector('[data-perm-open]');
      if (perm.granted && btn) btn.remove();
    });

    if (banner) {
      var missing = data.permissions.filter(function (p) { return !p.granted; });
      if (missing.length) {
        banner.textContent = missing.length === 1
          ? missing[0].label + ' is not granted. ' + missing[0].impact
          : missing.length + ' permissions are not granted — dictate will not work correctly.';
        banner.hidden = false;
      } else {
        banner.hidden = true;
      }
    }
  }

  function refreshPermissions() {
    return fetch('/api/permissions', { headers: { 'X-Dictate-WebUI': '1' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(renderPermissions)
      .catch(function () { /* transient; next poll retries */ });
  }

  function initPermissions() {
    var panel = document.querySelector('[data-permissions-panel]');
    if (!panel) return;

    panel.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-perm-open]');
      if (!btn) return;
      btn.disabled = true;
      fetch('/api/permissions/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Dictate-WebUI': '1' },
        body: JSON.stringify({ key: btn.dataset.permOpen })
      }).finally(function () { btn.disabled = false; });
    });

    refreshPermissions();
    // Grants land while the user is in System Settings; poll so the panel
    // reflects reality without a manual reload.
    setInterval(refreshPermissions, 5000);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) refreshPermissions();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      init();
      initLaunchAtLogin();
      initPermissions();
    });
  } else {
    init();
    initLaunchAtLogin();
    initPermissions();
  }
})();
