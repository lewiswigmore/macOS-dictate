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
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); initLaunchAtLogin(); });
  } else {
    init();
    initLaunchAtLogin();
  }
})();
